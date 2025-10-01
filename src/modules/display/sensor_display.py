# sensor_display.py
"""
원형(기본 480x480) 디스플레이 - Ultra Minimal
- 센서 데이터(가용 항목만), 날짜, 시간만 표시
- 장식/아이콘/이모지 없음, 얇은 링과 깨끗한 타이포그래피

Kafka 소비/큐 구조 및 Tkinter 프리뷰 유지
"""

from __future__ import annotations

import argparse, json, math, os, queue, threading, time, sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

# Kafka
try:
    from kafka import KafkaConsumer
except Exception as exc:
    KafkaConsumer = None  # type: ignore
    _KAFKA_IMPORT_ERROR = exc
else:
    _KAFKA_IMPORT_ERROR = None

# Pillow
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:
    Image = ImageDraw = ImageFont = None  # type: ignore
    _PILLOW_IMPORT_ERROR = exc
else:
    _PILLOW_IMPORT_ERROR = None

# Tkinter (optional preview)
try:
    import tkinter as tk
    from tkinter import Label
    from PIL import ImageTk
except Exception as exc:
    tk = Label = ImageTk = None  # type: ignore
    _TKINTER_IMPORT_ERROR = exc
else:
    _TKINTER_IMPORT_ERROR = None

# Project settings
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from networks.kafka.kafka_config import settings


# ---------------- Data model ----------------
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
            v is not None for v in (self.temp_c, self.hum, self.noise, self.pir, self.pm1, self.pm25, self.pm10)
        )


