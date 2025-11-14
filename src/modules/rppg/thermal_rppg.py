# Thermal rPPG pipeline (MLX90640/90641) + MFSR + PresenceGate + UI + MQTT
# Run (from project root above src/):
#   cd src
#   python -m modules.rppg.thermal_rppg

import time, logging, warnings
import os
from dataclasses import dataclass
from enum import Enum
from collections import deque, Counter
from typing import Tuple, Dict, Optional, Any

import numpy as np
import cv2
from scipy import signal
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
import pickle

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("thermal_rppg")

# Absolute imports for your project layout
# src/modules/rppg/thermal_rppg.py
# src/modules/rppg/color_therapy_adapter.py
# src/networks/mqtt/mqtt_publisher.py
from modules.rppg.color_therapy_adapter import ColorTherapist, ColorMetrics
from networks.mqtt.mqtt_publisher import MqttColorPublisher

# --------------------- Sensor backend detection ---------------------
MLX_BACKEND = None
SENSOR_MODEL = None
RESOLUTION = (24, 32)  # default
FRAME_LEN = RESOLUTION[0] * RESOLUTION[1]

try:
    import board, busio
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
    target_hr_range: Tuple[float, float] = (0.7, 3.5)  # up to 240 bpm
    processing_mode: ProcessingMode = ProcessingMode.HIGH_ACCURACY
    enable_motion_compensation: bool = True
    debug_visual: bool = True
    
    # Super-resolution
    enable_superres: bool = True
    superres_scale: int = 2
    superres_frames: int = 12
    superres_deconvolution: bool = True

    # Logging / compute throttling
    status_interval: float = 2.0
    min_change_hr: float = 1.0
    min_change_rr: float = 1.0
    min_change_q: float = 0.05
    mqtt_quality_min: float = 0.1
    hr_period: float = 0.75
    rr_period: float = 2.0
    sr_stride: int = 3
    mc_stride: int = 2

    # Ambient compensation & artifacts
    ambient_comp: bool = False
    ambient_alpha: float = 0.02
    ambient_gain: float = 0.8
    persp_drop_degC: float = 0.30
    persp_window_sec: float = 2.5
    persp_hold_sec: float = 10.0
    motion_px_warn: float = 6.0
    snr_min: float = 1.6

    # Presence (face) gate - 더 관대한 온도 범위
    temp_face_min: float = 26.0  # 더 낮은 최소 온도
    temp_face_max: float = 42.0  # 더 높은 최대 온도
    min_ambient_delta: float = 0.0  # ambient 델타 요구사항 완화
    snr_face_min: float = 1.5
    hr_agreement_bpm: float = 10.0
    harmonic_min_ratio: float = 0.08
    present_rise_frames: int = 6   # 0.75s @16Hz
    present_fall_frames: int = 6    # 0.5s @16Hz
    absent_buffer_sec: float = 3.0  # keep only this much history when absent
    hr_slope_bpm_per_s: float = 15.0   # 초당 허용 변화량
    hr_ema_alpha: float = 0.2          # 저역 평활(0..1)
    sensor_rotation_deg: float = 0.0   # +값=반시계(CCW). 예) 135.0
    
    # AI Enhancement parameters
    enable_ensemble_learning: bool = True
    enable_wavelet_denoising: bool = True
    enable_adaptive_filtering: bool = True
    enable_personalized_model: bool = True
    model_update_interval: float = 300.0  # 5분마다 모델 업데이트
    
    # Raspberry Pi optimization parameters
    enable_pi_optimization: bool = True
    pi_memory_limit_mb: int = 512  # 메모리 사용량 제한
    pi_cpu_throttle: bool = True   # CPU 부하 제한
    pi_reduced_precision: bool = True  # 정밀도 감소로 성능 향상
    
    # Fast measurement parameters
    enable_fast_mode: bool = False
    fast_min_duration: int = 6      # 빠른 모드 최소 측정 시간 (초)
    fast_hr_period: float = 0.5     # 빠른 모드 HR 계산 주기
    fast_present_frames: int = 3    # 빠른 모드 얼굴 인식 프레임
    fast_sampling_rate: float = 20.0 # 빠른 모드 샘플링 레이트

    # Session management parameters
    session_min_duration: float = 45.0   # 한 세션 최소 측정 시간 (초)
    session_max_duration: float = 75.0   # 한 세션 최대 유지 시간 (초) - 무조건 75초에 종료
    session_quality_target: float = 0.55 # 최종 확정에 필요한 품질
    session_quality_min: float = 0.45    # 후보로 인정되는 최소 품질
    session_roi_quality_min: float = 0.25  # 품질 기준 완화 (0.35 → 0.25) - 신호 약할 때도 측정 가능
    session_roi_max_count: int = 2
    
    # Real-time MQTT publishing (세션 완료 전에도 주기적으로 전송)
    enable_realtime_mqtt: bool = True     # 실시간 MQTT 전송 활성화
    realtime_mqtt_interval: float = 5.0  # 실시간 전송 주기 (초)
    realtime_mqtt_quality_min: float = 0.3  # 실시간 전송 최소 품질
    
    # Face detection enhancement parameters
    enable_face_preprocessing: bool = True  # 전처리 파이프라인 활성화
    enable_dead_pixel_removal: bool = True  # Dead pixel 제거
    enable_clahe: bool = True  # CLAHE contrast enhancement
    enable_bilateral_filter: bool = False  # Bilateral filtering (느리지만 노이즈 제거 효과)
    clahe_clip_limit: float = 2.0  # CLAHE clip limit
    clahe_tile_size: int = 8  # CLAHE tile grid size
    face_temp_range: Tuple[float, float] = (26.0, 38.0)  # 얼굴 온도 검증 범위 (°C) - 확대
    enable_kcf_tracking: bool = False  # KCF 추적기 사용 (템플릿 매칭 대신)
    
    # ROI extraction parameters
    roi_patch_size: int = 6  # ROI 중심 패치 크기 (기본값 3 → 6으로 확대)
    roi_use_weighted_mean: bool = True  # ROI 전체 평균과 중심 패치 가중 평균 사용
    roi_center_weight: float = 0.9  # 중심 패치 가중치 (0.9 = 중심 90% + 전체 10%) - 신호 강조
    roi_dynamic_positioning: bool = True  # 온도 분포 기반 ROI 위치 동적 조정
    roi_use_center_only: bool = False  # True면 중심 패치만 사용 (가중 평균 대신)
    
    # Upscaling parameters
    up_scale: int = 3  # 얼굴 탐지 및 ROI 추출용 업스케일 배수 (3-6 권장, 카메라 거리에 따라 조정)
    
    # UI display parameters
    ui_scale: float = 2.5  # 모니터링 화면 확대 배수 (1.0=기본, 2.0=2배, 2.5=2.5배 등)
    ui_window_width: Optional[int] = None  # 창 초기 너비 (None이면 자동, 권장: 1280-1920)
    ui_window_height: Optional[int] = None  # 창 초기 높이 (None이면 자동, 권장: 720-1080)


# --------------------- AI Enhancement Classes ---------------------
class WaveletDenoiser:
    """웨이블릿 변환을 이용한 적응형 노이즈 제거"""
    def __init__(self, wavelet='db4', threshold_mode='soft'):
        self.wavelet = wavelet
        self.threshold_mode = threshold_mode
        self.threshold_history = deque(maxlen=100)
        
    def denoise_signal(self, signal, noise_variance=None):
        """웨이블릿 기반 노이즈 제거"""
        try:
            from pywt import wavedec, waverec, threshold
            
            # 웨이블릿 분해
            coeffs = wavedec(signal, self.wavelet, mode='symmetric')
            
            # 적응형 임계값 계산
            if noise_variance is None:
                # 첫 번째 디테일 계수에서 노이즈 분산 추정
                sigma = np.median(np.abs(coeffs[-1])) / 0.6745
            else:
                sigma = np.sqrt(noise_variance)
            
            # 임계값 계산 (BayesShrink 방식)
            threshold_val = sigma * np.sqrt(2 * np.log(len(signal)))
            self.threshold_history.append(threshold_val)
            
            # 임계값 적용
            coeffs_thresh = []
            coeffs_thresh.append(coeffs[0])  # 근사 계수는 그대로
            
            for detail in coeffs[1:]:
                coeffs_thresh.append(threshold(detail, threshold_val, self.threshold_mode))
            
            # 역변환
            denoised = waverec(coeffs_thresh, self.wavelet)
            
            return denoised[:len(signal)]  # 길이 맞춤
            
        except ImportError:
            logger.warning("PyWavelets not available. Using basic filtering.")
            return signal
        except Exception as e:
            logger.warning(f"Wavelet denoising failed: {e}")
            return signal


class AdaptiveKalmanFilter:
    """적응형 칼만 필터를 이용한 HR 추정"""
    def __init__(self, process_noise=0.01, measurement_noise=0.1):
        self.Q = process_noise  # 프로세스 노이즈
        self.R = measurement_noise  # 측정 노이즈
        self.x = 0.0  # 상태 (HR)
        self.P = 1.0  # 오차 공분산
        self.initialized = False
        
    def update(self, measurement, dt=1.0):
        """측정값으로 상태 업데이트"""
        if not self.initialized:
            self.x = measurement
            self.initialized = True
            return self.x
            
        # 예측 단계
        F = 1.0  # 상태 전이 행렬 (HR은 일정하다고 가정)
        self.x = F * self.x
        self.P = F * self.P * F + self.Q * dt
        
        # 업데이트 단계
        H = 1.0  # 측정 행렬
        y = measurement - H * self.x  # 잔차
        S = H * self.P * H + self.R  # 잔차 공분산
        K = self.P * H / S  # 칼만 게인
        
        self.x = self.x + K * y
        self.P = (1 - K * H) * self.P
        
        return self.x
    
    def adapt_noise(self, innovation_history):
        """혁신 시퀀스를 이용한 노이즈 적응"""
        if len(innovation_history) < 10:
            return
            
        # 혁신의 분산으로 측정 노이즈 추정
        innovation_var = np.var(innovation_history)
        self.R = max(0.01, min(1.0, innovation_var))


class EnsembleROIOptimizer:
    """앙상블 학습을 이용한 ROI 가중치 최적화"""
    def __init__(self, pi_optimizer=None):
        # 라즈베리파이 최적화 적용
        if pi_optimizer and pi_optimizer.is_pi:
            n_estimators = 20  # 라즈베리파이용으로 축소
            max_history = 200
        else:
            n_estimators = 50  # 기본값
            max_history = 1000
            
        self.rf_model = RandomForestRegressor(n_estimators=n_estimators, random_state=42)
        self.gb_model = GradientBoostingRegressor(n_estimators=n_estimators, random_state=42)
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_history = deque(maxlen=max_history)
        self.target_history = deque(maxlen=max_history)
        self.pi_optimizer = pi_optimizer
        
    def extract_features(self, roi_diag, motion_level, ambient_temp):
        """ROI 진단 정보에서 특징 추출"""
        features = []
        
        roi_names = ['forehead', 'l_cheek', 'r_cheek', 'nose']
        for name in roi_names:
            roi_data = roi_diag.get(name, {})
            features.extend([
                roi_data.get('snr', 0.0),
                roi_data.get('q', 0.0),
                roi_data.get('harm', 0.0),
                roi_data.get('hr', 0.0)
            ])
        
        # 전체 통계
        snrs = [roi_diag.get(name, {}).get('snr', 0.0) for name in roi_names]
        hrs = [roi_diag.get(name, {}).get('hr', 0.0) for name in roi_names]
        
        features.extend([
            np.mean(snrs),
            np.std(snrs),
            np.mean(hrs),
            np.std(hrs),
            motion_level,
            ambient_temp
        ])
        
        return np.array(features)
    
    def update_model(self, roi_diag, motion_level, ambient_temp, true_hr=None):
        """모델 업데이트 (온라인 학습)"""
        features = self.extract_features(roi_diag, motion_level, ambient_temp)
        self.feature_history.append(features)
        
        if true_hr is not None:
            self.target_history.append(true_hr)
            
            # 충분한 데이터가 쌓이면 모델 재훈련
            if len(self.target_history) >= 50 and len(self.target_history) % 20 == 0:
                self._retrain_model()
    
    def _retrain_model(self):
        """앙상블 모델 재훈련"""
        if len(self.feature_history) < 20:
            return
            
        X = np.array(list(self.feature_history))
        y = np.array(list(self.target_history))
        
        try:
            X_scaled = self.scaler.fit_transform(X)
            self.rf_model.fit(X_scaled, y)
            self.gb_model.fit(X_scaled, y)
            self.is_trained = True
            logger.info(f"Ensemble model retrained with {len(y)} samples")
        except Exception as e:
            logger.warning(f"Model retraining failed: {e}")
    
    def predict_optimal_weights(self, roi_diag, motion_level, ambient_temp):
        """최적 ROI 가중치 예측"""
        if not self.is_trained:
            return self._default_weights(roi_diag)
            
        features = self.extract_features(roi_diag, motion_level, ambient_temp)
        features_scaled = self.scaler.transform(features.reshape(1, -1))
        
        # 앙상블 예측
        rf_pred = self.rf_model.predict(features_scaled)[0]
        gb_pred = self.gb_model.predict(features_scaled)[0]
        ensemble_pred = (rf_pred + gb_pred) / 2
        
        # 예측된 HR과 실제 ROI HR의 차이로 가중치 계산
        roi_names = ['forehead', 'l_cheek', 'r_cheek', 'nose']
        weights = {}
        
        for name in roi_names:
            roi_hr = roi_diag.get(name, {}).get('hr', 0.0)
            if roi_hr > 0:
                # 예측값과의 차이가 작을수록 높은 가중치
                error = abs(roi_hr - ensemble_pred)
                weight = np.exp(-error / 10.0)  # 지수 감쇠
                weights[name] = max(0.1, min(2.0, weight))
            else:
                weights[name] = 0.1
                
        return weights
    
    def _default_weights(self, roi_diag):
        """기본 가중치 (모델이 훈련되지 않았을 때)"""
        roi_names = ['forehead', 'l_cheek', 'r_cheek', 'nose']
        weights = {}
        
        for name in roi_names:
            roi_data = roi_diag.get(name, {})
            snr = roi_data.get('snr', 0.0)
            q = roi_data.get('q', 0.0)
            
            # SNR과 품질 기반 기본 가중치
            weight = 1.0
            if snr > 2.0:
                weight *= 1.2
            elif snr < 1.0:
                weight *= 0.8
                
            if q > 0.7:
                weight *= 1.1
            elif q < 0.3:
                weight *= 0.9
                
            weights[name] = max(0.1, min(2.0, weight))
            
        return weights


