# sensor_display_final.py
"""
'Dynamic Day/Night Sensor Display' (Final Version)

시간에 따라 낮과 밤 테마가 자동으로 전환되고, UI/UX 및 시각 효과를
극한으로 끌어올린 센서 디스플레이의 최종 버전입니다.

주요 개선 사항:
1.  **동적 테마 시스템 (Dynamic Day/Night Theme):**
    -   현재 시간에 맞춰 '햇살 비치는 낮'과 '오로라가 빛나는 밤' 테마가
        자동으로 전환됩니다.
    -   각 테마는 하늘, 광원(태양/달), 산, 호수 반사, UI 색상 등 모든 시각적
        요소를 포함하여 완전히 다른 경험을 제공합니다.

2.  **직관적인 UI/UX 업그레이드:**
    -   습도와 미세먼지 정보를 한눈에 파악할 수 있도록 세련된 **원형 게이지(Gauge)**
        UI를 도입했습니다.
    -   테마 전환 시 배경 밝기에 맞춰 텍스트와 아이콘 색상이 자동으로
        대비되는 색상으로 변경되어 항상 뛰어난 가독성을 보장합니다.

3.  **사실적인 시각 효과 (Photorealistic Effects):**
    -   호수 반사에 미세한 블러와 왜곡 효과를 추가하여 실제 수면처럼
        느껴지도록 현실감을 극대화했습니다.
    -   밤하늘의 별들이 부드럽게 반짝이는 애니메이션을 추가하여 깊이와
        생동감을 더했습니다.

4.  **코드 안정성 및 호환성 향상:**
    -   모든 운영체제(Windows, Linux, macOS)에서 호환되는 방식으로
        고유 시드를 생성하도록 코드를 수정하여 안정성을 높였습니다.
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
from typing import Any, Dict, Optional, Tuple, Iterable
import socket
import os
import random
import hashlib

# --- Dependency Imports ---
try:
    from kafka import KafkaConsumer
except ImportError as e:
    KafkaConsumer, _KAFKA_IMPORT_ERROR = None, e
else: _KAFKA_IMPORT_ERROR = None

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError as e:
    Image = ImageDraw = ImageFont = ImageFilter = None
    _PILLOW_IMPORT_ERROR = e
else: _PILLOW_IMPORT_ERROR = None

try:
    import tkinter as tk
    from tkinter import Label
    from PIL import ImageTk
except ImportError as e:
    tk = Label = ImageTk = None
    _TKINTER_IMPORT_ERROR = e
else: _TKINTER_IMPORT_ERROR = None

# --- Application Settings ---
@dataclass
class AppSettings:
    bootstrap_servers: list[str] = field(default_factory=lambda: ["localhost:9092"])
    sensor_topic: str = "sensor-data"
    value_encoding: str = "utf-8"
    diameter_pixels: int = 480
    display_refresh_hz: float = 20.0
    font_path: str = "Pretendard-Regular.otf"

settings = AppSettings()

# -----------------------------------------------------------------------------
# Data Parsing & Model (from v1 for stability)
# -----------------------------------------------------------------------------
@dataclass
class SensorSnapshot:
    ts: Optional[float] = None
    device_id: Optional[str] = "Dynamic-Sensor"
    temp_c: Optional[float] = None
    hum: Optional[float] = None
    noise: Optional[float] = None
    pir: Optional[int] = None
    pm25: Optional[float] = None
    ingested_at: float = field(default_factory=time.time)

    def has_payload(self) -> bool:
        return any(v is not None for v in (self.temp_c, self.hum, self.noise, self.pir, self.pm25))

    @classmethod
    def mock_data(cls) -> "SensorSnapshot":
        now = time.time()
        temp = 22.5 + 5 * math.sin(now / 300)
        hum = 60 + 25 * (math.sin(now / 450) + 1) / 2
        pm25 = 40 + 35 * abs(math.sin(now / 600))
        noise = 45 + 20 * abs(math.sin(now / 15))
        pir = 1 if int(now) % 25 < 4 else 0
        return cls(ts=now, temp_c=temp, hum=hum, noise=noise, pir=pir, pm25=pm25)

# ... (Robust parsing functions from v3 are kept as they are stable)
def _to_float(v: Any) -> Optional[float]:
    if v is None: return None
    try: return float(v)
    except (ValueError, TypeError): return None

def _to_int01(v: Any) -> Optional[int]:
    if v is None: return None
    try:
        s = str(v).lower().strip()
        if s in ('true', '1', 'on', 'motion'): return 1
        if s in ('false', '0', 'off', 'clear'): return 0
    except Exception: pass
    return None

def _parse_timestamp(v: Any) -> Optional[float]:
    if v is None: return None
    try:
        ts = float(v)
        return ts / 1000.0 if ts > 1e12 else ts
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError): return None

def _snapshot_from_payload(payload: Dict[str, Any]) -> SensorSnapshot | None:
    if not isinstance(payload, dict): return None
    def _pick(d: Dict[str, Any], keys: Iterable[str]) -> Any:
        for k in keys:
            if k in d and d[k] is not None: return d[k]
        return None
    sensors = payload.get("sensors", payload)
    dht = sensors.get("dht22", {})
    snd = sensors.get("sound", {})
    pm = sensors.get("pm", {})
    snap = SensorSnapshot(
        ts=_parse_timestamp(_pick(payload, ["ts", "timestamp"])),
        device_id=str(_pick(payload, ["device_id", "device"]) or "Dynamic-Sensor"),
        temp_c=_to_float(_pick(sensors, ["temp_c", "temperature"]) or _pick(dht, ["temp_c", "temperature"])),
        hum=_to_float(_pick(sensors, ["hum", "humidity"]) or _pick(dht, ["hum", "humidity"])),
        noise=_to_float(_pick(sensors, ["noise"]) or _pick(snd, ["noise", "level"])),
        pir=_to_int01(_pick(sensors, ["pir", "motion"])),
        pm25=_to_float(_pick(sensors, ["pm25", "pm2.5"]) or _pick(pm, ["pm25", "pm2.5", "pm2_5"])),
    )
    return snap if snap.has_payload() else None

# -----------------------------------------------------------------------------
# Dynamic Theme & Style
# -----------------------------------------------------------------------------
class Theme:
    class Night:
        SKY = ((10, 15, 30), (30, 40, 65))
        LIGHT_SOURCE_COLOR = (220, 230, 255, 200)
        MOUNTAIN_COLORS = [(35, 45, 70), (50, 60, 90)]
        AURORA_COLORS = [(10, 255, 150), (80, 220, 255), (180, 100, 255)]
        WATER_OVERLAY = (15, 25, 45, 180)
        TEXT_MAIN = (255, 255, 255, 220)
        TEXT_SUB = (200, 210, 230, 180)
        ICON_COLOR = (255, 255, 255, 160)
        GAUGE_BG = (255, 255, 255, 40)

    class Day:
        SKY = ((70, 150, 255), (180, 220, 255))
        LIGHT_SOURCE_COLOR = (255, 245, 200, 255)
        MOUNTAIN_COLORS = [(100, 160, 120), (130, 190, 150)]
        WATER_OVERLAY = (50, 100, 150, 100)
        TEXT_MAIN = (50, 70, 90, 220)
        TEXT_SUB = (100, 120, 140, 200)
        ICON_COLOR = (80, 100, 120, 180)
        GAUGE_BG = (255, 255, 255, 80)

    HUM_COLOR = (150, 200, 255, 220)
    PM_COLOR = (200, 180, 255, 220)
    LIVE_COLOR = (120, 255, 150, 220)
    RECENT_COLOR = (255, 220, 120, 220)
    OLD_COLOR = (255, 130, 130, 220)

# -----------------------------------------------------------------------------
# Tkinter Preview Driver (Unchanged)
# -----------------------------------------------------------------------------
class TkinterDisplayDriver: # ... (No changes from v3)
    def __init__(self, diameter: int):
        if tk is None: raise RuntimeError(f"Tkinter import failed: {_TKINTER_IMPORT_ERROR}")
        self.root = tk.Tk()
        self.root.title("Dynamic Sensor Display")
        self.root.geometry(f"{diameter + 20}x{diameter + 50}")
        self.root.configure(bg="#000")
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.is_closing = False
        self.label = Label(self.root, bg="#000")
        self.label.pack(pady=10, expand=True)
    def _on_closing(self): self.is_closing = True; self.root.destroy()
    def display(self, image: Image.Image):
        if self.is_closing: return
        try:
            photo = ImageTk.PhotoImage(image)
            self.label.configure(image=photo)
            self.label.image = photo; self.root.update()
        except tk.TclError: self.is_closing = True

# -----------------------------------------------------------------------------
# Main Renderer
# -----------------------------------------------------------------------------
class DynamicDisplay:
    def __init__(self, diameter: int, font_path: str | None, use_tkinter: bool = True):
        if Image is None: raise RuntimeError(f"Pillow import failed: {_PILLOW_IMPORT_ERROR}")
        self.diameter = diameter
        self.center = (diameter / 2, diameter / 2)
        self.driver = TkinterDisplayDriver(diameter) if use_tkinter else None
        self.theme = Theme()
        self.fonts = {
            "xl": self._load_font(font_path, int(diameter * 0.22)),
            "md": self._load_font(font_path, int(diameter * 0.08)),
            "sm": self._load_font(font_path, int(diameter * 0.045)),
            "icon": self._load_font(font_path, int(diameter * 0.06)),
        }
        self.bg_cache: Dict[str, Image.Image] = {}
        self.dynamic_state = {"ripple_start_time": 0, "stars": self._generate_stars()}
        self.is_closing = False
        try: # Cross-platform compatible seeding
            hostname = socket.gethostname()
            self.scene_seed = int(hashlib.sha256(hostname.encode()).hexdigest()[:8], 16)
        except: self.scene_seed = 12345

    def _load_font(self, font_path, size): # ... (Unchanged from v3)
        try: return ImageFont.truetype(font_path, size)
        except (OSError, IOError): return ImageFont.load_default()

    def _generate_stars(self, count=200):
        return [(random.randint(0, self.diameter), random.randint(0, int(self.diameter*0.6)), random.uniform(0.5, 1.5))
                for _ in range(count)]

    def _get_time_phase(self, ts: float) -> str:
        hour = datetime.fromtimestamp(ts).hour
        return "day" if 6 <= hour < 19 else "night"

    def _draw_text(self, draw, text, pos, font, fill, anchor="mm"):
        draw.text(pos, text, font=font, fill=fill, anchor=anchor)
    
    def _draw_gauge(self, draw: ImageDraw.ImageDraw, center: Tuple[float, float], radius: float, value: float, color: Tuple, bg_color: Tuple, width: int):
        bounds = [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius]
        draw.arc(bounds, start=-90, end=270, fill=bg_color, width=width)
        if value > 0.01:
            end_angle = -90 + (360 * min(value, 1.0))
            draw.arc(bounds, start=-90, end=end_angle, fill=color, width=width)

    def _create_background(self, phase: str, t: float) -> Image.Image:
        palette = self.theme.Day if phase == "day" else self.theme.Night
        bg = Image.new("RGBA", (self.diameter, self.diameter))
        draw = ImageDraw.Draw(bg)
        
        # Sky Gradient
        top_c, bot_c = palette.SKY
        for y in range(self.diameter):
            r = y / self.diameter
            color = tuple(int(top_c[i]*(1-r) + bot_c[i]*r) for i in range(3))
            draw.line([(0, y), (self.diameter, y)], fill=color)

        # Light Source (Sun/Moon) & Stars
        if phase == "night":
            # Stars with twinkling
            for x, y, speed in self.dynamic_state["stars"]:
                brightness = int(128 + 127 * math.sin(t * speed))
                draw.point((x,y), fill=(brightness, brightness, brightness, brightness))
            # Moon
            light_pos = (self.diameter * 0.8, self.diameter * 0.2)
            light_radius = self.diameter * 0.08
        else: # Day
            # Sun
            light_pos = (self.diameter * 0.2, self.diameter * 0.25)
            light_radius = self.diameter * 0.12
        
        glow = Image.new("RGBA", bg.size)
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse((light_pos[0] - light_radius*2.5, light_pos[1] - light_radius*2.5,
                           light_pos[0] + light_radius*2.5, light_pos[1] + light_radius*2.5),
                          fill=(255, 255, 220, 70 if phase == 'day' else 40))
        glow = glow.filter(ImageFilter.GaussianBlur(20))
        bg.alpha_composite(glow)
        draw.ellipse((light_pos[0] - light_radius, light_pos[1] - light_radius,
                      light_pos[0] + light_radius, light_pos[1] + light_radius),
                     fill=palette.LIGHT_SOURCE_COLOR)
        
        # Mountains
        random.seed(self.scene_seed)
        horizon = self.diameter * 0.55
        for i, color in enumerate(palette.MOUNTAIN_COLORS):
            points = [(0, self.diameter)]
            y_base = horizon + i * 40
            amp = 70 - i * 20
            freq = 0.005 + i * 0.001
            offset = random.uniform(0, 100)
            for x in range(0, self.diameter + 20, 10):
                y = y_base + math.sin(x * freq + offset) * amp
                points.append((x,y))
            points.append((self.diameter, self.diameter))
            draw.polygon(points, fill=color)
        
        return bg

    def _create_reflection(self, base_image: Image.Image, palette: Any, t: float, pir: int) -> Image.Image:
        horizon = int(self.diameter * 0.55)
        sky = base_image.crop((0, 0, self.diameter, horizon))
        reflection = sky.transpose(Image.FLIP_TOP_BOTTOM)
        
        # Enhanced water effect
        reflection = reflection.filter(ImageFilter.GaussianBlur(1))
        
        water = Image.new("RGBA", reflection.size, palette.WATER_OVERLAY)
        reflection = Image.alpha_composite(reflection, water)

        if pir and self.dynamic_state["ripple_start_time"] == 0:
            self.dynamic_state["ripple_start_time"] = t
        
        if self.dynamic_state["ripple_start_time"] > 0:
            elapsed = t - self.dynamic_state["ripple_start_time"]
            if elapsed > 3: self.dynamic_state["ripple_start_time"] = 0
            else:
                pixels = reflection.load()
                width, height = reflection.size
                for y in range(height):
                    for x in range(width):
                        wave = math.sin(y*0.15 + elapsed*6) * 6 * (1 - elapsed/3)
                        dx = int(x + wave)
                        if 0 <= dx < width: pixels[x, y] = pixels[dx, y]
        return reflection

    def _draw_dynamic_effects(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot, t: float):
        # Aurora (Night only)
        noise = snapshot.noise or 30.0
        pir = snapshot.pir or 0
        intensity = min(1.0, max(0.0, (noise - 35.0) / 50.0) + pir * 0.2)
        
        for i, color in enumerate(self.theme.Night.AURORA_COLORS):
            points = []
            amp = (15 + i*15) * (1 + intensity*2)
            for x in range(-50, self.diameter + 50, 20):
                y = 120 + i*40 + math.sin(x*0.015 + t*0.6 + i*2) * amp * math.cos(x*0.005 - t*0.2)
                points.append((x,y))
            alpha = int((30 + 90 * intensity) * (math.sin(t*0.5+i) + 1.5) / 2.5)
            draw.line(points, fill=color + (alpha,), width=40, joint="curve")

    def _draw_ui(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot, palette: Any):
        cx, cy = self.center
        
        # Main Temperature
        temp_str = f"{snapshot.temp_c:.1f}°" if snapshot.temp_c is not None else "--°"
        self._draw_text(draw, temp_str, (cx, cy - 60), self.fonts["xl"], palette.TEXT_MAIN)

        # Sub-info with Gauges
        items = [
            ("💧", snapshot.hum, 100.0, self.theme.HUM_COLOR, cx - 100), # Hum: 0-100%
            ("💨", snapshot.pm25, 100.0, self.theme.PM_COLOR, cx + 100), # PM2.5: 0-100 ug/m3 (bad)
        ]
        ui_y = self.diameter * 0.78
        gauge_radius = self.diameter * 0.08
        for icon, val, max_val, color, x_pos in items:
            value_norm = (val or 0) / max_val
            self._draw_gauge(draw, (x_pos, ui_y), gauge_radius, value_norm, color, palette.GAUGE_BG, width=6)
            self._draw_text(draw, icon, (x_pos, ui_y - 5), self.fonts["icon"], palette.ICON_COLOR)
            val_str = f"{val:.0f}" if val is not None else "--"
            self._draw_text(draw, val_str, (x_pos, ui_y + 12), self.fonts["md"], palette.TEXT_SUB)
            
        # Footer
        now_str = datetime.now().strftime("%H:%M")
        age = time.time() - snapshot.ingested_at
        if age < 10: status, s_color = "● LIVE", self.theme.LIVE_COLOR
        elif age < 60: status, s_color = "● RECENT", self.theme.RECENT_COLOR
        else: status, s_color = "● OLD", self.theme.OLD_COLOR
        
        footer_y = self.diameter - 20
        self._draw_text(draw, status, (cx, footer_y), self.fonts["sm"], s_color)
        self._draw_text(draw, now_str, (self.diameter - 25, footer_y), self.fonts["sm"], palette.TEXT_SUB, anchor="rm")

    def render(self, snapshot: SensorSnapshot) -> Image.Image:
        if self.driver and self.driver.is_closing:
            self.is_closing = True
            return Image.new("RGB", (self.diameter, self.diameter))

        t = time.time()
        phase = self._get_time_phase(snapshot.ts or t)
        palette = self.theme.Day if phase == "day" else self.theme.Night
        
        bg_key = f"bg_{phase}"
        canvas = self.bg_cache.get(bg_key)
        if not canvas:
            canvas = self._create_background(phase, t)
            self.bg_cache[bg_key] = canvas
        else: # Update dynamic elements like stars
            canvas = canvas.copy()
            if phase == 'night':
                draw = ImageDraw.Draw(canvas)
                for x, y, speed in self.dynamic_state["stars"]:
                    brightness = int(128 + 127 * math.sin(t * speed))
                    draw.point((x,y), fill=(brightness, brightness, brightness, brightness))
        
        if phase == "night":
            draw = ImageDraw.Draw(canvas)
            self._draw_dynamic_effects(draw, snapshot, t)
        
        reflection = self._create_reflection(canvas, palette, t, snapshot.pir or 0)
        canvas.paste(reflection, (0, int(self.diameter * 0.55)), reflection)
        
        draw = ImageDraw.Draw(canvas)
        
        if snapshot.has_payload():
            self._draw_ui(draw, snapshot, palette)
        else:
            self._draw_text(draw, "Connecting...", self.center, self.fonts["md"], palette.TEXT_MAIN)
            
        mask = Image.new("L", (self.diameter, self.diameter), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, self.diameter, self.diameter), fill=255)
        final_image = Image.new("RGBA", canvas.size)
        final_image.paste(canvas, (0,0), mask)
        
        return final_image.convert("RGB")

    def present(self, image: Image.Image):
        if self.driver and not self.is_closing:
            self.driver.display(image)

# -----------------------------------------------------------------------------
# Kafka Stream & Main Execution (Unchanged)
# -----------------------------------------------------------------------------
class KafkaSensorStream: # ... (No changes from v3)
    def __init__(self, out_queue: queue.Queue[SensorSnapshot]):
        self.out_queue = out_queue
        self._stop_event = threading.Event()
        self._thread = None
    def start(self):
        if KafkaConsumer is None: raise RuntimeError(f"Kafka-python import failed: {_KAFKA_IMPORT_ERROR}")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    def stop(self):
        self._stop_event.set()
        if self._thread: self._thread.join(timeout=2.0)
    def _run(self):
        try:
            consumer = KafkaConsumer(
                settings.sensor_topic, bootstrap_servers=settings.bootstrap_servers,
                value_deserializer=lambda v: v.decode(settings.value_encoding, 'ignore'),
                consumer_timeout_ms=1000, auto_offset_reset='latest',
            )
            print(f"[Kafka] Connected: {settings.bootstrap_servers}")
        except Exception as e:
            print(f"[Kafka] Connection failed: {e}")
            return
        while not self._stop_event.is_set():
            try:
                for msg in consumer:
                    if self._stop_event.is_set(): break
                    try:
                        payload = json.loads(msg.value)
                        snapshot = _snapshot_from_payload(payload)
                        if snapshot: self.out_queue.put(snapshot, block=False)
                    except (json.JSONDecodeError, queue.Full): continue
            except Exception as e:
                print(f"[Kafka] Error during consumption: {e}")
                time.sleep(5)
        consumer.close()

def main():
    parser = argparse.ArgumentParser(description="Dynamic Day/Night Sensor Display")
    parser.add_argument("--diameter", type=int, default=settings.diameter_pixels)
    parser.add_argument("--font", type=str, default=settings.font_path)
    parser.add_argument("--hz", type=float, default=settings.display_refresh_hz)
    parser.add_argument("--mock", action="store_true", help="Use mock data instead of Kafka")
    args = parser.parse_args()
    display = DynamicDisplay(diameter=args.diameter, font_path=args.font)
    data_queue = queue.Queue(maxsize=10)
    stream = None
    if not args.mock:
        stream = KafkaSensorStream(data_queue)
        stream.start()
    latest_snapshot = SensorSnapshot()
    frame_interval = 1.0 / args.hz
    next_frame_time = time.time()
    try:
        while not display.is_closing:
            if args.mock: latest_snapshot = SensorSnapshot.mock_data()
            else:
                try: latest_snapshot = data_queue.get_nowait()
                except queue.Empty: pass
            now = time.time()
            if now >= next_frame_time:
                image = display.render(latest_snapshot)
                display.present(image)
                next_frame_time = now + frame_interval
            time.sleep(max(0, next_frame_time - time.time()))
    except KeyboardInterrupt: print("\n[Main] Exiting.")
    finally:
        if stream: stream.stop()

if __name__ == "__main__":
    main()