# ---------------- Helpers ----------------
def _pick(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None


def _to_int01(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in ("1", "true", "on", "motion", "active", "triggered"):
        return 1
    if s in ("0", "false", "off", "idle", "inactive", "clear"):
        return 0
    try:
        return 1 if float(s) >= 0.5 else 0
    except Exception:
        return None


def _parse_ts(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
        return x / 1000.0 if x > 1e12 else x
    except Exception:
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except Exception:
            return None


def _extract_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    direct = {k for k in ("temp_c", "hum", "noise", "pir", "pm1", "pm25", "pm10") if k in payload}
    r = {"ts": payload.get("ts"), "device_id": payload.get("device_id")}
    if direct:
        for k in ("temp_c", "hum", "noise", "pir", "pm1", "pm25", "pm10"):
            r[k] = payload.get(k)
        return r

    base = payload.get("sensors") if isinstance(payload.get("sensors"), dict) else payload
    base = base if isinstance(base, dict) else {}

    dht = base.get("dht22") if isinstance(base.get("dht22"), dict) else {}
    ir = base.get("ir") if isinstance(base.get("ir"), dict) else {}
    snd = base.get("sound") if isinstance(base.get("sound"), dict) else {}
    pm = base.get("pm") if isinstance(base.get("pm"), dict) else {}

    r.update(
        {
            "temp_c": _pick(dht, ["temp_c", "temperature", "temp", "t"]),
            "hum": _pick(dht, ["hum", "humidity", "h"]),
            "noise": _pick(snd, ["noise", "noise_raw", "level", "raw", "value"]),
            "pir": _pick(ir, ["pir", "motion", "value", "status"]) or _pick(base, ["pir", "motion"]),
            "pm1": _pick(pm, ["pm1", "pm1_0", "pm_1_0"]),
            "pm25": _pick(pm, ["pm25", "pm2_5", "pm2.5", "pm_2_5"]),
            "pm10": _pick(pm, ["pm10", "pm_10"]),
        }
    )
    return r


def _snapshot_from_payload(p: Dict[str, Any]) -> Optional[SensorSnapshot]:
    f = _extract_fields(p)
    if not f:
        return None
    return SensorSnapshot(
        ts=_parse_ts(f.get("ts")),
        device_id=f.get("device_id") or p.get("device"),
        temp_c=_to_float(f.get("temp_c")),
        hum=_to_float(f.get("hum")),
        noise=_to_float(f.get("noise")),
        pir=_to_int01(f.get("pir")),
        pm1=_to_float(f.get("pm1")),
        pm25=_to_float(f.get("pm25")),
        pm10=_to_float(f.get("pm10")),
    )


# ---------------- Tk preview ----------------
class TkinterDisplayDriver:
    def __init__(self, diameter: int):
        if tk is None or ImageTk is None:
            raise RuntimeError(f"Tkinter import 실패: {_TKINTER_IMPORT_ERROR}")
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


# ---------------- Minimal Renderer ----------------
class CircularMinimalDisplay:
    # neutral palette
    BG_TOP = (248, 250, 252)
    BG_BOTTOM = (240, 244, 248)
    RING = (205, 212, 220)
    TEXT_MAIN = (28, 32, 36)
    TEXT_MUTED = (128, 136, 144)
    ACCENT = (255, 120, 95)     # TEMP
    ACCENT2 = (95, 150, 255)    # HUM/PM 등

    def __init__(self, *, diameter: int, font_path: str | None = None, dump_dir: Path | None = None,
                 driver=None, use_tkinter=True) -> None:
        if Image is None or ImageDraw is None or ImageFont is None:  # type: ignore
            raise RuntimeError(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")
        self.diameter = diameter
        self.center = diameter / 2
        self.inner_size = int(diameter * 0.78)  # 원 안 정사각형(텍스트 안전 영역)
        self.safe_inset = int((diameter - self.inner_size) / 2)

        # fonts
        self.font_xl = self._font(font_path, int(diameter * 0.16))  # 큰 값
        self.font_lg = self._font(font_path, int(diameter * 0.09))  # 행 값
        self.font_md = self._font(font_path, int(diameter * 0.06))  # 날짜/시간/라벨
        self.font_sm = self._font(font_path, int(diameter * 0.05))  # 단위

        # preview driver
        if driver is None and use_tkinter:
            try:
                self.driver = TkinterDisplayDriver(diameter)
            except RuntimeError as e:
                print(f"[Display] Tkinter 드라이버 실패: {e}")
                self.driver = None
        else:
            self.driver = driver

        self.dump_dir = Path(dump_dir) if dump_dir else None
        if self.dump_dir:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
        self.frame_index = 0

    def _font(self, path: Optional[str], size: int) -> ImageFont.ImageFont:
        from pathlib import Path
        cands = []
        if path:
            cands.append(Path(path))
        cands += [
            Path("C:/Windows/Fonts/malgun.ttf"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ]
        for p in cands:
            if p.is_file():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _text_size(self, draw, text, font):
        if hasattr(draw, "textbbox"):
            l, t, r, b = draw.textbbox((0, 0), text, font=font)
            return r - l, b - t
        return draw.textsize(text, font=font)

    def _draw_text(self, draw, text, xy, font, fill, align="center"):
        w, h = self._text_size(draw, text, font)
        if align == "center":
            pos = (xy[0] - w / 2, xy[1] - h / 2)
        elif align == "right":
            pos = (xy[0] - w, xy[1] - h / 2)
        else:
            pos = (xy[0], xy[1] - h / 2)
        draw.text(pos, text, font=font, fill=fill)

    def _ring(self, draw, center, r, width, color):
        x, y = center
        draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=width)

    # -------- render --------
    def render(self, snap: SensorSnapshot) -> Image.Image:
        w = h = self.diameter

        # background (subtle vertical blend)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(self.BG_TOP[0] * (1 - t) + self.BG_BOTTOM[0] * t)
            g = int(self.BG_TOP[1] * (1 - t) + self.BG_BOTTOM[1] * t)
            b = int(self.BG_TOP[2] * (1 - t) + self.BG_BOTTOM[2] * t)
            d.line([(0, y), (w, y)], fill=(r, g, b, 255))

        # inner safe square (for text) centered in circle
        inner = (
            self.safe_inset,
            self.safe_inset,
            w - self.safe_inset,
            h - self.safe_inset,
        )

        # header: DATE (top)
        date_str = datetime.now().strftime("%Y-%m-%d")
        self._draw_text(d, date_str, (self.center, inner[1] + self.diameter * 0.06), self.font_md, self.TEXT_MUTED)

        # build sensor rows (visible only)
        rows = []
        if snap.temp_c is not None:
            rows.append(("TEMP", f"{snap.temp_c:.1f}", "°C", self.ACCENT))
        if snap.hum is not None:
            rows.append(("HUM", f"{snap.hum:.0f}", "%", self.ACCENT2))
        if snap.pm25 is not None:
            rows.append(("PM2.5", f"{snap.pm25:.1f}", "µg/m³", self.ACCENT2))
        if snap.pm10 is not None:
            rows.append(("PM10", f"{snap.pm10:.1f}", "µg/m³", self.TEXT_MAIN))
        if snap.noise is not None:
            rows.append(("NOISE", f"{int(snap.noise)}", "dB", self.TEXT_MAIN))
        if snap.pir is not None:
            rows.append(("PIR", "ON" if snap.pir else "OFF", "", self.TEXT_MAIN))

        # empty state
        if not rows:
            self._draw_text(d, "No data", (self.center, self.center - self.diameter * 0.02), self.font_lg, self.TEXT_MUTED)
        else:
            # vertical layout within inner square
            line_gap = int(self.diameter * 0.015)
            row_height = self._text_size(d, "Ag", self.font_lg)[1] + line_gap
            total_h = row_height * len(rows)
            start_y = self.center - total_h / 2

            left_x = inner[0] + int(self.diameter * 0.06)
            right_x = inner[2] - int(self.diameter * 0.06)

            # draw each row: label (left, muted) | value (right, accent) | unit (just right of value, muted)
            for i, (label, value, unit, color) in enumerate(rows):
                y = start_y + i * row_height
                # label
                self._draw_text(d, label, (left_x, y), self.font_md, self.TEXT_MUTED, align="left")
                # value (right aligned to right_x)
                self._draw_text(d, value, (right_x, y), self.font_lg, color, align="right")
                # unit (after value with small gap)
                if unit:
                    vw, _ = self._text_size(d, value, self.font_lg)
                    self._draw_text(d, unit, (right_x - vw - int(self.diameter * -0.01), y + self.diameter * 0.002),
                                    self.font_sm, self.TEXT_MUTED, align="left")

        # footer: TIME (bottom)
        time_str = datetime.now().strftime("%H:%M")
        self._draw_text(d, time_str, (self.center, inner[3] - self.diameter * 0.06), self.font_md, self.TEXT_MUTED)

        # mask to circle + ring
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, w, h), fill=255)
        final = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        final.paste(img, (0, 0), mask)

        ring_w = max(2, int(self.diameter * 0.004))
        self._ring(ImageDraw.Draw(final), (self.center, self.center), self.center - ring_w, ring_w, self.RING)

        return final.convert("RGB")

    # present
    def present(self, image: Image.Image) -> None:
        shown = False
        if self.driver is not None:
            try:
                if hasattr(self.driver, "display"):
                    self.driver.display(image); shown = True
                elif hasattr(self.driver, "image"):
                    self.driver.image(image); shown = True
            except Exception as e:
                print(f"[Display] 드라이버 오류: {e}")

        if not shown:
            print("[Display] 드라이버가 없어 화면에 표시되지 않습니다.")

        if self.dump_dir:
            p = self.dump_dir / f"frame_{self.frame_index:06d}.png"
            image.save(p)
            print(f"[Display] 프레임 저장: {p}")
        self.frame_index += 1


# ---------------- Kafka stream ----------------
class KafkaSensorStream:
    def __init__(self, out_q: queue.Queue[SensorSnapshot], *, debug: bool = False) -> None:
        self.out_q = out_q
        self.debug = debug
        self._stop = threading.Event()
        self._th: threading.Thread | None = None

    def start(self) -> None:
        if KafkaConsumer is None:
            raise RuntimeError(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
        self._stop.clear()
        self._th = threading.Thread(target=self._run, name="kafka-sensor-consumer", daemon=True)
        self._th.start()

    def stop(self) -> None:
        self._stop.set()
        if self._th and self._th.is_alive():
            self._th.join(timeout=2.0)

    def _publish(self, snap: SensorSnapshot) -> None:
        try:
            self.out_q.put(snap, timeout=0.05)
        except queue.Full:
            try:
                self.out_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.out_q.put(snap, timeout=0.05)
            except queue.Full:
                if self.debug:
                    print("[Kafka] 출력 큐 full")

    def _run(self) -> None:
        try:
            print(f"[Kafka] connect {settings.bootstrap_servers}")
            consumer = KafkaConsumer(
                enable_auto_commit=True,
                value_deserializer=lambda v: v.decode(settings.value_encoding, "ignore"),
                consumer_timeout_ms=1000,
                **settings.kafka_kwargs,
            )
            consumer.subscribe([settings.sensor_topic])
            print(f"[Kafka] subscribed: {settings.sensor_topic}")
        except Exception as e:
            print(f"[Kafka] init fail: {e}")
            return

        while not self._stop.is_set():
            try:
                records = consumer.poll(timeout_ms=500)
            except Exception as e:
                print(f"[Kafka] poll fail: {e}")
                time.sleep(1.0)
                continue
            if not records:
                continue
            for batch in records.values():
                for msg in batch:
                    raw = msg.value
                    try:
                        payload = json.loads(raw)
                    except Exception as e:
                        if self.debug:
                            print(f"[Kafka] JSON error: {e} :: {raw!r}")
                        continue
                    snap = _snapshot_from_payload(payload)
                    if snap is None:
                        if self.debug:
                            print(f"[Kafka] unsupported payload: {payload}")
                        continue
                    snap.raw = payload
                    snap.ingested_at = time.time()
                    self._publish(snap)
        try:
            consumer.close()
        except Exception:
            pass


# ---------------- Main ----------------
def build_arg_parser():
    p = argparse.ArgumentParser(description="Circular sensor display (Ultra Minimal)")
    p.add_argument("--diameter", type=int, default=settings.diameter_pixels)
    p.add_argument("--font", type=str, default=settings.font_path)
    p.add_argument("--refresh-hz", type=float, default=settings.display_refresh_hz)
    p.add_argument("--frame-dump", type=str, default=None)
    p.add_argument("--debug", action="store_true")
    return p


def main():
    if KafkaConsumer is None:
        raise SystemExit(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
    if Image is None or ImageDraw is None or ImageFont is None:
        raise SystemExit(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")

    args = build_arg_parser().parse_args()
    refresh_hz = args.refresh_hz if args.refresh_hz > 0 else 1.0
    period = 1.0 / refresh_hz

    display = CircularMinimalDisplay(
        diameter=args.diameter,
        font_path=args.font,
        dump_dir=Path(args.frame_dump) if args.frame_dump else None,
    )

    out_q: queue.Queue[SensorSnapshot] = queue.Queue(maxsize=16)
    stream = KafkaSensorStream(out_q, debug=args.debug)
    stream.start()

    latest = SensorSnapshot()
    next_t = time.time()

    try:
        while True:
            try:
                latest = out_q.get(timeout=max(0.0, next_t - time.time()))
            except queue.Empty:
                pass

            now = time.time()
            if now >= next_t:
                frame = display.render(latest)
                display.present(frame)
                next_t = now + period
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()


if __name__ == "__main__":
    main()
