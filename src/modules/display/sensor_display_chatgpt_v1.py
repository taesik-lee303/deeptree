# sensor_display.py
"""
2.1인치 원형(기본 480x480) 디스플레이에 '현실적인 미니멀 자연 테마'로 센서 데이터를 렌더링.

자연 요소(하늘/태양·달 글로우/구름·헤이즈/잔디 스웨이/물결 리플)를
센서 값과 시간대에 연동:
- 시간대: 하늘 그라디언트/태양·달 위치, 색·밝기
- PM2.5: 구름의 농담과 헤이즈 강도
- 습도: 물방울/연무 강조
- PIR/소음: 바람 강도(잔디 스웨이)와 물결 리플

UI는 글래스모피즘 중앙 패널과 3개 카드(TEMP/HUM/PM2.5) + 하단 보조 정보(소음/PIR/시간).
Kafka 소비/큐 구조, Tkinter 프리뷰 유지.
"""

from __future__ import annotations

import argparse
import json
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import sys
import os
import random
import hashlib

# Kafka
try:
    from kafka import KafkaConsumer
except Exception as exc:  # pragma: no cover
    KafkaConsumer = None  # type: ignore
    _KAFKA_IMPORT_ERROR = exc
else:
    _KAFKA_IMPORT_ERROR = None

# Pillow
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
except Exception as exc:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore
    ImageFilter = None  # type: ignore
    ImageOps = None    # type: ignore
    _PILLOW_IMPORT_ERROR = exc
else:
    _PILLOW_IMPORT_ERROR = None

# Tkinter (옵션 미리보기)
try:
    import tkinter as tk
    from tkinter import Label
    from PIL import ImageTk
except Exception as exc:  # pragma: no cover
    tk = None  # type: ignore
    Label = None  # type: ignore
    ImageTk = None  # type: ignore
    _TKINTER_IMPORT_ERROR = exc
else:
    _TKINTER_IMPORT_ERROR = None

# 프로젝트 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from networks.kafka.kafka_config import settings


# -----------------------------
# 데이터 스냅샷
# -----------------------------
@dataclass
class SensorSnapshot:
    ts: Optional[float] = None
    device_id: Optional[str] = None
    temp_c: Optional[float] = None
    hum: Optional[float] = None
    noise: Optional[float] = None
    pir: Optional[int] = None
    pm1: Optional[float] = None
    pm25: Optional[float] = None
    pm10: Optional[float] = None
    raw: Dict[str, Any] | None = None
    ingested_at: float = field(default_factory=time.time)

    def has_payload(self) -> bool:
        return any(
            v is not None
            for v in (self.temp_c, self.hum, self.noise, self.pir, self.pm1, self.pm25, self.pm10)
        )


