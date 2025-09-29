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


class CircularSensorDisplay:
    def __init__(
        self,
        *,
        diameter: int,
        font_path: str | None = None,
        dump_dir: Path | None = None,
        driver: Any | None = None,
    ) -> None:
        if Image is None or ImageDraw is None or ImageFont is None:
            raise RuntimeError(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")
        self.diameter = diameter
        self.center = diameter / 2.0
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
        img = Image.new("RGB", (self.diameter, self.diameter), color=(6, 10, 18))
        draw = ImageDraw.Draw(img)

        # 외곽 배경
        outer_margin = 6
        draw.ellipse(
            (
                outer_margin,
                outer_margin,
                self.diameter - outer_margin,
                self.diameter - outer_margin,
            ),
            fill=(16, 24, 42),
            outline=(70, 90, 140),
            width=4,
        )
        inner_margin = outer_margin + 18
        draw.ellipse(
            (
                inner_margin,
                inner_margin,
                self.diameter - inner_margin,
                self.diameter - inner_margin,
            ),
            fill=(8, 12, 24),
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
        self._draw_text(draw, "Waiting for data", (self.center, self.center - 10), self.font_medium, (150, 160, 190))
        self._draw_text(draw, "Kafka stream idle", (self.center, self.center + 40), self.font_small, (110, 130, 170))

    def _draw_metric_rings(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        ring_thickness = 18
        gap = 6
        max_radius = self.diameter / 2.0 - 22
        specs = [
            ("TEMP", snapshot.temp_c, (0.0, 40.0), (244, 138, 109)),
            ("HUM", snapshot.hum, (0.0, 100.0), (120, 200, 255)),
            ("PM2.5", snapshot.pm25, (0.0, 150.0), (186, 160, 255)),
        ]
        for idx, (label, value, value_range, color) in enumerate(specs):
            radius = max_radius - idx * (ring_thickness + gap)
            if radius <= ring_thickness / 2:
                continue
            bbox = (
                self.center - radius,
                self.center - radius,
                self.center + radius,
                self.center + radius,
            )
            base_color = tuple(max(30, int(c * 0.35)) for c in color)
            draw.arc(bbox, start=135, end=405, width=ring_thickness, fill=base_color)
            ratio = _clamp_ratio(value, value_range)
            if ratio > 0:
                draw.arc(bbox, start=135, end=135 + 270 * ratio, width=ring_thickness, fill=color)
            label_y = self.center - radius + ring_thickness / 2.0
            self._draw_text(draw, label, (self.center, label_y), self.font_tiny, color, align="center")

    def _draw_center_text(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        header = snapshot.device_id or "UART SENSOR"
        age = max(0.0, time.time() - snapshot.ingested_at)
        time_text = _format_time(snapshot.ts, snapshot.ingested_at)
        age_text = _format_age(age)

        self._draw_text(draw, header, (self.center, self.diameter * 0.18), self.font_small, (180, 200, 255))
        self._draw_text(draw, time_text, (self.center, self.diameter * 0.26), self.font_tiny, (120, 150, 200))
        self._draw_text(draw, age_text, (self.diameter * 0.82, self.diameter * 0.26), self.font_tiny, (140, 160, 210), align="right")

        if snapshot.temp_c is not None:
            main_text = f"{snapshot.temp_c:0.1f}°C"
            main_color = (255, 190, 120)
        elif snapshot.hum is not None:
            main_text = f"RH {snapshot.hum:0.0f}%"
            main_color = (120, 200, 255)
        else:
            main_text = "--"
            main_color = (160, 170, 190)
        self._draw_text(draw, main_text, (self.center, self.center - 10), self.font_big, main_color)

        secondary_parts = []
        if snapshot.hum is not None:
            secondary_parts.append(f"RH {snapshot.hum:0.0f}%")
        if snapshot.noise is not None:
            secondary_parts.append(f"Noise {snapshot.noise:0.0f}dB")
        if not secondary_parts:
            secondary_parts.append("No secondary metrics")
        self._draw_text(draw, " | ".join(secondary_parts), (self.center, self.center + 70), self.font_small, (150, 170, 210))

    def _draw_footer(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        pm_parts = []
        if snapshot.pm1 is not None:
            pm_parts.append(f"PM1 {snapshot.pm1:0.0f}")
        if snapshot.pm25 is not None:
            pm_parts.append(f"PM2.5 {snapshot.pm25:0.0f}")
        if snapshot.pm10 is not None:
            pm_parts.append(f"PM10 {snapshot.pm10:0.0f}")
        pm_text = " | ".join(pm_parts) if pm_parts else "PM data --"
        self._draw_text(draw, pm_text, (self.center, self.diameter * 0.78), self.font_small, (130, 160, 210))

        pir_text: str
        pir_color: tuple[int, int, int]
        if snapshot.pir is None:
            pir_text = "PIR --"
            pir_color = (120, 130, 150)
        elif snapshot.pir:
            pir_text = "MOTION"
            pir_color = (255, 110, 110)
        else:
            pir_text = "IDLE"
            pir_color = (110, 190, 140)
        pad_x = 80
        pad_y = self.diameter * 0.86
        box = (
            self.center - pad_x,
            pad_y - 24,
            self.center + pad_x,
            pad_y + 24,
        )
        draw.rounded_rectangle(box, radius=24, fill=(pir_color[0], pir_color[1], pir_color[2],), outline=None)
        self._draw_text(draw, pir_text, (self.center, pad_y), self.font_small, (12, 16, 22))

    def present(self, image: Image.Image) -> None:
        if self.driver is not None:
            if hasattr(self.driver, "display"):
                self.driver.display(image)
            elif hasattr(self.driver, "image"):
                self.driver.image(image)
        if self.dump_dir:
            frame_path = self.dump_dir / f"frame_{self.frame_index:06d}.png"
            image.save(frame_path)
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

    refresh_hz = args.refresh_hz if args.refresh_hz > 0 else 1.0
    refresh_period = 1.0 / refresh_hz

    dump_dir = Path(args.frame_dump) if args.frame_dump else None
    display = CircularSensorDisplay(
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
                if args.debug:
                    print(
                        f"[Kafka] 업데이트: device={snapshot.device_id} "
                        f"temp={snapshot.temp_c} hum={snapshot.hum} noise={snapshot.noise}"
                    )
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
