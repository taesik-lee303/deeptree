# Thermal rPPG pipeline (MLX90640/90641) + MFSR + UI + MQTT publish of color therapy recommendations
# Run:
#   python -m modules.rppg.thermal_rppg
#   (프로젝트 루트에서 실행, src가 루트)

import numpy as np
import cv2
from scipy import signal
from collections import deque
import time
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Dict, Optional
import warnings
warnings.filterwarnings('ignore')

# 절대경로 import (프로젝트 구조: src/modules/rppg, src/networks/mqtt)
from modules.rppg.color_therapy_adapter import ColorTherapist, ColorMetrics
from networks.mqtt.mqtt_publisher import MqttColorPublisher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("thermal_rppg")

MLX_BACKEND = None
SENSOR_MODEL = None
RESOLUTION = (24, 32)  # default
FRAME_LEN = RESOLUTION[0] * RESOLUTION[1]

try:
    import board
    import busio
except ImportError:
    board = None
    busio = None

try:
    import adafruit_mlx90640 as mlx40
    MLX_BACKEND = 'mlx90640'
    SENSOR_MODEL = 'MLX90640'
    RESOLUTION = (24, 32)
    FRAME_LEN = 24 * 32
except Exception:
    try:
        import adafruit_mlx90641 as mlx41
        MLX_BACKEND = 'mlx90641'
        SENSOR_MODEL = 'MLX90641'
        RESOLUTION = (12, 16)
        FRAME_LEN = 12 * 16
    except Exception:
        MLX_BACKEND = None


class ProcessingMode(Enum):
    REAL_TIME = "real_time"
    HIGH_ACCURACY = "high_accuracy"
    PRIVACY_FOCUSED = "privacy_focused"


@dataclass
class ThermalrPPGConfig:
    sampling_rate: float = 16.0
    min_measurement_duration: int = 12
    max_measurement_duration: int = 300
    target_hr_range: Tuple[float, float] = (0.7, 3.0)
    processing_mode: ProcessingMode = ProcessingMode.HIGH_ACCURACY
    enable_motion_compensation: bool = True
    debug_visual: bool = True
    enable_superres: bool = True
    superres_scale: int = 2
    superres_frames: int = 12
    superres_deconvolution: bool = True

    # ---- status / compute throttling ----
    status_interval: float = 2.0     # 상태 로그 최소 간격(sec)
    min_change_hr: float = 1.0       # HR 변화량 임계
    min_change_rr: float = 1.0       # RR 변화량 임계
    min_change_q: float = 0.05       # q 변화량 임계
    mqtt_quality_min: float = 0.35   # q 낮으면 MQTT 생략

    hr_period: float = 0.75          # HR 계산 최소 간격(sec)
    rr_period: float = 2.0           # RR 계산 최소 간격(sec)

    sr_stride: int = 3               # MFSR 빌드 주기(매 N프레임마다)
    mc_stride: int = 2               # 모션보정(ECC) 주기(매 N프레임마다)