# -----------------------------
# 유틸
# -----------------------------
def _pick(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not math.isnan(float(value)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            s = s.replace(",", ".")
            try:
                return float(s)
            except ValueError:
                return None
    return None


def _to_int01(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if float(value) >= 0.5 else 0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "on", "motion", "triggered", "active"):
            return 1
        if s in ("0", "false", "off", "clear", "idle", "inactive"):
            return 0
    return None


def _parse_timestamp(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # ms 방어
            ts = ts / 1000.0
        return ts
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return _parse_timestamp(float(s))
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
    return None


def _extract_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    direct = {k for k in ("temp_c", "hum", "noise", "pir", "pm1", "pm25", "pm10") if k in payload}
    result = {"ts": payload.get("ts"), "device_id": payload.get("device_id")}
    if direct:
        for k in ("temp_c", "hum", "noise", "pir", "pm1", "pm25", "pm10"):
            result[k] = payload.get(k)
        return result

    base = payload.get("sensors") if isinstance(payload.get("sensors"), dict) else payload
    if not isinstance(base, dict):
        base = {}

    dht = base.get("dht22") if isinstance(base.get("dht22"), dict) else {}
    ir = base.get("ir") if isinstance(base.get("ir"), dict) else {}
    snd = base.get("sound") if isinstance(base.get("sound"), dict) else {}
    pm = base.get("pm") if isinstance(base.get("pm"), dict) else {}

    result.update(
        {
            "temp_c": _pick(dht, ["temp_c", "temperature", "temp", "t"]),
            "hum": _pick(dht, ["hum", "humidity", "h"]),
            "noise": _pick(snd, ["noise_raw", "noise", "value", "raw", "level"]),
            "pir": _pick(ir, ["pir", "motion", "value", "status"]) or _pick(base, ["pir", "motion"]),
            "pm1": _pick(pm, ["pm1", "pm1_0", "pm_1_0"]),
            "pm25": _pick(pm, ["pm25", "pm2_5", "pm2.5", "pm_2_5"]),
            "pm10": _pick(pm, ["pm10", "pm_10"]),
        }
    )
    return result


def _snapshot_from_payload(payload: Dict[str, Any]) -> SensorSnapshot | None:
    f = _extract_fields(payload)
    if not f:
        return None
    ts = _parse_timestamp(f.get("ts"))
    snap = SensorSnapshot(
        ts=ts,
        device_id=f.get("device_id") or payload.get("device"),
        temp_c=_to_float(f.get("temp_c")),
        hum=_to_float(f.get("hum")),
        noise=_to_float(f.get("noise")),
        pir=_to_int01(f.get("pir")),
        pm1=_to_float(f.get("pm1")),
        pm25=_to_float(f.get("pm25")),
        pm10=_to_float(f.get("pm10")),
    )
    return snap


# -----------------------------
# Tkinter 드라이버 (옵션)
# -----------------------------
class TkinterDisplayDriver:
    def __init__(self, diameter: int):
        if tk is None or ImageTk is None:
            raise RuntimeError(f"Tkinter import 실패: {_TKINTER_IMPORT_ERROR}")
        self.diameter = diameter
        self.root = tk.Tk()
        self.root.title("Sensor Display")
        self.root.geometry(f"{diameter + 20}x{diameter + 50}")
        self.root.configure(bg="black")

        self.label = Label(self.root, bg="black")
        self.label.pack(pady=10)

        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after_idle(lambda: self.root.attributes("-topmost", False))

    def display(self, image: Image.Image):
        photo = ImageTk.PhotoImage(image)
        self.label.configure(image=photo)
        self.label.image = photo
        self.root.update()


# -----------------------------
# 배경 캐시(성능) & 랜덤 시드
# -----------------------------
class BackgroundCache:
    def __init__(self):
        self.image: Optional[Image.Image] = None
        self.key: Optional[tuple] = None  # (phase, pm_tier, size)

    def get(self, key: tuple[int, int, int]) -> Optional[Image.Image]:
        if self.key == key and self.image is not None:
            return self.image.copy()
        return None

    def set(self, key: tuple[int, int, int], img: Image.Image) -> None:
        self.key = key
        self.image = img.copy()


def _hash_seed(s: str) -> int:
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


# -----------------------------
# 미니멀 자연 테마 렌더러
# -----------------------------
class CircularNaturalDisplay:
    # 팔레트
    SKY_DAY = ((160, 205, 255), (220, 240, 255))      # 상단→하단
    SKY_DAWN = ((255, 170, 120), (255, 220, 200))
    SKY_DUSK = ((130, 160, 220), (240, 210, 200))
    SKY_NIGHT = ((25, 35, 60), (60, 75, 110))
    RING = (210, 220, 235)
    HAZE = (220, 220, 220, 0)  # alpha 동적
    GRASS_NEAR = (70, 150, 80)
    GRASS_FAR = (110, 170, 120)
    HILL_1 = (90, 150, 110)
    HILL_2 = (120, 180, 140)
    HILL_3 = (150, 200, 160)
    TEXT_MAIN = (30, 40, 50)
    TEXT_SUB = (105, 115, 125)
    TEMP_COLOR = (255, 137, 115)
    HUM_COLOR = (110, 175, 245)
    PM_COLOR = (165, 140, 245)
    LIVE = (62, 201, 85)
    RECENT = (255, 187, 70)
    OLD = (235, 95, 85)
    GLASS = (255, 255, 255, 210)
    CARD_BORDER = (210, 220, 235)

    def __init__(
        self,
        *,
        diameter: int,
        font_path: str | None = None,
        dump_dir: Path | None = None,
        driver: Any | None = None,
        use_tkinter: bool = True,
    ) -> None:
        if Image is None or ImageDraw is None or ImageFont is None:
            raise RuntimeError(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")
        self.diameter = diameter
        self.center = diameter / 2.0

        if driver is None and use_tkinter:
            try:
                self.driver = TkinterDisplayDriver(diameter)
                print("[Display] Tkinter 디스플레이 드라이버 초기화 완료")
            except RuntimeError as e:
                print(f"[Display] Tkinter 드라이버 실패: {e}")
                self.driver = None
        else:
            self.driver = driver

        self.dump_dir = Path(dump_dir) if dump_dir else None
        if self.dump_dir:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
        self.frame_index = 0

        # 폰트
        self.font_xl = self._load_font(font_path, 110)
        self.font_lg = self._load_font(font_path, 64)
        self.font_md = self._load_font(font_path, 36)
        self.font_sm = self._load_font(font_path, 26)
        self.font_xs = self._load_font(font_path, 20)

        # 배경 캐시
        self.bg_cache = BackgroundCache()

        # 장면 랜덤 고정(디바이스별 다른 풍경)
        self.scene_seed = _hash_seed(os.uname().nodename if hasattr(os, "uname") else "deepcare")
        random.seed(self.scene_seed)

        # 물결 리플 상태
        self._ripple_start: Optional[float] = None

    # ---- 폰트/텍스트 ----
    def _load_font(self, font_path: str | None, size: int) -> ImageFont.ImageFont:
        candidates = []
        if font_path:
            candidates.append(Path(font_path))
        candidates.extend(
            Path(p)
            for p in (
                "C:/Windows/Fonts/malgun.ttf",
                "C:/Windows/Fonts/seguiemj.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            )
        )
        for c in candidates:
            if c.is_file():
                try:
                    return ImageFont.truetype(str(c), size)
                except OSError:
                    continue
        return ImageFont.load_default()

    @staticmethod
    def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
        if hasattr(draw, "textbbox"):
            l, t, r, b = draw.textbbox((0, 0), text, font=font)
            return int(r - l), int(b - t)
        return draw.textsize(text, font=font)

    def _draw_text(self, draw, text, xy, font, fill, align="center"):
        w, h = self._text_size(draw, text, font)
        if align == "center":
            pos = (xy[0] - w / 2.0, xy[1] - h / 2.0)
        elif align == "right":
            pos = (xy[0] - w, xy[1] - h / 2.0)
        else:
            pos = (xy[0], xy[1] - h / 2.0)
        draw.text(pos, text, font=font, fill=fill)

    # ---- 시간대/페이즈 ----
    def _phase_from_time(self, ts: Optional[float]) -> int:
        # 0=night, 1=dawn, 2=day, 3=dusk
        if ts is None:
            hour = datetime.now().hour
        else:
            hour = datetime.fromtimestamp(ts).hour
        if 22 <= hour or hour < 6:
            return 0
        if 6 <= hour < 8:
            return 1
        if 8 <= hour < 18:
            return 2
        return 3

    def _sky_colors(self, phase: int):
        return {
            0: self.SKY_NIGHT,
            1: self.SKY_DAWN,
            2: self.SKY_DAY,
            3: self.SKY_DUSK,
        }[phase]

    # ---- 그림자/글로우/라운드 ----
    def _soft_glow(self, base: Image.Image, x: float, y: float, r: float, color: tuple[int, int, int], alpha=200, blur=16):
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.ellipse((x - r, y - r, x + r, y + r), fill=color + (alpha,))
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
        base.alpha_composite(layer)

    def _rounded_rect(
        self,
        base: Image.Image,
        rect: tuple[int, int, int, int],
        radius: int,
        fill: tuple[int, int, int, int],
        outline: Optional[tuple[int, int, int]] = None,
        width: int = 1,
        shadow: bool = True,
    ):
        x0, y0, x1, y1 = rect
        w = x1 - x0
        h = y1 - y0
        card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((0, 0, w, h), radius=radius, fill=fill, outline=outline, width=width)
        if shadow:
            shadow_layer = Image.new("RGBA", (w + 10, h + 10), (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow_layer)
            sd.rounded_rectangle((5, 5, w + 5, h + 5), radius=radius + 2, fill=(0, 0, 0, 60))
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(3))
            base.alpha_composite(shadow_layer, (x0 - 5, y0 - 5))
        base.alpha_composite(card, (x0, y0))

    def _ring(self, draw: ImageDraw.ImageDraw, center: tuple[float, float], r: float, width: int, color: tuple[int, int, int]):
        x, y = center
        bbox = (x - r, y - r, x + r, y + r)
        draw.ellipse(bbox, outline=color, width=width)

    # ---- 자연 요소: 구름/언덕/잔디/헤이즈/물결 ----
    def _draw_sky(self, phase: int) -> Image.Image:
        img = Image.new("RGBA", (self.diameter, self.diameter), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        top, bottom = self._sky_colors(phase)
        for y in range(self.diameter):
            t = y / max(1, self.diameter - 1)
            r = int(top[0] * (1 - t) + bottom[0] * t)
            g = int(top[1] * (1 - t) + bottom[1] * t)
            b = int(top[2] * (1 - t) + bottom[2] * t)
            d.line([(0, y), (self.diameter, y)], fill=(r, g, b, 255))
        return img

    def _draw_sun_moon(self, canvas: Image.Image, phase: int, temp_c: Optional[float], ts: Optional[float]):
        # 위치: 시간대에 따라 좌→우 이동
        if ts is None:
            hour = datetime.now().hour + datetime.now().minute / 60.0
        else:
            dt = datetime.fromtimestamp(ts)
            hour = dt.hour + dt.minute / 60.0

        # x: 8h~18h 사이 가장 높음
        t = (hour - 6) / 12.0  # 6h 기준
        t = max(0.0, min(1.0, t))
        x = int(self.diameter * (0.15 + 0.7 * t))
        y = int(self.diameter * (0.22 - 0.12 * math.cos(t * math.pi)))  # 부드러운 포물선

        if phase == 0:  # night -> 달
            self._soft_glow(canvas, x, y, 22, (200, 220, 255), alpha=140, blur=20)
            ld = ImageDraw.Draw(canvas)
            ld.ellipse((x - 12, y - 12, x + 12, y + 12), fill=(230, 240, 255, 240))
        else:  # sun
            # 온도 영향: 뜨거울수록 크고 더 오렌지
            tr = 0.0 if temp_c is None else max(0.0, min(1.0, temp_c / 40.0))
            radius = 14 + 10 * tr
            col = (255, int(220 - 80 * tr), int(140 - 90 * tr))
            self._soft_glow(canvas, x, y, radius + 10, col, alpha=180, blur=18)
            ld = ImageDraw.Draw(canvas)
            ld.ellipse((x - radius, y - radius, x + radius, y + radius), fill=col + (230,))

    def _cloud_color(self, pm25: Optional[float]) -> tuple[int, int, int, int]:
        if pm25 is None:
            return (255, 255, 255, 210)
        intensity = min(max(pm25 / 150.0, 0.0), 1.0)
        base = 255 - int(120 * intensity)
        alpha = 210 - int(80 * intensity)
        return (base, base, base, max(100, alpha))

    def _draw_clouds(self, canvas: Image.Image, pm25: Optional[float], tsec: float):
        # 구름은 느리게 좌→우로 이동
        w, h = self.diameter, self.diameter
        col = self._cloud_color(pm25)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        random.seed(self.scene_seed)  # 장면 고정

        for i in range(5):
            base_y = int(h * (0.18 + 0.12 * i))
            size = int(40 + i * 8)
            speed = 6 + i * 2
            base_x = int((tsec * speed + 60 * i) % (w + 120)) - 60
            parts = [
                (base_x - size//2, base_y, size),
                (base_x, base_y - size//6, size + 8),
                (base_x + size//2, base_y + size//10, size - 6),
                (base_x + size, base_y, size//2),
            ]
            for cx, cy, s in parts:
                d.ellipse((cx - s, cy - s, cx + s, cy + s), fill=col)

        # 약간 블러로 부드럽게
        layer = layer.filter(ImageFilter.GaussianBlur(1.2))
        canvas.alpha_composite(layer)

    def _draw_haze(self, canvas: Image.Image, pm25: Optional[float], hum: Optional[float]):
        # PM2.5/습도 높을수록 헤이즈+연무 강조
        pm = 0.0 if pm25 is None else min(pm25, 150.0) / 150.0
        hm = 0.0 if hum is None else min(max(hum - 60.0, 0.0) / 40.0, 1.0)
        alpha = int(30 + 90 * max(pm, hm))
        haze = Image.new("RGBA", canvas.size, (220, 225, 230, alpha))
        canvas.alpha_composite(haze)

    def _draw_hills(self, canvas: Image.Image):
        w, h = self.diameter, self.diameter
        y_base = int(h * 0.72)

        def hill_layer(offset: float, amp: float, step: int, color: tuple[int, int, int], blur=0):
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            points = []
            for x in range(0, w + step, step):
                y = y_base + int(math.sin((x + offset) * 0.012) * amp) + int(math.sin((x + 2*offset) * 0.004) * amp * 0.6)
                points.append((x, y))
            points = [(0, h), (0, points[0][1])] + points + [(w, points[-1][1]), (w, h)]
            d.polygon(points, fill=color + (255,))
            if blur:
                layer = layer.filter(ImageFilter.GaussianBlur(blur))
            canvas.alpha_composite(layer)

        # 뒤→앞 (대기원근, 밝게→짙게)
        hill_layer(30, 8, 8, self.HILL_3, blur=2)
        hill_layer(0, 12, 6, self.HILL_2, blur=1)
        hill_layer(-20, 18, 5, self.HILL_1, blur=0)

    def _draw_grass(self, canvas: Image.Image, tsec: float, wind_strength: float):
        w, h = self.diameter, self.diameter
        y_start = int(h * 0.78)
        d = ImageDraw.Draw(canvas)

        # 바닥 초록 그라디언트
        for y in range(y_start, h):
            t = (y - y_start) / max(1, (h - y_start))
            r = int(self.GRASS_FAR[0] * (1 - t) + self.GRASS_NEAR[0] * t)
            g = int(self.GRASS_FAR[1] * (1 - t) + self.GRASS_NEAR[1] * t)
            b = int(self.GRASS_FAR[2] * (1 - t) + self.GRASS_NEAR[2] * t)
            # 원형 클리핑 고려: 좌우 여백 줄이기
            radius_at_y = math.sqrt(max(self.center ** 2 - (y - self.center) ** 2, 0))
            x0 = int(self.center - radius_at_y)
            x1 = int(self.center + radius_at_y)
            d.line([(x0, y), (x1, y)], fill=(r, g, b, 255))

        # 앞으로 들어오는 잔디 줄기 (가까운 영역만)
        blades = 42
        for i in range(blades):
            base_x = int(self.center - self.diameter * 0.35 + (i / (blades - 1)) * self.diameter * 0.70)
            base_y = int(h * 0.90 + (i % 5) - 2)
            height = 18 + (i % 9)
            sway = math.sin(tsec * (1.4 + 0.1 * i) + i * 0.35) * (1.0 + wind_strength * 1.8)
            top_x = base_x + sway
            top_y = base_y - height
            col = (60 + (i % 3) * 10, 160 + (i % 4) * 10, 70 + (i % 5) * 6)
            d.line([(base_x, base_y), (top_x, top_y)], fill=col + (255,), width=2)

    def _draw_ripple(self, canvas: Image.Image, tsec: float, trigger: bool):
        # PIR로 트리거, 일정 시간 감쇠
        now = tsec
        if trigger and self._ripple_start is None:
            self._ripple_start = now
        if self._ripple_start is None:
            return
        elapsed = now - self._ripple_start
        if elapsed > 2.5:
            self._ripple_start = None
            return

        cx, cy = int(self.center), int(self.diameter * 0.82)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        rings = 5
        for i in range(rings):
            r = int(8 + (elapsed * 90) + i * 10)
            alpha = max(0, 120 - int((elapsed * 60) + i * 18))
            d.ellipse((cx - r, cy - 10 - r//6, cx + r, cy + r//6), outline=(200, 220, 255, alpha), width=1)
        layer = layer.filter(ImageFilter.GaussianBlur(0.6))
        canvas.alpha_composite(layer)

    def _draw_dew(self, canvas: Image.Image, hum: Optional[float]):
        if hum is None or hum < 82:
            return
        # 상단 좌우에 작은 물방울
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        drops = [(self.center - 90, self.diameter * 0.32), (self.center + 110, self.diameter * 0.28)]
        for (x, y) in drops:
            d.ellipse((x - 6, y - 10, x + 6, y + 6), fill=(180, 210, 255, 110))
            d.ellipse((x - 2, y - 6, x + 1, y - 3), fill=(255, 255, 255, 160))
        layer = layer.filter(ImageFilter.GaussianBlur(0.5))
        canvas.alpha_composite(layer)

    # ---- UI: 중앙 패널/카드/푸터 ----
    def _draw_center_panel(self, draw: ImageDraw.ImageDraw, base: Image.Image, snapshot: SensorSnapshot):
        cx, cy = self.center, self.center * 0.98
        card_w, card_h = int(self.diameter * 0.62), int(self.diameter * 0.28)
        rect = (int(cx - card_w / 2), int(cy - card_h / 2), int(cx + card_w / 2), int(cy + card_h / 2))
        self._rounded_rect(base, rect, radius=28, fill=self.GLASS, outline=self.CARD_BORDER, width=2, shadow=True)

        device = snapshot.device_id or "Device"
        self._draw_text(draw, device, (cx, rect[1] + 22), self.font_sm, self.TEXT_SUB)

        if snapshot.temp_c is not None:
            main_txt = f"{snapshot.temp_c:.1f}°C"
            color = self.TEMP_COLOR
        elif snapshot.hum is not None:
            main_txt = f"{snapshot.hum:.0f}%"
            color = self.HUM_COLOR
        else:
            main_txt, color = "---", self.TEXT_MAIN

        self._draw_text(draw, main_txt, (cx, cy + 6), self.font_xl, color)

        age = time.time() - snapshot.ingested_at
        if age < 5:  status, s_col = "● LIVE", self.LIVE
        elif age < 30: status, s_col = "● RECENT", self.RECENT
        else:        status, s_col = "● OLD", self.OLD
        self._draw_text(draw, status, (cx, rect[3] - 20), self.font_xs, s_col)

    def _draw_sensor_cards(self, draw: ImageDraw.ImageDraw, base: Image.Image, snapshot: SensorSnapshot):
        items = [
            ("🌡️ TEMP", snapshot.temp_c, "°C", self.TEMP_COLOR),
            ("💧 HUM", snapshot.hum, "%", self.HUM_COLOR),
            ("🌫️ PM2.5", snapshot.pm25, "µg/m³", self.PM_COLOR),
        ]
        card_w, card_h = 168, 98
        radius = self.diameter * 0.36
        total = 3
        for i, (label, value, unit, color) in enumerate(items):
            angle = (-85 + i * (360 / total)) * math.pi / 180.0
            x = self.center + radius * math.cos(angle)
            y = self.center - self.diameter * 0.08 + radius * math.sin(angle)
            rect = (int(x - card_w / 2), int(y - card_h / 2), int(x + card_w / 2), int(y + card_h / 2))
            self._rounded_rect(base, rect, radius=18, fill=(255, 255, 255, 225), outline=self.CARD_BORDER, width=2, shadow=True)
            self._draw_text(draw, label, (x, rect[1] + 20), self.font_xs, self.TEXT_SUB)
            if value is None:
                self._draw_text(draw, "--", (x, y + 6), self.font_lg, self.TEXT_SUB)
            else:
                self._draw_text(draw, f"{value:.1f}", (x - 22, y + 6), self.font_lg, color)
                self._draw_text(draw, unit, (x + 56, y + 10), self.font_sm, color)

    def _draw_footer(self, draw: ImageDraw.ImageDraw, base: Image.Image, snapshot: SensorSnapshot):
        cx, y = self.center, int(self.diameter * 0.90)
        draw.line([(int(cx - self.diameter * 0.28), y - 24), (int(cx + self.diameter * 0.28), y - 24)],
                  fill=self.CARD_BORDER, width=1)
        now = datetime.now().strftime("%H:%M")
        self._draw_text(draw, f"🕒 {now}", (cx, y), self.font_sm, self.TEXT_SUB)
        if snapshot.noise is not None:
            self._draw_text(draw, f"  ·  🔊 {int(snapshot.noise)} dB", (cx + 90, y), self.font_sm, self.TEXT_SUB)
        if snapshot.pir is not None:
            icon = "👁️" if snapshot.pir else "😴"
            self._draw_text(draw, f"  ·  {icon}", (cx + 220, y), self.font_sm, self.TEXT_SUB)

    # ---- 메인 렌더 ----
    def render(self, snapshot: SensorSnapshot) -> Image.Image:
        phase = self._phase_from_time(snapshot.ts or time.time())
        pm = snapshot.pm25 if snapshot.pm25 is not None else 0.0
        pm_tier = 0 if pm < 35 else (1 if pm < 75 else 2)

        # 배경 캐시(시간대/PM tier/크기)
        cache_key = (phase, pm_tier, self.diameter)
        bg = self.bg_cache.get(cache_key)
        tsec = time.time()
        if bg is None:
            # 하늘
            sky = self._draw_sky(phase)
            # 태양/달
            self._draw_sun_moon(sky, phase, snapshot.temp_c, snapshot.ts)
            # 구름(초기 위치)
            self._draw_clouds(sky, snapshot.pm25, tsec * 0)  # 정지 상태로 캡처
            # 언덕
            self._draw_hills(sky)
            # 헤이즈(기본 pm tier 반영)
            self._draw_haze(sky, snapshot.pm25, snapshot.hum)
            self.bg_cache.set(cache_key, sky)
            bg = sky

        # 동적요소를 위한 복사본
        canvas = bg.copy()
        draw = ImageDraw.Draw(canvas)

        # 구름 애니메이션(느리게)
        self._draw_clouds(canvas, snapshot.pm25, tsec * 0.10)

        # 잔디 스웨이 & 바닥
        wind_strength = 0.0
        if snapshot.pir:
            wind_strength += 0.9
        if snapshot.noise is not None:
            # 40~80dB → 0~1
            wind_strength += max(0.0, min(1.0, (snapshot.noise - 40.0) / 40.0)) * 0.6
        self._draw_grass(canvas, tsec, wind_strength)

        # 습도 물방울/연무 강조
        self._draw_dew(canvas, snapshot.hum)

        # PIR 물결 리플
        self._draw_ripple(canvas, tsec, bool(snapshot.pir))

        # 중앙 패널/카드/푸터
        self._draw_center_panel(draw, canvas, snapshot)
        self._draw_sensor_cards(draw, canvas, snapshot)
        self._draw_footer(draw, canvas, snapshot)

        # 원형 마스크/링
        mask = Image.new("L", (self.diameter, self.diameter), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse((0, 0, self.diameter, self.diameter), fill=255)
        final = Image.new("RGBA", (self.diameter, self.diameter), (255, 255, 255, 0))
        final.paste(canvas, (0, 0), mask)

        ring_draw = ImageDraw.Draw(final)
        self._ring(ring_draw, (self.center, self.center), self.center - 2, 2, self.RING)

        return final.convert("RGB")

    # ---- 프레젠트 ----
    def present(self, image: Image.Image) -> None:
        presented = False
        if self.driver is not None:
            try:
                if hasattr(self.driver, "display"):
                    self.driver.display(image)
                    presented = True
                elif hasattr(self.driver, "image"):
                    self.driver.image(image)
                    presented = True
            except Exception as e:
                print(f"[Display] 드라이버 오류: {e}")

        if not presented:
            print("[Display] 드라이버가 없어 화면에 표시되지 않습니다.")

        if self.dump_dir:
            frame_path = self.dump_dir / f"frame_{self.frame_index:06d}.png"
            image.save(frame_path)
            print(f"[Display] 프레임 저장: {frame_path}")
        self.frame_index += 1


# -----------------------------
# Kafka 스트림
# -----------------------------
class KafkaSensorStream:
    def __init__(self, out_queue: queue.Queue[SensorSnapshot], *, debug: bool = False) -> None:
        self.out_queue = out_queue
        self.debug = debug
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if KafkaConsumer is None:
            raise RuntimeError(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, name="kafka-sensor-consumer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _publish(self, snapshot: SensorSnapshot) -> None:
        try:
            self.out_queue.put(snapshot, timeout=0.05)
        except queue.Full:
            try:
                self.out_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.out_queue.put(snapshot, timeout=0.05)
            except queue.Full:
                if self.debug:
                    print("[Kafka] 출력 큐가 가득 찼습니다.")

    def _run(self) -> None:
        try:
            print(f"[Kafka] 연결 시도 중... servers: {settings.bootstrap_servers}")
            consumer = KafkaConsumer(
                enable_auto_commit=True,
                value_deserializer=lambda v: v.decode(settings.value_encoding, "ignore"),
                consumer_timeout_ms=1000,
                **settings.kafka_kwargs,
            )
            print(f"[Kafka] 소비자 생성 완료")
            consumer.subscribe([settings.sensor_topic])
            print(f"[Kafka] 토픽 구독 완료: {settings.sensor_topic}")
        except Exception as exc:
            print(f"[Kafka] 소비자 초기화 실패: {exc}")
            return

        while not self._stop_evt.is_set():
            try:
                records = consumer.poll(timeout_ms=500)
            except Exception as exc:
                print(f"[Kafka] poll 실패: {exc}")
                time.sleep(1.0)
                continue
            if not records:
                continue
            for messages in records.values():
                for message in messages:
                    raw_value = message.value
                    try:
                        payload = json.loads(raw_value)
                    except Exception as exc:
                        if self.debug:
                            print(f"[Kafka] JSON 파싱 실패: {exc} :: {raw_value!r}")
                        continue
                    snapshot = _snapshot_from_payload(payload)
                    if snapshot is None:
                        if self.debug:
                            print(f"[Kafka] 지원하지 않는 페이로드: {payload}")
                        continue
                    snapshot.raw = payload
                    snapshot.ingested_at = time.time()
                    self._publish(snapshot)
        try:
            consumer.close()
        except Exception:
            pass


# -----------------------------
# 엔트리 포인트
# -----------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Kafka -> 원형 디스플레이 센서 뷰어 (현실적 자연 테마)")
    p.add_argument("--diameter", type=int, default=settings.diameter_pixels, help="디스플레이 지름(px)")
    p.add_argument("--font", type=str, default=settings.font_path, help="TTF 폰트 경로")
    p.add_argument("--refresh-hz", type=float, default=settings.display_refresh_hz, help="화면 갱신 주기(Hz)")
    p.add_argument("--frame-dump", type=str, default=None, help="프레임 저장 디렉터리(옵션)")
    p.add_argument("--debug", action="store_true", help="디버그 로그")
    return p


def main() -> None:
    if KafkaConsumer is None:
        raise SystemExit(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
    if Image is None or ImageDraw is None or ImageFont is None:
        raise SystemExit(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")

    args = build_arg_parser().parse_args()
    print(f"[Main] 시작 - 디버그 모드: {args.debug}")
    print(f"[Main] Kafka 설정: {settings.bootstrap_servers} / {settings.sensor_topic}")

    refresh_hz = args.refresh_hz if args.refresh_hz > 0 else 1.0
    refresh_period = 1.0 / refresh_hz

    dump_dir = Path(args.frame_dump) if args.frame_dump else None
    display = CircularNaturalDisplay(
        diameter=args.diameter,
        font_path=args.font,
        dump_dir=dump_dir,
    )

    out_queue: queue.Queue[SensorSnapshot] = queue.Queue(maxsize=16)
    stream = KafkaSensorStream(out_queue, debug=args.debug)
    print("[Main] 카프카 스트림 시작...")
    stream.start()

    latest = SensorSnapshot()
    next_frame = time.time()

    try:
        while True:
            timeout = max(0.0, next_frame - time.time())
            try:
                snapshot = out_queue.get(timeout=timeout if timeout > 0 else 0.01)
                latest = snapshot
            except queue.Empty:
                pass

            now = time.time()
            if now >= next_frame:
                image = display.render(latest if latest.has_payload() else latest)
                display.present(image)
                next_frame = now + refresh_period
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()


if __name__ == "__main__":
    main()
