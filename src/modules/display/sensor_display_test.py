# sensor_display.py
"""
Round Sensor UI - 'Aura' style (ref. pastel smart clock)
- Pastel radial background
- Dual ring (base + gradient progress by HUM)
- Center: big time (HH:MM) + AM/PM, Date below
- Top-right: temperature (°C)
- Bottom: humidity % + vector droplet
- Optional tiny weather glyph (sun/cloud) from temp/hum/pm heuristics
- No emoji dependence (drawn vector icons)

Kafka consumer + Tkinter preview preserved.
"""

from __future__ import annotations

import argparse, json, math, os, queue, threading, time, sys
from dataclasses import dataclass, field
from datetime import datetime
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
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except Exception as exc:
    Image = ImageDraw = ImageFont = ImageFilter = None  # type: ignore
    _PILLOW_IMPORT_ERROR = exc
else:
    _PILLOW_IMPORT_ERROR = None

# Tkinter preview (optional)
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
    if v is None: return None
    try: return float(str(v).replace(",", "."))
    except Exception: return None

def _to_int01(v: Any) -> Optional[int]:
    if v is None: return None
    if isinstance(v, bool): return 1 if v else 0
    s=str(v).strip().lower()
    if s in ("1","true","on","motion","active","triggered"): return 1
    if s in ("0","false","off","idle","inactive","clear"): return 0
    try: return 1 if float(s)>=0.5 else 0
    except Exception: return None

def _parse_ts(v: Any) -> Optional[float]:
    if v is None: return None
    try:
        x=float(v); return x/1000.0 if x>1e12 else x
    except Exception:
        try: return datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp()
        except Exception: return None

def _extract_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict): return {}
    direct={k for k in ("temp_c","hum","noise","pir","pm1","pm25","pm10") if k in payload}
    r={"ts": payload.get("ts"), "device_id": payload.get("device_id")}
    if direct:
        for k in ("temp_c","hum","noise","pir","pm1","pm25","pm10"):
            r[k]=payload.get(k)
        return r
    base=payload.get("sensors") if isinstance(payload.get("sensors"),dict) else payload
    base=base if isinstance(base,dict) else {}
    dht=base.get("dht22") if isinstance(base.get("dht22"),dict) else {}
    ir =base.get("ir")    if isinstance(base.get("ir"),dict)    else {}
    snd=base.get("sound") if isinstance(base.get("sound"),dict) else {}
    pm =base.get("pm")    if isinstance(base.get("pm"),dict)    else {}
    r.update({
        "temp_c": _pick(dht,["temp_c","temperature","temp","t"]),
        "hum":    _pick(dht,["hum","humidity","h"]),
        "noise":  _pick(snd,["noise","noise_raw","level","raw","value"]),
        "pir":    _pick(ir, ["pir","motion","value","status"]) or _pick(base,["pir","motion"]),
        "pm1":    _pick(pm, ["pm1","pm1_0","pm_1_0"]),
        "pm25":   _pick(pm, ["pm25","pm2_5","pm2.5","pm_2_5"]),
        "pm10":   _pick(pm, ["pm10","pm_10"]),
    })
    return r

def _snapshot_from_payload(p: Dict[str, Any]) -> Optional[SensorSnapshot]:
    f=_extract_fields(p)
    if not f: return None
    return SensorSnapshot(
        ts=_parse_ts(f.get("ts")), device_id=f.get("device_id") or p.get("device"),
        temp_c=_to_float(f.get("temp_c")), hum=_to_float(f.get("hum")),
        noise=_to_float(f.get("noise")), pir=_to_int01(f.get("pir")),
        pm1=_to_float(f.get("pm1")), pm25=_to_float(f.get("pm25")), pm10=_to_float(f.get("pm10")),
    )


