"""Kafka 파이프라인을 통해 수집한 UART 센서 값을 2.1인치 원형 디스플레이에 맞춰 렌더링.

자연적이고 현실적인 디자인으로 센서 데이터를 시각화합니다.
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple, List

try:
    from kafka import KafkaConsumer
except Exception as exc:  # pragma: no cover
    KafkaConsumer = None  # type: ignore
    _KAFKA_IMPORT_ERROR = exc
else:
    _KAFKA_IMPORT_ERROR = None

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except Exception as exc:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore
    ImageFilter = None  # type: ignore
    _PILLOW_IMPORT_ERROR = exc
else:
    _PILLOW_IMPORT_ERROR = None

# 디스플레이를 위한 Tkinter 임포트
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

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from networks.kafka.kafka_config import settings


class NaturalColors:
    """자연적인 색상 팔레트"""
    
    @staticmethod
    def get_sky_gradient(hour: int) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
        """시간대별 하늘 그라디언트"""
        # 0-23시 기준
        if 5 <= hour < 7:  # 새벽
            return (20, 30, 60), (100, 120, 180)  # 남색 -> 연한 파랑
        elif 7 <= hour < 9:  # 아침
            return (135, 170, 220), (255, 200, 150)  # 하늘색 -> 따뜻한 노을
        elif 9 <= hour < 17:  # 낮
            return (135, 206, 250), (220, 240, 255)  # 맑은 하늘색
        elif 17 <= hour < 19:  # 저녁
            return (255, 150, 100), (120, 100, 180)  # 노을 -> 보라
        elif 19 <= hour < 21:  # 황혼
            return (70, 80, 120), (30, 40, 80)  # 짙은 파랑
        else:  # 밤
            return (10, 15, 40), (30, 40, 70)  # 검은 남색
    
    @staticmethod
    def get_sun_color(temp: float) -> Tuple[int, ...]:
        """온도에 따른 태양 색상"""
        if temp < 10:
            return (255, 220, 180)  # 차가운 백색
        elif temp < 20:
            return (255, 235, 150)  # 연한 노랑
        elif temp < 30:
            return (255, 220, 100)  # 밝은 노랑
        else:
            return (255, 180, 80)  # 뜨거운 주황
    
    @staticmethod
    def get_cloud_color(pm25: float) -> Tuple[int, ...]:
        """미세먼지 농도에 따른 구름 색상"""
        if pm25 < 15:
            return (255, 255, 255)  # 깨끗한 흰색
        elif pm25 < 35:
            return (230, 230, 230)  # 연한 회색
        elif pm25 < 75:
            return (180, 180, 180)  # 회색
        else:
            return (140, 140, 140)  # 짙은 회색


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
            value is not None
            for value in (self.temp_c, self.hum, self.noise, self.pir, self.pm1, self.pm25, self.pm10)
        )


class ParticleSystem:
    """자연스러운 파티클 효과 시스템"""
    
    def __init__(self, max_particles: int = 50):
        self.particles: List[Dict[str, Any]] = []
        self.max_particles = max_particles
    
    def add_particle(self, x: float, y: float, vx: float, vy: float, 
                    size: float, color: Tuple[int, ...], lifetime: float):
        """파티클 추가"""
        if len(self.particles) < self.max_particles:
            self.particles.append({
                'x': x, 'y': y,
                'vx': vx, 'vy': vy,
                'size': size,
                'color': color,
                'lifetime': lifetime,
                'age': 0
            })
    
    def update(self, dt: float):
        """파티클 업데이트"""
        self.particles = [
            p for p in self.particles 
            if p['age'] < p['lifetime']
        ]
        
        for p in self.particles:
            p['x'] += p['vx'] * dt
            p['y'] += p['vy'] * dt
            p['age'] += dt
            # 중력 효과
            p['vy'] += 50 * dt
    
    def draw(self, draw: ImageDraw.ImageDraw, center: float, radius: float):
        """파티클 그리기"""
        for p in self.particles:
            # 원형 경계 체크
            dx = p['x'] - center
            dy = p['y'] - center
            if dx*dx + dy*dy > radius*radius:
                continue
            
            # 페이드 효과
            alpha = 1.0 - (p['age'] / p['lifetime'])
            size = p['size'] * (1 + p['age'] * 0.5)  # 시간에 따라 커짐
            
            if alpha > 0:
                color = p['color'][:3] + (int(alpha * 255),)
                draw.ellipse(
                    [p['x'] - size, p['y'] - size, 
                     p['x'] + size, p['y'] + size],
                    fill=color
                )


def _pick(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not math.isnan(value):
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
        if ts > 1e12:  # 밀리초 방어
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

    direct_keys = {key for key in ("temp_c", "hum", "noise", "pir", "pm1", "pm25", "pm10") if key in payload}
    result = {
        "ts": payload.get("ts"),
        "device_id": payload.get("device_id"),
    }
    if direct_keys:
        for key in ("temp_c", "hum", "noise", "pir", "pm1", "pm25", "pm10"):
            result[key] = payload.get(key)
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
            "pir": _pick(ir, ["pir", "motion", "value", "status"])
            or _pick(base, ["pir", "motion"]),
            "pm1": _pick(pm, ["pm1", "pm1_0", "pm_1_0"]),
            "pm25": _pick(pm, ["pm25", "pm2_5", "pm2.5", "pm_2_5"]),
            "pm10": _pick(pm, ["pm10", "pm_10"]),
        }
    )
    return result


def _snapshot_from_payload(payload: Dict[str, Any]) -> SensorSnapshot | None:
    fields = _extract_fields(payload)
    if not fields:
        return None
    ts = _parse_timestamp(fields.get("ts"))
    snapshot = SensorSnapshot(
        ts=ts,
        device_id=fields.get("device_id") or payload.get("device"),
        temp_c=_to_float(fields.get("temp_c")),
        hum=_to_float(fields.get("hum")),
        noise=_to_float(fields.get("noise")),
        pir=_to_int01(fields.get("pir")),
        pm1=_to_float(fields.get("pm1")),
        pm25=_to_float(fields.get("pm25")),
        pm10=_to_float(fields.get("pm10")),
    )
    return snapshot


class TkinterDisplayDriver:
    def __init__(self, diameter: int):
        if tk is None or ImageTk is None:
            raise RuntimeError(f"Tkinter import 실패: {_TKINTER_IMPORT_ERROR}")
        self.diameter = diameter
        self.root = tk.Tk()
        self.root.title("Natural Sensor Display")
        self.root.geometry(f"{diameter + 20}x{diameter + 50}")
        self.root.configure(bg="black")

        self.label = Label(self.root, bg="black")
        self.label.pack(pady=10)

        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after_idle(lambda: self.root.attributes('-topmost', False))

    def display(self, image: Image.Image):
        photo = ImageTk.PhotoImage(image)
        self.label.configure(image=photo)
        self.label.image = photo
        self.root.update()


class NaturalCircularDisplay:
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
        self.radius = diameter / 2.0

        # 드라이버 설정
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
        
        # 폰트 설정
        self.font_xlarge = self._load_font(font_path, 64)
        self.font_large = self._load_font(font_path, 42)
        self.font_medium = self._load_font(font_path, 28)
        self.font_small = self._load_font(font_path, 20)
        self.font_tiny = self._load_font(font_path, 16)
        
        # 애니메이션 및 효과 상태
        self.animation_time = 0
        self.particle_system = ParticleSystem()
        self.cloud_positions = self._init_cloud_positions()
        self.stars = self._init_stars()
        self.fireflies = []  # 반딧불이
        self.rain_drops = []  # 빗방울
        self.wind_strength = 0
        self.last_pir_time = 0

    def _load_font(self, font_path: str | None, size: int) -> ImageFont.ImageFont:
        candidates = []
        if font_path:
            candidates.append(Path(font_path))
        
        candidates.extend(
            Path(p) for p in (
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/malgun.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            )
        )
        
        for candidate in candidates:
            if candidate.is_file():
                try:
                    return ImageFont.truetype(str(candidate), size)
                except OSError:
                    continue
        
        return ImageFont.load_default()

    def _init_cloud_positions(self) -> List[Dict[str, float]]:
        """구름 초기 위치"""
        return [
            {'x': self.radius * 0.3, 'y': self.radius * 0.4, 'size': 40, 'speed': 0.1},
            {'x': self.radius * 1.5, 'y': self.radius * 0.3, 'size': 50, 'speed': 0.15},
            {'x': self.radius * 1.2, 'y': self.radius * 0.5, 'size': 35, 'speed': 0.08},
        ]
    
    def _init_stars(self) -> List[Dict[str, float]]:
        """별 초기화"""
        stars = []
        for _ in range(30):
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(self.radius * 0.3, self.radius * 0.9)
            stars.append({
                'x': self.center + distance * math.cos(angle),
                'y': self.center + distance * math.sin(angle),
                'brightness': random.uniform(0.3, 1.0),
                'twinkle_speed': random.uniform(1, 3)
            })
        return stars

    def _draw_realistic_sky(self, draw: ImageDraw.ImageDraw, img: Image.Image, hour: int):
        """시간대별 현실적인 하늘 그라디언트"""
        color_top, color_bottom = NaturalColors.get_sky_gradient(hour)
        
        # 부드러운 원형 그라디언트
        for y in range(self.diameter):
            for x in range(self.diameter):
                dx = x - self.center
                dy = y - self.center
                distance = math.sqrt(dx * dx + dy * dy)
                
                if distance <= self.radius:
                    # 중심에서 가장자리로 갈수록 어두워지는 비네팅 효과
                    vignette = 1.0 - (distance / self.radius) * 0.3
                    
                    # 수직 그라디언트
                    vertical_grad = y / self.diameter
                    
                    # 색상 보간
                    r = int((color_top[0] * (1 - vertical_grad) + color_bottom[0] * vertical_grad) * vignette)
                    g = int((color_top[1] * (1 - vertical_grad) + color_bottom[1] * vertical_grad) * vignette)
                    b = int((color_top[2] * (1 - vertical_grad) + color_bottom[2] * vertical_grad) * vignette)
                    
                    img.putpixel((x, y), (r, g, b))

    def _draw_sun_moon(self, draw: ImageDraw.ImageDraw, hour: int, temp: Optional[float]):
        """태양 또는 달 그리기"""
        if 6 <= hour < 18:  # 낮 - 태양
            # 태양 위치 (시간에 따라 이동)
            sun_angle = ((hour - 6) / 12) * math.pi  # 6시~18시를 0~π로
            sun_x = self.center + self.radius * 0.6 * math.cos(sun_angle - math.pi/2)
            sun_y = self.center - self.radius * 0.4 * math.sin(sun_angle)
            
            if temp is not None:
                sun_color = NaturalColors.get_sun_color(temp)
                sun_size = 20 + min(temp / 40 * 15, 15)  # 온도에 따라 크기 변화
            else:
                sun_color = (255, 220, 100)
                sun_size = 25
            
            # 광채 효과 (여러 겹)
            for i in range(4, 0, -1):
                glow_size = sun_size + i * 15
                alpha = int(30 * (1 / i))
                glow_color = sun_color[:3] + (alpha,)
                draw.ellipse(
                    [sun_x - glow_size, sun_y - glow_size,
                     sun_x + glow_size, sun_y + glow_size],
                    fill=glow_color
                )
            
            # 태양 본체
            draw.ellipse(
                [sun_x - sun_size, sun_y - sun_size,
                 sun_x + sun_size, sun_y + sun_size],
                fill=sun_color
            )
            
            # 빛줄기 효과
            if 9 <= hour <= 15:  # 한낮에만
                for i in range(8):
                    angle = i * math.pi / 4 + self.animation_time * 0.5
                    for j in range(1, 4):
                        ray_x = sun_x + math.cos(angle) * (sun_size + j * 20)
                        ray_y = sun_y + math.sin(angle) * (sun_size + j * 20)
                        ray_alpha = int(40 - j * 10)
                        draw.ellipse(
                            [ray_x - 2, ray_y - 2, ray_x + 2, ray_y + 2],
                            fill=sun_color[:3] + (ray_alpha,)
                        )
        
        else:  # 밤 - 달
            moon_x = self.center - self.radius * 0.3
            moon_y = self.center - self.radius * 0.3
            moon_size = 20
            
            # 달빛 광채
            for i in range(3, 0, -1):
                glow_size = moon_size + i * 10
                alpha = int(20 * (1 / i))
                draw.ellipse(
                    [moon_x - glow_size, moon_y - glow_size,
                     moon_x + glow_size, moon_y + glow_size],
                    fill=(200, 210, 255, alpha)
                )
            
            # 달 본체
            draw.ellipse(
                [moon_x - moon_size, moon_y - moon_size,
                 moon_x + moon_size, moon_y + moon_size],
                fill=(240, 245, 255)
            )
            
            # 달 표면 디테일
            draw.ellipse(
                [moon_x - 5, moon_y - 8, moon_x + 3, moon_y],
                fill=(220, 225, 235)
            )
            draw.ellipse(
                [moon_x + 5, moon_y + 3, moon_x + 10, moon_y + 8],
                fill=(220, 225, 235)
            )

    def _draw_clouds(self, draw: ImageDraw.ImageDraw, humidity: Optional[float], pm25: Optional[float]):
        """구름 그리기 (습도와 미세먼지 반영)"""
        # 구름 밀도와 색상 결정
        cloud_density = 0.3
        if humidity is not None:
            cloud_density += (humidity / 100) * 0.4
        
        cloud_color = (255, 255, 255)
        if pm25 is not None:
            cloud_color = NaturalColors.get_cloud_color(pm25)
        
        # 구름 이동
        for cloud in self.cloud_positions:
            cloud['x'] += cloud['speed']
            if cloud['x'] > self.diameter + cloud['size']:
                cloud['x'] = -cloud['size']
            
            # 원형 경계 체크
            dx = cloud['x'] - self.center
            dy = cloud['y'] - self.center
            if dx*dx + dy*dy > (self.radius * 0.8) ** 2:
                continue
            
            # 구름 그리기 (여러 원으로 구성)
            base_alpha = int(150 * cloud_density)
            for i in range(5):
                offset_x = (i - 2) * cloud['size'] * 0.3
                offset_y = math.sin(i) * cloud['size'] * 0.2
                size_variation = cloud['size'] * (0.7 + random.random() * 0.3)
                
                alpha = min(base_alpha - i * 10, 255)
                color = cloud_color[:3] + (alpha,)
                
                draw.ellipse(
                    [cloud['x'] + offset_x - size_variation/2,
                     cloud['y'] + offset_y - size_variation/2,
                     cloud['x'] + offset_x + size_variation/2,
                     cloud['y'] + offset_y + size_variation/2],
                    fill=color
                )

    def _draw_rain(self, draw: ImageDraw.ImageDraw, humidity: Optional[float]):
        """비 효과 (습도가 높을 때)"""
        if humidity is not None and humidity > 70:
            rain_intensity = (humidity - 70) / 30  # 70-100%를 0-1로
            
            # 빗방울 추가
            if random.random() < rain_intensity:
                for _ in range(int(5 * rain_intensity)):
                    x = random.uniform(0, self.diameter)
                    self.rain_drops.append({
                        'x': x,
                        'y': 0,
                        'speed': random.uniform(5, 10),
                        'length': random.uniform(10, 20)
                    })
            
            # 빗방울 업데이트 및 그리기
            self.rain_drops = [d for d in self.rain_drops if d['y'] < self.diameter]
            
            for drop in self.rain_drops:
                drop['y'] += drop['speed']
                
                # 원형 경계 체크
                dx = drop['x'] - self.center
                dy = drop['y'] - self.center
                if dx*dx + dy*dy > self.radius ** 2:
                    continue
                
                # 빗줄기 그리기
                alpha = int(100 * rain_intensity)
                draw.line(
                    [drop['x'], drop['y'], drop['x'], drop['y'] + drop['length']],
                    fill=(150, 170, 200, alpha),
                    width=1
                )

    def _draw_fireflies(self, draw: ImageDraw.ImageDraw, pir: Optional[int]):
        """반딧불이 효과 (모션 감지 시)"""
        if pir:
            self.last_pir_time = time.time()
        
        # 최근 모션 감지 후 5초간 반딧불이 효과
        if time.time() - self.last_pir_time < 5:
            # 반딧불이 추가
            if random.random() < 0.2:
                angle = random.uniform(0, 2 * math.pi)
                distance = random.uniform(self.radius * 0.4, self.radius * 0.8)
                self.fireflies.append({
                    'x': self.center + distance * math.cos(angle),
                    'y': self.center + distance * math.sin(angle),
                    'vx': random.uniform(-1, 1),
                    'vy': random.uniform(-1, 1),
                    'brightness': random.uniform(0, 1),
                    'phase': random.uniform(0, 2 * math.pi)
                })
            
            # 반딧불이 업데이트 및 그리기
            self.fireflies = self.fireflies[-20:]  # 최대 20개
            
            for firefly in self.fireflies:
                # 움직임
                firefly['x'] += firefly['vx']
                firefly['y'] += firefly['vy']
                
                # 원형 경계 체크
                dx = firefly['x'] - self.center
                dy = firefly['y'] - self.center
                if dx*dx + dy*dy > self.radius ** 2:
                    continue
                
                # 깜빡임
                brightness = (math.sin(self.animation_time * 3 + firefly['phase']) + 1) / 2
                firefly['brightness'] = brightness
                
                if brightness > 0.3:
                    # 광채
                    glow_size = 8 * brightness
                    alpha = int(50 * brightness)
                    draw.ellipse(
                        [firefly['x'] - glow_size, firefly['y'] - glow_size,
                         firefly['x'] + glow_size, firefly['y'] + glow_size],
                        fill=(255, 255, 150, alpha)
                    )
                    
                    # 중심점
                    draw.ellipse(
                        [firefly['x'] - 2, firefly['y'] - 2,
                         firefly['x'] + 2, firefly['y'] + 2],
                        fill=(255, 255, 200)
                    )

    def _draw_stars(self, draw: ImageDraw.ImageDraw, hour: int):
        """별 그리기 (밤에만)"""
        if hour < 6 or hour >= 19:  # 밤 시간대
            for star in self.stars:
                # 원형 경계 체크
                dx = star['x'] - self.center
                dy = star['y'] - self.center
                if dx*dx + dy*dy > self.radius ** 2:
                    continue
                
                # 반짝임 효과
                twinkle = (math.sin(self.animation_time * star['twinkle_speed']) + 1) / 2
                brightness = star['brightness'] * twinkle
                
                if brightness > 0.2:
                    size = 1 + brightness
                    alpha = int(200 * brightness)
                    
                    # 별 십자 모양
                    color = (255, 255, 240, alpha)
                    draw.line(
                        [star['x'] - size, star['y'], star['x'] + size, star['y']],
                        fill=color, width=1
                    )
                    draw.line(
                        [star['x'], star['y'] - size, star['x'], star['y'] + size],
                        fill=color, width=1
                    )

    def _draw_glass_card(
        self,
        draw: ImageDraw.ImageDraw,
        x: float, y: float,
        width: float, height: float,
        content_callback,
        bg_alpha: int = 180
    ):
        """글라스모피즘 카드"""
        # 카드 영역
        card_rect = [x - width/2, y - height/2, x + width/2, y + height/2]
        
        # 블러 효과를 위한 배경
        blur_color = (255, 255, 255, bg_alpha // 4)
        for i in range(3):
            blur_rect = [
                card_rect[0] - i*2, card_rect[1] - i*2,
                card_rect[2] + i*2, card_rect[3] + i*2
            ]
            draw.rounded_rectangle(blur_rect, radius=15, fill=blur_color)
        
        # 메인 글라스 배경
        draw.rounded_rectangle(
            card_rect, radius=12,
            fill=(255, 255, 255, bg_alpha)
        )
        
        # 테두리
        draw.rounded_rectangle(
            card_rect, radius=12,
            outline=(255, 255, 255, 100), width=1
        )
        
        # 내부 컨텐츠
        if content_callback:
            content_callback(draw, x, y, width, height)

    def _draw_sensor_value_card(self, draw: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float,
                                label: str, value: Optional[float], unit: str, color: Tuple[int, ...]):
        """센서 값 카드 내용"""
        if value is not None:
            # 라벨
            draw.text((x, y - h/4), label, font=self.font_tiny, fill=(80, 80, 80), anchor="mm")
            
            # 값
            value_text = f"{value:.1f}"
            draw.text((x, y), value_text, font=self.font_large, fill=color, anchor="mm")
            
            # 단위
            draw.text((x, y + h/4), unit, font=self.font_small, fill=(100, 100, 100), anchor="mm")
        else:
            draw.text((x, y), "--", font=self.font_large, fill=(180, 180, 180), anchor="mm")

    def _draw_info_panel(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot):
        """정보 패널"""
        hour = datetime.now().hour
        
        # 중앙 시계 (글라스 카드)
        def draw_clock_content(d, x, y, w, h):
            current_time = datetime.now().strftime("%H:%M")
            current_date = datetime.now().strftime("%m/%d")
            device_name = snapshot.device_id or "Nature Sensor"
            
            d.text((x, y - 15), current_time, font=self.font_xlarge, 
                  fill=(30, 30, 50), anchor="mm")
            d.text((x, y + 25), current_date, font=self.font_small, 
                  fill=(80, 80, 100), anchor="mm")
            d.text((x, y + 45), device_name, font=self.font_tiny, 
                  fill=(120, 120, 140), anchor="mm")
        
        self._draw_glass_card(
            draw, self.center, self.center,
            180, 140,
            draw_clock_content,
            bg_alpha=160
        )
        
        # 센서 카드들 (원형 배치)
        sensors = []
        if snapshot.temp_c is not None:
            sensors.append(("온도", snapshot.temp_c, "°C", (255, 120, 80)))
        if snapshot.hum is not None:
            sensors.append(("습도", snapshot.hum, "%", (100, 180, 255)))
        if snapshot.pm25 is not None:
            sensors.append(("미세먼지", snapshot.pm25, "㎍/㎥", (180, 120, 255)))
        if snapshot.noise is not None:
            sensors.append(("소음", snapshot.noise, "dB", (255, 200, 100)))
        
        if sensors:
            angle_step = 2 * math.pi / len(sensors)
            radius = self.radius * 0.65
            
            for i, (label, value, unit, color) in enumerate(sensors):
                angle = i * angle_step - math.pi / 2
                card_x = self.center + radius * math.cos(angle)
                card_y = self.center + radius * math.sin(angle)
                
                # 원형 경계 내부 체크
                if (card_x - self.center)**2 + (card_y - self.center)**2 <= (self.radius - 50)**2:
                    def make_content_drawer(l, v, u, c):
                        def drawer(d, x, y, w, h):
                            self._draw_sensor_value_card(d, x, y, w, h, l, v, u, c)
                        return drawer
                    
                    self._draw_glass_card(
                        draw, card_x, card_y,
                        90, 70,
                        make_content_drawer(label, value, unit, color),
                        bg_alpha=140
                    )

    def _draw_weather_effects(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot):
        """날씨 효과 종합"""
        hour = datetime.now().hour
        
        # 안개/미스트 효과 (PM2.5 기반)
        if snapshot.pm25 is not None and snapshot.pm25 > 35:
            fog_intensity = min((snapshot.pm25 - 35) / 100, 0.5)
            fog_color = (200, 200, 200, int(100 * fog_intensity))
            
            # 여러 겹의 안개
            for i in range(3):
                y_offset = self.center + (i - 1) * 50
                for x in range(0, self.diameter, 20):
                    wave = math.sin(x * 0.02 + self.animation_time + i) * 20
                    draw.ellipse(
                        [x - 30, y_offset + wave - 15,
                         x + 30, y_offset + wave + 15],
                        fill=fog_color
                    )

    def render(self, snapshot: SensorSnapshot) -> Image.Image:
        """메인 렌더링"""
        self.animation_time = time.time()
        hour = datetime.now().hour
        
        # 배경 이미지
        img = Image.new("RGB", (self.diameter, self.diameter), (0, 0, 0))
        
        # 시간대별 하늘 그라디언트
        self._draw_realistic_sky(None, img, hour)
        
        # 원형 마스크
        mask = Image.new("L", (self.diameter, self.diameter), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, self.diameter, self.diameter), fill=255)
        
        # 마스크 적용
        background = Image.new("RGB", (self.diameter, self.diameter), (0, 0, 0))
        background.paste(img, mask=mask)
        img = background
        
        # RGBA 드로우
        draw = ImageDraw.Draw(img, "RGBA")
        
        # 배경 요소들
        self._draw_stars(draw, hour)
        self._draw_sun_moon(draw, hour, snapshot.temp_c)
        self._draw_clouds(draw, snapshot.hum, snapshot.pm25)
        
        # 날씨 효과
        self._draw_rain(draw, snapshot.hum)
        self._draw_weather_effects(draw, snapshot)
        
        # 인터랙티브 요소
        self._draw_fireflies(draw, snapshot.pir)
        
        # 파티클 시스템
        self.particle_system.update(0.016)  # 60fps 가정
        self.particle_system.draw(draw, self.center, self.radius)
        
        # 정보 패널
        if snapshot.has_payload():
            self._draw_info_panel(draw, snapshot)
        else:
            # 연결 대기 상태
            def draw_connecting(d, x, y, w, h):
                dots = "." * (int(self.animation_time * 2) % 4)
                d.text((x, y), "연결 중" + dots, font=self.font_medium,
                      fill=(100, 100, 120), anchor="mm")
            
            self._draw_glass_card(draw, self.center, self.center,
                                 150, 60, draw_connecting, bg_alpha=180)
        
        # 외곽 비네팅 효과
        for i in range(10):
            alpha = int(5 * i)
            draw.ellipse(
                [i, i, self.diameter - i, self.diameter - i],
                outline=(0, 0, 0, alpha), width=1
            )
        
        return img

    def present(self, image: Image.Image) -> None:
        """디스플레이 출력"""
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
            consumer = KafkaConsumer(
                enable_auto_commit=True,
                value_deserializer=lambda v: v.decode(settings.value_encoding, "ignore"),
                consumer_timeout_ms=1000,
                **settings.kafka_kwargs,
            )
            consumer.subscribe([settings.sensor_topic])
            if self.debug:
                print(f"[Kafka] 토픽 구독: {settings.sensor_topic}")
        except Exception as exc:
            print(f"[Kafka] 소비자 초기화 실패: {exc}")
            return

        while not self._stop_evt.is_set():
            try:
                records = consumer.poll(timeout_ms=500)
            except Exception as exc:
                if self.debug:
                    print(f"[Kafka] poll 실패: {exc}")
                time.sleep(1.0)
                continue
                
            if not records:
                continue
                
            for messages in records.values():
                for message in messages:
                    try:
                        payload = json.loads(message.value)
                    except Exception as exc:
                        if self.debug:
                            print(f"[Kafka] JSON 파싱 실패: {exc}")
                        continue
                        
                    snapshot = _snapshot_from_payload(payload)
                    if snapshot:
                        snapshot.raw = payload
                        snapshot.ingested_at = time.time()
                        self._publish(snapshot)
                        
        try:
            consumer.close()
        except Exception:
            pass


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="자연 테마 리얼리스틱 센서 디스플레이")
    parser.add_argument("--diameter", type=int, default=settings.diameter_pixels, help="디스플레이 지름(px)")
    parser.add_argument("--font", type=str, default=settings.font_path, help="TTF 폰트 경로")
    parser.add_argument("--refresh-hz", type=float, default=settings.display_refresh_hz, help="화면 갱신 주기(Hz)")
    parser.add_argument("--frame-dump", type=str, default=None, help="프레임 이미지 저장 디렉터리")
    parser.add_argument("--debug", action="store_true", help="디버그 로그 출력")
    return parser


def main() -> None:
    if KafkaConsumer is None:
        raise SystemExit(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
    if Image is None or ImageDraw is None or ImageFont is None:
        raise SystemExit(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")

    parser = build_arg_parser()
    args = parser.parse_args()

    refresh_hz = args.refresh_hz if args.refresh_hz > 0 else 1.0
    refresh_period = 1.0 / refresh_hz

    dump_dir = Path(args.frame_dump) if args.frame_dump else None
    display = NaturalCircularDisplay(
        diameter=args.diameter,
        font_path=args.font,
        dump_dir=dump_dir,
    )

    out_queue: queue.Queue[SensorSnapshot] = queue.Queue(maxsize=16)
    stream = KafkaSensorStream(out_queue, debug=args.debug)
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
                image = display.render(latest)
                display.present(image)
                next_frame = now + refresh_period
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()


if __name__ == "__main__":
    main()