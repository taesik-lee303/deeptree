# sensor_display.py
"""
Kafka 파이프라인을 통해 수집한 UART 센서 값을 2.1인치 원형 디스플레이(기본 480x480)에
미니멀하고 세련된 카드형 UI로 렌더링합니다.

- kafka-python 소비자로 settings.sensor_topic 구독
- 메시지 페이로드는 uart_receiver.py와 유사한 JSON 스키마를 가정
- Pillow로 원형 레이아웃을 구성하고, Tkinter 프리뷰(옵션) 혹은 외부 드라이버에 전달
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

# Kafka
try:
    from kafka import KafkaConsumer
except Exception as exc:  # pragma: no cover
    KafkaConsumer = None  # type: ignore
    _KAFKA_IMPORT_ERROR = exc
else:
    _KAFKA_IMPORT_ERROR = None

# Pillow
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
except Exception as exc:  # pragma: no cover
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore
    ImageFilter = None  # type: ignore
    ImageOps = None    # type: ignore
    _PILLOW_IMPORT_ERROR = exc
else:
    _PILLOW_IMPORT_ERROR = None

# Tkinter (옵션 미리보기)
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


# -----------------------------
# 데이터 스냅샷
# -----------------------------
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
            v is not None
            for v in (self.temp_c, self.hum, self.noise, self.pir, self.pm1, self.pm25, self.pm10)
        )


# -----------------------------
# 유틸
# -----------------------------
def _pick(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not math.isnan(float(value)):
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
        if ts > 1e12:  # ms 방어
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
    direct = {k for k in ("temp_c", "hum", "noise", "pir", "pm1", "pm25", "pm10") if k in payload}
    result = {"ts": payload.get("ts"), "device_id": payload.get("device_id")}
    if direct:
        for k in ("temp_c", "hum", "noise", "pir", "pm1", "pm25", "pm10"):
            result[k] = payload.get(k)
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
            "pir": _pick(ir, ["pir", "motion", "value", "status"]) or _pick(base, ["pir", "motion"]),
            "pm1": _pick(pm, ["pm1", "pm1_0", "pm_1_0"]),
            "pm25": _pick(pm, ["pm25", "pm2_5", "pm2.5", "pm_2_5"]),
            "pm10": _pick(pm, ["pm10", "pm_10"]),
        }
    )
    return result


def _snapshot_from_payload(payload: Dict[str, Any]) -> SensorSnapshot | None:
    f = _extract_fields(payload)
    if not f:
        return None
    ts = _parse_timestamp(f.get("ts"))
    snap = SensorSnapshot(
        ts=ts,
        device_id=f.get("device_id") or payload.get("device"),
        temp_c=_to_float(f.get("temp_c")),
        hum=_to_float(f.get("hum")),
        noise=_to_float(f.get("noise")),
        pir=_to_int01(f.get("pir")),
        pm1=_to_float(f.get("pm1")),
        pm25=_to_float(f.get("pm25")),
        pm10=_to_float(f.get("pm10")),
    )
    return snap


# -----------------------------
# Tkinter 드라이버 (옵션)
# -----------------------------
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

        # Top-most 트릭(깜빡임 방지)
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after_idle(lambda: self.root.attributes("-topmost", False))

    def display(self, image: Image.Image):
        photo = ImageTk.PhotoImage(image)
        self.label.configure(image=photo)
        self.label.image = photo
        self.root.update()


# -----------------------------
# 미니멀 원형 대시보드 렌더러
# -----------------------------
class CircularSensorDisplay:
    # 컬러 팔레트 (파스텔/뉴모피즘 느낌)
    BG_TOP = (244, 248, 252)
    BG_BOTTOM = (225, 235, 245)
    RING = (210, 220, 235)
    CARD_FILL = (255, 255, 255)
    CARD_BORDER = (210, 220, 235)
    TEXT_MAIN = (40, 50, 60)
    TEXT_SUB = (110, 120, 130)
    TEMP_COLOR = (255, 137, 115)   # 살구빛 오렌지
    HUM_COLOR = (110, 175, 245)    # 하늘색
    PM_COLOR = (165, 140, 245)     # 연보라
    LIVE = (62, 201, 85)
    RECENT = (255, 187, 70)
    OLD = (235, 95, 85)

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

        # 드라이버
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

        # 폰트
        self.font_xl = self._load_font(font_path, 110)
        self.font_lg = self._load_font(font_path, 64)
        self.font_md = self._load_font(font_path, 36)
        self.font_sm = self._load_font(font_path, 26)
        self.font_xs = self._load_font(font_path, 20)

    # ---- 폰트/텍스트 ----
    def _load_font(self, font_path: str | None, size: int) -> ImageFont.ImageFont:
        candidates = []
        if font_path:
            candidates.append(Path(font_path))
        candidates.extend(
            Path(p)
            for p in (
                # Windows (한글 포함)
                "C:/Windows/Fonts/malgun.ttf",
                "C:/Windows/Fonts/seguiemj.ttf",
                # Linux
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            )
        )
        for c in candidates:
            if c.is_file():
                try:
                    return ImageFont.truetype(str(c), size)
                except OSError:
                    continue
        return ImageFont.load_default()

    @staticmethod
    def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
        if hasattr(draw, "textbbox"):
            l, t, r, b = draw.textbbox((0, 0), text, font=font)
            return int(r - l), int(b - t)
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
        w, h = self._text_size(draw, text, font)
        if align == "center":
            pos = (xy[0] - w / 2.0, xy[1] - h / 2.0)
        elif align == "right":
            pos = (xy[0] - w, xy[1] - h / 2.0)
        else:
            pos = (xy[0], xy[1] - h / 2.0)
        draw.text(pos, text, font=font, fill=fill)

    # ---- 도형 헬퍼 ----
    def _rounded_rect(
        self,
        base: Image.Image,
        rect: tuple[int, int, int, int],
        radius: int,
        fill: tuple[int, int, int] | tuple[int, int, int, int],
        outline: Optional[tuple[int, int, int]] = None,
        width: int = 1,
        shadow: bool = True,
    ):
        x0, y0, x1, y1 = rect
        w = x1 - x0
        h = y1 - y0

        # 카드 레이어
        card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((0, 0, w, h), radius=radius, fill=fill, outline=outline, width=width)
        if shadow:
            # 부드러운 그림자
            shadow_layer = Image.new("RGBA", (w + 10, h + 10), (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow_layer)
            sd.rounded_rectangle((5, 5, w + 5, h + 5), radius=radius + 2, fill=(0, 0, 0, 60))
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(3))
            base.alpha_composite(shadow_layer, (x0 - 5, y0 - 5))
        base.alpha_composite(card, (x0, y0))

    def _ring(self, draw: ImageDraw.ImageDraw, center: tuple[float, float], r: float, width: int, color: tuple[int, int, int]):
        x, y = center
        bbox = (x - r, y - r, x + r, y + r)
        draw.ellipse(bbox, outline=color, width=width)

    # ---- 메인 렌더 ----
    def render(self, snapshot: SensorSnapshot) -> Image.Image:
        # 배경 그라디언트
        bg = Image.new("RGBA", (self.diameter, self.diameter), (0, 0, 0, 0))
        g = ImageDraw.Draw(bg)
        for y in range(self.diameter):
            t = y / max(1, self.diameter - 1)
            r = int(self.BG_TOP[0] * (1 - t) + self.BG_BOTTOM[0] * t)
            g_ = int(self.BG_TOP[1] * (1 - t) + self.BG_BOTTOM[1] * t)
            b = int(self.BG_TOP[2] * (1 - t) + self.BG_BOTTOM[2] * t)
            g.line([(0, y), (self.diameter, y)], fill=(r, g_, b, 255))

        # 원형 마스크
        mask = Image.new("L", (self.diameter, self.diameter), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse((0, 0, self.diameter, self.diameter), fill=255)

        # 링(테두리)
        self._ring(g, (self.center, self.center), self.center - 2, 2, self.RING)

        # 데이터 없음 -> 심플 대기 화면
        if not snapshot.has_payload():
            draw = ImageDraw.Draw(bg)
            self._draw_text(draw, "Waiting for data...", (self.center, self.center - 6), self.font_lg, self.TEXT_SUB)
            now = datetime.now().strftime("%H:%M")
            self._draw_text(draw, now, (self.center, self.center + 34), self.font_md, self.TEXT_SUB)
            final = Image.new("RGBA", (self.diameter, self.diameter), (255, 255, 255, 0))
            final.paste(bg, (0, 0), mask)
            return final.convert("RGB")

        # 실제 콘텐츠 렌더
        canvas = bg.copy()
        draw = ImageDraw.Draw(canvas)

        # 중앙 메인 값 (온도 우선, 없으면 습도)
        self._draw_center(draw, canvas, snapshot)

        # 주요 3 카드 (TEMP/HUM/PM2.5) 원형 배치
        self._draw_sensor_cards(draw, canvas, snapshot)

        # 하단 보조 정보 (소음 / PIR / 시간 / 상태)
        self._draw_footer(draw, canvas, snapshot)

        # 원형 클리핑
        final = Image.new("RGBA", (self.diameter, self.diameter), (255, 255, 255, 0))
        final.paste(canvas, (0, 0), mask)
        return final.convert("RGB")

    # ---- 섹션: 중앙 메인 값 ----
    def _draw_center(self, draw: ImageDraw.ImageDraw, base: Image.Image, snapshot: SensorSnapshot):
        cx, cy = self.center, self.center
        # 얇은 내부 링
        self._ring(draw, (cx, cy), self.center * 0.62, 2, self.RING)

        # 카드
        card_w, card_h = int(self.diameter * 0.56), int(self.diameter * 0.30)
        rect = (
            int(cx - card_w / 2),
            int(cy - card_h / 2),
            int(cx + card_w / 2),
            int(cy + card_h / 2),
        )
        self._rounded_rect(base, rect, radius=28, fill=self.CARD_FILL + (240,), outline=self.CARD_BORDER, width=2, shadow=True)

        # 디바이스 / 시간
        device = snapshot.device_id or "Device"
        self._draw_text(draw, device, (cx, rect[1] + 22), self.font_sm, self.TEXT_SUB)

        # 메인 값
        main_txt = "---"
        color = self.TEXT_MAIN
        if snapshot.temp_c is not None:
            main_txt = f"{snapshot.temp_c:.1f}°C"
            color = self.TEMP_COLOR
        elif snapshot.hum is not None:
            main_txt = f"{snapshot.hum:.0f}%"
            color = self.HUM_COLOR

        self._draw_text(draw, main_txt, (cx, cy + 8), self.font_xl, color)

        # 상태 배지
        age = time.time() - snapshot.ingested_at
        if age < 5:  status, s_col = "● LIVE", self.LIVE
        elif age < 30: status, s_col = "● RECENT", self.RECENT
        else:        status, s_col = "● OLD", self.OLD
        self._draw_text(draw, status, (cx, rect[3] - 20), self.font_xs, s_col)

    # ---- 섹션: 센서 카드 ----
    def _draw_sensor_cards(self, draw: ImageDraw.ImageDraw, base: Image.Image, snapshot: SensorSnapshot):
        items = [
            ("🌡️ TEMP", snapshot.temp_c, "°C", self.TEMP_COLOR),
            ("💧 HUM", snapshot.hum, "%", self.HUM_COLOR),
            ("🌫️ PM2.5", snapshot.pm25, "µg/m³", self.PM_COLOR),
        ]
        data_items = [(l, v, u, c) for (l, v, u, c) in items if v is not None]
        if not data_items:
            return

        card_w, card_h = 160, 96
        radius = self.diameter * 0.34
        total = max(3, len(items))  # 자리 간격은 고정 3분할
        for i, (label, value, unit, color) in enumerate(items):
            # 미표시 값도 자리 유지 (시각적 균형)
            angle = (-90 + i * (360 / total)) * math.pi / 180.0
            x = self.center + radius * math.cos(angle)
            y = self.center + radius * math.sin(angle)

            rect = (int(x - card_w / 2), int(y - card_h / 2), int(x + card_w / 2), int(y + card_h / 2))
            self._rounded_rect(base, rect, radius=18, fill=self.CARD_FILL + (235,), outline=self.CARD_BORDER, width=2, shadow=True)

            # 라벨
            self._draw_text(draw, label, (x, rect[1] + 20), self.font_xs, self.TEXT_SUB)

            # 값
            if value is None:
                self._draw_text(draw, "--", (x, y + 6), self.font_lg, self.TEXT_SUB)
            else:
                self._draw_text(draw, f"{value:.1f}", (x - 20, y + 6), self.font_lg, color)
                self._draw_text(draw, unit, (x + 52, y + 10), self.font_sm, color)

    # ---- 섹션: 하단 보조 정보 ----
    def _draw_footer(self, draw: ImageDraw.ImageDraw, base: Image.Image, snapshot: SensorSnapshot):
        cx, cy = self.center, self.center
        y = int(self.diameter * 0.86)

        # 얇은 구분선
        draw.line([(int(cx - self.diameter * 0.28), y - 24), (int(cx + self.diameter * 0.28), y - 24)],
                  fill=self.CARD_BORDER, width=1)

        # 시간
        now = datetime.now().strftime("%H:%M")
        self._draw_text(draw, f"🕒 {now}", (cx, y), self.font_sm, self.TEXT_SUB)

        # 소음
        if snapshot.noise is not None:
            self._draw_text(draw, f"  ·  🔊 {int(snapshot.noise)} dB", (cx + 90, y), self.font_sm, self.TEXT_SUB)
        # PIR
        if snapshot.pir is not None:
            pir_icon = "👁️" if snapshot.pir else "😴"
            self._draw_text(draw, f"  ·  {pir_icon}", (cx + 220, y), self.font_sm, self.TEXT_SUB)

    # ---- 프레젠트 ----
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


# -----------------------------
# Kafka 스트림
# -----------------------------
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


# -----------------------------
# 엔트리 포인트
# -----------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Kafka -> 원형 디스플레이 센서 뷰어 (미니멀 UI)")
    p.add_argument("--diameter", type=int, default=settings.diameter_pixels, help="디스플레이 지름(px)")
    p.add_argument("--font", type=str, default=settings.font_path, help="TTF 폰트 경로")
    p.add_argument("--refresh-hz", type=float, default=settings.display_refresh_hz, help="화면 갱신 주기(Hz)")
    p.add_argument("--frame-dump", type=str, default=None, help="프레임 저장 디렉터리(옵션)")
    p.add_argument("--debug", action="store_true", help="디버그 로그")
    return p


def main() -> None:
    if KafkaConsumer is None:
        raise SystemExit(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
    if Image is None or ImageDraw is None or ImageFont is None:
        raise SystemExit(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")

    args = build_arg_parser().parse_args()
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
    stream = KafkaSensorStream(out_queue, debug=args.debug)
    print("[Main] 카프카 스트림 시작...")
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
