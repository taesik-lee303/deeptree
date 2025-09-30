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
from typing import Any, Dict, Iterable, Optional

try:
    from kafka import KafkaConsumer
except Exception as exc:  # pragma: no cover
    KafkaConsumer = None  # type: ignore
    _KAFKA_IMPORT_ERROR = exc
else:
    _KAFKA_IMPORT_ERROR = None

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore
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


def _clamp_ratio(value: Optional[float], value_range: tuple[float, float]) -> float:
    if value is None:
        return 0.0
    low, high = value_range
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _format_time(ts: Optional[float], fallback: float) -> str:
    base_ts = ts if ts is not None else fallback
    try:
        dt = datetime.fromtimestamp(base_ts, tz=timezone.utc).astimezone()
    except (OSError, OverflowError, ValueError):
        return "--:--:--"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_age(age_seconds: float) -> str:
    if age_seconds < 60:
        return f"+{age_seconds:0.1f}s"
    minutes = int(age_seconds // 60)
    seconds = int(age_seconds % 60)
    return f"+{minutes}m{seconds:02d}s"


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


class CircularSensorDisplay:
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

        # 드라이버가 제공되지 않고 use_tkinter가 True면 Tkinter 드라이버 생성
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
        self.font_big = self._load_font(font_path, 96)
        self.font_medium = self._load_font(font_path, 48)
        self.font_small = self._load_font(font_path, 30)
        self.font_tiny = self._load_font(font_path, 22)

    def _load_font(self, font_path: str | None, size: int) -> ImageFont.ImageFont:
        candidates = []
        if font_path:
            candidates.append(Path(font_path))
        candidates.extend(
            Path(p)
            for p in (
                "C:/Windows/Fonts/malgun.ttf",
                "C:/Windows/Fonts/seguiemj.ttf",
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

    @staticmethod
    def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
        if hasattr(draw, "textbbox"):
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return int(right - left), int(bottom - top)
        return draw.textsize(text, font=font)

    def _draw_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        xy: tuple[float, float],
        font: ImageFont.ImageFont,
        fill: tuple[int, int, int],
        align: str = "center",
    ) -> None:
        width, height = self._text_size(draw, text, font)
        if align == "center":
            pos = (xy[0] - width / 2.0, xy[1] - height / 2.0)
        elif align == "right":
            pos = (xy[0] - width, xy[1] - height / 2.0)
        else:  # left
            pos = (xy[0], xy[1] - height / 2.0)
        draw.text(pos, text, font=font, fill=fill)

    def render(self, snapshot: SensorSnapshot) -> Image.Image:
        # 자연 풍경 배경 - 하늘 그라디언트
        img = Image.new("RGB", (self.diameter, self.diameter), color=(135, 206, 235))
        draw = ImageDraw.Draw(img)

        # 하늘 그라디언트 (위쪽 파랑 -> 아래쪽 연한 하늘색)
        for y in range(self.diameter):
            progress = y / self.diameter
            # 위쪽: 진한 하늘색, 아래쪽: 연한 하늘색
            r = int(135 + progress * (220 - 135))
            g = int(206 + progress * (240 - 206))
            b = int(235 + progress * (250 - 235))
            draw.line([(0, y), (self.diameter, y)], fill=(r, g, b))

        # 원형 마스크
        mask = Image.new("L", (self.diameter, self.diameter), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, self.diameter, self.diameter), fill=255)

        # 마스크 적용을 위한 배경 이미지
        background = Image.new("RGB", (self.diameter, self.diameter), (255, 255, 255))
        background.paste(img, mask=mask)
        img = background

        draw = ImageDraw.Draw(img)

        if not snapshot.has_payload():
            self._draw_waiting_nature(draw)
            return img

        self._draw_natural_landscape(draw, snapshot)
        return img

    def _draw_waiting_nature(self, draw: ImageDraw.ImageDraw) -> None:
        # 기본 구름들
        self._draw_cloud(draw, self.center - 80, self.diameter * 0.3, 40, (255, 255, 255))
        self._draw_cloud(draw, self.center + 60, self.diameter * 0.25, 35, (255, 255, 255))

        # 기본 풀밭
        self._draw_grass(draw, wind_strength=0)

        # 연결 메시지
        self._draw_text(draw, "🌱 Connecting to nature...", (self.center, self.center), self.font_medium, (50, 120, 50))

    def _draw_natural_landscape(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        # 구름 (미세먼지 농도에 따라 색상 변화)
        cloud_color = self._get_cloud_color(snapshot.pm25)
        self._draw_cloud(draw, self.center - 80, self.diameter * 0.25, 45, cloud_color)
        self._draw_cloud(draw, self.center + 70, self.diameter * 0.2, 35, cloud_color)

        # 태양 (온도 표시)
        if snapshot.temp_c is not None:
            self._draw_sun(draw, snapshot.temp_c)

        # 물방울들 (습도 표시)
        if snapshot.hum is not None:
            self._draw_humidity_drops(draw, snapshot.hum)

        # 풀밭 (PIR 감지 시 흔들림)
        wind_strength = 3 if snapshot.pir else 0
        self._draw_grass(draw, wind_strength)

        # 중앙 정보 패널
        self._draw_info_panel(draw, snapshot)

    def _get_cloud_color(self, pm25: float | None) -> tuple[int, int, int]:
        if pm25 is None:
            return (255, 255, 255)  # 기본 하얀 구름

        # PM2.5 농도에 따라 구름 색상 변화 (0-150 범위)
        intensity = min(pm25 / 150.0, 1.0)  # 0-1 사이로 정규화

        # 하얀색(255,255,255)에서 회색(120,120,120)으로 변화
        r = int(255 - intensity * 135)
        g = int(255 - intensity * 135)
        b = int(255 - intensity * 135)

        return (r, g, b)

    def _draw_cloud(self, draw: ImageDraw.ImageDraw, x: float, y: float, size: int, color: tuple[int, int, int]) -> None:
        # 구름을 여러 원으로 그리기
        cloud_parts = [
            (x - size//3, y, size//2),
            (x + size//3, y, size//2),
            (x, y - size//4, size//3),
            (x - size//6, y + size//6, size//4),
            (x + size//6, y + size//6, size//4),
        ]

        for cx, cy, radius in cloud_parts:
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=color
            )

    def _draw_grass(self, draw: ImageDraw.ImageDraw, wind_strength: int = 0) -> None:
        # 풀밭을 원의 아래쪽 1/3에 그리기
        grass_start_y = self.diameter * 0.65
        grass_height = self.diameter - grass_start_y

        # 풀밭 배경
        for y in range(int(grass_start_y), self.diameter):
            # 원형 마스크 내에서만 그리기
            radius_at_y = math.sqrt((self.center ** 2) - ((y - self.center) ** 2))
            if radius_at_y > 0:
                x_start = int(self.center - radius_at_y)
                x_end = int(self.center + radius_at_y)

                # 그라디언트 풀색 (위쪽 연한 초록 -> 아래쪽 진한 초록)
                progress = (y - grass_start_y) / grass_height
                r = int(50 + progress * 20)
                g = int(150 + progress * 50)
                b = int(50 + progress * 20)

                draw.line([(x_start, y), (x_end, y)], fill=(r, g, b))

        # 풀잎들 그리기
        num_grass = 30
        for i in range(num_grass):
            # 풀 위치
            angle = (i / num_grass) * 2 * math.pi
            distance = self.center * 0.4 + (i % 3) * 20  # 다양한 거리

            base_x = self.center + distance * math.cos(angle)
            base_y = self.center + distance * math.sin(angle)

            # 원형 영역 내에서만 풀 그리기
            if (base_x - self.center) ** 2 + (base_y - self.center) ** 2 <= (self.center - 10) ** 2:
                if base_y >= grass_start_y:  # 풀밭 영역에서만
                    # 바람 효과 (PIR 감지 시)
                    wind_offset = 0
                    if wind_strength > 0:
                        wind_time = time.time() * 3  # 빠른 애니메이션
                        wind_offset = math.sin(wind_time + i * 0.5) * wind_strength

                    # 풀잎 그리기
                    grass_height = 15 + (i % 8)
                    top_x = base_x + wind_offset
                    top_y = base_y - grass_height

                    # 풀잎 색상 (랜덤하게 조금씩 다르게)
                    shade = i % 3
                    grass_colors = [(60, 180, 60), (70, 190, 70), (50, 170, 50)]
                    grass_color = grass_colors[shade]

                    draw.line([(base_x, base_y), (top_x, top_y)], fill=grass_color, width=2)

    def _draw_sun(self, draw: ImageDraw.ImageDraw, temperature: float) -> None:
        # 태양 위치 (우상단)
        sun_x = self.center + self.diameter * 0.25
        sun_y = self.diameter * 0.25

        # 온도에 따른 태양 크기와 색상
        temp_ratio = min(max(temperature / 40.0, 0), 1)  # 0-40도를 0-1로 정규화

        # 태양 크기 (온도가 높을수록 크게)
        sun_radius = 20 + temp_ratio * 15

        # 태양 색상 (시원한 노랑 -> 뜨거운 주황)
        r = int(255)
        g = int(255 - temp_ratio * 100)  # 온도가 높으면 주황색으로
        b = int(100 - temp_ratio * 100)

        # 태양 그리기
        draw.ellipse(
            (sun_x - sun_radius, sun_y - sun_radius, sun_x + sun_radius, sun_y + sun_radius),
            fill=(r, g, b)
        )

        # 태양 광선들
        for i in range(8):
            angle = i * math.pi / 4
            ray_length = sun_radius + 10
            end_x = sun_x + ray_length * math.cos(angle)
            end_y = sun_y + ray_length * math.sin(angle)

            draw.line([(sun_x, sun_y), (end_x, end_y)], fill=(r, g, b), width=2)

        # 온도 텍스트
        temp_text = f"{temperature:.1f}°C"
        self._draw_text(draw, temp_text, (sun_x, sun_y + sun_radius + 20), self.font_tiny, (r, g, b))

    def _draw_humidity_drops(self, draw: ImageDraw.ImageDraw, humidity: float) -> None:
        # 습도에 따라 물방울 개수 결정
        num_drops = int(humidity / 20)  # 0-100% -> 0-5개 물방울

        for i in range(num_drops):
            # 물방울 위치 (왼쪽 상단 영역에 분산)
            drop_x = self.center - 60 + (i % 3) * 30
            drop_y = self.diameter * 0.35 + (i % 2) * 20

            # 물방울 모양 (작은 타원)
            drop_size = 4
            draw.ellipse(
                (drop_x - drop_size, drop_y - drop_size*1.5, drop_x + drop_size, drop_y + drop_size),
                fill=(100, 150, 255)
            )

        # 습도 텍스트 (좌상단)
        humidity_text = f"💧 {humidity:.0f}%"
        self._draw_text(draw, humidity_text, (self.diameter * 0.2, self.diameter * 0.15), self.font_tiny, (100, 150, 255))

    def _draw_info_panel(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        # 중앙 정보 패널 (반투명 배경)
        panel_width = 100
        panel_height = 60
        panel_x = self.center - panel_width // 2
        panel_y = self.center - panel_height // 2

        # 반투명 배경
        overlay = Image.new("RGBA", (panel_width, panel_height), (255, 255, 255, 180))
        temp_img = Image.new("RGBA", (self.diameter, self.diameter), (0, 0, 0, 0))
        temp_img.paste(overlay, (panel_x, panel_y))

        # 패널 테두리
        draw.rounded_rectangle(
            (panel_x, panel_y, panel_x + panel_width, panel_y + panel_height),
            radius=15,
            outline=(150, 150, 150),
            width=2
        )

        # 장치 이름
        device_name = snapshot.device_id or "🏡 Home"
        self._draw_text(draw, device_name, (self.center, self.center - 20), self.font_small, (70, 70, 70))

        # 현재 시간 표시
        current_time = time.strftime("%H:%M")
        self._draw_text(draw, current_time, (self.center, self.center), self.font_medium, (50, 50, 50))

        # 데이터 상태
        age = time.time() - snapshot.ingested_at
        if age < 5:
            status = "🟢 LIVE"
        elif age < 30:
            status = "🟡 RECENT"
        else:
            status = "🔴 STALE"

        self._draw_text(draw, status, (self.center, self.center + 20), self.font_tiny, (80, 80, 80))

    def _draw_data_cards(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        # 카드 형태로 데이터 표시
        card_width = 80
        card_height = 50
        card_spacing = 20

        # 센서 데이터와 색상 정의
        sensors = [
            ("TEMP", snapshot.temp_c, "°C", (255, 100, 100)),  # 따뜻한 빨강
            ("HUMIDITY", snapshot.hum, "%", (100, 180, 255)),   # 시원한 파랑
            ("PM2.5", snapshot.pm25, "μg", (150, 100, 255)),    # 보라색
        ]

        # 카드들을 원형으로 배치
        import math
        total_cards = len([s for s in sensors if s[1] is not None])
        if total_cards == 0:
            return

        radius = self.diameter * 0.28
        angle_step = 2 * math.pi / max(3, total_cards)

        for i, (label, value, unit, color) in enumerate(sensors):
            if value is None:
                continue

            # 카드 위치 계산
            angle = i * angle_step - math.pi / 2  # -90도부터 시작
            x = self.center + radius * math.cos(angle)
            y = self.center + radius * math.sin(angle)

            # 카드 배경 (둥근 모서리)
            card_rect = (
                x - card_width // 2,
                y - card_height // 2,
                x + card_width // 2,
                y + card_height // 2,
            )

            # 그림자 효과
            shadow_rect = (
                card_rect[0] + 2,
                card_rect[1] + 2,
                card_rect[2] + 2,
                card_rect[3] + 2,
            )
            draw.rounded_rectangle(shadow_rect, radius=8, fill=(200, 200, 200, 100))

            # 메인 카드
            draw.rounded_rectangle(card_rect, radius=8, fill=(255, 255, 255))
            draw.rounded_rectangle(card_rect, radius=8, outline=color, width=2)

            # 값 표시
            value_text = f"{value:.1f}"
            self._draw_text(draw, value_text, (x, y - 8), self.font_medium, color)
            self._draw_text(draw, f"{label}", (x, y + 8), self.font_tiny, (80, 80, 80))
            self._draw_text(draw, unit, (x + 25, y - 8), self.font_tiny, color)

    def _draw_center_display(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        # 중앙 메인 정보 영역
        center_bg = (
            self.center - 60,
            self.center - 40,
            self.center + 60,
            self.center + 40,
        )

        # 중앙 배경 카드
        draw.rounded_rectangle(center_bg, radius=20, fill=(255, 255, 255, 220))
        draw.rounded_rectangle(center_bg, radius=20, outline=(150, 180, 220), width=2)

        # 장치 이름
        device_name = snapshot.device_id or "🏠 Smart Sensor"
        self._draw_text(draw, device_name, (self.center, self.center - 25), self.font_small, (60, 80, 120))

        # 메인 표시값 결정
        if snapshot.temp_c is not None:
            main_value = f"{snapshot.temp_c:.1f}°"
            main_color = (255, 100, 100)
        elif snapshot.hum is not None:
            main_value = f"{snapshot.hum:.0f}%"
            main_color = (100, 180, 255)
        else:
            main_value = "---"
            main_color = (150, 150, 150)

        self._draw_text(draw, main_value, (self.center, self.center + 5), self.font_big, main_color)

        # 상태 표시
        age = time.time() - snapshot.ingested_at
        if age < 5:
            status = "🟢 LIVE"
            status_color = (50, 200, 50)
        elif age < 30:
            status = "🟡 RECENT"
            status_color = (255, 180, 50)
        else:
            status = "🔴 OLD"
            status_color = (255, 100, 100)

        self._draw_text(draw, status, (self.center, self.center + 25), self.font_tiny, status_color)

        # 하단 추가 정보
        if snapshot.noise is not None:
            noise_y = self.diameter * 0.85
            noise_text = f"🔊 Noise: {snapshot.noise:.0f}dB"
            self._draw_text(draw, noise_text, (self.center, noise_y), self.font_small, (120, 100, 200))

        # PIR 상태 (우하단)
        if snapshot.pir is not None:
            pir_x = self.diameter * 0.8
            pir_y = self.diameter * 0.9

            if snapshot.pir:
                pir_icon = "👁️"
                pir_color = (255, 100, 100)
            else:
                pir_icon = "😴"
                pir_color = (100, 200, 100)

            self._draw_text(draw, pir_icon, (pir_x, pir_y), self.font_medium, pir_color)

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
                consumer_timeout_ms=1000,  # 연결 타임아웃 추가
                **settings.kafka_kwargs,
            )
            print(f"[Kafka] 소비자 생성 완료")
            consumer.subscribe([settings.sensor_topic])
            print(f"[Kafka] 토픽 구독 완료: {settings.sensor_topic}")
            if self.debug:
                print(f"[Kafka] 토픽 구독: {settings.sensor_topic}")
        except Exception as exc:
            print(f"[Kafka] 소비자 초기화 실패: {exc}")
            return

        while not self._stop_evt.is_set():
            try:
                print("[Kafka] Polling for messages...")
                records = consumer.poll(timeout_ms=500)
                if records:
                    print(f"[Kafka] Received {sum(len(msgs) for msgs in records.values())} messages")
            except Exception as exc:
                print(f"[Kafka] poll 실패: {exc}")
                time.sleep(1.0)
                continue
            if not records:
                print("[Kafka] No messages received, continuing...")
                continue
            for messages in records.values():
                for message in messages:
                    raw_value = message.value
                    print(f"[Kafka] Processing message: {raw_value[:100]}...")
                    try:
                        payload = json.loads(raw_value)
                        print(f"[Kafka] Parsed payload keys: {list(payload.keys())}")
                    except Exception as exc:
                        if self.debug:
                            print(f"[Kafka] JSON 파싱 실패: {exc} :: {raw_value!r}")
                        continue
                    snapshot = _snapshot_from_payload(payload)
                    if snapshot is None:
                        print(f"[Kafka] 지원하지 않는 페이로드: {payload}")
                        continue
                    print(f"[Kafka] Created snapshot: temp={snapshot.temp_c}, hum={snapshot.hum}")
                    snapshot.raw = payload
                    snapshot.ingested_at = time.time()
                    print("[Kafka] Publishing snapshot to queue...")
                    self._publish(snapshot)
                    print("[Kafka] Snapshot published successfully")
        try:
            consumer.close()
        except Exception:
            pass


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kafka -> 원형 디스플레이 센서 뷰어")
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

    print(f"[Main] 시작 - 디버그 모드: {args.debug}")
    print(f"[Main] Kafka 설정: {settings.bootstrap_servers} / {settings.sensor_topic}")

    refresh_hz = args.refresh_hz if args.refresh_hz > 0 else 1.0
    refresh_period = 1.0 / refresh_hz

    dump_dir = Path(args.frame_dump) if args.frame_dump else None
    display = CircularSensorDisplay(
        diameter=args.diameter,
        font_path=args.font,
        dump_dir=dump_dir,
    )

    out_queue: queue.Queue[SensorSnapshot] = queue.Queue(maxsize=16)
    stream = KafkaSensorStream(out_queue, debug=True)  # 강제로 디버그 활성화
    print("[Main] 카프카 스트림 시작...")
    stream.start()

    latest = SensorSnapshot()
    next_frame = time.time()

    try:
        while True:
            timeout = max(0.0, next_frame - time.time())
            try:
                print("[Main] Waiting for snapshot from queue...")
                snapshot = out_queue.get(timeout=timeout if timeout > 0 else 0.01)
                latest = snapshot
                print(f"[Main] 업데이트: device={snapshot.device_id} temp={snapshot.temp_c} hum={snapshot.hum}")
            except queue.Empty:
                print("[Main] Queue timeout, no new data")
                pass

            now = time.time()
            if now >= next_frame:
                print("[Main] Rendering frame...")
                image = display.render(latest)
                print("[Main] Presenting image...")
                display.present(image)
                next_frame = now + refresh_period
                print("[Main] Frame completed")
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()


if __name__ == "__main__":
    main()