class PersonalizedBiometricModel:
    """개인화된 생체신호 모델"""
    def __init__(self):
        self.user_profile = {
            'baseline_hr': None,
            'hr_variability': None,
            'thermal_patterns': {},
            'adaptation_rate': 0.1
        }
        self.adaptation_history = deque(maxlen=500)
        
    def update_profile(self, hr, thermal_features, ambient_conditions):
        """사용자 프로필 업데이트"""
        if hr is None:
            return
            
        self.adaptation_history.append({
            'hr': hr,
            'thermal_features': thermal_features,
            'ambient': ambient_conditions,
            'timestamp': time.time()
        })
        
        # 베이스라인 HR 업데이트
        if self.user_profile['baseline_hr'] is None:
            self.user_profile['baseline_hr'] = hr
        else:
            alpha = self.user_profile['adaptation_rate']
            self.user_profile['baseline_hr'] = (
                (1 - alpha) * self.user_profile['baseline_hr'] + alpha * hr
            )
        
        # HR 변동성 계산
        if len(self.adaptation_history) >= 30:
            hrs = [h['hr'] for h in list(self.adaptation_history)[-30:]]
            self.user_profile['hr_variability'] = np.std(hrs)
    
    def get_personalized_correction(self, raw_hr, thermal_features):
        """개인화된 보정값 반환"""
        if self.user_profile['baseline_hr'] is None:
            return raw_hr
            
        baseline = self.user_profile['baseline_hr']
        variability = self.user_profile['hr_variability'] or 5.0
        
        # 개인별 특성에 따른 보정
        correction_factor = 1.0
        
        # 베이스라인에서 크게 벗어나면 보정
        hr_diff = abs(raw_hr - baseline)
        if hr_diff > variability * 2:
            correction_factor = 0.8  # 급격한 변화 억제
        
        return raw_hr * correction_factor + baseline * (1 - correction_factor)


class RaspberryPiOptimizer:
    """라즈베리파이 최적화 클래스"""
    def __init__(self, cfg: ThermalrPPGConfig):
        self.cfg = cfg
        self.memory_monitor = deque(maxlen=100)
        self.cpu_monitor = deque(maxlen=100)
        self.is_pi = self._detect_raspberry_pi()
        
        if self.is_pi:
            logger.info("Raspberry Pi detected. Enabling optimizations.")
            self._apply_pi_optimizations()
    
    def _detect_raspberry_pi(self):
        """라즈베리파이 감지"""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                cpuinfo = f.read()
                return 'BCM' in cpuinfo or 'Raspberry Pi' in cpuinfo
        except:
            return False
    
    def _apply_pi_optimizations(self):
        """라즈베리파이 최적화 적용"""
        if not self.cfg.enable_pi_optimization:
            return
            
        # NumPy 최적화
        try:
            import numpy as np
            # BLAS 라이브러리 최적화
            os.environ['OPENBLAS_NUM_THREADS'] = '2'
            os.environ['MKL_NUM_THREADS'] = '2'
            os.environ['NUMEXPR_NUM_THREADS'] = '2'
            os.environ['OMP_NUM_THREADS'] = '2'
        except:
            pass
    
    def monitor_resources(self):
        """리소스 모니터링"""
        if not self.is_pi:
            return
            
        try:
            import psutil
            memory_percent = psutil.virtual_memory().percent
            cpu_percent = psutil.cpu_percent()
            
            self.memory_monitor.append(memory_percent)
            self.cpu_monitor.append(cpu_percent)
            
            # 메모리 사용량이 높으면 경고
            if memory_percent > 85:
                logger.warning(f"High memory usage: {memory_percent:.1f}%")
                return True  # 최적화 필요
                
            # CPU 사용량이 높으면 경고
            if cpu_percent > 90:
                logger.warning(f"High CPU usage: {cpu_percent:.1f}%")
                return True  # 최적화 필요
                
        except ImportError:
            pass
            
        return False
    
    def optimize_for_pi(self, model_config):
        """라즈베리파이용 모델 설정 최적화"""
        if not self.is_pi or not self.cfg.enable_pi_optimization:
            return model_config
            
        # 메모리 사용량 제한
        if hasattr(model_config, 'n_estimators'):
            model_config.n_estimators = min(model_config.n_estimators, 20)  # 기본 50에서 20으로
            
        # 히스토리 크기 제한
        if hasattr(model_config, 'maxlen'):
            model_config.maxlen = min(model_config.maxlen, 200)  # 기본 1000에서 200으로
            
        return model_config
    
    def get_optimized_config(self):
        """라즈베리파이용 최적화된 설정 반환"""
        if not self.is_pi:
            return {}
            
        return {
            'reduced_precision': self.cfg.pi_reduced_precision,
            'memory_limit': self.cfg.pi_memory_limit_mb,
            'cpu_throttle': self.cfg.pi_cpu_throttle,
            'smaller_models': True,
            'reduced_history': True
        }


class FastMeasurementMode:
    """빠른 측정 모드 클래스"""
    def __init__(self, cfg: ThermalrPPGConfig):
        self.cfg = cfg
        self.is_active = cfg.enable_fast_mode
        self.measurement_start_time = None
        self.first_hr_time = None
        self.first_rr_time = None
        
        if self.is_active:
            logger.info("Fast measurement mode enabled")
            self._apply_fast_settings()
    
    def _apply_fast_settings(self):
        """빠른 측정을 위한 설정 적용"""
        # 설정값들을 빠른 모드로 변경
        self.cfg.min_measurement_duration = self.cfg.fast_min_duration
        self.cfg.hr_period = self.cfg.fast_hr_period
        self.cfg.present_rise_frames = self.cfg.fast_present_frames
        self.cfg.sampling_rate = self.cfg.fast_sampling_rate
        
        logger.info(f"Fast mode settings: min_duration={self.cfg.min_measurement_duration}s, "
                   f"hr_period={self.cfg.hr_period}s, sampling={self.cfg.sampling_rate}Hz")
    
    def start_measurement(self):
        """측정 시작 시간 기록"""
        self.measurement_start_time = time.time()
        logger.info("Fast measurement started")
    
    def get_elapsed_time(self):
        """경과 시간 반환"""
        if self.measurement_start_time is None:
            return 0.0
        return time.time() - self.measurement_start_time
    
    def record_first_hr(self):
        """첫 HR 측정 시간 기록"""
        if self.first_hr_time is None:
            self.first_hr_time = time.time()
            elapsed = self.get_elapsed_time()
            logger.info(f"First HR measurement: {elapsed:.2f}s")
    
    def record_first_rr(self):
        """첫 RR 측정 시간 기록"""
        if self.first_rr_time is None:
            self.first_rr_time = time.time()
            elapsed = self.get_elapsed_time()
            logger.info(f"First RR measurement: {elapsed:.2f}s")
    
    def get_measurement_stats(self):
        """측정 통계 반환"""
        if self.measurement_start_time is None:
            return {}
        
        stats = {
            'total_elapsed': self.get_elapsed_time(),
            'first_hr_time': None,
            'first_rr_time': None
        }
        
        if self.first_hr_time:
            stats['first_hr_time'] = self.first_hr_time - self.measurement_start_time
        
        if self.first_rr_time:
            stats['first_rr_time'] = self.first_rr_time - self.measurement_start_time
        
        return stats


# --------------------- Utils ---------------------
def normalize_to_uint8(temp_frame, p_low=5, p_high=95, face_bbox=None):
    """
    온도 프레임을 uint8로 정규화
    얼굴 영역이 있으면 해당 영역의 percentile 사용 (더 좁은 범위로 신호 강조)
    """
    if face_bbox is not None:
        x, y, w, h = face_bbox
        x = max(0, min(x, temp_frame.shape[1] - 1))
        y = max(0, min(y, temp_frame.shape[0] - 1))
        w = min(w, temp_frame.shape[1] - x)
        h = min(h, temp_frame.shape[0] - y)
        if w > 0 and h > 0:
            face_region = temp_frame[y:y+h, x:x+w]
            # 얼굴 영역의 percentile 사용 (더 좁은 범위)
            lo = np.percentile(face_region, p_low)
            hi = np.percentile(face_region, p_high)
            # 전체 프레임 범위와 조합
            frame_lo = np.percentile(temp_frame, p_low)
            frame_hi = np.percentile(temp_frame, p_high)
            lo = min(lo, frame_lo)
            hi = max(hi, frame_hi)
        else:
            lo = np.percentile(temp_frame, p_low)
            hi = np.percentile(temp_frame, p_high)
    else:
        lo = np.percentile(temp_frame, p_low)
        hi = np.percentile(temp_frame, p_high)
    
    if hi <= lo:
        hi = lo + 1e-3
    im = np.clip((temp_frame - lo) / (hi - lo), 0, 1)
    return (im * 255).astype(np.uint8)


# --------------------- Sensor interface ---------------------
class MLX9064XInterface:
    def __init__(self, i2c_frequency=800_000, refresh_hz=16):
        self.i2c = None
        self.sensor = None
        self.is_initialized = False
        self.res = RESOLUTION
        self.frame_len = FRAME_LEN
        self.refresh_hz = refresh_hz
        self.frame_interval = 1.0 / max(1, refresh_hz)
        self.last_frame_time = 0.0

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
                # Dead pixel removal (median filter) - 문서 권장사항
                frame = cv2.medianBlur(frame, 3)
                # 기본 가우시안 블러
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
        return base + 8.0 * mask.astype(np.float32)

    def close(self):
        try:
            if self.i2c:
                self.i2c.deinit()
        except Exception:
            pass


# --------------------- Super-Resolution ---------------------
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


