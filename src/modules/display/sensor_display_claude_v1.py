"""Kafka 파이프라인을 통해 수집한 UART 센서 값을 2.1인치 원형 디스플레이에 맞춰 렌더링.

깔끔하고 가독성 높은 미니멀 디자인으로 센서 데이터를 시각화합니다.
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


class MinimalColors:
    """깔끔한 미니멀 색상 팔레트"""
    
    # 배경 그라데이션 (시간대별)
    @staticmethod
    def get_background_gradient(hour: int) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
        """시간대별 배경 그라데이션"""
        if 5 <= hour < 8:  # 아침
            return (255, 230, 210), (255, 245, 235)  # 따뜻한 베이지
        elif 8 <= hour < 17:  # 낮
            return (220, 240, 255), (245, 250, 255)  # 밝은 하늘색
        elif 17 <= hour < 20:  # 저녁
            return (255, 220, 200), (240, 230, 245)  # 노을색
        else:  # 밤
            return (25, 35, 55), (45, 60, 90)  # 다크 네이비
    
    # 센서별 강조색
    TEMP_HOT = (255, 87, 51)     # 뜨거운 온도 - 강렬한 오렌지
    TEMP_WARM = (255, 152, 0)    # 따뜻한 온도 - 앰버
    TEMP_COOL = (33, 150, 243)   # 시원한 온도 - 블루
    TEMP_COLD = (100, 181, 246)  # 차가운 온도 - 라이트 블루
    
    HUMIDITY_LOW = (255, 193, 7)   # 낮은 습도 - 앰버
    HUMIDITY_MID = (3, 169, 244)   # 중간 습도 - 라이트 블루
    HUMIDITY_HIGH = (0, 121, 207)  # 높은 습도 - 딥 블루
    
    PM_GOOD = (76, 175, 80)      # 좋음 - 그린
    PM_MODERATE = (255, 193, 7)  # 보통 - 앰버
    PM_BAD = (255, 87, 34)       # 나쁨 - 오렌지
    PM_VERY_BAD = (244, 67, 54)  # 매우 나쁨 - 레드
    
    NOISE_QUIET = (139, 195, 74)   # 조용함 - 라이트 그린
    NOISE_NORMAL = (255, 193, 7)   # 보통 - 앰버
    NOISE_LOUD = (255, 87, 34)     # 시끄러움 - 오렌지
    
    MOTION_DETECTED = (255, 64, 129)  # 모션 감지 - 핑크
    MOTION_CLEAR = (158, 158, 158)    # 모션 없음 - 그레이
    
    # UI 색상
    CARD_BG_DAY = (255, 255, 255, 230)    # 낮 카드 배경
    CARD_BG_NIGHT = (30, 40, 60, 230)     # 밤 카드 배경
    TEXT_PRIMARY_DAY = (33, 33, 33)       # 낮 주 텍스트
    TEXT_PRIMARY_NIGHT = (245, 245, 245)  # 밤 주 텍스트
    TEXT_SECONDARY = (117, 117, 117)      # 보조 텍스트


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
        self.root.title("Minimal Sensor Display")
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


class MinimalCircularDisplay:
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
        
        # 폰트 설정 (크기 증가)
        self.font_time = self._load_font(font_path, 72)      # 시간용 대형 폰트
        self.font_xlarge = self._load_font(font_path, 56)    # 메인 값용
        self.font_large = self._load_font(font_path, 42)     # 큰 값용
        self.font_medium = self._load_font(font_path, 32)    # 중간 텍스트
        self.font_small = self._load_font(font_path, 24)     # 라벨용
        self.font_tiny = self._load_font(font_path, 18)      # 부가 정보용
        
        # 애니메이션 상태
        self.animation_time = 0
        self.pulse_phase = 0

    def _load_font(self, font_path: str | None, size: int) -> ImageFont.ImageFont:
        candidates = []
        if font_path:
            candidates.append(Path(font_path))
        
        # 시스템 폰트 우선순위
        candidates.extend(
            Path(p) for p in (
                # Windows
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/SegoeUI-Bold.ttf",
                "C:/Windows/Fonts/malgun.ttf",
                # macOS
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Avenir.ttc",
                # Linux
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

    def _get_temp_color(self, temp: float) -> Tuple[int, ...]:
        """온도에 따른 색상"""
        if temp < 10:
            return MinimalColors.TEMP_COLD
        elif temp < 20:
            return MinimalColors.TEMP_COOL
        elif temp < 28:
            return MinimalColors.TEMP_WARM
        else:
            return MinimalColors.TEMP_HOT

    def _get_humidity_color(self, humidity: float) -> Tuple[int, ...]:
        """습도에 따른 색상"""
        if humidity < 30:
            return MinimalColors.HUMIDITY_LOW
        elif humidity < 60:
            return MinimalColors.HUMIDITY_MID
        else:
            return MinimalColors.HUMIDITY_HIGH

    def _get_pm_color(self, pm25: float) -> Tuple[int, ...]:
        """PM2.5에 따른 색상"""
        if pm25 <= 15:
            return MinimalColors.PM_GOOD
        elif pm25 <= 35:
            return MinimalColors.PM_MODERATE
        elif pm25 <= 75:
            return MinimalColors.PM_BAD
        else:
            return MinimalColors.PM_VERY_BAD

    def _get_noise_color(self, noise: float) -> Tuple[int, ...]:
        """소음에 따른 색상"""
        if noise < 40:
            return MinimalColors.NOISE_QUIET
        elif noise < 70:
            return MinimalColors.NOISE_NORMAL
        else:
            return MinimalColors.NOISE_LOUD

    def _draw_smooth_gradient(self, img: Image.Image, color_top: Tuple[int, ...], color_bottom: Tuple[int, ...]):
        """부드러운 원형 그라데이션 배경"""
        draw = ImageDraw.Draw(img, "RGBA")
        
        # 원형 그라데이션
        for i in range(self.diameter // 2):
            progress = i / (self.diameter // 2)
            # Ease-out 곡선 적용
            progress = 1 - (1 - progress) ** 2
            
            r = int(color_top[0] + (color_bottom[0] - color_top[0]) * progress)
            g = int(color_top[1] + (color_bottom[1] - color_top[1]) * progress)
            b = int(color_top[2] + (color_bottom[2] - color_top[2]) * progress)
            
            draw.ellipse(
                [self.center - (self.radius - i), self.center - (self.radius - i),
                 self.center + (self.radius - i), self.center + (self.radius - i)],
                fill=(r, g, b)
            )

    def _draw_arc_progress(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: float, center_y: float,
        radius: float,
        start_angle: float, end_angle: float,
        value: float, max_value: float,
        color: Tuple[int, ...],
        thickness: int = 8
    ):
        """원호형 프로그레스 바"""
        # 배경 트랙
        track_color = color[:3] + (50,)
        for t in range(thickness):
            r = radius - t
            bbox = [center_x - r, center_y - r, center_x + r, center_y + r]
            draw.arc(bbox, start_angle, end_angle, fill=track_color, width=1)
        
        # 값 표시
        if value is not None and max_value > 0:
            progress = min(value / max_value, 1.0)
            value_angle = start_angle + (end_angle - start_angle) * progress
            
            for t in range(thickness):
                r = radius - t
                bbox = [center_x - r, center_y - r, center_x + r, center_y + r]
                # 그라데이션 효과
                alpha = 255 - (t * 20)
                fill_color = color[:3] + (alpha,) if len(color) == 3 else color
                draw.arc(bbox, start_angle, value_angle, fill=fill_color, width=1)

    def _draw_modern_card(
        self,
        draw: ImageDraw.ImageDraw,
        x: float, y: float,
        width: float, height: float,
        is_night: bool = False
    ) -> Tuple[float, float, float, float]:
        """모던한 카드 배경"""
        rect = [x - width/2, y - height/2, x + width/2, y + height/2]
        
        # 그림자 (더 부드럽게)
        for i in range(3, 0, -1):
            shadow_alpha = 10 * i if not is_night else 5 * i
            shadow_rect = [rect[0] - i, rect[1] - i, rect[2] + i, rect[3] + i]
            draw.rounded_rectangle(
                shadow_rect, 
                radius=12 + i,
                fill=(0, 0, 0, shadow_alpha)
            )
        
        # 카드 배경
        bg_color = MinimalColors.CARD_BG_NIGHT if is_night else MinimalColors.CARD_BG_DAY
        draw.rounded_rectangle(rect, radius=12, fill=bg_color)
        
        # 얇은 테두리
        border_color = (255, 255, 255, 30) if is_night else (0, 0, 0, 10)
        draw.rounded_rectangle(rect, radius=12, outline=border_color, width=1)
        
        return rect

    def _draw_main_display(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot, is_night: bool):
        """메인 디스플레이 영역"""
        # 시간
        current_time = datetime.now().strftime("%H:%M")
        text_color = MinimalColors.TEXT_PRIMARY_NIGHT if is_night else MinimalColors.TEXT_PRIMARY_DAY
        
        # 시간 표시 (크고 굵게)
        draw.text(
            (self.center, self.center - 20),
            current_time,
            font=self.font_time,
            fill=text_color,
            anchor="mm"
        )
        
        # 날짜
        current_date = datetime.now().strftime("%m/%d")
        draw.text(
            (self.center, self.center + 35),
            current_date,
            font=self.font_small,
            fill=MinimalColors.TEXT_SECONDARY,
            anchor="mm"
        )
        
        # 디바이스 이름
        device_name = snapshot.device_id or "Smart Sensor"
        draw.text(
            (self.center, self.center + 60),
            device_name,
            font=self.font_tiny,
            fill=MinimalColors.TEXT_SECONDARY,
            anchor="mm"
        )
        
        # 연결 상태 표시 (작은 점)
        age = time.time() - snapshot.ingested_at
        if age < 5:
            status_color = MinimalColors.PM_GOOD
            status_text = "LIVE"
        elif age < 30:
            status_color = MinimalColors.PM_MODERATE  
            status_text = "ACTIVE"
        else:
            status_color = MinimalColors.TEXT_SECONDARY
            status_text = "OFFLINE"
        
        # 상태 점 (펄스 효과)
        pulse = abs(math.sin(self.animation_time * 3))
        dot_size = 3 + pulse * 1
        draw.ellipse(
            [self.center - 50 - dot_size, self.center + 60 - dot_size,
             self.center - 50 + dot_size, self.center + 60 + dot_size],
            fill=status_color
        )
        draw.text(
            (self.center - 40, self.center + 60),
            status_text,
            font=self.font_tiny,
            fill=status_color,
            anchor="lm"
        )

    def _draw_sensor_widgets(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot, is_night: bool):
        """센서 위젯 배치"""
        text_color = MinimalColors.TEXT_PRIMARY_NIGHT if is_night else MinimalColors.TEXT_PRIMARY_DAY
        
        # 큰 센서 카드 4개 (2x2 그리드 대신 원형 배치)
        widgets = []
        
        # 온도
        if snapshot.temp_c is not None:
            color = self._get_temp_color(snapshot.temp_c)
            widgets.append({
                'value': f"{snapshot.temp_c:.1f}",
                'unit': '°C',
                'label': '온도',
                'color': color,
                'icon': '🌡' if snapshot.temp_c > 25 else '❄️'
            })
        
        # 습도
        if snapshot.hum is not None:
            color = self._get_humidity_color(snapshot.hum)
            widgets.append({
                'value': f"{snapshot.hum:.0f}",
                'unit': '%',
                'label': '습도',
                'color': color,
                'icon': '💧'
            })
        
        # PM2.5
        if snapshot.pm25 is not None:
            color = self._get_pm_color(snapshot.pm25)
            quality = "좋음" if snapshot.pm25 <= 15 else "보통" if snapshot.pm25 <= 35 else "나쁨" if snapshot.pm25 <= 75 else "매우나쁨"
            widgets.append({
                'value': f"{snapshot.pm25:.0f}",
                'unit': 'μg/m³',
                'label': f'미세먼지 ({quality})',
                'color': color,
                'icon': '🌫' if snapshot.pm25 > 35 else '☀️'
            })
        
        # 소음
        if snapshot.noise is not None:
            color = self._get_noise_color(snapshot.noise)
            widgets.append({
                'value': f"{snapshot.noise:.0f}",
                'unit': 'dB',
                'label': '소음',
                'color': color,
                'icon': '🔊' if snapshot.noise > 50 else '🔇'
            })
        
        # 위젯 배치 (상하좌우)
        if len(widgets) > 0:
            positions = [
                (self.center, self.center - 140),  # 상단
                (self.center + 120, self.center),  # 우측
                (self.center, self.center + 140),  # 하단
                (self.center - 120, self.center),  # 좌측
            ]
            
            for i, widget in enumerate(widgets[:4]):
                if i < len(positions):
                    x, y = positions[i]
                    
                    # 원형 경계 체크
                    dx = x - self.center
                    dy = y - self.center
                    if dx*dx + dy*dy <= (self.radius - 30) ** 2:
                        # 카드 배경
                        card_rect = self._draw_modern_card(draw, x, y, 100, 70, is_night)
                        
                        # 아이콘
                        draw.text((x - 30, y - 10), widget['icon'], font=self.font_medium, 
                                 fill=widget['color'], anchor="mm")
                        
                        # 값 (크고 굵게)
                        draw.text((x + 10, y - 10), widget['value'], font=self.font_large,
                                 fill=widget['color'], anchor="mm")
                        
                        # 단위
                        draw.text((x + 10, y + 15), widget['unit'], font=self.font_tiny,
                                 fill=MinimalColors.TEXT_SECONDARY, anchor="mm")
                        
                        # 라벨
                        draw.text((x, y - 30), widget['label'], font=self.font_tiny,
                                 fill=MinimalColors.TEXT_SECONDARY, anchor="mm")
        
        # PIR 모션 표시 (우하단 작은 인디케이터)
        if snapshot.pir is not None:
            motion_x = self.center + 100
            motion_y = self.center + 100
            
            if snapshot.pir:
                # 모션 감지 - 애니메이션 효과
                pulse = abs(math.sin(self.animation_time * 5))
                for i in range(3):
                    alpha = int(50 * (1 - i/3) * pulse)
                    size = 20 + i * 10
                    draw.ellipse(
                        [motion_x - size, motion_y - size,
                         motion_x + size, motion_y + size],
                        fill=MinimalColors.MOTION_DETECTED[:3] + (alpha,)
                    )
                
                draw.text((motion_x, motion_y), "👁", font=self.font_medium,
                         fill=MinimalColors.MOTION_DETECTED, anchor="mm")
                draw.text((motion_x, motion_y + 25), "Motion", font=self.font_tiny,
                         fill=MinimalColors.MOTION_DETECTED, anchor="mm")
            else:
                draw.text((motion_x, motion_y), "😴", font=self.font_small,
                         fill=MinimalColors.MOTION_CLEAR, anchor="mm")

    def _draw_decorative_elements(self, draw: ImageDraw.ImageDraw, is_night: bool):
        """장식 요소"""
        if is_night:
            # 밤 - 작은 별들
            for i in range(10):
                angle = (i / 10) * 2 * math.pi
                distance = self.radius * 0.85
                star_x = self.center + distance * math.cos(angle)
                star_y = self.center + distance * math.sin(angle)
                
                # 반짝임
                brightness = abs(math.sin(self.animation_time * 2 + i))
                if brightness > 0.5:
                    size = 1 + brightness
                    alpha = int(100 * brightness)
                    draw.ellipse(
                        [star_x - size, star_y - size, star_x + size, star_y + size],
                        fill=(255, 255, 240, alpha)
                    )
        else:
            # 낮 - 부드러운 장식
            pass

    def _draw_waiting_state(self, draw: ImageDraw.ImageDraw, is_night: bool):
        """연결 대기 상태"""
        text_color = MinimalColors.TEXT_PRIMARY_NIGHT if is_night else MinimalColors.TEXT_PRIMARY_DAY
        
        # 로딩 애니메이션
        for i in range(3):
            angle = (self.animation_time * 2 + i * 2.094) % (2 * math.pi)
            x = self.center + 30 * math.cos(angle)
            y = self.center + 30 * math.sin(angle)
            
            size = 3 + abs(math.sin(angle)) * 2
            alpha = int(100 + 155 * abs(math.sin(angle)))
            
            draw.ellipse(
                [x - size, y - size, x + size, y + size],
                fill=text_color[:3] + (alpha,)
            )
        
        # 메시지
        draw.text(
            (self.center, self.center + 60),
            "센서 연결 대기중",
            font=self.font_small,
            fill=MinimalColors.TEXT_SECONDARY,
            anchor="mm"
        )

    def render(self, snapshot: SensorSnapshot) -> Image.Image:
        """메인 렌더링"""
        self.animation_time = time.time()
        self.pulse_phase = (self.pulse_phase + 0.1) % (2 * math.pi)
        
        hour = datetime.now().hour
        is_night = hour < 6 or hour >= 20
        
        # 배경 그라데이션
        bg_top, bg_bottom = MinimalColors.get_background_gradient(hour)
        img = Image.new("RGB", (self.diameter, self.diameter), bg_top)
        self._draw_smooth_gradient(img, bg_top, bg_bottom)
        
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
        
        # 장식 요소
        self._draw_decorative_elements(draw, is_night)
        
        # 컨텐츠
        if snapshot.has_payload():
            # 메인 디스플레이
            self._draw_main_display(draw, snapshot, is_night)
            
            # 센서 위젯
            self._draw_sensor_widgets(draw, snapshot, is_night)
        else:
            # 대기 상태
            self._draw_waiting_state(draw, is_night)
        
        # 외곽 테두리 (은은하게)
        border_color = (30, 30, 30, 50) if not is_night else (200, 200, 200, 30)
        draw.ellipse(
            [1, 1, self.diameter - 1, self.diameter - 1],
            outline=border_color, width=1
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
    parser = argparse.ArgumentParser(description="미니멀 센서 디스플레이")
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

    print("[Main] 미니멀 센서 디스플레이 시작")

    refresh_hz = args.refresh_hz if args.refresh_hz > 0 else 1.0
    refresh_period = 1.0 / refresh_hz

    dump_dir = Path(args.frame_dump) if args.frame_dump else None
    display = MinimalCircularDisplay(
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