class MLX9064XInterface:
    def __init__(self, i2c_frequency=800_000, refresh_hz=16):
        self.i2c = None
        self.sensor = None
        self.is_initialized = False
        self.res = RESOLUTION
        self.frame_len = FRAME_LEN
        self.last_frame_time = 0
        self.refresh_hz = refresh_hz
        self.frame_interval = 1.0 / max(1, refresh_hz)

        if MLX_BACKEND and board and busio:
            try:
                self.i2c = busio.I2C(board.SCL, board.SDA, frequency=i2c_frequency)
                if MLX_BACKEND == 'mlx90640':
                    self.sensor = mlx40.MLX90640(self.i2c)
                    try:
                        self.sensor.refresh_rate = mlx40.RefreshRate.REFRESH_16_HZ
                        self.refresh_hz = 16
                        self.frame_interval = 1.0 / 16
                    except Exception:
                        pass
                elif MLX_BACKEND == 'mlx90641':
                    self.sensor = mlx41.MLX90641(self.i2c)
                    try:
                        self.sensor.refresh_rate = mlx41.RefreshRate.REFRESH_16_HZ
                        self.refresh_hz = 16
                        self.frame_interval = 1.0 / 16
                    except Exception:
                        pass
                logger.info(f"Initialized {SENSOR_MODEL} @ ~{self.refresh_hz}Hz, res={self.res}")
                time.sleep(2.0)
                self.is_initialized = True
            except Exception as e:
                logger.warning(f"MLX init failed ({SENSOR_MODEL}): {e}. Falling back to simulation.")
        else:
            logger.warning("MLX libraries unavailable. Using simulation mode.")

    def read_frame(self):
        now = time.time()
        if now - self.last_frame_time < self.frame_interval:
            return None
        self.last_frame_time = now
        try:
            if self.is_initialized and self.sensor is not None:
                buf = [0] * self.frame_len
                self.sensor.getFrame(buf)
                frame = np.array(buf, dtype=np.float32).reshape(self.res)
                frame = np.clip(frame, -20.0, 100.0)
                frame = cv2.GaussianBlur(frame, (3, 3), 0.4)
                return frame
        except Exception as e:
            logger.warning(f"Frame read failed: {e}. Using simulation for this frame.")
        return self._simulate()

    def _simulate(self):
        h, w = self.res
        base = 25.0 + np.random.randn(h, w).astype(np.float32) * 0.15
        cy, cx = int(h*0.5), int(w*0.5)
        yy, xx = np.ogrid[:h, :w]
        mask = np.exp(-(((yy-cy)**2)/(2*(h*0.18)**2)+((xx-cx)**2)/(2*(w*0.18)**2)))
        frame = base + 8.0*mask.astype(np.float32)
        return frame

    def close(self):
        try:
            if self.i2c:
                self.i2c.deinit()
        except Exception:
            pass


def normalize_to_uint8(temp_frame, p_low=5, p_high=95):
    lo = np.percentile(temp_frame, p_low)
    hi = np.percentile(temp_frame, p_high)
    if hi <= lo:
        hi = lo + 1e-3
    im = np.clip((temp_frame - lo) / (hi - lo), 0, 1)
    return (im * 255).astype(np.uint8)