# --------------------- Detection / Tracking ---------------------
class ThermalFaceDetector:
    def __init__(self, ambient_delta: float = 0.5, p_hot: float = 65.0,  # 임계값 완화 (얼굴 영역 더 넓게 감지)
                 min_area_frac: float = 0.015, max_area_frac: float = 0.5,  # 면적 범위 확대
                 top_bias: float = 0.5, search_expand: float = 0.8, lost_tolerance: int = 20,  # 더 관대한 설정
                 enable_preprocessing: bool = True, enable_clahe: bool = True,
                 enable_bilateral: bool = False, clahe_clip_limit: float = 2.0,
                 clahe_tile_size: int = 8, face_temp_range: Tuple[float, float] = (26.0, 38.0),
                 enable_kcf: bool = False):
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
        
        # Enhanced preprocessing options (문서 기반 개선사항)
        self.enable_preprocessing = enable_preprocessing
        self.enable_clahe = enable_clahe
        self.enable_bilateral = enable_bilateral
        self.face_temp_range = face_temp_range
        self.enable_kcf = enable_kcf
        
        # CLAHE 초기화
        if self.enable_clahe:
            self.clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=(clahe_tile_size, clahe_tile_size))
        else:
            self.clahe = None
        
        # KCF Tracker 초기화
        self.kcf_tracker = None
        self.kcf_bbox = None

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

    def _preprocess_frame(self, frame: np.ndarray, face_bbox=None) -> Tuple[np.ndarray, np.ndarray]:
        """
        열화상 프레임 전처리 파이프라인 (문서 기반 개선)
        얼굴 영역의 온도 범위를 동적으로 계산하여 정규화
        Returns: (processed_uint8, original_thermal)
        """
        if not self.enable_preprocessing:
            return normalize_to_uint8(frame, face_bbox=face_bbox), frame
        
        # 1. 온도 정규화 - 얼굴 영역이 있으면 동적 범위 계산, 없으면 기본 범위 사용
        if face_bbox is not None:
            x, y, w, h = face_bbox
            x = max(0, min(x, frame.shape[1] - 1))
            y = max(0, min(y, frame.shape[0] - 1))
            w = min(w, frame.shape[1] - x)
            h = min(h, frame.shape[0] - y)
            if w > 0 and h > 0:
                face_region = frame[y:y+h, x:x+w]
                # 얼굴 영역의 10-90 percentile 사용 (더 좁은 범위로 신호 강조)
                temp_min = float(np.percentile(face_region, 10))
                temp_max = float(np.percentile(face_region, 90))
                # 안전 범위 확보
                if temp_max <= temp_min:
                    temp_max = temp_min + 1.0
                # 전체 프레임 범위와 얼굴 영역 범위의 조합
                frame_min, frame_max = float(np.min(frame)), float(np.max(frame))
                temp_min = min(temp_min, frame_min)
                temp_max = max(temp_max, frame_max)
            else:
                temp_min, temp_max = 20.0, 40.0
        else:
            # 얼굴 영역이 없으면 전체 프레임의 20-80 percentile 사용
            temp_min = float(np.percentile(frame, 20))
            temp_max = float(np.percentile(frame, 80))
            if temp_max <= temp_min:
                temp_min, temp_max = 20.0, 40.0
        
        normalized = np.clip(
            (frame - temp_min) / (temp_max - temp_min) * 255,
            0, 255
        ).astype(np.uint8)
        
        # 2. CLAHE enhancement (문서 권장)
        if self.enable_clahe and self.clahe is not None:
            enhanced = self.clahe.apply(normalized)
        else:
            enhanced = normalized
        
        # 3. Bilateral filtering (선택적, 느리지만 노이즈 제거 효과)
        if self.enable_bilateral:
            enhanced = cv2.bilateralFilter(enhanced, d=9, sigmaColor=75, sigmaSpace=75)
        
        return enhanced, frame
    
    def _validate_face_temperature(self, frame: np.ndarray, bbox) -> bool:
        """
        온도 기반 얼굴 검증 (문서 권장: 28-35°C 범위)
        """
        if bbox is None:
            return False
        
        x, y, w, h = bbox
        # bbox가 프레임 범위를 벗어나지 않도록 클리핑
        x = max(0, min(x, frame.shape[1] - 1))
        y = max(0, min(y, frame.shape[0] - 1))
        w = min(w, frame.shape[1] - x)
        h = min(h, frame.shape[0] - y)
        
        if w <= 0 or h <= 0:
            return False
        
        roi_temps = frame[y:y+h, x:x+w]
        if roi_temps.size == 0:
            return False
        
        mean_temp = float(np.mean(roi_temps))
        temp_min, temp_max = self.face_temp_range
        
        # 얼굴 온도 범위 검증
        is_valid = temp_min <= mean_temp <= temp_max
        
        # 추가: 핫 픽셀 비율 체크 (30°C 이상 픽셀 비율)
        hot_pixels = np.sum(roi_temps > 30.0)
        hot_ratio = hot_pixels / roi_temps.size if roi_temps.size > 0 else 0.0
        
        # 온도 범위 내이고, 적절한 핫 픽셀 비율이면 유효
        return is_valid and hot_ratio > 0.1
    
    def _threshold(self, frame):
        ambient = float(np.median(frame))
        t1 = ambient + self.ambient_delta
        t2 = float(np.percentile(frame, self.p_hot))
        thr = max(t1, t2)
        return (frame >= thr).astype(np.uint8)
    
    def _track_kcf(self, frame_u8: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        KCF 추적기 사용 (문서 권장 - 템플릿 매칭보다 안정적)
        """
        if not self.enable_kcf:
            return None
        
        if self.kcf_tracker is None or self.kcf_bbox is None:
            return None
        
        try:
            success, bbox = self.kcf_tracker.update(frame_u8)
            if success:
                x, y, w, h = tuple(map(int, bbox))
                # bbox 유효성 검사
                if w > 0 and h > 0 and x >= 0 and y >= 0:
                    self.kcf_bbox = (x, y, w, h)
                    return self.kcf_bbox
            else:
                # 추적 실패 시 리셋
                self.kcf_tracker = None
                self.kcf_bbox = None
        except Exception as e:
            logger.debug(f"KCF tracking error: {e}")
            self.kcf_tracker = None
            self.kcf_bbox = None
        
        return None
    
    def _init_kcf_tracker(self, frame_u8: np.ndarray, bbox: Tuple[int, int, int, int]):
        """KCF 추적기 초기화"""
        if not self.enable_kcf:
            return
        
        try:
            self.kcf_tracker = cv2.TrackerKCF_create()
            # bbox를 (x, y, w, h) 형식으로 변환
            x, y, w, h = bbox
            bbox_float = (float(x), float(y), float(w), float(h))
            success = self.kcf_tracker.init(frame_u8, bbox_float)
            if success:
                self.kcf_bbox = bbox
            else:
                self.kcf_tracker = None
                self.kcf_bbox = None
        except Exception as e:
            logger.debug(f"KCF tracker init failed: {e}")
            self.kcf_tracker = None
            self.kcf_bbox = None

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
        
        # 전처리 파이프라인 적용 (문서 기반 개선)
        # 이전 bbox가 있으면 얼굴 영역 기반 동적 정규화 사용
        face_bbox_for_preprocess = self.last_bbox if self.last_bbox is not None else None
        frame_u8, frame_thermal = self._preprocess_frame(frame, face_bbox=face_bbox_for_preprocess)

        # 디버깅 정보 수집
        debug_info = {
            'frame_stats': {
                'min': float(np.min(frame)),
                'max': float(np.max(frame)),
                'mean': float(np.mean(frame)),
                'std': float(np.std(frame))
            },
            'detection_method': 'none',
            'components_found': 0,
            'threshold_stats': {}
        }

        # KCF 추적기 우선 시도 (활성화된 경우)
        if self.enable_kcf and self.kcf_tracker is not None:
            kcf_bbox = self._track_kcf(frame_u8)
            if kcf_bbox is not None:
                # 온도 기반 검증
                if self._validate_face_temperature(frame_thermal, kcf_bbox):
                    self.last_bbox = kcf_bbox
                    self.missed = 0
                    debug_info['detection_method'] = 'kcf_tracking'
                    return self.last_bbox

        if self.last_bbox is not None and self.missed < self.lost_tolerance:
            debug_info['detection_method'] = 'tracking'
            lx, ly, lw, lh = self.last_bbox
            ex = int(lw*self.search_expand)
            ey = int(lh*self.search_expand)
            sx = max(0, lx-ex)
            sy = max(0, ly-ey)
            sw = min(W-sx, lw+2*ex)
            sh = min(H-sy, lh+2*ey)
            local = frame_thermal[sy:sy+sh, sx:sx+sw]
            hot = self._threshold(local)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            hot = cv2.morphologyEx(hot, cv2.MORPH_OPEN, k, iterations=1)
            hot = cv2.morphologyEx(hot, cv2.MORPH_CLOSE, k, iterations=2)
            num, labels, stats, cents = cv2.connectedComponentsWithStats(hot, 8)
            debug_info['components_found'] = num - 1  # 배경 제외
            
            if num > 1:
                bbox = self._score_components(local, stats, cents, cx_img - sx, cy_img - sy)
                if bbox is not None:
                    x, y, w, h = bbox
                    full_bbox = (sx+x, sy+y, w, h)
                    # 온도 기반 검증 추가
                    if self._validate_face_temperature(frame_thermal, full_bbox):
                        self.last_bbox = full_bbox
                        self.missed = 0
                        # KCF 추적기 초기화
                        if self.enable_kcf:
                            self._init_kcf_tracker(frame_u8, full_bbox)
                        roi_u8 = frame_u8[sy+y:sy+y+h, sx+x:sx+x+w]
                        if roi_u8.size >= 9:
                            self.last_template = cv2.resize(roi_u8, (max(8, w), max(8, h)))
                        debug_info['detection_method'] = 'tracking_components'
                        return self.last_bbox
            # 템플릿 매칭 시도 (KCF가 비활성화된 경우)
            if not self.enable_kcf:
                track = self._template_track(frame_u8, (sx, sy, sw, sh))
                if track is not None:
                    # 온도 기반 검증
                    if self._validate_face_temperature(frame_thermal, track):
                        self.last_bbox = track
                        self.missed = 0
                        debug_info['detection_method'] = 'tracking_template'
                        return self.last_bbox
            self.missed += 1

        # 전체 프레임 검색
        debug_info['detection_method'] = 'full_frame'
        hot = self._threshold(frame_thermal)
        
        # 임계값 통계 수집
        ambient = float(np.median(frame_thermal))
        t1 = ambient + self.ambient_delta
        t2 = float(np.percentile(frame_thermal, self.p_hot))
        thr = max(t1, t2)
        debug_info['threshold_stats'] = {
            'ambient': ambient,
            'threshold_delta': t1,
            'percentile_hot': t2,
            'final_threshold': thr,
            'hot_pixels': int(np.sum(hot))
        }
        
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        hot = cv2.morphologyEx(hot, cv2.MORPH_OPEN, k, iterations=1)
        hot = cv2.morphologyEx(hot, cv2.MORPH_CLOSE, k, iterations=2)
        num, labels, stats, cents = cv2.connectedComponentsWithStats(hot, 8)
        debug_info['components_found'] = num - 1  # 배경 제외
        
        if num <= 1:
            self.missed += 1
            # KCF 추적기 리셋
            if self.enable_kcf:
                self.kcf_tracker = None
                self.kcf_bbox = None
            # 디버깅 로그 출력
            if self.missed % 30 == 0:  # 30프레임마다 로그
                logger.warning(f"얼굴 인식 실패 - 컴포넌트 없음: {debug_info}")
            return None
            
        bbox = self._score_components(frame_thermal, stats, cents, cx_img, cy_img)
        if bbox is None:
            self.missed += 1
            # KCF 추적기 리셋
            if self.enable_kcf:
                self.kcf_tracker = None
                self.kcf_bbox = None
            # 디버깅 로그 출력
            if self.missed % 30 == 0:  # 30프레임마다 로그
                logger.warning(f"얼굴 인식 실패 - 스코어링 실패: {debug_info}")
            return None
        
        # 온도 기반 검증 추가 (문서 권장)
        if not self._validate_face_temperature(frame_thermal, bbox):
            self.missed += 1
            if self.missed % 30 == 0:
                mean_temp = float(np.mean(frame_thermal[bbox[1]:bbox[1]+bbox[3], bbox[0]:bbox[0]+bbox[2]]))
                logger.warning(f"얼굴 인식 실패 - 온도 검증 실패: {mean_temp:.1f}°C (범위: {self.face_temp_range[0]}-{self.face_temp_range[1]}°C)")
            return None
            
        self.last_bbox = bbox
        self.missed = 0
        
        # KCF 추적기 초기화
        if self.enable_kcf:
            self._init_kcf_tracker(frame_u8, bbox)
        
        x, y, w, h = bbox
        roi_u8 = frame_u8[y:y+h, x:x+w]
        if roi_u8.size >= 9:
            self.last_template = cv2.resize(roi_u8, (max(8, w), max(8, h)))
        
        # 성공 시 디버깅 로그
        if self.missed == 0:  # 첫 성공이거나 연속 성공
            mean_temp = float(np.mean(frame_thermal[y:y+h, x:x+w]))
            logger.info(f"얼굴 인식 성공: {debug_info} | 온도: {mean_temp:.1f}°C")
            
        return self.last_bbox


# --------------------- Motion Compensation ---------------------
class MotionCompensator:
    def __init__(self):
        self.ref = None
        self.M = np.eye(2, 3, dtype=np.float32)
        self._tick = 0
        self.mc_stride = 2
        self.motion_level = 0.0
        self.last_warp = None

    def compensate(self, frame: np.ndarray, bbox):
        if bbox is None:
            return frame
        self._tick += 1
        if self._tick % max(1, int(self.mc_stride)) != 0 and self.ref is not None:
            out = cv2.warpAffine(frame, self.M, (frame.shape[1], frame.shape[0]),
                                 flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
            self.last_warp = out
            return out
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
            self.last_warp = out
            self.motion_level = float(np.hypot(M[0, 2], M[1, 2]))
            return out
        except Exception:
            return frame


# --------------------- ROI Manager ---------------------
class ROIManager:
    def __init__(self, patch_size: int = 6, use_weighted_mean: bool = True, 
                 center_weight: float = 0.9, dynamic_positioning: bool = True,
                 use_center_only: bool = False):
        self.buffers: Dict[str, deque] = {}
        self.patch_size = patch_size
        self.use_weighted_mean = use_weighted_mean
        self.center_weight = center_weight
        self.dynamic_positioning = dynamic_positioning
        self.use_center_only = use_center_only

    def _find_face_center_from_temp(self, frame: np.ndarray, bbox) -> Tuple[float, float]:
        """온도 분포를 기반으로 얼굴 중심 위치 찾기 (원형/타원형 고려)"""
        if bbox is None:
            return None, None
        x, y, w, h = bbox
        x = max(0, min(x, frame.shape[1] - 1))
        y = max(0, min(y, frame.shape[0] - 1))
        w = min(w, frame.shape[1] - x)
        h = min(h, frame.shape[0] - y)
        if w <= 0 or h <= 0:
            return None, None
        
        face_region = frame[y:y+h, x:x+w]
        # 온도가 높은 영역의 중심 찾기 (가중 중심)
        yy, xx = np.ogrid[:h, :w]
        # 온도가 높을수록 높은 가중치
        weights = face_region - np.min(face_region)
        weights = np.maximum(weights, 0)  # 음수 제거
        
        if np.sum(weights) > 0:
            center_x = float(np.sum(xx * weights) / np.sum(weights))
            center_y = float(np.sum(yy * weights) / np.sum(weights))
            # 전체 프레임 좌표로 변환
            return x + center_x, y + center_y
        else:
            # 가중치가 없으면 기하학적 중심
            return x + w/2, y + h/2

    def _adjust_roi_position(self, frame: np.ndarray, bbox, base_roi: Tuple[float, float, float, float],
                            face_center_x: float, face_center_y: float) -> Tuple[int, int, int, int]:
        """온도 분포 기반으로 ROI 위치 동적 조정"""
        if not self.dynamic_positioning or face_center_x is None or face_center_y is None:
            # 동적 조정 비활성화 또는 얼굴 중심을 찾을 수 없으면 기본 위치 사용
            return tuple(map(int, base_roi))
        
        x, y, w, h = bbox
        rx_base, ry_base, rw_base, rh_base = base_roi
        
        # 얼굴 중심을 기준으로 ROI 위치 미세 조정
        # 얼굴 중심과 ROI 중심의 차이를 고려하여 조정
        roi_center_x = rx_base + rw_base / 2
        roi_center_y = ry_base + rh_base / 2
        
        # 얼굴 중심으로의 이동량 계산 (약간만 조정)
        dx = (face_center_x - roi_center_x) * 0.3  # 30%만 이동 (너무 급격한 변화 방지)
        dy = (face_center_y - roi_center_y) * 0.3
        
        rx = int(rx_base + dx)
        ry = int(ry_base + dy)
        
        # 프레임 범위 내로 클리핑
        rx = max(0, min(rx, frame.shape[1] - 1))
        ry = max(0, min(ry, frame.shape[0] - 1))
        rw = int(rw_base)
        rh = int(rh_base)
        
        # ROI가 프레임을 벗어나지 않도록 조정
        rw = min(rw, frame.shape[1] - rx)
        rh = min(rh, frame.shape[0] - ry)
        
        return rx, ry, rw, rh

    def extract(self, frame: np.ndarray, bbox, patch=None):
        if bbox is None:
            return {}, {}
        if patch is None:
            patch = self.patch_size
        
        x, y, w, h = bbox
        
        # 얼굴 중심 찾기 (온도 분포 기반)
        face_center_x, face_center_y = self._find_face_center_from_temp(frame, bbox)
        
        # 기본 ROI 위치 (기존 방식)
        base_rois = {
            'forehead': (x + 0.25*w, y + 0.05*h, 0.5*w, 0.22*h),
            'l_cheek': (x + 0.05*w, y + 0.45*h, 0.28*w, 0.28*h),
            'r_cheek': (x + 0.67*w, y + 0.45*h, 0.28*w, 0.28*h),
            'nose': (x + 0.40*w, y + 0.40*h, 0.20*w, 0.22*h),
        }
        
        rois = {}
        vals = {}
        
        for name, base_roi in base_rois.items():
            # 동적 위치 조정
            rx, ry, rw, rh = self._adjust_roi_position(frame, bbox, base_roi, face_center_x, face_center_y)
            
            # 프레임 범위 내로 클리핑
            rx = max(0, min(rx, frame.shape[1]-1))
            ry = max(0, min(ry, frame.shape[0]-1))
            rw = max(2, min(rw, frame.shape[1]-rx))
            rh = max(2, min(rh, frame.shape[0]-ry))
            
            region = frame[ry:ry+rh, rx:rx+rw]
            if region.size == 0:
                continue
            
            # 중심 패치 추출
            cx, cy = rw//2, rh//2
            x0, x1 = max(0, cx-patch), min(rw, cx+patch+1)
            y0, y1 = max(0, cy-patch), min(rh, cy+patch+1)
            patch_arr = region[y0:y1, x0:x1]
            
            # 값 계산: 중심 패치만, 가중 평균, 또는 전체 평균
            if patch_arr.size > 0:
                center_mean = float(np.mean(patch_arr))
                if self.use_center_only:
                    # 중심 패치만 사용 (신호 강조)
                    vals[name] = center_mean
                elif self.use_weighted_mean:
                    region_mean = float(np.mean(region))
                    # 가중 평균 (중심 90%, 전체 10% - 신호 강조)
                    vals[name] = self.center_weight * center_mean + (1.0 - self.center_weight) * region_mean
                else:
                    # 중심 패치만 사용 (기본)
                    vals[name] = center_mean
            else:
                # 패치가 없으면 전체 영역 평균
                vals[name] = float(np.mean(region))
            
            rois[name] = (rx, ry, rw, rh)
        
        return vals, rois


# --------------------- Signal Processing ---------------------
class SignalProc:
    def __init__(self, fs, band=(0.7, 4.0)):
        self.fs = fs
        self.band = band
        self.sos = signal.butter(4, self.band, btype='band', fs=self.fs, output='sos')

    def detrend_bandpass(self, x):
        x = x - np.mean(x)
        return signal.sosfilt(self.sos, x)

    def hr_fft(self, x):
        if len(x) < int(8 * self.fs):
            return None, 0.0, None, 0.0

        n = int(2 ** np.ceil(np.log2(len(x) * 2)))
        win = np.hanning(len(x))
        X = np.fft.rfft(x * win, n=n)
        f = np.fft.rfftfreq(n, 1 / self.fs)
        m = (f >= self.band[0]) & (f <= self.band[1])
        if not np.any(m):
            return None, 0.0, None, 0.0

        mag = np.abs(X[m]); fi = f[m]

        # 유틸: target 주파수 주변 파워(최댓값) 구하기
        def pick_power(freq, spec, target, width=0.08):
            if target <= 0: return 0.0
            mask = (freq >= target - width) & (freq <= target + width)
            return float(np.max(spec[mask])) if np.any(mask) else 0.0

        # 1) 1차 피크
        pk = int(np.argmax(mag)); f0 = fi[pk]
        p0 = float(mag[pk])

        # 2) 주변 잡음 → SNR
        excl = np.abs(fi - f0) <= 0.1
        noise = mag[~excl]
        noise_med = np.median(noise) if noise.size > 0 else np.mean(mag)
        snr = float(p0 / (noise_med + 1e-8))

        # 3) 하모닉 검사
        p_half  = pick_power(fi, mag, f0 * 0.5)
        p_double= pick_power(fi, mag, f0 * 2.0)
        harm2   = pick_power(fi, mag, f0 * 2.0)  # 2차 고조파
        harm_ratio = float(harm2 / (p0 + 1e-8))

        f_sel = f0; p_sel = p0

        # --- 판정 규칙 ---
        # (a) 2배로 잡힌 의심: f0>1.8Hz(~108 bpm) 이고 f0/2 파워가 충분히 크면 -> 반으로 교정
        if f0 > 1.8 and p_half > 0 and (p_half >= 0.55 * p0 or harm_ratio >= 0.60):
            f_sel = f0 * 0.5; p_sel = p_half

        # (b) 반으로 잡힌 의심: f0<1.2Hz(~72 bpm) 이고 2*f0 파워가 훨씬 크고 품질이 낮으면 -> 2배로 교정
        elif f0 < 1.2 and p_double >= 0.75 * p0 and snr < 1.8:
            f_sel = f0 * 2.0; p_sel = p_double

        # 최종 SNR/신뢰도 재계산(선택): 같은 noise_med 기반으로 p_sel 사용
        snr_final = float(p_sel / (noise_med + 1e-8))
        conf = float(np.clip((snr_final - 1.2) / 3.2, 0.0, 1.0))

        hr_bpm = float(f_sel * 60.0)
        return hr_bpm, conf, snr_final, harm_ratio


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
        f = np.fft.rfftfreq(n, 1 / self.fs)
        m = (f >= self.band[0]) & (f <= self.band[1])
        if not np.any(m):
            return None, 0.0
        mag = np.abs(X[m])
        fi = f[m]
        pk = int(np.argmax(mag))
        rr = float(fi[pk] * 60.0)
        conf = float(np.clip((np.max(mag)/(np.mean(mag)+1e-8))/6.0, 0.0, 1.0))
        return rr, conf


# --------------------- Presence Gate ---------------------
class PresenceGate:
    def __init__(self, cfg: ThermalrPPGConfig):
        self.cfg = cfg
        self.present = False
        self.pass_cnt = 0
        self.fail_cnt = 0
        self.last_reason = "init"

    def update(self, bbox, fh, nose, lch, rch, ambient, roi_diag):
        c = self.cfg
        reasons = []

        # --- 기하/열(필수) ---
        ok_geom = True
        if bbox is None:
            ok_geom = False; reasons.append("no_bbox")

        # 이마 절대온도 필수
        if fh is None:
            ok_geom = False; reasons.append("no_fh")
        else:
            if not (c.temp_face_min <= fh <= c.temp_face_max):
                ok_geom = False; reasons.append("fh_range")

        # ambient가 제공될 때만 ΔT 요건 적용(없으면 통과)
        if (ambient is not None) and (c.min_ambient_delta > 0.0) and (fh is not None):
            if (fh - ambient) < c.min_ambient_delta:
                ok_geom = False; reasons.append("fh_amb_delta")

    # 볼/코 패턴은 게이트에서 제외(추운 환경에서 false negative 방지)
    # 필요하면 디버깅용으로만 기록:
    # if lch is not None and rch is not None and fh is not None:
    #     cheeks_delta = ((lch + rch)/2.0 - fh)
    #     if cheeks_delta < -0.35: reasons.append("cheek_cold_note")
    # if nose is not None and fh is not None:
    #     if (nose - fh) > 0.8: reasons.append("nose_hot_note")

    # --- 스펙트럼(선택) : roi_diag 없으면 건너뜀 ---
        ok_spec = True
        if roi_diag:
            hrs = []
            good = 0
            harm_ok = 0
            for name in ("forehead","l_cheek","r_cheek","nose"):
                r = roi_diag.get(name)
                if not r: continue
                if r.get('snr',0.0) >= c.snr_face_min:
                    good += 1
                if r.get('harm',0.0) >= c.harmonic_min_ratio:
                    harm_ok += 1
                if 'hr' in r: hrs.append(r['hr'])
            if good < 2:
                ok_spec = False; reasons.append("snr_low")
            if harm_ok < 1:
                ok_spec = False; reasons.append("harm_low")
            if len(hrs) >= 2 and (np.max(hrs) - np.min(hrs)) > c.hr_agreement_bpm:
                ok_spec = False; reasons.append("hr_disagree")

        ok = ok_geom and ok_spec

        # --- 히스테리시스 ---
        if ok:
            self.pass_cnt += 1; self.fail_cnt = 0
            if not self.present and self.pass_cnt >= c.present_rise_frames:
                self.present = True
        else:
            self.fail_cnt += 1; self.pass_cnt = 0
            if self.present and self.fail_cnt >= c.present_fall_frames:
                self.present = False

        self.last_reason = ",".join(reasons) if reasons else "ok"
        
        # 디버깅 정보 로깅
        if not ok and (self.fail_cnt % 60 == 0):  # 60프레임마다 로그 (약 4초마다)
            temp_info = {
                'bbox': bbox,
                'fh': fh,
                'nose': nose,
                'lch': lch,
                'rch': rch,
                'ambient': ambient,
                'fh_range': f"{c.temp_face_min}-{c.temp_face_max}",
                'ambient_delta': c.min_ambient_delta
            }
            logger.warning(f"PresenceGate 실패: {reasons} | 온도정보: {temp_info}")
        elif ok and self.present and (self.pass_cnt % 60 == 0):  # 성공 시에도 주기적 로그
            fh_str = f"{fh:.1f}" if fh is not None else "--"
            nose_str = f"{nose:.1f}" if nose is not None else "--"
            ambient_str = f"{ambient:.1f}" if ambient is not None else "--"
            logger.info(f"PresenceGate 성공: 온도정보 fh={fh_str}°C, nose={nose_str}°C, ambient={ambient_str}°C")
            
        return self.present, self.last_reason


# --------------------- UI ---------------------
class MonitorUI:
    def __init__(self, up_scale: int, fs: float, ui_scale: float = 1.5, 
                 window_width: Optional[int] = None, window_height: Optional[int] = None):
        self.up_scale = up_scale
        self.fs = fs
        self.ui_scale = ui_scale
        self.window_width = window_width
        self.window_height = window_height
        self.hr_hist = deque(maxlen=240)
        self.qual_hist = deque(maxlen=240)
        self.last_tick = time.time()
        self.fps = 0.0
        self.window_name = 'Thermal rPPG Monitor'
        self.compare_mode = 'SR'
        self._ui_tick = 0
        self.ui_stride = 1
        self._window_created = False
        self._window_size_set = False
        try:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            self._window_created = True
        except Exception:
            logger.warning("Cannot create window (headless?). UI disabled.")

    def _draw_chart(self, canvas, series: deque, rect, y_min: float, y_max: float, label: str):
        x0, y0, w, h = rect
        cv2.rectangle(canvas, (x0, y0), (x0+w, y0+h), (40, 40, 40), 1)
        if len(series) < 2:
            cv2.putText(canvas, f"{label}: --", (x0+5, y0+15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230,230,230), 1)
            return
        vals = np.array(series, dtype=np.float32)
        vals = np.clip((vals - y_min) / max(1e-6, (y_max - y_min)), 0, 1)
        xs = np.linspace(0, w-1, len(vals)).astype(int)
        ys = (y0 + h - (vals * (h-2)).astype(int) - 1)
        pts = np.stack([x0+xs, ys], axis=1)
        for i in range(1, len(pts)):
            cv2.line(canvas, tuple(pts[i-1]), tuple(pts[i]), (200, 200, 200), 1)
        cv2.putText(canvas, f"{label}: {series[-1]:.1f}", (x0+5, y0+15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230,230,230), 1)

    def update(self, thermal_u8_lr: np.ndarray, bbox, roi_boxes, hr: Optional[float], q: float,
               rr: Optional[float], dT_nose: Optional[float], dT_cheek: Optional[float],
               samples: int, thermal_u8_sr: Optional[np.ndarray] = None,
               tracking_ok: bool = True, color_rec=None, artifacts: Optional[str] = None):
        self._ui_tick += 1
        if self._ui_tick % max(1, int(self.ui_stride)) != 0:
            return None

        now = time.time()
        dt = now - self.last_tick
        if dt > 0:
            self.fps = 0.9*self.fps + 0.1*(1.0/dt)
        self.last_tick = now

        vis_lr = cv2.applyColorMap(thermal_u8_lr, cv2.COLORMAP_INFERNO)
        vis_sr = cv2.applyColorMap(thermal_u8_sr if thermal_u8_sr is not None else thermal_u8_lr,
                                   cv2.COLORMAP_INFERNO)

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
        panel_w = 280
        panel = np.zeros((h, panel_w, 3), dtype=np.uint8)
        panel[:] = (25, 25, 25)

        if hr is not None:
            self.hr_hist.append(hr)
        self.qual_hist.append(q)
        self._draw_chart(panel, self.hr_hist, (10, 10, panel_w-20, 80), 45, 120, "HR(BPM)")
        self._draw_chart(panel, self.qual_hist, (10, 100, panel_w-20, 60), 0, 1, "Quality")

        line = max(10, min(h - 60, 180))

        def put(k, v):
            nonlocal line
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
        
        # 얼굴 인식 상태 표시 개선
        if bbox is not None:
            x, y, w, h = bbox
            put("Face", f"OK ({w}x{h})")
        else:
            put("Face", "NOT DETECTED")
            
        put("Track", "OK" if tracking_ok else "LOST")
        if artifacts and line + 18 < h:
            cv2.putText(panel, f"Art: {artifacts}", (10, line), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180,180,180), 1)
            line += 18

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
        
        # UI 스케일링 적용
        if self.ui_scale != 1.0:
            h_out, w_out = out.shape[:2]
            new_h = int(h_out * self.ui_scale)
            new_w = int(w_out * self.ui_scale)
            out = cv2.resize(out, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        try:
            # 창 크기 초기 설정 (첫 프레임에서만)
            if self._window_created and not self._window_size_set:
                if self.window_width is not None and self.window_height is not None:
                    # 명시적으로 지정된 크기 사용
                    cv2.resizeWindow(self.window_name, self.window_width, self.window_height)
                    self._window_size_set = True
                elif self.window_width is not None:
                    # 너비만 지정된 경우, 높이는 비율 유지
                    h, w = out.shape[:2]
                    aspect = h / w
                    cv2.resizeWindow(self.window_name, self.window_width, int(self.window_width * aspect))
                    self._window_size_set = True
                elif self.window_height is not None:
                    # 높이만 지정된 경우, 너비는 비율 유지
                    h, w = out.shape[:2]
                    aspect = w / h
                    cv2.resizeWindow(self.window_name, int(self.window_height * aspect), self.window_height)
                    self._window_size_set = True
                else:
                    # 창 크기가 지정되지 않은 경우, ui_scale 적용 후 실제 이미지 크기로 설정
                    h, w = out.shape[:2]
                    # 최소 크기 보장 (너무 작지 않도록)
                    min_width = 800
                    min_height = 600
                    if w < min_width or h < min_height:
                        scale = max(min_width / w, min_height / h)
                        w = int(w * scale)
                        h = int(h * scale)
                    cv2.resizeWindow(self.window_name, w, h)
                    self._window_size_set = True
            
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


# --------------------- Main App ---------------------
class ThermalrPPG:
    def __init__(self, cfg: ThermalrPPGConfig, mqtt_pub: Optional[MqttColorPublisher] = None):
        self.cfg = cfg
        self.sensor = MLX9064XInterface(refresh_hz=int(cfg.sampling_rate))
        self.detector = ThermalFaceDetector(
            ambient_delta=0.5,  # 임계값 완화
            p_hot=65.0,  # 임계값 완화
            enable_preprocessing=cfg.enable_face_preprocessing,
            enable_clahe=cfg.enable_clahe,
            enable_bilateral=cfg.enable_bilateral_filter,
            clahe_clip_limit=cfg.clahe_clip_limit,
            clahe_tile_size=cfg.clahe_tile_size,
            face_temp_range=cfg.face_temp_range,
            enable_kcf=cfg.enable_kcf_tracking
        )
        self.motion = MotionCompensator()
        self.motion.mc_stride = cfg.mc_stride
        self.roi = ROIManager(
            patch_size=cfg.roi_patch_size,
            use_weighted_mean=cfg.roi_use_weighted_mean,
            center_weight=cfg.roi_center_weight,
            dynamic_positioning=cfg.roi_dynamic_positioning,
            use_center_only=cfg.roi_use_center_only
        )
        self.proc = SignalProc(cfg.sampling_rate, band=cfg.target_hr_range)
        self.resp = RespEstimator(cfg.sampling_rate)
        self.buffers: Dict[str, deque] = {}
      
        self.up_scale = cfg.up_scale
        self.mfsr = MultiFrameSuperRes(
            scale=cfg.superres_scale,
            max_frames=cfg.superres_frames,
            deconvolution=cfg.superres_deconvolution
        ) if cfg.enable_superres else None
        self._sr_count = 0

        self.monitor = MonitorUI(
            self.up_scale, 
            cfg.sampling_rate,
            ui_scale=cfg.ui_scale,
            window_width=cfg.ui_window_width,
            window_height=cfg.ui_window_height
        ) if cfg.debug_visual else None
        if self.monitor is not None:
            self.monitor.ui_stride = 1  # increase to 2~3 to reduce UI load

        self.therapist = ColorTherapist()
        self.mqtt = mqtt_pub

        self._hr_next_ts = 0.0
        self._rr_next_ts = 0.0
        self._last_status = {'ts': 0.0, 'hr': None, 'rr': None, 'q': None, 'dtn': None, 'dtc': None}
        self._persp_until = 0.0
        self._ambient_ema = None
        self.presence = PresenceGate(cfg)
        self._hr_smooth: Optional[float] = None
        self._hr_ts: Optional[float] = None
        
        # Real-time MQTT publishing
        self._last_realtime_mqtt_ts = 0.0
        
        # Raspberry Pi optimization
        self.pi_optimizer = RaspberryPiOptimizer(cfg)
        
        # Fast measurement mode
        self.fast_mode = FastMeasurementMode(cfg)
        
        # AI Enhancement components
        self.wavelet_denoiser = WaveletDenoiser() if cfg.enable_wavelet_denoising else None
        self.kalman_filter = AdaptiveKalmanFilter() if cfg.enable_adaptive_filtering else None
        self.ensemble_optimizer = EnsembleROIOptimizer(self.pi_optimizer) if cfg.enable_ensemble_learning else None
        self.personalized_model = PersonalizedBiometricModel() if cfg.enable_personalized_model else None
        
        # AI model update tracking
        self._last_model_update = time.time()
        self._innovation_history = deque(maxlen=50)
        self._was_present = False
        self.session_active = False
        self.session_reported = False
        self.session_start_ts = 0.0
        self.session_best: Optional[Dict[str, Any]] = None
        self.session_measurements: list = []  # 세션 동안 모든 측정값 저장

        logger.info(f"Config: sampling={cfg.sampling_rate}Hz, mode={cfg.processing_mode.value}")
        logger.info(f"AI Enhancements: Wavelet={cfg.enable_wavelet_denoising}, "
                   f"Kalman={cfg.enable_adaptive_filtering}, "
                   f"Ensemble={cfg.enable_ensemble_learning}, "
                   f"Personalized={cfg.enable_personalized_model}")

    # ---------- helpers ----------
    def _append(self, roi_vals: Dict[str, float], ambient: Optional[float]):
        for k, v in roi_vals.items():
            if k not in self.buffers:
                self.buffers[k] = deque(maxlen=2048)
            self.buffers[k].append(v)
        if ambient is not None:
            if 'ambient' not in self.buffers:
                self.buffers['ambient'] = deque(maxlen=2048)
            self.buffers['ambient'].append(ambient)

    def _decay_buffers_on_absent(self):
        keep = int(self.cfg.absent_buffer_sec * self.cfg.sampling_rate)
        for k, dq in self.buffers.items():
            if len(dq) > keep:
                arr = list(dq)[-keep:]
                dq.clear()
                dq.extend(arr)

    def _enough(self):
        need = int(self.cfg.sampling_rate * max(8, self.cfg.min_measurement_duration))
        return any(len(buf) >= need for buf in self.buffers.values())

    def _ambient_series(self, n: int):
        if not self.cfg.ambient_comp or 'ambient' not in self.buffers:
            return None
        arr = np.array(self.buffers['ambient'], dtype=np.float32)
        if arr.size < n:
            return None
        return arr[-n:]

    def _preprocess_series(self, name: str, n: int):
        arr = np.array(self.buffers.get(name, []), dtype=np.float32)
        if arr.size < n:
            return None
        x = arr[-n:].copy()
        if self.cfg.ambient_comp:
            amb = self._ambient_series(n)
            if amb is not None:
                if self._ambient_ema is None:
                    self._ambient_ema = float(amb[0])
                alpha = self.cfg.ambient_alpha
                ema = self._ambient_ema
                for v in amb:
                    ema = (1 - alpha) * ema + alpha * v
                self._ambient_ema = float(ema)
                x = x - self.cfg.ambient_gain * (amb - np.mean(amb))
        
        # 웨이블릿 노이즈 제거 적용
        if self.wavelet_denoiser is not None and len(x) >= 16:
            try:
                x = self.wavelet_denoiser.denoise_signal(x)
            except Exception as e:
                logger.warning(f"Wavelet denoising failed for {name}: {e}")
        
        return x

    def _compute_hr(self):
        need = int(self.cfg.sampling_rate * max(8, self.cfg.min_measurement_duration))
        hrs, qs, snrs, harms, names = [], [], [], [], []
        for name in ['forehead', 'l_cheek', 'r_cheek', 'nose']:
            x = self._preprocess_series(name, need)
            if x is None:
                continue
            x = self.proc.detrend_bandpass(x)
            hr, conf, snr, harm = self.proc.hr_fft(x)
            if hr is not None:
                hrs.append(hr); qs.append(conf); snrs.append(snr); harms.append(harm); names.append(name)
            else:
                # 디버깅: HR이 None인 이유 로그
                signal_std = float(np.std(x)) if len(x) > 0 else 0.0
                signal_mean = float(np.mean(x)) if len(x) > 0 else 0.0
                logger.debug(f"ROI {name}: HR=None, 신호 std={signal_std:.4f}, mean={signal_mean:.4f}, 길이={len(x)}")

        if not hrs:
            # 디버깅: 왜 HR이 없는지 로그
            buffer_lengths = {name: len(self.buffers.get(name, [])) for name in ['forehead', 'l_cheek', 'r_cheek', 'nose']}
            logger.debug(f"HR 계산 실패: 버퍼 길이={buffer_lengths}, 필요={need}")
            return None, 0.0, {}

        # 품질 보정(모션/발한)
        motion_pen = float(np.clip(1.0 - (self.motion.motion_level / self.cfg.motion_px_warn), 0.4, 1.0))
        persp_pen  = 0.6 if time.time() < self._persp_until else 1.0
        q_arr = np.array(qs, dtype=np.float32) * motion_pen * persp_pen
        hr_arr = np.array(hrs, dtype=np.float32)
        snr_arr = np.array(snrs, dtype=np.float32)
        harm_arr = np.array(harms, dtype=np.float32)
        names_arr = np.array(names, dtype=object)

        # SNR 하한 미달 ROI는 추가 감산
        for i, s in enumerate(snr_arr):
            if s < self.cfg.snr_face_min:
                q_arr[i] *= 0.5

        # 품질 기준 이하 ROI 제거 및 상위 ROI만 활용
        quality_idx = [i for i, q_val in enumerate(q_arr) if q_val >= self.cfg.session_roi_quality_min]
        if not quality_idx:
            # 품질 기준 미달 시에도 최고 품질 ROI 사용 (디버깅용)
            if len(q_arr) > 0:
                best_idx = int(np.argmax(q_arr))
                max_q = float(q_arr[best_idx])
                logger.debug(f"품질 기준 미달 (최고={max_q:.3f} < {self.cfg.session_roi_quality_min}), 최고 품질 ROI 사용: {names_arr[best_idx]}")
                quality_idx = [best_idx]
            else:
                logger.debug(f"HR 계산 실패: 모든 ROI 품질 기준 미달")
                return None, 0.0, {}
        quality_idx = sorted(quality_idx, key=lambda i: q_arr[i], reverse=True)
        if self.cfg.session_roi_max_count > 0:
            quality_idx = quality_idx[:self.cfg.session_roi_max_count]

        hr_arr = hr_arr[quality_idx]
        q_arr = q_arr[quality_idx]
        snr_arr = snr_arr[quality_idx]
        harm_arr = harm_arr[quality_idx]
        names_arr = names_arr[quality_idx]

        diag = {
            str(names_arr[i]): {
                'hr':   float(hr_arr[i]),
                'snr':  float(snr_arr[i]),
                'q':    float(q_arr[i]),
                'harm': float(harm_arr[i])
            } for i in range(len(names_arr))
        }
        names_list = [str(n) for n in names_arr]

        # 🔹 AI 기반 ROI 가중치 최적화
        if self.ensemble_optimizer is not None:
            # 앙상블 학습으로 최적 가중치 예측
            forehead_buffer = list(self.buffers.get('forehead', []))
            ambient_temp = float(np.mean(forehead_buffer)) if forehead_buffer else 25.0
            optimal_weights = self.ensemble_optimizer.predict_optimal_weights(
                diag, self.motion.motion_level, ambient_temp
            )
            w = np.array([optimal_weights.get(name, 1.0) for name in names_list], dtype=np.float32)
        else:
            # 기존 방식
            roi_boost = self._roi_dynamic_boost(diag)
            w = q_arr.copy()
            for i, name in enumerate(names_list):
                w[i] *= roi_boost.get(name, 1.0)
        
        w = w / (w.sum() + 1e-6)

        # 최종 HR/Q
        hr_final = float(np.sum(hr_arr * w))
        q_final  = float(np.mean(q_arr))
        
        # 칼만 필터 적용
        if self.kalman_filter is not None:
            hr_final = self.kalman_filter.update(hr_final)
            # 혁신 시퀀스 업데이트
            if len(self._innovation_history) > 0:
                innovation = hr_final - self._innovation_history[-1] if len(self._innovation_history) > 0 else 0
                self._innovation_history.append(innovation)
                self.kalman_filter.adapt_noise(list(self._innovation_history))
        
        # 개인화된 보정 적용
        if self.personalized_model is not None:
            forehead_buffer = list(self.buffers.get('forehead', []))
            ambient_temp = float(np.mean(forehead_buffer)) if forehead_buffer else 25.0
            thermal_features = {
                'motion_level': self.motion.motion_level,
                'ambient_temp': ambient_temp
            }
            hr_final = self.personalized_model.get_personalized_correction(hr_final, thermal_features)

        return hr_final, q_final, diag


    def _compute_rr(self):
        if 'nose' not in self.buffers or len(self.buffers['nose']) < int(12*self.cfg.sampling_rate):
            return None, 0.0
        n = int(12*self.cfg.sampling_rate)
        x = self._preprocess_series('nose', n)
        if x is None:
            return None, 0.0
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

    def _maybe_status(self, hr, q, rr, dT_nose, dT_cheek, color_rec, artifacts):
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
            art = f" | Art:{artifacts}" if artifacts else ""
            logger.info(
                f"🫀 {hr if hr is not None else float('nan'):.1f} BPM | q={q:.2f} | "
                f"🌬 {rr_txt} brpm | ΔT_nose {dtn_txt} ΔT_cheek {dtc_txt} | "
                f"🎨 {mode} RGB{rgb} I={inten:.2f} {dur}s{art}"
            )
            st.update({'ts': now, 'hr': hr, 'rr': rr, 'q': q, 'dtn': dT_nose, 'dtc': dT_cheek})

    def _start_session(self):
        self.session_active = True
        self.session_reported = False
        self.session_start_ts = time.time()
        self.session_best = None
        self.session_measurements = []  # 세션 측정값 초기화
        logger.info("Measurement session started")

    def _reset_session(self):
        if self.session_active and not self.session_reported:
            logger.info("Measurement session reset without final result")
        self.session_active = False
        self.session_reported = False
        self.session_start_ts = 0.0
        self.session_best = None
        self.session_measurements = []

    def _update_session(self, hr, q, rr, dT_nose, dT_cheek, fh_temp, color_rec, diag, artifacts):
        if not self.session_active:
            return

        now = time.time()
        elapsed = now - self.session_start_ts if self.session_start_ts else 0.0

        # HR 60 이하는 제외 (기본 원칙)
        if hr is not None and hr > 60.0 and q >= self.cfg.session_quality_min:
            candidate = {
                'hr': float(hr),
                'q': float(q),
                'rr': float(rr) if rr is not None else None,
                'dT_nose': dT_nose,
                'dT_cheek': dT_cheek,
                'forehead_temp': fh_temp,
                'color_rec': color_rec,
                'diag': diag,
                'artifacts': artifacts,
                'timestamp': now,
            }
            # 세션 측정값 저장 (HR 60 초과만)
            self.session_measurements.append(candidate)
            if self.session_best is None:
                self.session_best = candidate
            else:
                best_q = self.session_best.get('q', 0.0)
                best_hr = self.session_best.get('hr')
                if candidate['q'] > best_q + 1e-3:
                    self.session_best = candidate
                elif abs(candidate['q'] - best_q) <= 1e-3 and best_hr is not None:
                    if abs(candidate['hr'] - best_hr) <= 2.0:
                        self.session_best = candidate
                else:
                    if candidate['artifacts'] and not self.session_best.get('artifacts'):
                        self.session_best['artifacts'] = candidate['artifacts']
                    if candidate['color_rec'] is not None and not self.session_best.get('color_rec'):
                        self.session_best['color_rec'] = candidate['color_rec']

        if self.session_reported:
            return
        
        # 세션 상태 디버깅 로그 (10초마다)
        if int(elapsed) % 10 == 0 and elapsed > 0:
            best_q = self.session_best.get('q', 0.0) if self.session_best else 0.0
            best_hr = self.session_best.get('hr') if self.session_best else None
            logger.info(f"📊 세션 진행 중: elapsed={elapsed:.1f}s / {self.cfg.session_max_duration:.1f}s | "
                       f"best_HR={best_hr:.1f if best_hr else 'None'}, best_Q={best_q:.2f} | "
                       f"측정값 수={len(self.session_measurements)} | "
                       f"조건: min_dur={elapsed >= self.cfg.session_min_duration}, "
                       f"q_target={best_q >= self.cfg.session_quality_target if self.session_best else False}")

        if self.session_best is None:
            # 측정값이 없어도 75초가 지나면 종료 (빈 세션이라도)
            if elapsed >= self.cfg.session_max_duration:
                logger.warning(f"⚠️ 세션 {elapsed:.1f}초 경과했으나 측정값 없음. 빈 세션으로 종료.")
                self._finalize_session("max_duration_empty")
            return

        # 최대 시간(75초)이 지나면 무조건 종료 및 전송
        if elapsed >= self.cfg.session_max_duration:
            logger.info(f"⏰ 세션 최대 시간 도달 ({elapsed:.1f}s >= {self.cfg.session_max_duration:.1f}s). 세션 완료 처리.")
            self._finalize_session("max_duration")
            return  # 세션 종료 후 더 이상 업데이트하지 않음
        # 최소 시간 지나고 품질 기준 만족하면 전송 (75초 전에 조기 완료 가능)
        elif elapsed >= self.cfg.session_min_duration and self.session_best['q'] >= self.cfg.session_quality_target:
            logger.info(f"✅ 세션 품질 기준 만족 ({elapsed:.1f}s, Q={self.session_best['q']:.2f}). 세션 완료 처리.")
            self._finalize_session("quality_target")
            return  # 세션 종료 후 더 이상 업데이트하지 않음

    def _finalize_session(self, reason: str):
        if self.session_reported:
            logger.warning(f"⚠️ 세션 이미 완료됨. reason={reason}")
            return
        
        # 측정값이 없어도 세션 완료 처리 (75초 종료 보장)
        if self.session_best is None:
            logger.warning(f"⚠️ 세션 완료 시도했으나 측정값 없음. reason={reason}")
            # 빈 세션이라도 통계는 계산 시도
            stats = self._calculate_session_statistics()
            if not stats:
                logger.error(f"❌ 세션 완료 실패: 측정값 없음. reason={reason}")
                self._reset_session()
                return
            # 통계가 있으면 계속 진행
        
        best = self.session_best if self.session_best else {}
        logger.info(f"🔔 세션 완료 시작: reason={reason}, HR={best.get('hr') if best else 'None'}, Q={best.get('q', 0.0):.2f if best else 0.0}")
        if best.get('color_rec') is None and self.therapist is not None:
            best['color_rec'] = self.therapist.recommend(
                ColorMetrics(
                    hr=best['hr'],
                    q=best['q'],
                    rr=best['rr'],
                    dT_nose=best['dT_nose'],
                    dT_cheek=best['dT_cheek'],
                    forehead_temp=best['forehead_temp']
                )
            )
        self.session_reported = True
        self._report_session_result(best, reason)

    def _calculate_session_statistics(self) -> Dict[str, Any]:
        """세션 측정값으로부터 통계 계산 (HR 60 초과만 포함)"""
        if not self.session_measurements:
            return {}
        
        # HR 60 초과만 필터링 (이미 저장 시 필터링했지만 재확인)
        valid_measurements = [m for m in self.session_measurements if m.get('hr') is not None and m.get('hr') > 60.0]
        if not valid_measurements:
            return {}
        
        # HR 값 추출
        hrs = [m['hr'] for m in valid_measurements]
        
        # 1. 최대 HR값을 가진 측정값
        hr_max = float(np.max(hrs))
        max_hr_measurement = max(valid_measurements, key=lambda m: m.get('hr', 0.0))
        
        # 2. 최빈값의 중앙값에 가장 가까운 측정값
        # HR을 1 BPM 단위로 반올림하여 구간별 그룹화
        hr_rounded = [round(h) for h in hrs]
        counter = Counter(hr_rounded)
        if counter:
            # 가장 빈도가 높은 값(들) 찾기
            max_count = max(counter.values())
            most_common_values = [val for val, count in counter.items() if count == max_count]
            # 가장 빈도 높은 구간의 원본 값들
            mode_hrs = [h for h, r in zip(hrs, hr_rounded) if r in most_common_values]
            hr_mode_median = float(np.median(mode_hrs)) if mode_hrs else hr_max
            # 중앙값에 가장 가까운 측정값 찾기
            mode_median_measurement = min(
                [m for m in valid_measurements if round(m.get('hr', 0)) in most_common_values],
                key=lambda m: abs(m.get('hr', 0) - hr_mode_median)
            )
        else:
            hr_mode_median = hr_max
            mode_median_measurement = max_hr_measurement
        
        # 3. 최고 q값을 가진 측정값
        qs = [m['q'] for m in valid_measurements if m.get('q') is not None]
        q_max = float(np.max(qs)) if qs else 0.0
        best_q_measurement = max(valid_measurements, key=lambda m: m.get('q', 0.0))
        
        return {
            'hr_max': hr_max,
            'hr_mode_median': hr_mode_median,
            'q_max': q_max,
            'max_hr_measurement': max_hr_measurement,  # 최대 HR값을 가진 측정값
            'mode_median_measurement': mode_median_measurement,  # 최빈값 중앙값에 가장 가까운 측정값
            'best_q_measurement': best_q_measurement,  # 최고 q값을 가진 측정값
            'total_measurements': len(valid_measurements)
        }

    def _report_session_result(self, best: Dict[str, Any], reason: str):
        elapsed = time.time() - self.session_start_ts if self.session_start_ts else 0.0
        
        # 세션 통계 계산 (HR 60 초과만 포함)
        stats = self._calculate_session_statistics()
        
        # 세 가지 기준으로 각각의 측정값 추출
        max_hr_measurement = stats.get('max_hr_measurement') if stats else None
        mode_median_measurement = stats.get('mode_median_measurement') if stats else None
        best_q_measurement = stats.get('best_q_measurement') if stats else None
        
        # 통계가 없으면 best를 세 가지 모두로 사용 (75초 종료 시 무조건 전송 보장)
        if not stats:
            logger.warning(f"⚠️ 세션 통계 없음 (HR 60 초과 측정값 없음). best를 세 가지 방식으로 모두 전송 | elapsed={elapsed:.1f}s")
            max_hr_measurement = best
            mode_median_measurement = best
            best_q_measurement = best
        
        if stats:
            logger.info(
                f"✅ Measurement finalized ({reason}) | elapsed={elapsed:.1f}s | "
                f"HR_max={stats['hr_max']:.1f} | HR_mode_median={stats['hr_mode_median']:.1f} | "
                f"Q_max={stats['q_max']:.2f} | measurements={stats['total_measurements']}"
            )
        else:
            logger.info(
                f"✅ Measurement finalized ({reason}) | elapsed={elapsed:.1f}s | "
                f"통계 없음 - best 사용: HR={best.get('hr')}, Q={best.get('q', 0.0):.2f}"
            )
        
        # 세 가지 측정값 각각에 대해 color_rec 생성 및 MQTT 전송
        measurements_to_send = [
            ('max_hr', max_hr_measurement, '최대 HR값'),
            ('mode_median', mode_median_measurement, '최빈값 중앙값'),
            ('best_q', best_q_measurement, '최고 Q값')
        ]
        
        for label, measurement, description in measurements_to_send:
            if measurement is None:
                continue
            
            # color_rec 생성/업데이트
            if measurement.get('color_rec') is None and self.therapist is not None:
                measurement['color_rec'] = self.therapist.recommend(
                    ColorMetrics(
                        hr=measurement.get('hr'),
                        q=measurement.get('q'),
                        rr=measurement.get('rr'),
                        dT_nose=measurement.get('dT_nose'),
                        dT_cheek=measurement.get('dT_cheek'),
                        forehead_temp=measurement.get('forehead_temp')
                    )
                )
            
            color_rec = measurement.get('color_rec')
            if color_rec is None:
                continue
            
            # 로깅
            self._maybe_status(
                measurement.get('hr'),
                measurement.get('q'),
                measurement.get('rr'),
                measurement.get('dT_nose'),
                measurement.get('dT_cheek'),
                color_rec,
                measurement.get('artifacts'),
            )
            
            # MQTT 전송 (세션 종료 시 무조건 전송 - 품질 체크 무시)
            if self.mqtt is not None:
                q_val = measurement.get('q', 0.0)
                try:
                    from networks.mqtt.mqtt_config import settings
                    logger.info(f"📤 MQTT 전송 시도 ({description}): {settings.host}:{settings.port} | "
                               f"total={settings.topic_total} | pico={settings.pico_topic} | "
                               f"HR={measurement.get('hr'):.1f}, Q={q_val:.2f} (세션 종료 - 무조건 전송)")
                    self.mqtt.publish_color(color_rec, metrics={
                        "hr": measurement.get('hr'),
                        "rr": measurement.get('rr'),
                        "q": measurement.get('q'),
                        "dT_nose": measurement.get('dT_nose'),
                        "dT_cheek": measurement.get('dT_cheek'),
                        "forehead": measurement.get('forehead_temp'),
                        "motion_px": self.motion.motion_level,
                        "artifacts": measurement.get('artifacts'),
                        "measurement_type": label,  # 어떤 기준인지 표시
                        "session_stats": {
                            "hr_max": stats.get('hr_max') if stats else None,
                            "hr_mode_median": stats.get('hr_mode_median') if stats else None,
                            "q_max": stats.get('q_max') if stats else None,
                            "total_measurements": stats.get('total_measurements') if stats else 0
                        }
                    }, also_pico=True)
                    logger.info(f"✅ MQTT 전송 완료 ({description}): {settings.topic_total} 및 {settings.pico_topic}")
                except Exception as exc:
                    logger.error(f"❌ MQTT publish failed ({description}): {exc}", exc_info=True)
            else:
                logger.error(f"❌ MQTT 클라이언트 없음. 전송 불가 ({description})")

    def _ambient_from_frame(self, up: np.ndarray, bbox):
        if bbox is None:
            return None
        H, W = up.shape
        x, y, w, h = bbox
        pad = int(0.06 * max(H, W))
        regions = []
        # top
        y0, y1 = max(0, y - pad), y
        x0, x1 = max(0, x - pad), min(W, x + w + pad)
        if y1 > y0 and x1 > x0: regions.append(up[y0:y1, x0:x1])
        # bottom
        y0, y1 = y + h, min(H, y + h + pad)
        if y1 > y0 and x1 > x0: regions.append(up[y0:y1, x0:x1])
        # left
        x0, x1 = max(0, x - pad), x
        y0, y1 = max(0, y - pad), min(H, y + h + pad)
        if y1 > y0 and x1 > x0: regions.append(up[y0:y1, x0:x1])
        # right
        x0, x1 = x + w, min(W, x + w + pad)
        y0, y1 = max(0, y - pad), min(H, y + h + pad)
        if y1 > y0 and x1 > x0: regions.append(up[y0:y1, x0:x1])

        if not regions:
            return None
        vals = [float(np.mean(r)) for r in regions if r.size > 0]
        return float(np.mean(vals)) if vals else None

    def _update_perspiration_flag(self):
        name = 'forehead'
        fs = self.cfg.sampling_rate
        need = int(self.cfg.persp_window_sec * fs) + 2
        if name not in self.buffers or len(self.buffers[name]) < need:
            return
        n = int(self.cfg.persp_window_sec * fs)
        arr = np.array(self.buffers[name], dtype=np.float32)
        seg = arr[-(n+1):]
        drop = float(seg[-1] - seg[0])
        if drop <= -self.cfg.persp_drop_degC:
            self._persp_until = max(self._persp_until, time.time() + self.cfg.persp_hold_sec)

    def _smooth_hr(self, hr_now: float) -> float:
        # """HR 점프 억제: (1) 속도 제한, (2) 저역 EMA."""
        t = time.time()
        if self._hr_smooth is None:
            # 첫 값은 그대로 채택
            self._hr_smooth = float(hr_now)
            self._hr_ts = t
            return float(hr_now)

        dt = max(1e-3, t - (self._hr_ts or t))
        # ① 속도 제한: 초당 hr_slope_bpm_per_s 를 넘지 않게
        max_step = self.cfg.hr_slope_bpm_per_s * dt
        limited = float(np.clip(hr_now,
                                self._hr_smooth - max_step,
                                self._hr_smooth + max_step))
        # ② EMA 평활
        a = self.cfg.hr_ema_alpha
        self._hr_smooth = float((1 - a) * self._hr_smooth + a * limited)
        self._hr_ts = t
        return self._hr_smooth
    
    def _maybe_realtime_mqtt(self, hr: float, q: float, rr: Optional[float], 
                            dT_nose: Optional[float], dT_cheek: Optional[float],
                            fh_temp: Optional[float], color_rec, artifacts: Optional[str]):
        """실시간 MQTT 전송 (세션 완료 전에도 주기적으로 전송)"""
        now = time.time()
        
        # 품질 체크
        if q < self.cfg.realtime_mqtt_quality_min:
            return
        
        # 주기 체크
        if now - self._last_realtime_mqtt_ts < self.cfg.realtime_mqtt_interval:
            return
        
        # MQTT 전송
        if self.mqtt is not None:
            try:
                from networks.mqtt.mqtt_config import settings
                self.mqtt.publish_color(color_rec, metrics={
                    "hr": hr,
                    "rr": rr,
                    "q": q,
                    "dT_nose": dT_nose,
                    "dT_cheek": dT_cheek,
                    "forehead": fh_temp,
                    "motion_px": self.motion.motion_level,
                    "artifacts": artifacts,
                    "measurement_type": "realtime",  # 실시간 전송임을 표시
                    "session_active": self.session_active,
                    "session_elapsed": time.time() - self.session_start_ts if self.session_start_ts else 0.0
                }, also_pico=True)
                self._last_realtime_mqtt_ts = now
                logger.info(f"📤 실시간 MQTT 전송: HR={hr:.1f} BPM, Q={q:.2f}, RR={rr:.1f if rr else '--'} brpm | "
                           f"세션 진행: {time.time() - self.session_start_ts:.1f}s" if self.session_start_ts else "세션 미시작")
            except Exception as exc:
                logger.error(f"❌ 실시간 MQTT 전송 실패: {exc}", exc_info=True)
    
    def _roi_dynamic_boost(self, diag: dict) -> dict:
    #"""
    #ROI별 가중치 보정값(곱셈용)을 반환.
    #- 이마가 상대적으로 신뢰도 높으면 1.15배
    #- 이마 땀/저SNR이면 0.9배
    #- 코/볼이 HR 합의에서 어긋나면 0.85배
    #"""
        boost = {'forehead': 1.0, 'l_cheek': 1.0, 'r_cheek': 1.0, 'nose': 1.0}
        if not diag:
            return boost

        # 통계치
        snrs  = [d.get('snr', 0.0) for d in diag.values()]
        harms = [d.get('harm', 0.0) for d in diag.values()]
        med_snr  = float(np.median(snrs)) if snrs else 0.0
        med_harm = float(np.median(harms)) if harms else 0.0

        f = diag.get('forehead')
        perspiring = (time.time() < self._persp_until)

        # 이마 보정
        if f:
            # 이마가 전반보다 확실히 좋으면 +15%
            if (f.get('snr', 0.0) >= med_snr + 0.2) and (f.get('harm', 0.0) >= med_harm):
                boost['forehead'] *= 1.15
            # 땀/저SNR이면 감산
            if perspiring or (f.get('snr', 0.0) < self.cfg.snr_face_min):
                boost['forehead'] *= 0.90

        # ROI 간 HR 불일치가 크면(튀는 ROI 감산)
        hrs = [d.get('hr') for d in diag.values() if 'hr' in d]
        if len(hrs) >= 2:
            hr_max, hr_min = max(hrs), min(hrs)
            if (hr_max - hr_min) > self.cfg.hr_agreement_bpm:
                f_hr = f.get('hr') if f else None
                for k in ('nose', 'l_cheek', 'r_cheek'):
                    if k in diag and f_hr is not None and 'hr' in diag[k]:
                        if abs(diag[k]['hr'] - f_hr) > (self.cfg.hr_agreement_bpm * 0.5):
                            boost[k] *= 0.85
        return boost

    def _rotate_sensor(self, img: np.ndarray, deg: float) -> np.ndarray:
    #"""센서가 물리적으로 돌아가 설치된 경우 영상 보정.
    #+deg는 CCW. 90/180/270 근사값은 손실없는 rot90 사용."""
        d = ((deg % 360) + 360) % 360
        h, w = img.shape[:2]

        # 정각 최적화(±2° 허용)
        if abs(d - 90) < 2:
            return np.rot90(img, k=1)        # 90° CCW
        if abs(d - 180) < 2:
            return np.rot90(img, k=2)        # 180°
        if abs(d - 270) < 2:
            return np.rot90(img, k=3)        # 270° CCW(=90° CW)

        # 임의 각도: 경계 보존 회전 후 원래 크기로 리사이즈
        cX, cY = w * 0.5, h * 0.5
        M = cv2.getRotationMatrix2D((cX, cY), d, 1.0)  # OpenCV는 +가 CCW
        cos, sin = abs(M[0, 0]), abs(M[0, 1])
        nW, nH = int((h * sin) + (w * cos)), int((h * cos) + (w * sin))
        M[0, 2] += (nW / 2) - cX
        M[1, 2] += (nH / 2) - cY
        rotated = cv2.warpAffine(img, M, (nW, nH), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return cv2.resize(rotated, (w, h), interpolation=cv2.INTER_CUBIC)
    
    def _update_ai_models(self, hr, diag, roi_vals, ambient_val):
        """AI 모델들을 업데이트하고 개인화 학습 수행"""
        try:
            # 앙상블 학습 모델 업데이트
            if self.ensemble_optimizer is not None and hr is not None:
                thermal_features = {
                    'motion_level': self.motion.motion_level,
                    'ambient_temp': ambient_val or 25.0
                }
                self.ensemble_optimizer.update_model(
                    diag, self.motion.motion_level, ambient_val or 25.0, hr
                )
            
            # 개인화 모델 업데이트
            if self.personalized_model is not None and hr is not None:
                thermal_features = {
                    'motion_level': self.motion.motion_level,
                    'ambient_temp': ambient_val or 25.0,
                    'roi_temps': roi_vals
                }
                ambient_conditions = {
                    'temperature': ambient_val or 25.0,
                    'motion': self.motion.motion_level
                }
                self.personalized_model.update_profile(hr, thermal_features, ambient_conditions)
                
            logger.debug("AI models updated successfully")
            
        except Exception as e:
            logger.warning(f"AI model update failed: {e}")

    # ---------- main loop ----------
    def run(self):
        try:
            while True:
                frame = self.sensor.read_frame()
                if frame is None:
                    time.sleep(0.001)
                    continue
                H, W = frame.shape

                if abs(self.cfg.sensor_rotation_deg) > 1e-3:
                    frame = self._rotate_sensor(frame, self.cfg.sensor_rotation_deg)

                # Super-res (stride)
                sr = None
                if self.mfsr is not None:
                    self.mfsr.push(frame)
                    self._sr_count += 1
                    if (self._sr_count % max(1, int(self.cfg.sr_stride))) == 0:
                        sr = self.mfsr.build()

                proc = sr if sr is not None else frame
                up = cv2.resize(proc, (W*self.up_scale, H*self.up_scale), interpolation=cv2.INTER_CUBIC)
                up_lr = cv2.resize(frame, (W*self.up_scale, H*self.up_scale), interpolation=cv2.INTER_CUBIC)

                # Detect + optional motion compensation
                bbox = self.detector.detect(up)
                tracking_ok = bbox is not None and self.detector.missed == 0
                if self.cfg.enable_motion_compensation and bbox is not None:
                    up = self.motion.compensate(up, bbox)
                    up_lr = self.motion.compensate(up_lr, bbox)

                # -------- PresenceGate BEFORE appending --------
                roi_vals, roi_boxes = self.roi.extract(up, bbox)
                ambient_val = self._ambient_from_frame(up, bbox)

                fh_inst = roi_vals.get('forehead') if roi_vals else None
                nose_inst = roi_vals.get('nose') if roi_vals else None
                lch_inst = roi_vals.get('l_cheek') if roi_vals else None
                rch_inst = roi_vals.get('r_cheek') if roi_vals else None

                present, why = self.presence.update(
                    bbox=bbox,
                    fh=fh_inst, nose=nose_inst, lch=lch_inst, rch=rch_inst,
                    ambient=ambient_val,
                    roi_diag={}  # spectral diag not ready yet
                )

                if present:
                    if roi_vals:
                        self._append(roi_vals, ambient_val)
                        # 빠른 측정 모드 시작
                        if self.fast_mode.is_active and self.fast_mode.measurement_start_time is None:
                            self.fast_mode.start_measurement()
                else:
                    self._decay_buffers_on_absent()

                # Artifacts update (keep)
                self._update_perspiration_flag()
                artifacts = []
                if time.time() < self._persp_until:
                    artifacts.append("sweat")
                if self.motion.motion_level > self.cfg.motion_px_warn:
                    artifacts.append("motion")
                art_txt = ",".join(artifacts) if artifacts else None

                if present and not self._was_present:
                    self._start_session()
                elif not present and self._was_present:
                    if self.session_active and not self.session_reported and self.session_best and \
                            self.session_best.get('q', 0.0) >= self.cfg.session_quality_target:
                        self._finalize_session("presence_lost")
                    self._reset_session()
                self._was_present = present

                # Compute vitals (throttled)
                now = time.time()
                hr, q, diag = (None, 0.0, {})
                if self._enough() and now >= self._hr_next_ts:
                    hr, q, diag = self._compute_hr()
                    self._hr_next_ts = now + self.cfg.hr_period
                    # 첫 HR 측정 시간 기록
                    if hr is not None and self.fast_mode.is_active:
                        self.fast_mode.record_first_hr()
                if hr is not None:
                    hr = self._smooth_hr(hr)    

                rr, rrq = (None, 0.0)
                if now >= self._rr_next_ts:
                    rr, rrq = self._compute_rr()
                    self._rr_next_ts = now + self.cfg.rr_period
                    # 첫 RR 측정 시간 기록
                    if rr is not None and self.fast_mode.is_active:
                        self.fast_mode.record_first_rr()

                dT_nose, dT_cheek, fh_temp = self._compute_dT(win_sec=5)

                # Label no-face reason for logs/UI
                if not present and why:
                    art_txt = (art_txt + f"|noface:{why}") if art_txt else f"noface:{why}"
                    # 얼굴 인식 실패 시 주기적 로깅
                    if hasattr(self, '_last_face_log_time'):
                        if time.time() - self._last_face_log_time > 10.0:  # 10초마다 로그
                            logger.warning(f"얼굴 인식 실패 지속: {why} | bbox={bbox is not None} | present={present}")
                            self._last_face_log_time = time.time()
                    else:
                        self._last_face_log_time = time.time()
                else:
                    # 얼굴 인식 성공 시 로깅
                    if hasattr(self, '_last_face_log_time'):
                        if time.time() - self._last_face_log_time > 30.0:  # 30초마다 성공 로그
                            logger.info(f"얼굴 인식 정상: present={present} | bbox={bbox is not None}")
                            self._last_face_log_time = time.time()

                # AI 모델 업데이트 및 개인화 학습
                now = time.time()
                if now - self._last_model_update >= self.cfg.model_update_interval:
                    self._update_ai_models(hr, diag, roi_vals, ambient_val)
                    self._last_model_update = now

                # Color recommendation (UI / session tracking)
                color_rec = None
                if hr is not None and present:
                    color_rec = self.therapist.recommend(
                        ColorMetrics(hr=hr, q=q, rr=rr, dT_nose=dT_nose, dT_cheek=dT_cheek, forehead_temp=fh_temp)
                    )
                self._update_session(hr, q, rr, dT_nose, dT_cheek, fh_temp, color_rec, diag, art_txt)
                
                # Real-time MQTT publishing (세션 완료 전에도 주기적으로 전송)
                if self.cfg.enable_realtime_mqtt and present and hr is not None and color_rec is not None:
                    self._maybe_realtime_mqtt(hr, q, rr, dT_nose, dT_cheek, fh_temp, color_rec, art_txt)

                # UI
                if self.monitor is not None:
                    thermal_u8_sr = normalize_to_uint8(up)
                    thermal_u8_lr = normalize_to_uint8(up_lr)
                    samples = len(self.buffers.get('forehead', [])) if present else 0
                    action = self.monitor.update(
                        thermal_u8_lr, bbox, roi_boxes, hr, q, rr, dT_nose, dT_cheek,
                        samples, thermal_u8_sr, tracking_ok, color_rec=color_rec, artifacts=art_txt
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
    debug_visual_env = os.getenv("RPPG_DEBUG_VISUAL", "1")
    debug_visual = debug_visual_env.lower() not in ("0", "false", "off")
    cfg = ThermalrPPGConfig(
        sampling_rate=16.0,
        min_measurement_duration=12,
        enable_motion_compensation=True,
        debug_visual=debug_visual,
        enable_superres=True,
        superres_scale=2,
        superres_frames=12,
        superres_deconvolution=True,

        status_interval=2.0,
        hr_period=0.75,
        rr_period=2.0,
        sr_stride=3,
        mc_stride=2,
        sensor_rotation_deg=135.0,
        
        # AI Enhancement features
        enable_ensemble_learning=True,
        enable_wavelet_denoising=True,
        enable_adaptive_filtering=True,
        enable_personalized_model=True,
        model_update_interval=300.0,
        
        # Raspberry Pi optimization
        enable_pi_optimization=True,
        pi_memory_limit_mb=512,
        pi_cpu_throttle=True,
        pi_reduced_precision=True,
        
        # Fast measurement mode (선택적 활성화)
        enable_fast_mode=False,  # True로 변경하면 빠른 측정 모드 활성화
        fast_min_duration=6,
        fast_hr_period=0.5,
        fast_present_frames=3,
        fast_sampling_rate=20.0,
        
        # Upscaling (카메라 거리에 따라 조정: 가까우면 3-4, 멀면 5-6)
        up_scale=4,  # 기본값 4 (기존 6에서 성능 향상을 위해 낮춤)
        
        # UI Display (모니터링 화면 크기 조절)
        ui_scale=2.5,  # 화면 확대 배수 (기본값 2.5배로 증가, 더 크게 보이도록)
        ui_window_width=1280,  # 창 초기 너비 (명시적 설정으로 더 크게 표시)
        ui_window_height=720,  # 창 초기 높이 (명시적 설정으로 더 크게 표시)
    )
    try:
        mqtt_pub = MqttColorPublisher().connect()
    except Exception as e:
        mqtt_pub = None
        logger.warning(f"MQTT disabled ({e}). Running without publish.")

    app = ThermalrPPG(cfg, mqtt_pub=mqtt_pub)
    print("Starting thermal rPPG (MLX9064X)… Press Q to quit, S to snapshot, T to toggle view (SR/LR/SPLIT).")
    print("Presence-gated; buffers don't grow when no face. Ambient/perspiration/motion handled. SNR-weighted multi-ROI.")
    app.run()
    if mqtt_pub:
        mqtt_pub.close()
