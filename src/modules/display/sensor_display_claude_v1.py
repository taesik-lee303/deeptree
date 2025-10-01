"""Kafka 파이프라인을 통해 수집한 UART 센서 값을 2.1인치 원형 디스플레이에 맞춰 렌더링.

- kafka-python 소비자를 이용해 sensors.uart(기본) 토픽을 지속적으로 구독
- 메시지 페이로드는 uart_receiver.py와 동일/유사한 스키마(JSON)를 예상
- Pillow를 이용해 480x480(기본) 원형 레이아웃을 구성하고, 실제 디스플레이 드라이버에 이미지를 전달
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
from typing import Any, Dict, Iterable, Optional, Tuple

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


# 모던한 컬러 팔레트
class Colors:
    # 배경 그라디언트
    BG_TOP = (25, 28, 50)  # 다크 네이비
    BG_BOTTOM = (45, 55, 80)  # 미드나이트 블루
    
    # 메인 색상
    PRIMARY = (100, 200, 255)  # 스카이 블루
    SECONDARY = (255, 100, 150)  # 코랄 핑크
    ACCENT = (150, 255, 200)  # 민트
    
    # 상태 색상
    SUCCESS = (100, 255, 150)  # 그린
    WARNING = (255, 200, 100)  # 앰버
    DANGER = (255, 100, 100)  # 레드
    
    # 텍스트 색상
    TEXT_PRIMARY = (255, 255, 255)
    TEXT_SECONDARY = (200, 210, 230)
    TEXT_MUTED = (120, 140, 170)
    
    # 카드 색상
    CARD_BG = (35, 40, 65, 200)  # 반투명 다크
    CARD_BORDER = (80, 90, 120, 100)
    
    # 센서별 테마 색상
    TEMP_COLOR = (255, 120, 90)  # 웜 오렌지
    HUMIDITY_COLOR = (90, 180, 255)  # 쿨 블루
    PM_COLOR = (180, 120, 255)  # 퍼플
    NOISE_COLOR = (255, 200, 100)  # 옐로
    MOTION_COLOR = (100, 255, 200)  # 그린


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
        self.root.title("Modern Sensor Display")
        self.root.geometry(f"{diameter + 20}x{diameter + 50}")
        self.root.configure(bg="black")

        self.label = Label(self.root, bg="black")
        self.label.pack(pady=10)

        # 창을 맨 앞으로 가져오기
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after_idle(lambda: self.root.attributes('-topmost', False))

    def display(self, image: Image.Image):
        # PIL 이미지를 Tkinter가 사용할 수 있는 형태로 변환
        photo = ImageTk.PhotoImage(image)
        self.label.configure(image=photo)
        self.label.image = photo  # 참조 유지
        self.root.update()


class ModernCircularDisplay:
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
        self.font_large = self._load_font(font_path, 72)
        self.font_medium = self._load_font(font_path, 36)
        self.font_small = self._load_font(font_path, 24)
        self.font_tiny = self._load_font(font_path, 18)
        self.font_micro = self._load_font(font_path, 14)
        
        # 애니메이션 상태
        self.animation_time = 0

    def _load_font(self, font_path: str | None, size: int) -> ImageFont.ImageFont:
        candidates = []
        if font_path:
            candidates.append(Path(font_path))
        
        # 시스템 폰트 경로들
        candidates.extend(
            Path(p)
            for p in (
                "C:/Windows/Fonts/segoeui.ttf",  # Windows
                "C:/Windows/Fonts/malgun.ttf",
                "/System/Library/Fonts/Helvetica.ttc",  # macOS
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
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

    def _draw_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        xy: Tuple[float, float],
        font: ImageFont.ImageFont,
        fill: Tuple[int, ...],
        anchor: str = "mm"
    ) -> None:
        """텍스트 그리기 (anchor 지원)"""
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)

    def _draw_gradient_background(self, draw: ImageDraw.ImageDraw, img: Image.Image) -> None:
        """원형 그라디언트 배경"""
        # 방사형 그라디언트 생성
        for i in range(self.diameter):
            for j in range(self.diameter):
                # 중심으로부터의 거리 계산
                dx = i - self.center
                dy = j - self.center
                distance = math.sqrt(dx * dx + dy * dy)
                
                if distance <= self.radius:
                    # 정규화된 거리 (0 = 중심, 1 = 가장자리)
                    normalized = distance / self.radius
                    
                    # 그라디언트 색상 계산
                    r = int(Colors.BG_TOP[0] * (1 - normalized) + Colors.BG_BOTTOM[0] * normalized)
                    g = int(Colors.BG_TOP[1] * (1 - normalized) + Colors.BG_BOTTOM[1] * normalized)
                    b = int(Colors.BG_TOP[2] * (1 - normalized) + Colors.BG_BOTTOM[2] * normalized)
                    
                    img.putpixel((i, j), (r, g, b))

    def _draw_arc_indicator(
        self,
        draw: ImageDraw.ImageDraw,
        value: float,
        max_value: float,
        start_angle: float,
        end_angle: float,
        radius: float,
        width: int,
        color: Tuple[int, ...],
        bg_color: Tuple[int, ...] = (60, 70, 90, 100)
    ) -> None:
        """원호형 인디케이터"""
        # 배경 원호
        bbox = [
            self.center - radius,
            self.center - radius,
            self.center + radius,
            self.center + radius
        ]
        
        # 배경 호
        for i in range(width):
            current_bbox = [
                bbox[0] - i, bbox[1] - i,
                bbox[2] + i, bbox[3] + i
            ]
            draw.arc(current_bbox, start_angle, end_angle, fill=bg_color, width=1)
        
        # 값 표시 호
        if value is not None and max_value > 0:
            value_angle = start_angle + (end_angle - start_angle) * min(value / max_value, 1.0)
            for i in range(width):
                current_bbox = [
                    bbox[0] - i, bbox[1] - i,
                    bbox[2] + i, bbox[3] + i
                ]
                draw.arc(current_bbox, start_angle, value_angle, fill=color, width=1)

    def _draw_sensor_card(
        self,
        draw: ImageDraw.ImageDraw,
        x: float,
        y: float,
        width: float,
        height: float,
        title: str,
        value: Optional[float],
        unit: str,
        color: Tuple[int, ...],
        icon: str = ""
    ) -> None:
        """모던한 센서 카드"""
        # 카드 배경 (둥근 모서리)
        card_rect = [x - width/2, y - height/2, x + width/2, y + height/2]
        
        # 그림자 효과
        shadow_rect = [card_rect[0] + 2, card_rect[1] + 2, card_rect[2] + 2, card_rect[3] + 2]
        draw.rounded_rectangle(shadow_rect, radius=12, fill=(20, 25, 40, 150))
        
        # 카드 배경
        draw.rounded_rectangle(card_rect, radius=10, fill=(40, 45, 70, 220))
        
        # 카드 테두리 (얇고 은은한)
        draw.rounded_rectangle(card_rect, radius=10, outline=(80, 90, 120, 100), width=1)
        
        # 아이콘
        if icon:
            self._draw_text(draw, icon, (x - width/3, y - height/4), self.font_small, color, "mm")
        
        # 타이틀
        self._draw_text(draw, title, (x, y - height/3), self.font_micro, Colors.TEXT_MUTED, "mm")
        
        # 값
        if value is not None:
            value_text = f"{value:.1f}"
            self._draw_text(draw, value_text, (x, y), self.font_medium, Colors.TEXT_PRIMARY, "mm")
            self._draw_text(draw, unit, (x, y + height/4), self.font_tiny, Colors.TEXT_SECONDARY, "mm")
        else:
            self._draw_text(draw, "--", (x, y), self.font_medium, Colors.TEXT_MUTED, "mm")

    def _draw_status_indicator(
        self,
        draw: ImageDraw.ImageDraw,
        x: float,
        y: float,
        status: str,
        color: Tuple[int, ...]
    ) -> None:
        """상태 표시기"""
        # 깜빡이는 효과
        pulse = abs(math.sin(self.animation_time * 3))
        radius = 4 + pulse * 2
        
        # 외부 글로우
        for i in range(3):
            alpha = int(50 * (1 - i/3) * pulse)
            glow_color = color + (alpha,) if len(color) == 3 else color[:3] + (alpha,)
            draw.ellipse(
                [x - radius - i*2, y - radius - i*2, x + radius + i*2, y + radius + i*2],
                fill=glow_color
            )
        
        # 중심 점
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
        
        # 상태 텍스트
        self._draw_text(draw, status, (x + 15, y), self.font_micro, Colors.TEXT_SECONDARY, "lm")

    def _draw_center_display(
        self,
        draw: ImageDraw.ImageDraw,
        snapshot: SensorSnapshot
    ) -> None:
        """중앙 메인 디스플레이"""
        # 시간 표시
        current_time = datetime.now().strftime("%H:%M")
        self._draw_text(draw, current_time, (self.center, self.center - 60), 
                       self.font_large, Colors.TEXT_PRIMARY, "mm")
        
        # 날짜 표시
        current_date = datetime.now().strftime("%Y.%m.%d")
        self._draw_text(draw, current_date, (self.center, self.center - 20), 
                       self.font_tiny, Colors.TEXT_SECONDARY, "mm")
        
        # 디바이스 이름
        device_name = snapshot.device_id or "Smart Sensor"
        self._draw_text(draw, device_name, (self.center, self.center + 10), 
                       self.font_small, Colors.TEXT_MUTED, "mm")
        
        # 연결 상태
        age = time.time() - snapshot.ingested_at
        if age < 5:
            status = "LIVE"
            color = Colors.SUCCESS
        elif age < 30:
            status = "ACTIVE"
            color = Colors.WARNING
        else:
            status = "OFFLINE"
            color = Colors.TEXT_MUTED
        
        self._draw_status_indicator(draw, self.center - 30, self.center + 40, status, color)

    def _draw_waiting_state(self, draw: ImageDraw.ImageDraw) -> None:
        """대기 상태 화면"""
        # 로딩 애니메이션 (회전하는 원호)
        loading_radius = 50
        for i in range(4):
            angle_offset = (self.animation_time * 100 + i * 90) % 360
            start = angle_offset
            end = angle_offset + 60
            
            alpha = int(255 * (0.3 + 0.2 * i))
            color = Colors.PRIMARY[:3] + (alpha,)
            
            bbox = [
                self.center - loading_radius,
                self.center - loading_radius,
                self.center + loading_radius,
                self.center + loading_radius
            ]
            draw.arc(bbox, start, end, fill=color, width=3)
        
        # 메시지
        self._draw_text(draw, "Connecting", (self.center, self.center + 80), 
                       self.font_small, Colors.TEXT_SECONDARY, "mm")
        
        dots = "." * (int(self.animation_time * 2) % 4)
        self._draw_text(draw, dots, (self.center + 50, self.center + 80), 
                       self.font_small, Colors.TEXT_SECONDARY, "lm")

    def _draw_sensor_ring(
        self,
        draw: ImageDraw.ImageDraw,
        snapshot: SensorSnapshot
    ) -> None:
        """센서 데이터를 원형 링으로 표시"""
        # 온도 표시 (상단)
        if snapshot.temp_c is not None:
            self._draw_arc_indicator(
                draw, snapshot.temp_c, 50,  # 0-50도 범위
                -120, -60,  # 상단 좌측 호
                self.radius * 0.75, 8,
                Colors.TEMP_COLOR
            )
            self._draw_sensor_card(
                draw, self.center - 80, self.center - 120,
                80, 50, "TEMP", snapshot.temp_c, "°C",
                Colors.TEMP_COLOR, "🌡"
            )
        
        # 습도 표시 (우측)
        if snapshot.hum is not None:
            self._draw_arc_indicator(
                draw, snapshot.hum, 100,  # 0-100% 범위
                -30, 30,  # 우측 호
                self.radius * 0.75, 8,
                Colors.HUMIDITY_COLOR
            )
            self._draw_sensor_card(
                draw, self.center + 120, self.center,
                80, 50, "HUM", snapshot.hum, "%",
                Colors.HUMIDITY_COLOR, "💧"
            )
        
        # PM2.5 표시 (하단)
        if snapshot.pm25 is not None:
            pm_quality = self._get_pm_quality(snapshot.pm25)
            self._draw_arc_indicator(
                draw, snapshot.pm25, 150,  # 0-150 범위
                60, 120,  # 하단 우측 호
                self.radius * 0.75, 8,
                pm_quality["color"]
            )
            self._draw_sensor_card(
                draw, self.center + 80, self.center + 120,
                80, 50, "PM2.5", snapshot.pm25, "㎍",
                pm_quality["color"], pm_quality["icon"]
            )
        
        # 소음 표시 (좌측)
        if snapshot.noise is not None:
            self._draw_arc_indicator(
                draw, snapshot.noise, 100,  # 0-100dB 범위
                150, 210,  # 좌측 호
                self.radius * 0.75, 8,
                Colors.NOISE_COLOR
            )
            self._draw_sensor_card(
                draw, self.center - 120, self.center,
                80, 50, "NOISE", snapshot.noise, "dB",
                Colors.NOISE_COLOR, "🔊"
            )
        
        # PIR 모션 표시 (우하단)
        if snapshot.pir is not None:
            motion_color = Colors.MOTION_COLOR if snapshot.pir else Colors.TEXT_MUTED
            motion_text = "Motion" if snapshot.pir else "Clear"
            motion_icon = "👁" if snapshot.pir else "😴"
            
            # 모션 감지 시 펄스 효과
            if snapshot.pir:
                pulse = abs(math.sin(self.animation_time * 5))
                for i in range(3):
                    alpha = int(30 * (1 - i/3) * pulse)
                    draw.ellipse(
                        [self.center + 80 - 30 - i*5, self.center + 60 - 30 - i*5,
                         self.center + 80 + 30 + i*5, self.center + 60 + 30 + i*5],
                        fill=motion_color[:3] + (alpha,)
                    )
            
            self._draw_text(draw, motion_icon, (self.center + 80, self.center + 60),
                           self.font_medium, motion_color, "mm")
            self._draw_text(draw, motion_text, (self.center + 80, self.center + 80),
                           self.font_micro, Colors.TEXT_SECONDARY, "mm")

    def _get_pm_quality(self, pm25: float) -> Dict[str, Any]:
        """PM2.5 공기질 상태"""
        if pm25 <= 15:
            return {"status": "Good", "color": Colors.SUCCESS, "icon": "😊"}
        elif pm25 <= 35:
            return {"status": "Moderate", "color": Colors.WARNING, "icon": "😐"}
        elif pm25 <= 75:
            return {"status": "Poor", "color": Colors.DANGER, "icon": "😷"}
        else:
            return {"status": "Hazardous", "color": (150, 50, 50), "icon": "☠"}

    def render(self, snapshot: SensorSnapshot) -> Image.Image:
        """메인 렌더링"""
        # 애니메이션 시간 업데이트
        self.animation_time = time.time()
        
        # 배경 이미지 생성
        img = Image.new("RGB", (self.diameter, self.diameter), Colors.BG_TOP)
        draw = ImageDraw.Draw(img, "RGBA")
        
        # 그라디언트 배경
        self._draw_gradient_background(draw, img)
        
        # 원형 마스크 적용
        mask = Image.new("L", (self.diameter, self.diameter), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, self.diameter, self.diameter), fill=255)
        
        # 검은색 배경에 마스크 적용
        background = Image.new("RGB", (self.diameter, self.diameter), (0, 0, 0))
        background.paste(img, mask=mask)
        img = background
        
        # 새로운 드로우 객체 생성 (RGBA 지원)
        draw = ImageDraw.Draw(img, "RGBA")
        
        # 데이터 유무에 따른 렌더링
        if not snapshot.has_payload():
            self._draw_waiting_state(draw)
        else:
            # 센서 링 표시
            self._draw_sensor_ring(draw, snapshot)
            
            # 중앙 디스플레이
            self._draw_center_display(draw, snapshot)
        
        # 외곽 원 테두리 (subtle)
        draw.ellipse(
            (2, 2, self.diameter - 2, self.diameter - 2),
            outline=(60, 70, 90, 100), width=1
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="모던한 원형 센서 디스플레이")
    parser.add_argument("--diameter", type=int, default=settings.diameter_pixels, help="디스플레이 지름(px)")
    parser.add_argument("--font", type=str, default=settings.font_path, help="TTF 폰트 경로")
    parser.add_argument(
        "--refresh-hz",
        type=float,
        default=settings.display_refresh_hz,
        help="화면 갱신 주기(Hz)",
    )
    parser.add_argument(
        "--frame-dump",
        type=str,
        default=None,
        help="프레임 이미지를 저장할 디렉터리(테스트용)",
    )
    parser.add_argument("--debug", action="store_true", help="디버그 로그 출력")
    return parser


def main() -> None:
    if KafkaConsumer is None:
        raise SystemExit(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
    if Image is None or ImageDraw is None or ImageFont is None:
        raise SystemExit(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")

    parser = build_arg_parser()
    args = parser.parse_args()

    print(f"[Main] 모던 센서 디스플레이 시작")
    print(f"[Main] Kafka 설정: {settings.bootstrap_servers} / {settings.sensor_topic}")

    refresh_hz = args.refresh_hz if args.refresh_hz > 0 else 1.0
    refresh_period = 1.0 / refresh_hz

    dump_dir = Path(args.frame_dump) if args.frame_dump else None
    display = ModernCircularDisplay(
        diameter=args.diameter,
        font_path=args.font,
        dump_dir=dump_dir,
    )

    out_queue: queue.Queue[SensorSnapshot] = queue.Queue(maxsize=16)
    stream = KafkaSensorStream(out_queue, debug=args.debug)
    print("[Main] Kafka 스트림 시작...")
    stream.start()

    latest = SensorSnapshot()
    next_frame = time.time()

    try:
        while True:
            timeout = max(0.0, next_frame - time.time())
            try:
                snapshot = out_queue.get(timeout=timeout if timeout > 0 else 0.01)
                latest = snapshot
                if args.debug:
                    print(f"[Main] 업데이트: device={snapshot.device_id} temp={snapshot.temp_c} hum={snapshot.hum}")
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