# ---------------- Tk preview ----------------
class TkinterDisplayDriver:
    def __init__(self, diameter: int):
        if tk is None or ImageTk is None:
            raise RuntimeError(f"Tkinter import 실패: {_TKINTER_IMPORT_ERROR}")
        self.root=tk.Tk(); self.root.title("Sensor Display")
        self.root.geometry(f"{diameter+20}x{diameter+50}"); self.root.configure(bg="black")
        self.label=Label(self.root, bg="black"); self.label.pack(pady=10)
        self.root.lift(); self.root.attributes("-topmost", True)
        self.root.after_idle(lambda: self.root.attributes("-topmost", False))
    def display(self, image: Image.Image):
        photo=ImageTk.PhotoImage(image); self.label.configure(image=photo); self.label.image=photo; self.root.update()


# ---------------- Renderer ----------------
class AuraDisplay:
    # palette
    RING_BASE = (210, 220, 230)
    TEXT_MAIN = (255, 255, 255)
    TEXT_SOFT = (245, 245, 245)
    TEXT_MUTED = (230, 235, 240)

    TEMP_COLOR = (255, 235, 200)   # small temp text
    HUM_COLOR  = (210, 235, 255)   # drop + % accent

    def __init__(self, *, diameter:int, font_path:str|None=None, dump_dir:Path|None=None, driver=None, use_tkinter=True):
        if Image is None or ImageDraw is None or ImageFont is None:
            raise RuntimeError(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")
        self.d = diameter
        self.c = diameter/2
        self.safe = int(self.d * 0.04)

        # fonts
        self.font_time = self._font(font_path, int(self.d * 0.20))   # 6:30
        self.font_ampm = self._font(font_path, int(self.d * 0.075))  # AM
        self.font_date = self._font(font_path, int(self.d * 0.058))  # September 13
        self.font_small = self._font(font_path, int(self.d * 0.06))  # temp °C
        self.font_hum = self._font(font_path, int(self.d * 0.10))    # 46%

        # preview driver
        if driver is None and use_tkinter:
            try:
                self.driver=TkinterDisplayDriver(self.d)
            except RuntimeError as e:
                print(f"[Display] Tk 실패: {e}"); self.driver=None
        else:
            self.driver=driver

        self.dump_dir = Path(dump_dir) if dump_dir else None
        if self.dump_dir: self.dump_dir.mkdir(parents=True, exist_ok=True)
        self.frame_index=0

    # fonts
    def _font(self, path: Optional[str], size:int) -> ImageFont.ImageFont:
        from pathlib import Path
        cands=[]
        if path: cands.append(Path(path))
        cands += [
            Path("C:/Windows/Fonts/malgun.ttf"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ]
        for p in cands:
            if p.is_file():
                try: return ImageFont.truetype(str(p), size)
                except Exception: pass
        return ImageFont.load_default()

    # helpers
    def _text_size(self, draw, text, font):
        if hasattr(draw, "textbbox"):
            l,t,r,b = draw.textbbox((0,0), text, font=font)
            return r-l, b-t
        return draw.textsize(text, font=font)

    def _draw_text(self, d, text, xy, font, fill, align="center"):
        w,h=self._text_size(d, text, font)
        if align=="center": pos=(xy[0]-w/2, xy[1]-h/2)
        elif align=="right": pos=(xy[0]-w, xy[1]-h/2)
        else: pos=(xy[0], xy[1]-h/2)
        d.text(pos, text, font=font, fill=fill)

    # graphics
    def _radial_bg(self) -> Image.Image:
        # smooth radial pastel (top warm peach -> center light blue)
        img = Image.new("RGBA", (self.d, self.d), (0,0,0,0))
        base = Image.new("RGBA", (self.d, self.d), (0,0,0,0))
        gd = ImageDraw.Draw(base)
        # vertical blend (peach -> blue)
        top=(255, 214, 194); mid=(230, 238, 255); low=(210, 232, 255)
        for y in range(self.d):
            t=y/max(1,self.d-1)
            if t<0.6:
                tt=t/0.6
                r=int(top[0]*(1-tt)+mid[0]*tt); g=int(top[1]*(1-tt)+mid[1]*tt); b=int(top[2]*(1-tt)+mid[2]*tt)
            else:
                tt=(t-0.6)/0.4
                r=int(mid[0]*(1-tt)+low[0]*tt); g=int(mid[1]*(1-tt)+low[1]*tt); b=int(mid[2]*(1-tt)+low[2]*tt)
            gd.line([(0,y),(self.d,y)], fill=(r,g,b,255))
        # subtle vignette
        v = Image.new("L",(self.d,self.d),0); vd=ImageDraw.Draw(v)
        vd.ellipse((int(self.d*0.05),int(self.d*0.05),int(self.d*0.95),int(self.d*0.95)), fill=220)
        vign=Image.new("RGBA",(self.d,self.d),(0,0,0,0)); vign.putalpha(v.filter(ImageFilter.GaussianBlur(int(self.d*0.05))))
        img.alpha_composite(base); img.alpha_composite(vign)
        return img

    def _ring(self, d, center, r, width, color):
        x,y=center; d.ellipse((x-r,y-r,x+r,y+r), outline=color, width=width)

    def _progress_ring(self, base: Image.Image, center, r, width, value_01: float):
        # gradient arc (aqua -> sky -> peach)
        v=max(0.0, min(1.0, value_01))
        start=-210  # start angle (deg) like ref
        sweep=int(300 * v)  # 300° range
        if sweep<=0: return
        steps=max(18, int(sweep/4))
        arc=Image.new("RGBA", base.size, (0,0,0,0))
        ad=ImageDraw.Draw(arc)
        for i in range(steps):
            t=i/max(1,steps-1)
            # color interpolate: aqua(120,220,255)->sky(130,200,255)->peach(255,205,180)
            if t<0.55:
                tt=t/0.55; c0=(120,220,255); c1=(130,200,255)
            else:
                tt=(t-0.55)/0.45; c0=(130,200,255); c1=(255,205,180)
            rcol=tuple(int(c0[j]*(1-tt)+c1[j]*tt) for j in range(3))
            ad.arc(
                [center[0]-r, center[1]-r, center[0]+r, center[1]+r],
                start + int(sweep * (i/steps)),
                start + int(sweep * ((i+1)/steps)),
                fill=rcol+(255,), width=width
            )
        base.alpha_composite(arc)

    def _icon_sun_cloud(self, base: Image.Image, x:int, y:int, scale:int=1):
        # simple sun + small cloud
        layer=Image.new("RGBA", base.size, (0,0,0,0)); d=ImageDraw.Draw(layer)
        r=10*scale
        d.ellipse((x-r,y-r,x+r,y+r), fill=(255,205,120,230))  # sun
        # cloud
        cx=x+18*scale; cy=y+6*scale; cr=8*scale
        for dx,dy,rr in [(-cr,0,cr), (0,-3*scale,cr+2*scale), (cr,0,cr)]:
            d.ellipse((cx+dx-rr, cy+dy-rr, cx+dx+rr, cy+dy+rr), fill=(255,255,255,220))
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.3*scale)))

    def _icon_drop(self, base: Image.Image, x:int, y:int, scale:int=1, color=(210,235,255,220)):
        # teardrop: circle + triangle
        layer=Image.new("RGBA", base.size,(0,0,0,0)); d=ImageDraw.Draw(layer)
        w=14*scale; h=22*scale
        # body
        d.ellipse((x-w/2, y-h/2, x+w/2, y+h/2), fill=color)
        # tip overlay
        tip=[(x, y - h/2 - 6*scale), (x - w*0.28, y - h*0.18), (x + w*0.28, y - h*0.18)]
        d.polygon(tip, fill=color)
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.6*scale)))

    # ---- render ----
    def render(self, snap: SensorSnapshot) -> Image.Image:
        W=H=self.d
        # base background
        canvas=self._radial_bg()

        draw=ImageDraw.Draw(canvas)
        cx=cy=self.c

        # inner frosted circle
        inner_r = self.d*0.78/2
        fro=Image.new("RGBA",(W,H),(255,255,255,0))
        fd=ImageDraw.Draw(fro)
        fd.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r), fill=(255,255,255,70), outline=None)
        canvas.alpha_composite(fro.filter(ImageFilter.GaussianBlur(int(self.d*0.01))))

        # outer/base ring + progress
        ring_w = max(8, int(self.d*0.028))
        self._ring(draw, (cx,cy), self.c - ring_w//2 - self.safe, ring_w, self.RING_BASE)
        hum = 0.0 if snap.hum is None else max(0.0, min(100.0, snap.hum))
        self._progress_ring(canvas, (cx,cy), self.c - ring_w//2 - self.safe, ring_w, hum/100.0)

        # small weather glyph near top-left of center
        self._icon_sun_cloud(canvas, int(cx - inner_r*0.55), int(cy - inner_r*0.30), scale=max(1,int(self.d/480)))

        # top-right: temperature
        if snap.temp_c is not None:
            temp_txt = f"{snap.temp_c:.0f}°C"
            tx = cx + inner_r*0.42
            ty = cy - inner_r*0.42
            self._draw_text(draw, temp_txt, (tx, ty), self.font_small, self.TEMP_COLOR, align="right")

        # center time + AM/PM
        now_dt = datetime.now()
        hh = now_dt.strftime("%I").lstrip("0") or "0"
        mm = now_dt.strftime("%M")
        ampm = now_dt.strftime("%p")
        time_txt = f"{hh}:{mm}"
        month_day = now_dt.strftime("%B %d").replace(" 0", " ")
        weekday = now_dt.strftime("%a")
        date_txt = f"{weekday} {month_day}"

        time_w, time_h = self._text_size(draw, time_txt, self.font_time)
        _, date_h = self._text_size(draw, date_txt, self.font_date)
        stack_gap = max(self.d * 0.05, time_h * 0.32, date_h * 0.65)
        block_h = time_h + stack_gap + date_h
        block_top = max(cy - block_h / 2, self.safe + time_h * 0.1)
        time_center_y = block_top + time_h / 2
        date_center_y = time_center_y + time_h / 2 + stack_gap + date_h / 2
        date_center_y += max(self.d * 0.008, date_h * 0.15)  # keep date separated from the time block

        self._draw_text(draw, time_txt, (cx, time_center_y), self.font_time, self.TEXT_MAIN)

        ampm_w, ampm_h = self._text_size(draw, ampm, self.font_ampm)
        time_right = cx + time_w / 2
        ampm_left = time_right + max(self.d * 0.02, ampm_w * 0.4)
        ampm_left = min(ampm_left, cx + inner_r * 0.48 - ampm_w)
        ampm_center_y = (time_center_y - time_h / 2) + ampm_h / 2 + max(self.d * 0.002, time_h * 0.05)
        self._draw_text(draw, ampm, (ampm_left, ampm_center_y), self.font_ampm, self.TEXT_SOFT, align="left")

        max_date_center = cy + inner_r * 0.18
        date_center_y = min(date_center_y, max_date_center)

        # date (weekday + Month DD)
        self._draw_text(draw, date_txt, (cx, date_center_y), self.font_date, self.TEXT_MUTED)

        # bottom humidity with drop
        if snap.hum is not None:
            self._icon_drop(canvas, int(cx - inner_r*0.35), int(cy + inner_r*0.30), scale=max(1,int(self.d/480)), color=self.HUM_COLOR+(220,))
            hum_txt = f"{int(round(snap.hum))}%"
            self._draw_text(draw, hum_txt, (cx, cy + inner_r*0.30), self.font_hum, self.HUM_COLOR)

        # circular clip + thin outer edge
        mask=Image.new("L",(W,H),0); ImageDraw.Draw(mask).ellipse((0,0,W,H), fill=255)
        final=Image.new("RGBA",(W,H),(0,0,0,0)); final.paste(canvas,(0,0),mask)
        edge=ImageDraw.Draw(final); edge_w=max(2,int(self.d*0.004))
        self._ring(edge, (cx,cy), self.c-edge_w, edge_w, (230,235,240))
        return final.convert("RGB")

    # present
    def present(self, image: Image.Image) -> None:
        shown=False
        if self.driver is not None:
            try:
                if hasattr(self.driver,"display"): self.driver.display(image); shown=True
                elif hasattr(self.driver,"image"): self.driver.image(image); shown=True
            except Exception as e:
                print(f"[Display] 드라이버 오류: {e}")
        if not shown: print("[Display] 드라이버가 없어 화면에 표시되지 않습니다.")
        if self.dump_dir:
            p=self.dump_dir/f"frame_{self.frame_index:06d}.png"; image.save(p); print(f"[Display] 프레임 저장: {p}")
        self.frame_index+=1


# ---------------- Kafka stream ----------------
class KafkaSensorStream:
    def __init__(self, out_q: queue.Queue[SensorSnapshot], *, debug: bool=False) -> None:
        self.out_q=out_q; self.debug=debug; self._stop=threading.Event(); self._th:threading.Thread|None=None
    def start(self)->None:
        if KafkaConsumer is None: raise RuntimeError(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
        self._stop.clear(); self._th=threading.Thread(target=self._run, name="kafka-sensor-consumer", daemon=True); self._th.start()
    def stop(self)->None:
        self._stop.set(); 
        if self._th and self._th.is_alive(): self._th.join(timeout=2.0)
    def _publish(self, snap:SensorSnapshot)->None:
        try: self.out_q.put(snap, timeout=0.05)
        except queue.Full:
            try: self.out_q.get_nowait()
            except queue.Empty: pass
            try: self.out_q.put(snap, timeout=0.05)
            except queue.Full:
                if self.debug: print("[Kafka] 출력 큐 full")
    def _run(self)->None:
        try:
            print(f"[Kafka] connect {settings.bootstrap_servers}")
            consumer=KafkaConsumer(enable_auto_commit=True, value_deserializer=lambda v: v.decode(settings.value_encoding,"ignore"),
                                   consumer_timeout_ms=1000, **settings.kafka_kwargs)
            consumer.subscribe([settings.sensor_topic]); print(f"[Kafka] subscribed: {settings.sensor_topic}")
        except Exception as e:
            print(f"[Kafka] init fail: {e}"); return
        while not self._stop.is_set():
            try: records=consumer.poll(timeout_ms=500)
            except Exception as e: print(f"[Kafka] poll fail: {e}"); time.sleep(1.0); continue
            if not records: continue
            for msgs in records.values():
                for msg in msgs:
                    raw=msg.value
                    try: payload=json.loads(raw)
                    except Exception as e:
                        if self.debug: print(f"[Kafka] JSON error: {e} :: {raw!r}"); continue
                    snap=_snapshot_from_payload(payload)
                    if snap is None:
                        if self.debug: print(f"[Kafka] unsupported payload: {payload}"); continue
                    snap.raw=payload; snap.ingested_at=time.time(); self._publish(snap)
        try: consumer.close()
        except Exception: pass


# ---------------- Main ----------------
def build_arg_parser():
    p=argparse.ArgumentParser(description="Circular sensor display - Aura style")
    p.add_argument("--diameter", type=int, default=settings.diameter_pixels)
    p.add_argument("--font", type=str, default=settings.font_path)
    p.add_argument("--refresh-hz", type=float, default=settings.display_refresh_hz)
    p.add_argument("--frame-dump", type=str, default=None)
    p.add_argument("--debug", action="store_true")
    return p

def main():
    if KafkaConsumer is None: raise SystemExit(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
    if Image is None or ImageDraw is None or ImageFont is None: raise SystemExit(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")
    args=build_arg_parser().parse_args()
    refresh=max(0.1, args.refresh_hz); period=1.0/refresh

    display = AuraDisplay(diameter=args.diameter, font_path=args.font, dump_dir=Path(args.frame_dump) if args.frame_dump else None)

    out_q: queue.Queue[SensorSnapshot] = queue.Queue(maxsize=16)
    stream = KafkaSensorStream(out_q, debug=args.debug); stream.start()

    latest=SensorSnapshot(); next_t=time.time()
    try:
        while True:
            try: latest = out_q.get(timeout=max(0.0, next_t-time.time()))
            except queue.Empty: pass
            now=time.time()
            if now >= next_t:
                frame = display.render(latest)
                display.present(frame)
                next_t = now + period
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()

if __name__=="__main__":
    main()
