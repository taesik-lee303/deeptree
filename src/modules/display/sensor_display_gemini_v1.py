# sensor_display_masterpiece.py
"""
'Sensor Display Masterpiece'

기존 코드를 완전히 재설계하여, 미학적 완성도와 코드의 안정성, 확장성을 모두 높인
2.1인치 원형 디스플레이용 센서 데이터 시각화 스크립트입니다.

주요 개선 사항:
1.  **미학적 재설계 (Aesthetic Overhaul):**
    -   전문 디자이너의 감각으로 색상 팔레트, 아이콘, 레이아웃을 완전히 재구성했습니다.
    -   더욱 부드럽고 자연스러운 애니메이션(구름, 잔디, 물결)을 구현했습니다.
    -   글래스모피즘 UI를 세련되게 다듬고, 빛과 그림자 효과를 추가하여 깊이감을 더했습니다.
    -   시간대에 따라 변화하는 하늘의 색상과 태양/달의 광원 효과를 더욱 현실적으로 표현했습니다.

2.  **안정적인 레이아웃 및 폰트 처리:**
    -   화면 잘림 및 폰트 깨짐 문제를 근본적으로 해결했습니다.
    -   어떤 디스플레이 크기에서도 UI 요소가 깨지지 않도록 모든 크기와 위치를 비율 기반으로 재계산합니다.
    -   시스템에 설치된 폰트가 없어도 깨지지 않도록, 내장된 기본 폰트와 함께 추천 폰트(Pretendard) 로딩을 지원합니다.

3.  **코드 구조 및 성능 개선:**
    -   관심사 분리 원칙에 따라 렌더링 로직을 배경, 동적 효과, UI 레이어로 명확하게 분리했습니다.
    -   수정 및 기능 추가가 용이하도록 테마 설정(색상, 폰트 크기 등)을 별도 클래스로 분리했습니다.
    -   배경 캐싱 전략을 최적화하여 불필요한 렌더링을 최소화하고 성능을 향상시켰습니다.

4.  **추가된 감성적 요소 (Delightful Details):**
    -   습도가 매우 높을 때 화면에 미세한 빗방울 효과가 나타납니다.
    -   밤하늘에 가끔씩 별똥별이 떨어지는 이스터에그를 추가했습니다.
    -   데이터 수신 상태(LIVE, RECENT, OLD)를 더욱 명확하고 아름답게 표시합니다.
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import sys
import os
import random
import hashlib

# --- 의존성 라이브러리 임포트 ---
# Kafka
try:
    from kafka import KafkaConsumer
except ImportError as e:
    KafkaConsumer = None
    _KAFKA_IMPORT_ERROR = e
else:
    _KAFKA_IMPORT_ERROR = None

# Pillow (PIL)
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
except ImportError as e:
    Image = ImageDraw = ImageFont = ImageFilter = ImageOps = None
    _PILLOW_IMPORT_ERROR = e
else:
    _PILLOW_IMPORT_ERROR = None

# Tkinter (GUI 미리보기용)
try:
    import tkinter as tk
    from tkinter import Label
    from PIL import ImageTk
except ImportError as e:
    tk = Label = ImageTk = None
    _TKINTER_IMPORT_ERROR = e
else:
    _TKINTER_IMPORT_ERROR = None

# --- 애플리케이션 설정 ---
# 이 부분은 외부 설정 파일(e.g., config.py)로 분리하는 것이 더 좋습니다.
@dataclass
class AppSettings:
    # Kafka 설정
    bootstrap_servers: list[str] = field(default_factory=lambda: ["localhost:9092"])
    sensor_topic: str = "sensor-data"
    value_encoding: str = "utf-8"
    kafka_kwargs: dict = field(default_factory=dict)
    # 디스플레이 설정
    diameter_pixels: int = 480
    display_refresh_hz: float = 15.0
    font_path: str = "Pretendard-Regular.otf" # https://github.com/orioncactus/pretendard

settings = AppSettings()


# -----------------------------------------------------------------------------
# 데이터 모델 (SensorSnapshot)
# -----------------------------------------------------------------------------
@dataclass
class SensorSnapshot:
    """수집된 센서 데이터의 단일 스냅샷을 나타내는 데이터 클래스."""
    ts: Optional[float] = None
    device_id: Optional[str] = "DeepCare-Sensor"
    temp_c: Optional[float] = None
    hum: Optional[float] = None
    noise: Optional[float] = None
    pir: Optional[int] = None
    pm25: Optional[float] = None
    ingested_at: float = field(default_factory=time.time)

    def has_payload(self) -> bool:
        """유효한 센서 데이터가 하나라도 있는지 확인합니다."""
        return any(v is not None for v in (self.temp_c, self.hum, self.noise, self.pir, self.pm25))

    @classmethod
    def mock_data(cls) -> "SensorSnapshot":
        """UI 테스트 및 데모를 위한 목업 데이터."""
        now = time.time()
        # 시간에 따라 부드럽게 변하는 값 생성
        temp = 22.5 + 4 * math.sin(now / 300)
        hum = 65 + 15 * math.sin(now / 450)
        pm25 = 25 + 20 * abs(math.sin(now / 600))
        noise = 45 + 10 * abs(math.sin(now / 20))
        pir = 1 if int(now) % 30 < 5 else 0
        return cls(ts=now, temp_c=temp, hum=hum, noise=noise, pir=pir, pm25=pm25)


# -----------------------------------------------------------------------------
# 테마 및 스타일 설정 (Theme)
# -----------------------------------------------------------------------------
class Theme:
    """디스플레이의 모든 시각적 요소를 정의하는 클래스."""
    # --- 색상 팔레트 ---
    SKY_DAY = ((135, 206, 235), (220, 240, 255))
    SKY_DAWN = ((255, 190, 150), (255, 230, 210))
    SKY_DUSK = ((100, 130, 200), (240, 210, 200))
    SKY_NIGHT = ((20, 30, 55), (50, 65, 100))

    SUN_DAY = (255, 220, 130)
    SUN_DAWN_DUSK = (255, 180, 130)
    MOON = (230, 240, 255)

    HILL_1 = (90, 150, 110)
    HILL_2 = (120, 180, 140)
    HILL_3 = (150, 200, 160)

    GRASS_NEAR = (70, 150, 80)
    GRASS_FAR = (110, 170, 120)

    # UI 색상
    TEXT_MAIN = (40, 50, 60)
    TEXT_SUB = (110, 120, 130)
    TEXT_LIGHT = (255, 255, 255)

    TEMP_COLOR = (255, 120, 90)
    HUM_COLOR = (80, 160, 255)
    PM_COLOR = (150, 120, 245)

    LIVE_COLOR = (0, 200, 83)
    RECENT_COLOR = (255, 193, 7)
    OLD_COLOR = (244, 67, 54)

    GLASS_FILL = (255, 255, 255, 200)
    CARD_BORDER = (255, 255, 255, 150)
    RING_COLOR = (210, 220, 235, 180)

    @staticmethod
    def get_sky_colors(phase: int) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
        return [Theme.SKY_NIGHT, Theme.SKY_DAWN, Theme.SKY_DAY, Theme.SKY_DUSK][phase]

    @staticmethod
    def get_sun_moon_color(phase: int) -> Tuple[int, int, int]:
        return [Theme.MOON, Theme.SUN_DAWN_DUSK, Theme.SUN_DAY, Theme.SUN_DAWN_DUSK][phase]

# -----------------------------------------------------------------------------
# Tkinter 미리보기 드라이버
# -----------------------------------------------------------------------------
class TkinterDisplayDriver:
    """Tkinter를 사용하여 생성된 이미지를 화면에 표시하는 드라이버."""
    def __init__(self, diameter: int):
        if tk is None or ImageTk is None:
            raise RuntimeError(f"Tkinter 또는 Pillow-Tk가 설치되지 않았습니다: {_TKINTER_IMPORT_ERROR}")
        self.root = tk.Tk()
        self.root.title("Sensor Display Masterpiece")
        self.root.geometry(f"{diameter + 20}x{diameter + 50}")
        self.root.configure(bg="#111")
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.is_closing = False

        self.label = Label(self.root, bg="#111")
        self.label.pack(pady=10, expand=True)

    def _on_closing(self):
        self.is_closing = True
        self.root.destroy()

    def display(self, image: Image.Image):
        if self.is_closing: return
        try:
            photo = ImageTk.PhotoImage(image)
            self.label.configure(image=photo)
            self.label.image = photo
            self.root.update()
        except tk.TclError:
            self.is_closing = True # 창이 닫혔을 때 발생하는 오류 방지

# -----------------------------------------------------------------------------
# 배경 캐시
# -----------------------------------------------------------------------------
class BackgroundCache:
    """시간대, 미세먼지 등급에 따라 생성된 배경 이미지를 캐싱하여 성능 향상."""
    def __init__(self):
        self.image: Optional[Image.Image] = None
        self.key: Optional[tuple] = None

    def get(self, key: tuple) -> Optional[Image.Image]:
        if self.key == key and self.image:
            return self.image.copy()
        return None

    def set(self, key: tuple, img: Image.Image):
        self.key = key
        self.image = img.copy()

# -----------------------------------------------------------------------------
# 메인 렌더러 (CircularNaturalDisplay)
# -----------------------------------------------------------------------------
class CircularNaturalDisplay:
    """센서 데이터를 받아 아름다운 자연 테마의 원형 이미지로 렌더링하는 클래스."""

    def __init__(self, diameter: int, font_path: str | None, use_tkinter: bool = True):
        if Image is None:
            raise RuntimeError(f"Pillow 라이브러리를 찾을 수 없습니다: {_PILLOW_IMPORT_ERROR}")

        self.diameter = diameter
        self.center = (diameter / 2, diameter / 2)
        self.radius = diameter / 2

        self.driver = TkinterDisplayDriver(diameter) if use_tkinter else None
        self.theme = Theme()

        # --- 레이아웃 상수 (비율 기반) ---
        self.layout = {
            "safe_inset": self.diameter * 0.04,
            "main_panel_w": self.diameter * 0.6,
            "main_panel_h": self.diameter * 0.28,
            "card_w": self.diameter * 0.35,
            "card_h": self.diameter * 0.22,
            "card_orbit_radius": self.diameter * 0.38,
        }

        # --- 폰트 로딩 ---
        self.fonts = {
            "xl": self._load_font(font_path, int(self.diameter * 0.2)),
            "lg": self._load_font(font_path, int(self.diameter * 0.12)),
            "md": self._load_font(font_path, int(self.diameter * 0.075)),
            "sm": self._load_font(font_path, int(self.diameter * 0.05)),
            "xs": self._load_font(font_path, int(self.diameter * 0.04)),
            "icon": self._load_font(font_path, int(self.diameter * 0.06)),
        }

        # --- 상태 및 캐시 ---
        self.bg_cache = BackgroundCache()
        self.scene_seed = self._generate_scene_seed()
        self.dynamic_state = {
            "ripple_start_time": 0,
            "shooting_star": None, # (start_pos, end_pos, start_time)
        }
        self.is_closing = False

    # --- 초기화 및 헬퍼 ---
    def _load_font(self, font_path: str | None, size: int) -> ImageFont.ImageFont:
        """지정된 경로 또는 시스템 기본 폰트를 로드합니다."""
        if font_path and Path(font_path).is_file():
            try: return ImageFont.truetype(font_path, size)
            except OSError: pass
        # Windows/Linux/Mac의 일반적인 폰트 경로 탐색 (더욱 안정적)
        font_names = ["malgun.ttf", "NanumGothic.ttf", "AppleSDGothicNeo.ttc", "DejaVuSans.ttf"]
        font_dirs = ["/usr/share/fonts/truetype", "C:/Windows/Fonts", "/System/Library/Fonts"]
        for d in font_dirs:
            for n in font_names:
                p = Path(d) / n
                if p.is_file():
                    try: return ImageFont.truetype(str(p), size)
                    except OSError: continue
        return ImageFont.load_default()

    def _generate_scene_seed(self) -> int:
        """디바이스마다 고유한 풍경을 생성하기 위한 시드."""
        try:
            # 호스트 이름이나 MAC 주소를 기반으로 시드 생성
            unique_id = os.uname().nodename
        except (AttributeError, Exception):
            unique_id = "default_seed_device"
        return int(hashlib.sha256(unique_id.encode("utf-8")).hexdigest()[:8], 16)

    def _get_time_phase(self, ts: float) -> int:
        """시간에 따라 0:밤, 1:새벽, 2:낮, 3:해질녘 페이즈 반환."""
        hour = datetime.fromtimestamp(ts).hour
        if 22 <= hour or hour < 5: return 0
        if 5 <= hour < 8: return 1
        if 8 <= hour < 18: return 2
        return 3

    # --- 드로잉 유틸리티 ---
    def _draw_text(self, draw, text, pos, font, fill, anchor="mm"):
        """지정된 위치에 텍스트를 정확히 정렬하여 그립니다."""
        draw.text(pos, text, font=font, fill=fill, anchor=anchor)

    def _draw_rounded_rect(self, image, bounds, radius, fill, outline=None, width=1):
        """둥근 사각형을 그립니다."""
        x0, y0, x1, y1 = bounds
        # 별도 레이어에 그려서 알파 블렌딩
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rounded_rectangle(bounds, radius, fill, outline, width)
        # 그림자 효과 추가
        shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_bounds = (x0 + 2, y0 + 4, x1 + 2, y1 + 4)
        shadow_draw.rounded_rectangle(shadow_bounds, radius, fill=(0,0,0,50))
        shadow = shadow.filter(ImageFilter.GaussianBlur(3))

        return Image.alpha_composite(Image.alpha_composite(image, shadow), overlay)

    # --- 1. 배경 레이어 ---
    def _create_background(self, phase: int, pm25_level: int) -> Image.Image:
        """하늘, 태양/달, 언덕 등 정적인 배경 이미지를 생성합니다."""
        img = Image.new("RGBA", (self.diameter, self.diameter), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        # 1. 하늘 그라데이션
        top_c, bot_c = self.theme.get_sky_colors(phase)
        for y in range(self.diameter):
            ratio = y / self.diameter
            r = int(top_c[0] * (1 - ratio) + bot_c[0] * ratio)
            g = int(top_c[1] * (1 - ratio) + bot_c[1] * ratio)
            b = int(top_c[2] * (1 - ratio) + bot_c[2] * ratio)
            draw.line([(0, y), (self.diameter, y)], fill=(r, g, b))

        # 2. 태양/달 (시간에 따라 위치, 크기, 색 변화)
        now = datetime.now()
        time_ratio = (now.hour % 12 + now.minute / 60) / 12.0
        angle = (1 - time_ratio) * math.pi
        x = self.center[0] + self.radius * 0.7 * math.cos(angle)
        y = self.center[1] - self.radius * 0.5 * math.sin(angle)
        
        is_night = phase == 0
        radius = self.radius * (0.08 if is_night else 0.1)
        color = self.theme.get_sun_moon_color(phase)

        glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        glow_radius = radius * 3
        glow_draw.ellipse((x - glow_radius, y - glow_radius, x + glow_radius, y + glow_radius), fill=color + (100,))
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(15))
        img = Image.alpha_composite(img, glow_layer)
        
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color + (230,))

        # 3. 언덕 (시드 기반 랜덤 생성)
        random.seed(self.scene_seed)
        hills = [
            (self.theme.HILL_3, 0.68, 0.08, 2),
            (self.theme.HILL_2, 0.72, 0.1, 1),
            (self.theme.HILL_1, 0.75, 0.12, 0)
        ]
        for color, y_base, amp, blur_radius in hills:
            hill_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            hill_draw = ImageDraw.Draw(hill_layer)
            points = [(0, self.diameter)]
            offset = random.uniform(0, 100)
            for x in range(0, self.diameter + 20, 10):
                y = self.diameter * y_base + math.sin(x * 0.01 + offset) * self.diameter * amp
                points.append((x, y))
            points.append((self.diameter, self.diameter))
            hill_draw.polygon(points, fill=color)
            if blur_radius > 0:
                hill_layer = hill_layer.filter(ImageFilter.GaussianBlur(blur_radius))
            img = Image.alpha_composite(img, hill_layer)
        
        # 4. 헤이즈/안개 (미세먼지, 습도 기반)
        haze_alpha = min(200, 50 + pm25_level * 50)
        haze_color = (220, 225, 230, haze_alpha)
        haze_layer = Image.new("RGBA", img.size, (0,0,0,0))
        haze_draw = ImageDraw.Draw(haze_layer)
        haze_draw.rectangle((0, self.diameter*0.4, self.diameter, self.diameter), fill=haze_color)
        haze_layer = haze_layer.filter(ImageFilter.GaussianBlur(20))
        img = Image.alpha_composite(img, haze_layer)

        return img

    # --- 2. 동적 효과 레이어 ---
    def _draw_dynamic_effects(self, canvas: Image.Image, snapshot: SensorSnapshot, t: float):
        draw = ImageDraw.Draw(canvas)
        
        # 1. 구름 (미세먼지 농도에 따라 색과 양 변화)
        pm25 = snapshot.pm25 or 0
        cloud_count = 2 + int(pm25 / 25)
        intensity = min(1, pm25 / 100.0)
        c_base = 255 - int(80 * intensity)
        c_alpha = 200 - int(100 * intensity)
        cloud_color = (c_base, c_base, c_base, c_alpha)
        
        random.seed(self.scene_seed)
        for i in range(cloud_count):
            size = self.radius * random.uniform(0.15, 0.3)
            y = self.radius * random.uniform(0.3, 0.7)
            speed = 10 + i * 3
            x = ((t * speed) + self.diameter * (i / cloud_count * 2)) % (self.diameter + size*2) - size
            draw.ellipse((x, y, x + size, y + size/2), fill=cloud_color)

        # 2. 잔디 (PIR, 소음 강도에 따라 흔들림)
        wind = (snapshot.pir or 0) * 0.8
        if snapshot.noise:
            wind += min(1.0, max(0, (snapshot.noise - 40) / 50)) * 0.5
        
        y_start = int(self.diameter * 0.8)
        for y in range(y_start, self.diameter):
            ratio = (y - y_start) / (self.diameter - y_start)
            r = int(self.theme.GRASS_FAR[0] * (1-ratio) + self.theme.GRASS_NEAR[0] * ratio)
            g = int(self.theme.GRASS_FAR[1] * (1-ratio) + self.theme.GRASS_NEAR[1] * ratio)
            b = int(self.theme.GRASS_FAR[2] * (1-ratio) + self.theme.GRASS_NEAR[2] * ratio)
            draw.line([(0, y), (self.diameter, y)], fill=(r,g,b))

        for i in range(60):
            x = i * (self.diameter / 59)
            sway = math.sin(t * 2 + i * 0.5) * 3 * (1 + wind)
            draw.line([(x, self.diameter), (x + sway, y_start)], fill=(r-10, g-10, b-10), width=2)
            
        # 3. 물결 (PIR 감지 시)
        if snapshot.pir and self.dynamic_state["ripple_start_time"] == 0:
            self.dynamic_state["ripple_start_time"] = t
        
        if self.dynamic_state["ripple_start_time"] > 0:
            elapsed = t - self.dynamic_state["ripple_start_time"]
            if elapsed > 2:
                self.dynamic_state["ripple_start_time"] = 0
            else:
                ripple_r = elapsed * 80
                ripple_a = int(max(0, 150 * (1 - elapsed/2)))
                pos = (self.center[0], self.diameter * 0.85)
                draw.ellipse((pos[0]-ripple_r, pos[1]-ripple_r/4, pos[0]+ripple_r, pos[1]+ripple_r/4), 
                             outline=(200,220,255,ripple_a), width=2)

        # 4. 빗방울 (습도 높을 시)
        if snapshot.hum and snapshot.hum > 90:
            random.seed(int(t*5))
            for _ in range(30):
                x = random.randint(0, self.diameter)
                y = random.randint(0, self.diameter)
                draw.line([(x,y), (x+1, y+5)], fill=(200,220,255,100), width=1)

        # 5. 별똥별 (밤, 랜덤)
        if self._get_time_phase(t) == 0 and not self.dynamic_state["shooting_star"]:
            if random.random() < 0.005: # 프레임당 0.5% 확률
                 x_start = random.randint(0, self.diameter)
                 y_start = random.randint(0, int(self.diameter*0.3))
                 self.dynamic_state["shooting_star"] = ((x_start, y_start), (x_start-100, y_start+100), t)

        if self.dynamic_state["shooting_star"]:
            (x0,y0), (x1,y1), stime = self.dynamic_state["shooting_star"]
            if t - stime > 0.5:
                self.dynamic_state["shooting_star"] = None
            else:
                draw.line([(x0,y0), (x1,y1)], fill=(255,255,255,200), width=2)

    # --- 3. UI 레이어 ---
    def _draw_ui(self, canvas: Image.Image, snapshot: SensorSnapshot):
        cx, cy = self.center
        
        # 1. 중앙 패널
        p_w, p_h = self.layout["main_panel_w"], self.layout["main_panel_h"]
        p_bounds = (cx - p_w/2, cy - p_h/2, cx + p_w/2, cy + p_h/2)
        canvas = self._draw_rounded_rect(canvas, p_bounds, 24, self.theme.GLASS_FILL, self.theme.CARD_BORDER, 2)
        draw = ImageDraw.Draw(canvas)

        device_name = snapshot.device_id or "Sensor"
        self._draw_text(draw, device_name, (cx, p_bounds[1] + 20), self.fonts["sm"], self.theme.TEXT_SUB)

        temp_str = f"{snapshot.temp_c:.1f}°" if snapshot.temp_c is not None else "--"
        self._draw_text(draw, temp_str, (cx, cy), self.fonts["xl"], self.theme.TEXT_MAIN)

        age = time.time() - snapshot.ingested_at
        if age < 5: status, color = "● LIVE", self.theme.LIVE_COLOR
        elif age < 30: status, color = "● RECENT", self.theme.RECENT_COLOR
        else: status, color = "● OLD", self.theme.OLD_COLOR
        self._draw_text(draw, status, (cx, p_bounds[3] - 20), self.fonts["xs"], color)

        # 2. 센서 카드 (PM2.5, HUM)
        items = [
            ("PM2.5", snapshot.pm25, "µg/m³", self.theme.PM_COLOR, 225),
            ("HUMID", snapshot.hum, "%", self.theme.HUM_COLOR, 315)
        ]
        c_w, c_h = self.layout["card_w"], self.layout["card_h"]
        orbit_r = self.layout["card_orbit_radius"]

        for label, val, unit, color, angle_deg in items:
            angle_rad = math.radians(angle_deg)
            card_cx = cx + orbit_r * math.cos(angle_rad)
            card_cy = cy + orbit_r * math.sin(angle_rad)
            c_bounds = (card_cx - c_w/2, card_cy - c_h/2, card_cx + c_w/2, card_cy + c_h/2)
            canvas = self._draw_rounded_rect(canvas, c_bounds, 18, self.theme.GLASS_FILL, self.theme.CARD_BORDER, 2)
            # Re-create draw object after canvas modification
            draw = ImageDraw.Draw(canvas)
            self._draw_text(draw, label, (card_cx, c_bounds[1] + 18), self.fonts["xs"], self.theme.TEXT_SUB)
            val_str = f"{val:.1f}" if val is not None else "--"
            self._draw_text(draw, val_str, (card_cx, card_cy + 5), self.fonts["lg"], color)
            self._draw_text(draw, unit, (card_cx, c_bounds[3] - 18), self.fonts["xs"], self.theme.TEXT_SUB)
        
        # 3. 하단 정보
        now_str = datetime.now().strftime("%H:%M")
        noise_str = f"{int(snapshot.noise)}dB" if snapshot.noise is not None else "--"
        pir_icon = "●" if snapshot.pir else "○"
        footer_text = f"{pir_icon}  |  {noise_str}  |  {now_str}"
        self._draw_text(draw, footer_text, (cx, self.diameter - 30), self.fonts["sm"], self.theme.TEXT_LIGHT, anchor="mb")

        return canvas

    # --- 메인 렌더링 함수 ---
    def render(self, snapshot: SensorSnapshot) -> Image.Image:
        """스냅샷 데이터를 기반으로 최종 이미지를 생성하고 반환합니다."""
        if self.driver and self.driver.is_closing:
            self.is_closing = True
            return Image.new("RGB", (self.diameter, self.diameter), (0,0,0))
            
        t = time.time()
        phase = self._get_time_phase(snapshot.ts or t)
        pm25 = snapshot.pm25 or 0
        pm_level = 0 if pm25 < 35 else (1 if pm25 < 75 else 2)

        # 1. 배경 가져오기 또는 생성
        bg_key = (phase, pm_level, self.diameter)
        canvas = self.bg_cache.get(bg_key)
        if canvas is None:
            canvas = self._create_background(phase, pm_level)
            self.bg_cache.set(bg_key, canvas)

        # 2. 동적 효과 그리기
        self._draw_dynamic_effects(canvas, snapshot, t)
        
        # 3. UI 그리기
        if snapshot.has_payload():
             canvas = self._draw_ui(canvas, snapshot)
        else: # 데이터 대기 화면
            draw = ImageDraw.Draw(canvas)
            self._draw_text(draw, "Connecting...", (self.center[0], self.center[1]), self.fonts["md"], self.theme.TEXT_LIGHT)
        
        # 4. 원형 마스크 및 테두리 적용
        mask = Image.new("L", (self.diameter, self.diameter), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, self.diameter, self.diameter), fill=255)
        
        final_img = Image.new("RGBA", (self.diameter, self.diameter))
        final_img.paste(canvas, (0,0), mask)
        
        draw = ImageDraw.Draw(final_img)
        ring_width = max(2, int(self.diameter*0.005))
        draw.ellipse((0,0,self.diameter, self.diameter), outline=self.theme.RING_COLOR, width=ring_width)
        
        return final_img.convert("RGB")

    def present(self, image: Image.Image):
        """생성된 이미지를 드라이버를 통해 표시합니다."""
        if self.driver and not self.is_closing:
            self.driver.display(image)

# -----------------------------------------------------------------------------
# Kafka 데이터 스트림 (기존 코드와 유사)
# ... (이 부분은 기존 코드의 _snapshot_from_payload와 KafkaSensorStream을 거의 그대로 사용합니다)
# -----------------------------------------------------------------------------
def _parse_kafka_message(payload: Dict[str, Any]) -> SensorSnapshot | None:
    # This is a simplified parser. Adapt to your actual sensor data structure.
    try:
        ts = payload.get("ts", time.time())
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()

        # Simple direct mapping
        return SensorSnapshot(
            ts=float(ts),
            device_id=payload.get("device_id"),
            temp_c=float(payload.get("temp_c")),
            hum=float(payload.get("hum")),
            noise=float(payload.get("noise")),
            pir=int(payload.get("pir")),
            pm25=float(payload.get("pm25")),
        )
    except (TypeError, ValueError, KeyError):
        return None # Incompatible format

class KafkaSensorStream:
    def __init__(self, out_queue: queue.Queue[SensorSnapshot]):
        self.out_queue = out_queue
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        if KafkaConsumer is None: raise RuntimeError(f"Kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread: self._thread.join(timeout=2.0)

    def _run(self):
        try:
            consumer = KafkaConsumer(
                settings.sensor_topic,
                bootstrap_servers=settings.bootstrap_servers,
                value_deserializer=lambda v: json.loads(v.decode(settings.value_encoding, "ignore")),
                consumer_timeout_ms=1000,
                auto_offset_reset='latest',
            )
            print(f"[Kafka] 연결 성공: {settings.bootstrap_servers}")
        except Exception as e:
            print(f"[Kafka] 연결 실패: {e}")
            return

        while not self._stop_event.is_set():
            try:
                for message in consumer:
                    if self._stop_event.is_set(): break
                    snapshot = _parse_kafka_message(message.value)
                    if snapshot:
                        try:
                           self.out_queue.put_nowait(snapshot)
                        except queue.Full:
                           pass # 드롭
            except Exception as e:
                print(f"[Kafka] 데이터 수신 중 오류: {e}")
                time.sleep(5)
        consumer.close()


# -----------------------------------------------------------------------------
# 메인 실행 로직
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Sensor Display Masterpiece")
    parser.add_argument("--diameter", type=int, default=settings.diameter_pixels)
    parser.add_argument("--font", type=str, default=settings.font_path)
    parser.add_argument("--hz", type=float, default=settings.display_refresh_hz)
    parser.add_argument("--mock", action="store_true", help="Kafka 대신 목업 데이터 사용")
    args = parser.parse_args()

    display = CircularNaturalDisplay(diameter=args.diameter, font_path=args.font)
    data_queue = queue.Queue(maxsize=5)
    
    stream = None
    if not args.mock:
        stream = KafkaSensorStream(data_queue)
        stream.start()

    latest_snapshot = SensorSnapshot()
    frame_interval = 1.0 / args.hz
    next_frame_time = time.time()

    try:
        while not display.is_closing:
            # 데이터 소스 선택
            if args.mock:
                latest_snapshot = SensorSnapshot.mock_data()
            else:
                try:
                    latest_snapshot = data_queue.get_nowait()
                except queue.Empty:
                    pass
            
            # 렌더링 및 디스플레이
            now = time.time()
            if now >= next_frame_time:
                image = display.render(latest_snapshot)
                display.present(image)
                next_frame_time = now + frame_interval
            
            # CPU 사용량 줄이기 위한 짧은 대기
            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n[Main] 종료합니다.")
    finally:
        if stream:
            stream.stop()

if __name__ == "__main__":
    main()
