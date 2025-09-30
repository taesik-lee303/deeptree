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
        # 다크 그라디언트 배경
        img = Image.new("RGB", (self.diameter, self.diameter), color=(12, 15, 25))
        draw = ImageDraw.Draw(img)

        # 외곽 글로우 효과
        outer_margin = 8
        for i in range(3):
            glow_margin = outer_margin - i * 2
            alpha = 40 - i * 10
            glow_color = (20 + i * 15, 35 + i * 20, 60 + i * 25)
            draw.ellipse(
                (
                    glow_margin,
                    glow_margin,
                    self.diameter - glow_margin,
                    self.diameter - glow_margin,
                ),
                fill=glow_color,
                outline=None,
            )

        # 메인 배경 원
        main_margin = outer_margin + 12
        draw.ellipse(
            (
                main_margin,
                main_margin,
                self.diameter - main_margin,
                self.diameter - main_margin,
            ),
            fill=(18, 22, 35),
            outline=(45, 60, 85),
            width=2,
        )

        # 내부 그라디언트 원
        inner_margin = main_margin + 15
        draw.ellipse(
            (
                inner_margin,
                inner_margin,
                self.diameter - inner_margin,
                self.diameter - inner_margin,
            ),
            fill=(22, 28, 42),
            outline=None,
        )

        if not snapshot.has_payload():
            self._draw_waiting(draw)
            return img

        self._draw_metric_rings(draw, snapshot)
        self._draw_center_text(draw, snapshot)
        self._draw_footer(draw, snapshot)
        return img

    def _draw_waiting(self, draw: ImageDraw.ImageDraw) -> None:
        # 펄스 애니메이션을 위한 점들
        import time
        pulse = int((time.time() * 2) % 3)
        dots = "." * (pulse + 1) + " " * (2 - pulse)

        self._draw_text(draw, f"Waiting for data{dots}", (self.center, self.center - 15), self.font_medium, (180, 200, 240))
        self._draw_text(draw, "Kafka stream connecting", (self.center, self.center + 25), self.font_small, (120, 150, 200))

        # 로딩 원
        loading_radius = 35
        loading_bbox = (
            self.center - loading_radius,
            self.center - loading_radius + 80,
            self.center + loading_radius,
            self.center + loading_radius + 80,
        )
        angle_offset = int(time.time() * 180) % 360
        draw.arc(loading_bbox, start=angle_offset, end=angle_offset + 60, width=3, fill=(100, 150, 255))

    def _draw_metric_rings(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        ring_thickness = 20
        gap = 8
        max_radius = self.diameter / 2.0 - 35

        # 개선된 색상 및 그라디언트 효과
        specs = [
            ("TEMP", snapshot.temp_c, (0.0, 40.0), (255, 107, 107), "°C"),  # 따뜻한 빨강
            ("HUM", snapshot.hum, (0.0, 100.0), (74, 144, 226), "%"),       # 시원한 파랑
            ("PM2.5", snapshot.pm25, (0.0, 150.0), (168, 85, 247), "μg"),   # 보라색
        ]

        for idx, (label, value, value_range, color, unit) in enumerate(specs):
            radius = max_radius - idx * (ring_thickness + gap)
            if radius <= ring_thickness / 2:
                continue

            bbox = (
                self.center - radius,
                self.center - radius,
                self.center + radius,
                self.center + radius,
            )

            # 배경 링 (더 어둡고 투명한 효과)
            base_color = tuple(max(15, int(c * 0.25)) for c in color)
            draw.arc(bbox, start=135, end=405, width=ring_thickness, fill=base_color)

            # 값에 따른 색상 강도 조절
            ratio = _clamp_ratio(value, value_range)
            if ratio > 0:
                # 그라디언트 효과를 위한 다중 링
                for i in range(3):
                    thickness = ring_thickness - i * 2
                    intensity = 1.0 - i * 0.2
                    ring_color = tuple(int(c * intensity) for c in color)
                    inner_bbox = (
                        self.center - radius + i,
                        self.center - radius + i,
                        self.center + radius - i,
                        self.center + radius - i,
                    )
                    draw.arc(inner_bbox, start=135, end=135 + 270 * ratio, width=thickness, fill=ring_color)

            # 라벨과 값 표시 개선
            label_y = self.center - radius + ring_thickness / 2.0
            value_text = f"{value:.1f}{unit}" if value is not None else "--"

            # 라벨 배경
            label_bbox = (
                self.center - 30, label_y - 8,
                self.center + 30, label_y + 8
            )
            draw.rounded_rectangle(label_bbox, radius=8, fill=(0, 0, 0, 100))

            self._draw_text(draw, label, (self.center - 15, label_y), self.font_tiny, color, align="center")
            self._draw_text(draw, value_text, (self.center + 15, label_y), self.font_tiny, (255, 255, 255), align="center")

    def _draw_center_text(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        header = snapshot.device_id or "IoT SENSOR HUB"
        age = max(0.0, time.time() - snapshot.ingested_at)
        time_text = _format_time(snapshot.ts, snapshot.ingested_at)
        age_text = _format_age(age)

        # 헤더 배경
        header_y = self.diameter * 0.18
        header_bbox = (
            self.center - 80, header_y - 12,
            self.center + 80, header_y + 12
        )
        draw.rounded_rectangle(header_bbox, radius=12, fill=(30, 40, 60, 150))

        self._draw_text(draw, header, (self.center, header_y), self.font_small, (200, 220, 255))
        self._draw_text(draw, time_text, (self.center, self.diameter * 0.28), self.font_tiny, (150, 170, 200))

        # Age 표시를 더 눈에 띄게
        age_color = (100, 200, 100) if age < 5 else (255, 200, 100) if age < 30 else (255, 150, 150)
        self._draw_text(draw, age_text, (self.diameter * 0.85, self.diameter * 0.28), self.font_tiny, age_color, align="right")

        # 메인 값 표시
        if snapshot.temp_c is not None:
            main_text = f"{snapshot.temp_c:0.1f}°"
            main_color = (255, 120, 120)
            unit_text = "C"
        elif snapshot.hum is not None:
            main_text = f"{snapshot.hum:0.0f}"
            main_color = (120, 180, 255)
            unit_text = "%RH"
        else:
            main_text = "--"
            main_color = (160, 170, 190)
            unit_text = ""

        # 메인 값에 글로우 효과
        for offset in [(2, 2), (1, 1), (0, 0)]:
            glow_color = tuple(int(c * (0.3 + 0.35 * (2 - offset[0]))) for c in main_color)
            self._draw_text(draw, main_text, (self.center + offset[0], self.center - 10 + offset[1]), self.font_big, glow_color)

        if unit_text:
            self._draw_text(draw, unit_text, (self.center + 50, self.center - 25), self.font_medium, main_color)

        # 보조 정보
        secondary_parts = []
        if snapshot.hum is not None and snapshot.temp_c is not None:
            secondary_parts.append(f"RH {snapshot.hum:0.0f}%")
        if snapshot.noise is not None:
            secondary_parts.append(f"🔊 {snapshot.noise:0.0f}dB")
        if not secondary_parts:
            secondary_parts.append("⚡ Live Data")

        secondary_text = " • ".join(secondary_parts)
        self._draw_text(draw, secondary_text, (self.center, self.center + 50), self.font_small, (180, 200, 230))

    def _draw_footer(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        # PM 데이터를 더 세련되게 표시
        pm_parts = []
        pm_colors = [(255, 180, 100), (255, 140, 140), (255, 100, 180)]  # 그라디언트 색상

        if snapshot.pm1 is not None:
            pm_parts.append((f"PM1.0 {snapshot.pm1:0.0f}μg", pm_colors[0]))
        if snapshot.pm25 is not None:
            pm_parts.append((f"PM2.5 {snapshot.pm25:0.0f}μg", pm_colors[1]))
        if snapshot.pm10 is not None:
            pm_parts.append((f"PM10 {snapshot.pm10:0.0f}μg", pm_colors[2]))

        if pm_parts:
            pm_y = self.diameter * 0.75
            total_width = sum(len(text) for text, _ in pm_parts) * 6 + (len(pm_parts) - 1) * 20
            start_x = self.center - total_width / 2

            for i, (text, color) in enumerate(pm_parts):
                if i > 0:
                    start_x += 20  # 간격

                # 배경 박스
                text_width = len(text) * 6
                bbox = (start_x - 5, pm_y - 10, start_x + text_width + 5, pm_y + 10)
                draw.rounded_rectangle(bbox, radius=8, fill=(*color, 50))

                self._draw_text(draw, text, (start_x + text_width/2, pm_y), self.font_tiny, color)
                start_x += text_width
        else:
            self._draw_text(draw, "🌪️ Air Quality Monitoring", (self.center, self.diameter * 0.75), self.font_small, (150, 180, 220))

        # PIR 센서 상태를 더 현대적으로
        pir_text: str
        pir_color: tuple[int, int, int]
        pir_icon: str

        if snapshot.pir is None:
            pir_text = "PIR OFFLINE"
            pir_color = (120, 130, 150)
            pir_icon = "⚪"
        elif snapshot.pir:
            pir_text = "MOTION DETECTED"
            pir_color = (255, 100, 100)
            pir_icon = "🔴"
        else:
            pir_text = "AREA CLEAR"
            pir_color = (100, 255, 150)
            pir_icon = "🟢"

        # PIR 상태 박스를 더 세련되게
        pad_x = 90
        pad_y = self.diameter * 0.88

        # 그림자 효과
        shadow_box = (
            self.center - pad_x + 2,
            pad_y - 16 + 2,
            self.center + pad_x + 2,
            pad_y + 16 + 2,
        )
        draw.rounded_rectangle(shadow_box, radius=16, fill=(0, 0, 0, 80))

        # 메인 박스
        main_box = (
            self.center - pad_x,
            pad_y - 16,
            self.center + pad_x,
            pad_y + 16,
        )

        # 그라디언트 효과를 위한 다중 박스
        for i in range(3):
            inner_box = (
                self.center - pad_x + i,
                pad_y - 16 + i,
                self.center + pad_x - i,
                pad_y + 16 - i,
            )
            alpha = 1.0 - i * 0.3
            box_color = tuple(int(c * alpha) for c in pir_color)
            draw.rounded_rectangle(inner_box, radius=16-i, fill=box_color)

        # 아이콘과 텍스트
        self._draw_text(draw, pir_icon, (self.center - 40, pad_y), self.font_medium, (255, 255, 255))
        self._draw_text(draw, pir_text, (self.center + 10, pad_y), self.font_small, (255, 255, 255))

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
