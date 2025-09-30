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
        # 부드러운 배경
        img = Image.new("RGB", (self.diameter, self.diameter), color=(15, 20, 30))
        draw = ImageDraw.Draw(img)

        # 단순한 외곽 원
        margin = 10
        draw.ellipse(
            (margin, margin, self.diameter - margin, self.diameter - margin),
            fill=(25, 35, 50),
            outline=(60, 80, 120),
            width=3,
        )

        if not snapshot.has_payload():
            self._draw_waiting(draw)
            return img

        self._draw_metric_rings(draw, snapshot)
        self._draw_center_text(draw, snapshot)
        self._draw_footer(draw, snapshot)
        return img

    def _draw_waiting(self, draw: ImageDraw.ImageDraw) -> None:
        self._draw_text(draw, "Waiting for data...", (self.center, self.center - 20), self.font_medium, (160, 180, 220))
        self._draw_text(draw, "Kafka connecting", (self.center, self.center + 20), self.font_small, (120, 140, 180))

    def _draw_metric_rings(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        ring_thickness = 16
        gap = 12
        max_radius = self.diameter / 2.0 - 40

        # 깔끔한 색상
        specs = [
            ("TEMP", snapshot.temp_c, (0.0, 40.0), (220, 120, 120)),
            ("HUM", snapshot.hum, (0.0, 100.0), (120, 160, 220)),
            ("PM2.5", snapshot.pm25, (0.0, 150.0), (160, 120, 220)),
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

            # 배경 링
            base_color = tuple(int(c * 0.3) for c in color)
            draw.arc(bbox, start=135, end=405, width=ring_thickness, fill=base_color)

            # 값 표시 링
            ratio = _clamp_ratio(value, value_range)
            if ratio > 0:
                draw.arc(bbox, start=135, end=135 + 270 * ratio, width=ring_thickness, fill=color)

            # 라벨 (왼쪽에만)
            label_x = self.center - radius - 25
            label_y = self.center
            self._draw_text(draw, label, (label_x, label_y), self.font_tiny, color, align="center")

    def _draw_center_text(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        # 단순한 헤더
        header = snapshot.device_id or "Sensor Monitor"
        self._draw_text(draw, header, (self.center, self.diameter * 0.2), self.font_small, (180, 200, 230))

        # 메인 값 - 깔끔하게
        if snapshot.temp_c is not None:
            main_text = f"{snapshot.temp_c:0.1f}°C"
            main_color = (220, 150, 150)
        elif snapshot.hum is not None:
            main_text = f"{snapshot.hum:0.0f}%"
            main_color = (150, 180, 220)
        else:
            main_text = "No Data"
            main_color = (160, 170, 190)

        self._draw_text(draw, main_text, (self.center, self.center), self.font_big, main_color)

        # 간단한 보조 정보
        info_parts = []
        if snapshot.temp_c is not None and snapshot.hum is not None:
            info_parts.append(f"Humidity: {snapshot.hum:0.0f}%")
        elif snapshot.temp_c is None and snapshot.hum is not None:
            info_parts.append(f"Temperature: {snapshot.temp_c:0.1f}°C" if snapshot.temp_c else "")

        if info_parts:
            self._draw_text(draw, info_parts[0], (self.center, self.center + 40), self.font_small, (150, 170, 190))

    def _draw_footer(self, draw: ImageDraw.ImageDraw, snapshot: SensorSnapshot) -> None:
        # 간단한 하단 정보
        footer_y = self.diameter * 0.8

        # PM 데이터 간단히
        pm_text = ""
        if snapshot.pm25 is not None:
            pm_text = f"PM2.5: {snapshot.pm25:0.0f}μg/m³"
        elif snapshot.pm10 is not None:
            pm_text = f"PM10: {snapshot.pm10:0.0f}μg/m³"

        if pm_text:
            self._draw_text(draw, pm_text, (self.center, footer_y), self.font_small, (160, 180, 200))

        # PIR 상태 - 단순하게
        if snapshot.pir is not None:
            pir_y = self.diameter * 0.9
            if snapshot.pir:
                pir_text = "Motion Detected"
                pir_color = (220, 120, 120)
            else:
                pir_text = "No Motion"
                pir_color = (120, 180, 120)

            self._draw_text(draw, pir_text, (self.center, pir_y), self.font_small, pir_color)

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