class MultiFrameSuperRes:
    def __init__(self, scale=2, max_frames=12, deconvolution=True):
        self.scale = int(scale)
        self.max_frames = int(max_frames)
        self.deconvolution = deconvolution
        self.buffer = []

    def reset(self):
        self.buffer.clear()

    def push(self, frame_f32: np.ndarray):
        self.buffer.append(frame_f32.astype(np.float32))
        if len(self.buffer) > self.max_frames:
            self.buffer.pop(0)

    def build(self) -> Optional[np.ndarray]:
        if len(self.buffer) < max(6, self.max_frames // 2):
            return None
        ref = self.buffer[len(self.buffer)//2]
        ref_u8 = normalize_to_uint8(ref)
        H, W = ref.shape
        S = self.scale
        acc = np.zeros((H*S, W*S), dtype=np.float32)
        cnt = np.zeros((H*S, W*S), dtype=np.float32)
        for frm in self.buffer:
            mov_u8 = normalize_to_uint8(frm)
            try:
                ref_f = ref_u8.astype(np.float32) / 255.0
                mov_f = mov_u8.astype(np.float32) / 255.0
                M = np.eye(2, 3, dtype=np.float32)
                criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 1e-4)
                _, M = cv2.findTransformECC(ref_f, mov_f, M, cv2.MOTION_AFFINE, criteria)
            except Exception:
                M = np.eye(2, 3, dtype=np.float32)
            up = cv2.resize(frm, (W*S, H*S), interpolation=cv2.INTER_CUBIC)
            M_hr = M.copy()
            M_hr[0, 2] *= S
            M_hr[1, 2] *= S
            warped = cv2.warpAffine(up, M_hr, (W*S, H*S), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
            acc += warped
            cnt += 1.0
        out = acc / np.maximum(cnt, 1e-6)
        if self.deconvolution:
            blur = cv2.GaussianBlur(out, (0, 0), 0.8)
            out = np.clip(out + 0.6*(out - blur), np.min(out), np.max(out))
        return out.astype(np.float32)


class ThermalFaceDetector:
    def __init__(self, ambient_delta: float = 1.2, p_hot: float = 80.0,
                 min_area_frac: float = 0.02, max_area_frac: float = 0.45,
                 top_bias: float = 0.55, search_expand: float = 0.6, lost_tolerance: int = 12):
        self.ambient_delta = ambient_delta
        self.p_hot = p_hot
        self.min_area_frac = min_area_frac
        self.max_area_frac = max_area_frac
        self.top_bias = top_bias
        self.search_expand = search_expand
        self.lost_tolerance = lost_tolerance
        self.last_bbox = None
        self.last_template = None
        self.missed = 0

    def _score_components(self, frame, stats, cents, cx_img, cy_img):
        best_idx, best_score = -1, -1e9
        H, W = frame.shape
        for i in range(1, stats.shape[0]):
            x, y, bw, bh, area = stats[i]
            if area < (H*W)*self.min_area_frac or area > (H*W)*self.max_area_frac:
                continue
            ar = bw / max(1, bh)
            if ar < 0.5 or ar > 2.2:
                continue
            cx, cy = cents[i]
            region = frame[y:y+bh, x:x+bw]
            temp_score = float(np.mean(region))
            center_score = -((cx - cx_img)**2 + (cy - cy_img)**2)
            top_bonus = -abs(cy - (H*self.top_bias)) * 0.5
            score = 1.2*temp_score + 0.002*area + 0.002*center_score + top_bonus
            if score > best_score:
                best_score, best_idx = score, i
        if best_idx < 1:
            return None
        x, y, bw, bh, _ = stats[best_idx]
        pad = 0.12
        x = max(0, int(x - bw * pad))
        y = max(0, int(y - bh * pad))
        bw = int(min(W - x, int(bw * (1 + 2*pad))))
        bh = int(min(H - y, int(bh * (1 + 2*pad))))
        return (x, y, bw, bh)

    def _threshold(self, frame):
        ambient = float(np.median(frame))
        t1 = ambient + self.ambient_delta
        t2 = float(np.percentile(frame, self.p_hot))
        thr = max(t1, t2)
        return (frame >= thr).astype(np.uint8)

    def _template_track(self, frame_u8, search_bbox):
        x, y, w, h = search_bbox
        search = frame_u8[y:y+h, x:x+w]
        if self.last_template is None or search.size == 0:
            return None
        try:
            res = cv2.matchTemplate(search, self.last_template, cv2.TM_CCOEFF_NORMED)
            _, maxv, _, maxloc = cv2.minMaxLoc(res)
            if maxv < 0.35:
                return None
            tx, ty = maxloc
            th, tw = self.last_template.shape
            return (x+tx, y+ty, tw, th)
        except Exception:
            return None

    def detect(self, frame: np.ndarray):
        H, W = frame.shape
        cx_img, cy_img = W*0.5, H*self.top_bias
        frame_u8 = normalize_to_uint8(frame)

        # Tracker 우선
        if self.last_bbox is not None and self.missed < self.lost_tolerance:
            lx, ly, lw, lh = self.last_bbox
            ex = int(lw*self.search_expand)
            ey = int(lh*self.search_expand)
            sx = max(0, lx-ex)
            sy = max(0, ly-ey)
            sw = min(W-sx, lw+2*ex)
            sh = min(H-sy, lh+2*ey)
            local = frame[sy:sy+sh, sx:sx+sw]
            hot = self._threshold(local)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            hot = cv2.morphologyEx(hot, cv2.MORPH_OPEN, k, iterations=1)
            hot = cv2.morphologyEx(hot, cv2.MORPH_CLOSE, k, iterations=2)
            num, labels, stats, cents = cv2.connectedComponentsWithStats(hot, 8)
            if num > 1:
                bbox = self._score_components(local, stats, cents, cx_img - sx, cy_img - sy)
                if bbox is not None:
                    x, y, w, h = bbox
                    self.last_bbox = (sx+x, sy+y, w, h)
                    self.missed = 0
                    roi_u8 = frame_u8[sy+y:sy+y+h, sx+x:sx+x+w]
                    if roi_u8.size >= 9:
                        self.last_template = cv2.resize(roi_u8, (max(8, w), max(8, h)))
                    return self.last_bbox
            track = self._template_track(frame_u8, (sx, sy, sw, sh))
            if track is not None:
                self.last_bbox = track
                self.missed = 0
                return self.last_bbox
            self.missed += 1

        # Global detect
        hot = self._threshold(frame)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        hot = cv2.morphologyEx(hot, cv2.MORPH_OPEN, k, iterations=1)
        hot = cv2.morphologyEx(hot, cv2.MORPH_CLOSE, k, iterations=2)
        num, labels, stats, cents = cv2.connectedComponentsWithStats(hot, 8)
        if num <= 1:
            self.missed += 1
            return None
        bbox = self._score_components(frame, stats, cents, cx_img, cy_img)
        if bbox is None:
            self.missed += 1
            return None
        self.last_bbox = bbox
        self.missed = 0
        x, y, w, h = bbox
        roi_u8 = frame_u8[y:y+h, x:x+w]
        if roi_u8.size >= 9:
            self.last_template = cv2.resize(roi_u8, (max(8, w), max(8, h)))
        return self.last_bbox


class MotionCompensator:
    def __init__(self):
        self.ref = None
        self.M = np.eye(2, 3, dtype=np.float32)
        self._tick = 0
        self.mc_stride = 2  # 외부에서 재설정 가능

    def compensate(self, frame: np.ndarray, bbox):
        if bbox is None:
            return frame
        self._tick += 1
        # stride 적용: 이전 M을 재사용(저부하)
        if self._tick % max(1, int(self.mc_stride)) != 0 and self.ref is not None:
            return cv2.warpAffine(frame, self.M, (frame.shape[1], frame.shape[0]),
                                  flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
        x, y, w, h = bbox
        roi = frame[y:y+h, x:x+w]
        if self.ref is None:
            self.ref = roi.copy()
            return frame
        try:
            ref_u8 = normalize_to_uint8(self.ref)
            roi_u8 = normalize_to_uint8(roi)
            ref_f = ref_u8.astype(np.float32) / 255.0
            roi_f = roi_u8.astype(np.float32) / 255.0
            M = np.eye(2, 3, dtype=np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 1e-4)
            _, M = cv2.findTransformECC(ref_f, roi_f, M, cv2.MOTION_AFFINE, criteria)
            out = cv2.warpAffine(frame, M, (frame.shape[1], frame.shape[0]),
                                 flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
            self.M = M
            self.ref = 0.9 * self.ref + 0.1 * out[y:y+h, x:x+w]
            return out
        except Exception:
            return frame


class ROIManager:
    def __init__(self):
        self.buffers: Dict[str, deque] = {}

    def extract(self, frame: np.ndarray, bbox, patch=3):
        if bbox is None:
            return {}, {}
        x, y, w, h = bbox
        rois = {
            'forehead': (x + int(0.25*w), y + int(0.05*h), int(0.5*w), int(0.22*h)),
            'l_cheek': (x + int(0.05*w), y + int(0.45*h), int(0.28*w), int(0.28*h)),
            'r_cheek': (x + int(0.67*w), y + int(0.45*h), int(0.28*w), int(0.28*h)),
            'nose': (x + int(0.40*w), y + int(0.40*h), int(0.20*w), int(0.22*h)),
        }
        vals = {}
        for name, (rx, ry, rw, rh) in rois.items():
            rx = max(0, min(rx, frame.shape[1]-1))
            ry = max(0, min(ry, frame.shape[0]-1))
            rw = max(2, min(rw, frame.shape[1]-rx))
            rh = max(2, min(rh, frame.shape[0]-ry))
            region = frame[ry:ry+rh, rx:rx+rw]
            cx, cy = rw//2, rh//2
            x0, x1 = max(0, cx-patch), min(rw, cx+patch+1)
            y0, y1 = max(0, cy-patch), min(rh, cy+patch+1)
            patch_arr = region[y0:y1, x0:x1]
            vals[name] = float(np.mean(patch_arr))
            rois[name] = (rx, ry, rw, rh)
        return vals, rois


class SignalProc:
    def __init__(self, fs):
        self.fs = fs
        self.band = (0.7, 3.0)
        # 필터 계수 1회 설계
        self.sos = signal.butter(4, self.band, btype='band', fs=self.fs, output='sos')

    def detrend_bandpass(self, x):
        x = x - np.mean(x)
        return signal.sosfilt(self.sos, x)

    def hr_fft(self, x):
        if len(x) < int(8 * self.fs):
            return None, 0.0
        n = int(2 ** np.ceil(np.log2(len(x) * 2)))
        win = np.hanning(len(x))
        X = np.fft.rfft(x * win, n=n)
        f = np.fft.rfftfreq(n, 1/self.fs)
        m = (f >= self.band[0]) & (f <= self.band[1])
        if not np.any(m):
            return None, 0.0
        mag = np.abs(X[m])
        fi = f[m]
        pk = np.argmax(mag)
        hr = fi[pk] * 60.0
        conf = float(np.max(mag) / (np.mean(mag) + 1e-8))
        return hr, float(np.clip(conf/10.0, 0.0, 1.0))


class RespEstimator:
    def __init__(self, fs):
        self.fs = fs
        self.band = (0.1, 0.5)
        self.sos = signal.butter(4, self.band, btype='band', fs=self.fs, output='sos')

    def detrend_bandpass(self, x):
        x = x - np.mean(x)
        return signal.sosfilt(self.sos, x)

    def rr_fft(self, x):
        if len(x) < int(12 * self.fs):
            return None, 0.0
        n = int(2 ** np.ceil(np.log2(len(x) * 2)))
        win = np.hanning(len(x))
        X = np.fft.rfft(x * win, n=n)
        f = np.fft.rfftfreq(n, 1/self.fs)
        m = (f >= self.band[0]) & (f <= self.band[1])
        if not np.any(m):
            return None, 0.0
        mag = np.abs(X[m])
        fi = f[m]
        pk = np.argmax(mag)
        rr = fi[pk] * 60.0
        conf = float(np.max(mag) / (np.mean(mag) + 1e-8))
        return rr, float(np.clip(conf/10.0, 0.0, 1.0))


class MonitorUI:
    def __init__(self, up_scale: int, fs: float):
        self.up_scale = up_scale
        self.fs = fs
        self.hr_hist = deque(maxlen=240)
        self.qual_hist = deque(maxlen=240)
        self.last_tick = time.time()
        self.fps = 0.0
        self.window_name = 'Thermal rPPG Monitor'
        self.compare_mode = 'SR'
        self.status_text = ''
        self._ui_tick = 0
        self.ui_stride = 1  # 필요시 2~3으로 조절(부하 감소)
        try:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        except Exception:
            logger.warning("Cannot create window (headless?). UI disabled.")

    def _draw_chart(self, canvas, series: deque, rect, y_min: float, y_max: float, label: str):
        x0, y0, w, h = rect
        cv2.rectangle(canvas, (x0, y0), (x0+w, y0+h), (40, 40, 40), 1)
        if len(series) < 2:
            cv2.putText(canvas, f"{label}: --", (x0+5, y0+15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230,230,230), 1)
            return
        vals = np.array(series, dtype=np.float32)
        vals = np.clip((vals - y_min) / max(1e-6, (y_max - y_min)), 0, 1)
        xs = np.linspace(0, w-1, len(vals)).astype(int)
        ys = (y0 + h - (vals * (h-2)).astype(int) - 1)
        pts = np.stack([x0+xs, ys], axis=1)
        for i in range(1, len(pts)):
            cv2.line(canvas, tuple(pts[i-1]), tuple(pts[i]), (200, 200, 200), 1)
        cv2.putText(canvas, f"{label}: {series[-1]:.1f}", (x0+5, y0+15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230,230,230), 1)

    def update(self, thermal_u8_lr: np.ndarray, bbox, roi_boxes, hr: Optional[float], q: float,
               rr: Optional[float], dT_nose: Optional[float], dT_cheek: Optional[float],
               samples: int, thermal_u8_sr: Optional[np.ndarray] = None, tracking_ok: bool = True,
               color_rec = None):
        self._ui_tick += 1
        if self._ui_tick % max(1, int(self.ui_stride)) != 0:
            return None

        now = time.time()
        dt = now - self.last_tick
        if dt > 0:
            self.fps = 0.9*self.fps + 0.1*(1.0/dt)
        self.last_tick = now

        vis_lr = cv2.applyColorMap(thermal_u8_lr, cv2.COLORMAP_INFERNO)
        vis_sr = cv2.applyColorMap(thermal_u8_sr if thermal_u8_sr is not None else thermal_u8_lr, cv2.COLORMAP_INFERNO)

        def overlay(vis):
            if bbox is not None:
                x, y, w, h = bbox
                cv2.rectangle(vis, (x, y), (x+w, y+h), (0, 255, 255), 2)
            for name, (rx, ry, rw, rh) in roi_boxes.items():
                color = (0, 255, 0) if 'cheek' in name or name == 'forehead' else (0, 200, 255)
                cv2.rectangle(vis, (rx, ry), (rx+rw, ry+rh), color, 1)
                cv2.putText(vis, name, (rx, ry-4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
            return vis

        vis_lr = overlay(vis_lr)
        vis_sr = overlay(vis_sr)

        base = np.hstack([vis_lr, vis_sr]) if self.compare_mode == 'SPLIT' else (vis_lr if self.compare_mode == 'LR' else vis_sr)
        h, w = base.shape[:2]
        panel_w = 260
        panel = np.zeros((h, panel_w, 3), dtype=np.uint8)
        panel[:] = (25, 25, 25)

        if hr is not None:
            self.hr_hist.append(hr)
        self.qual_hist.append(q)
        self._draw_chart(panel, self.hr_hist, (10, 10, panel_w-20, 80), 45, 120, "HR(BPM)")
        self._draw_chart(panel, self.qual_hist, (10, 100, panel_w-20, 60), 0, 1, "Quality")

        # 안전한 시작 위치(패널 높이에 맞춰 clamp)
        line = max(10, min(h - 60, 180))

        def put(k, v):
            nonlocal line
            # 한 항목당 약 42px
            if line + 42 > h:
                return False
            cv2.putText(panel, f"{k}", (10, line), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180,180,180), 1)
            line += 18
            cv2.putText(panel, f"{v}", (20, line), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240,240,240), 1)
            line += 24
            return True

        put("Samples", samples)
        put("FPS", f"{self.fps:.1f}")
        put("Quality q", f"{q:.2f}")
        put("RR (brpm)", f"{rr:.1f}" if rr is not None else "--")
        put("ΔT_nose", f"{dT_nose:+.2f}°C" if dT_nose is not None else "--")
        put("ΔT_cheeks", f"{dT_cheek:+.2f}°C" if dT_cheek is not None else "--")
        put("View", self.compare_mode)
        put("Keys", "Q:quit  S:snap  T:view")
        put("Track", "OK" if tracking_ok else "LOST")

        if color_rec is not None:
            if line + 18 < h:
                cv2.putText(panel, f"Therapy: {color_rec.mode}", (10, line),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180,180,180), 1)
                line += 18
            if line + 40 <= h:
                swatch = np.zeros((40, 40, 3), dtype=np.uint8)
                r, g, b = color_rec.rgb_primary
                swatch[:] = (b, g, r)
                panel[line:line+40, 10:50] = swatch
                if line + 25 < h:
                    cv2.putText(panel, f"RGB{color_rec.rgb_primary} I={color_rec.intensity:.2f}",
                                (60, line+25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240,240,240), 1)
                line += 50

        out = np.hstack([base, panel])
        try:
            cv2.imshow(self.window_name, out)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                return 'quit'
            elif key == ord('s'):
                ts = time.strftime('%Y%m%d_%H%M%S')
                cv2.imwrite(f'thermal_snap_{ts}.png', out)
            elif key == ord('t'):
                self.compare_mode = {'SR': 'LR', 'LR': 'SPLIT', 'SPLIT': 'SR'}[self.compare_mode]
        except Exception:
            pass
        return None


class ThermalrPPG:
    def __init__(self, cfg: ThermalrPPGConfig, mqtt_pub: Optional[MqttColorPublisher] = None):
        self.cfg = cfg
        self.sensor = MLX9064XInterface(refresh_hz=int(cfg.sampling_rate))
        self.detector = ThermalFaceDetector()
        self.motion = MotionCompensator()
        self.motion.mc_stride = cfg.mc_stride   # stride 적용
        self.roi = ROIManager()
        self.proc = SignalProc(cfg.sampling_rate)
        self.resp = RespEstimator(cfg.sampling_rate)
        self.buffers: Dict[str, deque] = {}
        self.start_t = None

        self.up_scale = 6
        self.mfsr = MultiFrameSuperRes(
            scale=cfg.superres_scale,
            max_frames=cfg.superres_frames,
            deconvolution=cfg.superres_deconvolution
        ) if cfg.enable_superres else None
        self._sr_count = 0

        self.monitor = MonitorUI(self.up_scale, cfg.sampling_rate) if cfg.debug_visual else None
        if self.monitor is not None:
            self.monitor.ui_stride = 1  # 필요시 2~3으로 올려 부하 감소

        self.therapist = ColorTherapist()
        self.mqtt = mqtt_pub
        self._hr_next_ts = 0.0
        self._rr_next_ts = 0.0
        self._last_status = {'ts': 0.0, 'hr': None, 'rr': None, 'q': None, 'dtn': None, 'dtc': None}
        logger.info(f"Config: sampling={cfg.sampling_rate}Hz, mode={cfg.processing_mode.value}")

    def _append(self, roi_vals: Dict[str, float]):
        for k, v in roi_vals.items():
            if k not in self.buffers:
                self.buffers[k] = deque(maxlen=2048)
            self.buffers[k].append(v)

    def _enough(self):
        need = int(self.cfg.sampling_rate * max(8, self.cfg.min_measurement_duration))
        return any(len(buf) >= need for buf in self.buffers.values())

    def _compute_hr(self):
        hrs, qs = [], []
        for name, buf in self.buffers.items():
            x = np.array(buf, dtype=np.float32)
            x = self.proc.detrend_bandpass(x)
            hr, conf = self.proc.hr_fft(x)
            if hr is not None:
                hrs.append(hr)
                qs.append(conf)
        if not hrs:
            return None, 0.0
        w = np.array(qs)
        w = w / (w.sum() + 1e-6)
        return float(np.sum(np.array(hrs) * w)), float(np.mean(qs))

    def _compute_rr(self):
        if 'nose' not in self.buffers or len(self.buffers['nose']) < int(12*self.cfg.sampling_rate):
            return None, 0.0
        x = np.array(self.buffers['nose'], dtype=np.float32)
        x = self.resp.detrend_bandpass(x)
        return self.resp.rr_fft(x)

    def _compute_dT(self, win_sec: int = 5):
        fs = self.cfg.sampling_rate
        n = int(fs * win_sec)

        def mean_last(name):
            if name not in self.buffers or len(self.buffers[name]) < max(4, n):
                return None
            arr = np.array(self.buffers[name], dtype=np.float32)[-n:]
            return float(np.mean(arr))

        fh = mean_last('forehead')
        nose = mean_last('nose')
        lch = mean_last('l_cheek')
        rch = mean_last('r_cheek')
        if fh is None:
            return None, None, None
        dT_nose = (nose - fh) if nose is not None else None
        dT_cheek = ((lch + rch)/2.0 - fh) if (lch is not None and rch is not None) else None
        return dT_nose, dT_cheek, fh

    def _maybe_status(self, hr, q, rr, dT_nose, dT_cheek, color_rec):
        now = time.time()
        st = self._last_status

        def changed(a, b, th):
            if a is None or b is None:
                return False
            return abs(a - b) >= th

        if (now - st['ts'] >= self.cfg.status_interval) or \
           changed(hr, st['hr'], self.cfg.min_change_hr) or \
           changed(rr, st['rr'], self.cfg.min_change_rr) or \
           changed(q,  st['q'],  self.cfg.min_change_q):
            rr_txt = f"{rr:.1f}" if rr is not None else "--"
            dtn_txt = f"{dT_nose:+.2f}" if dT_nose is not None else "--"
            dtc_txt = f"{dT_cheek:+.2f}" if dT_cheek is not None else "--"
            mode = color_rec.mode if color_rec else "--"
            rgb = color_rec.rgb_primary if color_rec else (0, 0, 0)
            inten = color_rec.intensity if color_rec else 0.0
            dur = color_rec.duration_seconds if color_rec else 0
            logger.info(
                f"🫀 {hr if hr is not None else float('nan'):.1f} BPM | q={q:.2f} | "
                f"🌬 {rr_txt} brpm | ΔT_nose {dtn_txt} ΔT_cheek {dtc_txt} | "
                f"🎨 {mode} RGB{rgb} I={inten:.2f} {dur}s"
            )
            st.update({'ts': now, 'hr': hr, 'rr': rr, 'q': q, 'dtn': dT_nose, 'dtc': dT_cheek})

    def run(self):
        self.start_t = time.time()
        try:
            while True:
                frame = self.sensor.read_frame()
                if frame is None:
                    time.sleep(0.001)
                    continue
                H, W = frame.shape

                # MFSR: stride로 빌드
                sr = None
                if self.mfsr is not None:
                    self.mfsr.push(frame)
                    self._sr_count += 1
                    if (self._sr_count % max(1, int(self.cfg.sr_stride))) == 0:
                        sr = self.mfsr.build()

                proc = sr if sr is not None else frame
                up = cv2.resize(proc, (W*self.up_scale, H*self.up_scale), interpolation=cv2.INTER_CUBIC)
                up_lr = cv2.resize(frame, (W*self.up_scale, H*self.up_scale), interpolation=cv2.INTER_CUBIC)

                bbox = self.detector.detect(up)
                tracking_ok = bbox is not None and self.detector.missed == 0

                if self.cfg.enable_motion_compensation and bbox is not None:
                    up = self.motion.compensate(up, bbox)
                    up_lr = self.motion.compensate(up_lr, bbox)

                roi_vals, roi_boxes = self.roi.extract(up, bbox)
                if roi_vals:
                    self._append(roi_vals)

                now = time.time()
                hr, q = (None, 0.0)
                if self._enough() and now >= self._hr_next_ts:
                    hr, q = self._compute_hr()
                    self._hr_next_ts = now + self.cfg.hr_period

                rr, rrq = (None, 0.0)
                if now >= self._rr_next_ts:
                    rr, rrq = self._compute_rr()
                    self._rr_next_ts = now + self.cfg.rr_period

                dT_nose, dT_cheek, fh_temp = self._compute_dT(win_sec=5)

                color_rec = None
                if hr is not None:
                    color_rec = self.therapist.recommend(
                        ColorMetrics(hr=hr, q=q, rr=rr, dT_nose=dT_nose, dT_cheek=dT_cheek, forehead_temp=fh_temp)
                    )

                    # 로그 스로틀
                    self._maybe_status(hr, q, rr, dT_nose, dT_cheek, color_rec)

                    # MQTT 발행(q 낮으면 생략)
                    if self.mqtt is not None and q >= self.cfg.mqtt_quality_min:
                        self.mqtt.publish_color(color_rec, metrics={
                            "hr": hr, "rr": rr, "q": q,
                            "dT_nose": dT_nose, "dT_cheek": dT_cheek, "forehead": fh_temp
                        }, also_pico=True)

                if self.monitor is not None:
                    thermal_u8_sr = normalize_to_uint8(up)
                    thermal_u8_lr = normalize_to_uint8(up_lr)
                    samples = max((len(b) for b in self.buffers.values()), default=0)
                    action = self.monitor.update(
                        thermal_u8_lr, bbox, roi_boxes, hr, q, rr, dT_nose, dT_cheek,
                        samples, thermal_u8_sr, tracking_ok, color_rec=color_rec
                    )
                    if action == 'quit':
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self.sensor.close()
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass


if __name__ == "__main__":
    cfg = ThermalrPPGConfig(
        sampling_rate=16.0,
        min_measurement_duration=12,
        enable_motion_compensation=True,
        debug_visual=True,
        enable_superres=True,
        superres_scale=2,
        superres_frames=12,
        superres_deconvolution=True,

        # 필요시 아래 값들로 로그/부하를 더 줄일 수 있음
        status_interval=2.0,
        hr_period=0.75,
        rr_period=2.0,
        sr_stride=3,
        mc_stride=2,
        mqtt_quality_min=0.35,
    )
    mqtt_pub = None
    try:
        mqtt_pub = MqttColorPublisher().connect()
    except Exception as e:
        logger.warning(f"MQTT disabled ({e}). Running without publish.")
    rppg = ThermalrPPG(cfg, mqtt_pub=mqtt_pub)
    print("Starting thermal rPPG (MLX9064X)… Press Q to quit, S to snapshot, T to toggle view (SR/LR/SPLIT).")
    print("Tip: With 55°×35° FOV, keep ~20–25 cm distance for big face in LR; SR x2 lets you move to ~35–40 cm.")
    rppg.run()
    if mqtt_pub:
        mqtt_pub.close()
