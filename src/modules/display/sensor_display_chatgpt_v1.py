# sensor_display.py
"""
원형(기본 480x480) 디스플레이 - 현실적 자연 테마 v3

핵심 수정
- 온도 중복 제거: 중앙이 온도면 TEMP 카드는 숨김
- 이모지 제거: 시스템 폰트 의존성 없이 순수 텍스트 라벨 사용 (TEMP / HUM / PM2.5 / LIVE 등)
- 레이아웃 안정화: 세이프존 확대, 카드 2장(좌하 PM2.5, 우하 HUM)만 배치, 원 내부 충돌/클리핑 방지
- 하단 눈금 제거, 푸터 간소화
"""

from __future__ import annotations

import argparse, json, math, queue, threading, time, random, hashlib, sys, os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

# Kafka
try:
    from kafka import KafkaConsumer
except Exception as exc:
    KafkaConsumer = None
    _KAFKA_IMPORT_ERROR = exc
else:
    _KAFKA_IMPORT_ERROR = None

# Pillow
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
except Exception as exc:
    Image = ImageDraw = ImageFont = ImageFilter = ImageOps = None  # type: ignore
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

# project settings
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from networks.kafka.kafka_config import settings


# ---------------- Data ----------------
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
        return any(v is not None for v in (self.temp_c, self.hum, self.noise, self.pir, self.pm1, self.pm25, self.pm10))


def _pick(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None

def _to_float(v: Any) -> Optional[float]:
    if v is None: return None
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None

def _to_int01(v: Any) -> Optional[int]:
    if v is None: return None
    if isinstance(v, bool): return 1 if v else 0
    s = str(v).strip().lower()
    if s in ("1","true","on","motion","active","triggered"): return 1
    if s in ("0","false","off","idle","inactive","clear"):   return 0
    try: return 1 if float(s)>=0.5 else 0
    except: return None

def _parse_ts(v: Any) -> Optional[float]:
    if v is None: return None
    try:
        x = float(v)
        return x/1000.0 if x>1e12 else x
    except:
        try:
            return datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp()
        except:
            return None

def _extract_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict): return {}
    direct = {k for k in ("temp_c","hum","noise","pir","pm1","pm25","pm10") if k in payload}
    r = {"ts": payload.get("ts"), "device_id": payload.get("device_id")}
    if direct:
        for k in ("temp_c","hum","noise","pir","pm1","pm25","pm10"):
            r[k] = payload.get(k)
        return r
    base = payload.get("sensors") if isinstance(payload.get("sensors"), dict) else payload
    base = base if isinstance(base, dict) else {}
    dht = base.get("dht22") if isinstance(base.get("dht22"), dict) else {}
    ir  = base.get("ir") if isinstance(base.get("ir"), dict) else {}
    snd = base.get("sound") if isinstance(base.get("sound"), dict) else {}
    pm  = base.get("pm") if isinstance(base.get("pm"), dict) else {}
    r.update({
        "temp_c": _pick(dht, ["temp_c","temperature","temp","t"]),
        "hum":    _pick(dht, ["hum","humidity","h"]),
        "noise":  _pick(snd, ["noise","noise_raw","level","raw","value"]),
        "pir":    _pick(ir,  ["pir","motion","value","status"]) or _pick(base,["pir","motion"]),
        "pm1":    _pick(pm,  ["pm1","pm1_0","pm_1_0"]),
        "pm25":   _pick(pm,  ["pm25","pm2_5","pm2.5","pm_2_5"]),
        "pm10":   _pick(pm,  ["pm10","pm_10"]),
    })
    return r

def _snapshot_from_payload(p: Dict[str, Any]) -> Optional[SensorSnapshot]:
    f = _extract_fields(p)
    if not f: return None
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


# -------------- Tk driver --------------
class TkinterDisplayDriver:
    def __init__(self, diameter: int):
        if tk is None or ImageTk is None:
            raise RuntimeError(f"Tkinter import 실패: {_TKINTER_IMPORT_ERROR}")
        self.root = tk.Tk()
        self.root.title("Sensor Display")
        self.root.geometry(f"{diameter+20}x{diameter+50}")
        self.root.configure(bg="black")
        self.label = Label(self.root, bg="black"); self.label.pack(pady=10)
        self.root.lift(); self.root.attributes("-topmost", True)
        self.root.after_idle(lambda: self.root.attributes("-topmost", False))
    def display(self, image):
        photo = ImageTk.PhotoImage(image)
        self.label.configure(image=photo); self.label.image = photo
        self.root.update()


# -------------- Background cache --------------
class BackgroundCache:
    def __init__(self):
        self.image = None; self.key = None
    def get(self, key): return self.image.copy() if self.key==key and self.image is not None else None
    def set(self, key, img): self.key = key; self.image = img.copy()

def _hash_seed(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)


# -------------- Renderer --------------
class CircularNaturalDisplay:
    # palette
    SKY_DAY  = ((160,205,255),(220,240,255))
    SKY_DAWN = ((255,170,120),(255,220,200))
    SKY_DUSK = ((130,160,220),(240,210,200))
    SKY_NIGHT= ((25,35,60),(60,75,110))
    RING=(210,220,235)
    GRASS_NEAR=(70,150,80); GRASS_FAR=(110,170,120)
    HILL_1=(90,150,110); HILL_2=(120,180,140); HILL_3=(150,200,160)
    TEXT_MAIN=(30,40,50); TEXT_SUB=(105,115,125)
    TEMP_COLOR=(255,137,115); HUM_COLOR=(110,175,245); PM_COLOR=(165,140,245)
    LIVE=(62,201,85); RECENT=(255,187,70); OLD=(235,95,85)
    GLASS=(255,255,255,210); CARD_BORDER=(210,220,235)

    def __init__(self, *, diameter:int, font_path:str|None=None, dump_dir:Path|None=None, driver=None, use_tkinter=True):
        if Image is None: raise RuntimeError(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")
        self.diameter = diameter; self.center = diameter/2
        self.driver = None
        if driver is None and use_tkinter:
            try: self.driver = TkinterDisplayDriver(diameter)
            except RuntimeError as e: print(f"[Display] Tk 실패: {e}")
        else: self.driver = driver
        self.dump_dir = Path(dump_dir) if dump_dir else None
        if self.dump_dir: self.dump_dir.mkdir(parents=True, exist_ok=True)
        self.frame_index=0

        # Safe zones & sizes
        self.SAFE_INSET = max(22, int(self.diameter*0.05))   # 더 넉넉하게
        self.CARD_W = int(self.diameter*0.34)
        self.CARD_H = int(self.diameter*0.20)
        self.CENTER_W = int(self.diameter*0.58)
        self.CENTER_H = int(self.diameter*0.24)

        # fonts (no emoji dependency)
        self.font_xl=self._font(font_path,96); self.font_lg=self._font(font_path,56)
        self.font_md=self._font(font_path,34); self.font_sm=self._font(font_path,24); self.font_xs=self._font(font_path,18)

        self.bg_cache=BackgroundCache()
        self.scene_seed=_hash_seed(os.uname().nodename if hasattr(os,"uname") else "deepcare"); random.seed(self.scene_seed)
        self._ripple_start=None

    def _font(self, path,size):
        from pathlib import Path
        cands=[]
        if path: cands.append(Path(path))
        cands += [Path(p) for p in (
            "C:/Windows/Fonts/malgun.ttf","C:/Windows/Fonts/seguiemj.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        )]
        for p in cands:
            if p.is_file():
                try: return ImageFont.truetype(str(p), size)
                except: pass
        return ImageFont.load_default()

    def _text_size(self, draw, text, font):
        if hasattr(draw,"textbbox"):
            l,t,r,b = draw.textbbox((0,0), text, font=font); return r-l, b-t
        return draw.textsize(text,font=font)

    def _text(self, draw, text, xy, font, fill, align="center"):
        w,h = self._text_size(draw,text,font)
        if align=="center": pos=(xy[0]-w/2, xy[1]-h/2)
        elif align=="right": pos=(xy[0]-w, xy[1]-h/2)
        else: pos=(xy[0], xy[1]-h/2)
        draw.text(pos, text, font=font, fill=fill)

    def _phase(self, ts):
        hour = datetime.now().hour if ts is None else datetime.fromtimestamp(ts).hour
        if 22<=hour or hour<6: return 0
        if 6<=hour<8: return 1
        if 8<=hour<18: return 2
        return 3

    def _sky_colors(self, ph): return {0:self.SKY_NIGHT,1:self.SKY_DAWN,2:self.SKY_DAY,3:self.SKY_DUSK}[ph]

    def _soft_glow(self, base,x,y,r,color,alpha=200,blur=16):
        layer=Image.new("RGBA", base.size,(0,0,0,0))
        ImageDraw.Draw(layer).ellipse((x-r,y-r,x+r,y+r), fill=color+(alpha,))
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))

    def _rounded_rect(self, base, rect, radius, fill, outline=None, width=1, shadow=True):
        x0,y0,x1,y1=rect; w=x1-x0; h=y1-y0
        card=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(card)
        d.rounded_rectangle((0,0,w,h), radius=radius, fill=fill, outline=outline, width=width)
        if shadow:
            sh=Image.new("RGBA",(w+10,h+10),(0,0,0,0)); sd=ImageDraw.Draw(sh)
            sd.rounded_rectangle((5,5,w+5,h+5), radius=radius+2, fill=(0,0,0,60))
            base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(3)), (x0-5,y0-5))
        base.alpha_composite(card,(x0,y0))

    def _ring(self, draw, center, r, width, color):
        x,y=center; draw.ellipse((x-r,y-r,x+r,y+r), outline=color, width=width)

    # ---- natural layers ----
    def _sky(self, ph):
        img=Image.new("RGBA",(self.diameter,self.diameter),(0,0,0,0)); d=ImageDraw.Draw(img)
        top,bot=self._sky_colors(ph)
        for y in range(self.diameter):
            t=y/max(1,self.diameter-1)
            clr=(int(top[0]*(1-t)+bot[0]*t), int(top[1]*(1-t)+bot[1]*t), int(top[2]*(1-t)+bot[2]*t), 255)
            d.line([(0,y),(self.diameter,y)], fill=clr)
        return img

    def _sun_moon(self, canvas, ph, temp_c, ts):
        hour = (datetime.now() if ts is None else datetime.fromtimestamp(ts)).hour
        minute = (datetime.now() if ts is None else datetime.fromtimestamp(ts)).minute
        h = hour + minute/60.0
        t=(h-6)/12.0; t=max(0,min(1,t))
        x=int(self.diameter*(0.15+0.7*t)); y=int(self.diameter*(0.22-0.12*math.cos(t*math.pi)))
        if ph==0:
            self._soft_glow(canvas,x,y,22,(200,220,255),alpha=140,blur=20)
            ImageDraw.Draw(canvas).ellipse((x-12,y-12,x+12,y+12), fill=(230,240,255,240))
        else:
            tr=0.0 if temp_c is None else max(0.0,min(1.0,temp_c/40.0))
            r=14+10*tr; col=(255, int(220-80*tr), int(140-90*tr))
            self._soft_glow(canvas,x,y,r+10,col,alpha=180,blur=18)
            ImageDraw.Draw(canvas).ellipse((x-r,y-r,x+r,y+r), fill=col+(230,))

    def _cloud_color(self, pm25):
        if pm25 is None: return (255,255,255,210)
        inten=min(max(pm25/150.0,0.0),1.0)
        base=255-int(120*inten); alpha=max(100,210-int(80*inten))
        return (base,base,base,alpha)

    def _clouds(self, canvas, pm25, tsec):
        w,h=self.diameter,self.diameter
        col=self._cloud_color(pm25); col=(col[0],col[1],col[2], max(80,col[3]-70))
        layer=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(layer)
        random.seed(self.scene_seed)
        for i in range(3):
            by=int(h*(0.16+0.08*i)); size=int(28+7*i); speed=5+2*i
            bx=int((tsec*speed+80*i)%(w+140))-70
            for cx,cy,s in [(bx-size//2,by,size),(bx,by-size//6,size+6),(bx+size//2,by+size//12,size-5)]:
                d.ellipse((cx-s,cy-s,cx+s,cy+s), fill=col)
        canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(1.0)))

    def _haze(self, canvas, pm25, hum):
        pm=0.0 if pm25 is None else min(pm25,150.0)/150.0
        hm=0.0 if hum is None else min(max(hum-60.0,0.0)/40.0,1.0)
        alpha=int(30+90*max(pm,hm))
        canvas.alpha_composite(Image.new("RGBA",canvas.size,(220,225,230,alpha)))

    def _hills(self, canvas):
        w,h=self.diameter,self.diameter; yb=int(h*0.72)
        def layer(off,amp,step,col,blur=0):
            lay=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(lay); pts=[]
            for x in range(0,w+step,step):
                y=yb+int(math.sin((x+off)*0.012)*amp)+int(math.sin((x+2*off)*0.004)*amp*0.6)
                pts.append((x,y))
            pts=[(0,h),(0,pts[0][1])]+pts+[(w,pts[-1][1]),(w,h)]
            d.polygon(pts, fill=col+(255,))
            if blur: lay=lay.filter(ImageFilter.GaussianBlur(blur))
            canvas.alpha_composite(lay)
        layer(30,8,8,self.HILL_3,2); layer(0,12,6,self.HILL_2,1); layer(-20,18,5,self.HILL_1,0)

    def _grass(self, canvas, tsec, wind):
        w,h=self.diameter,self.diameter; ys=int(h*0.78); d=ImageDraw.Draw(canvas)
        for y in range(ys,h):
            t=(y-ys)/max(1,(h-ys))
            r=int(self.GRASS_FAR[0]*(1-t)+self.GRASS_NEAR[0]*t)
            g=int(self.GRASS_FAR[1]*(1-t)+self.GRASS_NEAR[1]*t)
            b=int(self.GRASS_FAR[2]*(1-t)+self.GRASS_NEAR[2]*t)
            rad=math.sqrt(max(self.center**2 - (y-self.center)**2, 0))
            x0=int(self.center-rad); x1=int(self.center+rad)
            d.line([(x0,y),(x1,y)], fill=(r,g,b,255))
        for i in range(42):
            bx=int(self.center - self.diameter*0.35 + (i/41)*self.diameter*0.70)
            by=int(h*0.90 + (i%5) - 2); ht=18 + (i%9)
            sway=math.sin(tsec*(1.4+0.1*i)+i*0.35)*(1.0+wind*1.8)
            tx=bx+sway; ty=by-ht
            col=(60+(i%3)*10,160+(i%4)*10,70+(i%5)*6)
            d.line([(bx,by),(tx,ty)], fill=col+(255,), width=2)

    def _ripple(self, canvas, tsec, trig):
        if trig and self._ripple_start is None: self._ripple_start=tsec
        if self._ripple_start is None: return
        el=tsec-self._ripple_start
        if el>2.5: self._ripple_start=None; return
        cx,cy=int(self.center), int(self.diameter*0.82)
        lay=Image.new("RGBA",canvas.size,(0,0,0,0)); d=ImageDraw.Draw(lay)
        for i in range(5):
            r=int(8+el*90+i*10); a=max(0,120-int(el*60+i*18))
            d.ellipse((cx-r, cy-10-r//6, cx+r, cy+r//6), outline=(200,220,255,a), width=1)
        canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(0.6)))

    def _dew(self, canvas, hum):
        if hum is None or hum<82: return
        lay=Image.new("RGBA",canvas.size,(0,0,0,0)); d=ImageDraw.Draw(lay)
        for x,y in [(self.center-90, self.diameter*0.32),(self.center+110, self.diameter*0.28)]:
            d.ellipse((x-6,y-10,x+6,y+6), fill=(180,210,255,110))
            d.ellipse((x-2,y-6,x+1,y-3), fill=(255,255,255,160))
        canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(0.5)))

    # ---- UI ----
    def _center_panel(self, draw, base, snap:SensorSnapshot):
        cx=self.center; cy=self.center*1.02
        rect=(int(cx-self.CENTER_W/2), int(cy-self.CENTER_H/2), int(cx+self.CENTER_W/2), int(cy+self.CENTER_H/2))
        self._rounded_rect(base, rect, 26, self.GLASS, outline=self.CARD_BORDER, width=2, shadow=True)
        self._text(draw, snap.device_id or "Device", (cx, rect[1]+18), self.font_sm, self.TEXT_SUB)
        if snap.temp_c is not None: main=f"{snap.temp_c:.1f}°C"; col=self.TEMP_COLOR
        elif snap.hum is not None:  main=f"{snap.hum:.0f}%";   col=self.HUM_COLOR
        else: main="---"; col=self.TEXT_MAIN
        self._text(draw, main, (cx, cy+2), self.font_xl, col)
        age=time.time()-snap.ingested_at
        status, col = ("LIVE", self.LIVE) if age<5 else ( "RECENT", self.RECENT) if age<30 else ("OLD", self.OLD)
        self._text(draw, f"{status}", (cx, rect[3]-18), self.font_xs, col)

    def _rect_within_circle(self, rect):
        # 모든 모서리가 원 내부로 들어오도록 확인
        x0,y0,x1,y1 = rect; cx=self.center; r=self.center - max(2, int(self.diameter*0.004)) - self.SAFE_INSET
        for x,y in [(x0,y0),(x0,y1),(x1,y0),(x1,y1)]:
            if (x-cx)**2 + (y-cx)**2 > r**2:  # y uses cx intentionally? bug: should use cy = center
                return False
        return True

    def _sensor_cards(self, draw, base, snap:SensorSnapshot):
        # 중앙이 온도면 TEMP 카드는 제거 → PM2.5, HUM 두 장만
        items=[]
        items.append(("PM2.5", snap.pm25, "µg/m³", self.PM_COLOR))
        items.append(("HUM",   snap.hum,  "%",     self.HUM_COLOR))

        # 목표 각도: 좌하(210°), 우하(330°) — 상단은 비움(겹침 방지)
        target_angles=[210,330]
        radius = self.diameter * 0.365
        card_w,card_h=self.CARD_W,self.CARD_H

        cx=self.center; cy=self.center*1.02
        center_rect=(int(cx-self.CENTER_W/2), int(cy-self.CENTER_H/2), int(cx+self.CENTER_W/2), int(cy+self.CENTER_H/2))

        def collide(a,b):
            return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

        for i,(label,val,unit,color) in enumerate(items):
            ang=math.radians(target_angles[i])
            x=self.center + radius*math.cos(ang); y=self.center + radius*math.sin(ang)

            # 세이프 인셋 적용
            x=max(self.SAFE_INSET+card_w/2, min(self.diameter-self.SAFE_INSET-card_w/2, x))
            y=max(self.SAFE_INSET+card_h/2, min(self.diameter-self.SAFE_INSET-card_h/2, y))
            rect=(int(x-card_w/2), int(y-card_h/2), int(x+card_w/2), int(y+card_h/2))

            # 중앙 패널 충돌시 원 중심 반대 방향으로 조금 이동
            step=0
            while collide(rect, center_rect) and step<4:
                x += 10*math.cos(ang); y += 10*math.sin(ang)
                rect=(int(x-card_w/2), int(y-card_h/2), int(x+card_w/2), int(y+card_h/2)); step+=1

            # 원 내부 보정: 모서리가 밖으로 나가면 반경 축소
            cstep=0
            while not self._rect_within_circle(rect) and cstep<6:
                x = (x+self.center)/2; y=(y+self.center)/2  # 중심 쪽으로 당김
                rect=(int(x-card_w/2), int(y-card_h/2), int(x+card_w/2), int(y+card_h/2)); cstep+=1

            self._rounded_rect(base, rect, 16, (255,255,255,230), outline=self.CARD_BORDER, width=2, shadow=True)
            self._text(draw, label, (x, rect[1]+18), self.font_xs, self.TEXT_SUB)
            if val is None:
                self._text(draw, "--", (x, y+4), self.font_lg, self.TEXT_SUB)
            else:
                self._text(draw, f"{val:.1f}", (x-24, y+4), self.font_lg, color)
                self._text(draw, unit, (x+58, y+8), self.font_sm, color)

    def _footer(self, draw, base, snap:SensorSnapshot):
        cx,y=self.center, int(self.diameter*0.92)
        draw.line([(int(cx-self.diameter*0.28), y-26),(int(cx+self.diameter*0.28), y-26)], fill=self.CARD_BORDER, width=1)
        now=datetime.now().strftime("%H:%M")
        suffix=[]
        if snap.noise is not None: suffix.append(f"{int(snap.noise)} dB")
        if snap.pir  is not None:  suffix.append("PIR:ON" if snap.pir else "PIR:OFF")
        txt = " | ".join([f"Time {now}"] + suffix) if suffix else f"Time {now}"
        self._text(draw, txt, (cx,y), self.font_sm, self.TEXT_SUB)

    # ---- render ----
    def render(self, snap:SensorSnapshot) -> Image.Image:
        ph=self._phase(snap.ts or time.time()); pm=(snap.pm25 or 0.0); tier=0 if pm<35 else (1 if pm<75 else 2)
        key=(ph,tier,self.diameter); bg=self.bg_cache.get(key); now=time.time()
        if bg is None:
            sky=self._sky(ph); self._sun_moon(sky, ph, snap.temp_c, snap.ts); self._clouds(sky, snap.pm25, 0.0)
            self._hills(sky); self._haze(sky, snap.pm25, snap.hum)
            self.bg_cache.set(key, sky); bg=sky

        canvas=bg.copy(); d=ImageDraw.Draw(canvas)

        # dynamic
        self._clouds(canvas, snap.pm25, now*0.10)
        wind=0.0 + (0.9 if snap.pir else 0.0) + (max(0.0,min(1.0, ( (snap.noise or 40)-40 )/40.0))*0.6 if snap.noise is not None else 0.0)
        self._grass(canvas, now, wind); self._dew(canvas, snap.hum); self._ripple(canvas, now, bool(snap.pir))

        # UI
        if snap.has_payload():
            self._center_panel(d, canvas, snap)
            self._sensor_cards(d, canvas, snap)
            self._footer(d, canvas, snap)
        else:
            self._text(d, "Waiting for data...", (self.center, self.center-6), self.font_lg, self.TEXT_SUB)
            self._text(d, datetime.now().strftime("%H:%M"), (self.center, self.center+34), self.font_md, self.TEXT_SUB)

        # circle mask + ring
        mask=Image.new("L",(self.diameter,self.diameter),0); ImageDraw.Draw(mask).ellipse((0,0,self.diameter,self.diameter), fill=255)
        final=Image.new("RGBA",(self.diameter,self.diameter),(255,255,255,0)); final.paste(canvas,(0,0),mask)
        ring_w=max(2,int(self.diameter*0.004)); self._ring(ImageDraw.Draw(final),(self.center,self.center), self.center-ring_w, ring_w, self.RING)
        return final.convert("RGB")

    def present(self, image):
        shown=False
        if self.driver is not None:
            try:
                if hasattr(self.driver,"display"): self.driver.display(image); shown=True
                elif hasattr(self.driver,"image"): self.driver.image(image); shown=True
            except Exception as e: print(f"[Display] 드라이버 오류: {e}")
        if not shown: print("[Display] 드라이버가 없어 화면에 표시되지 않습니다.")
        if self.dump_dir:
            p=self.dump_dir/f"frame_{self.frame_index:06d}.png"; image.save(p); print(f"[Display] 프레임 저장: {p}")
        self.frame_index+=1


# -------------- Kafka consumer --------------
class KafkaSensorStream:
    def __init__(self, out_q: queue.Queue[SensorSnapshot], *, debug=False):
        self.out_q=out_q; self.debug=debug; self._stop=threading.Event(); self._th=None
    def start(self):
        if KafkaConsumer is None: raise RuntimeError(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
        self._stop.clear(); self._th=threading.Thread(target=self._run, daemon=True); self._th.start()
    def stop(self):
        self._stop.set(); 
        if self._th and self._th.is_alive(): self._th.join(timeout=2.0)
    def _pub(self, snap):
        try: self.out_q.put(snap, timeout=0.05)
        except queue.Full:
            try: self.out_q.get_nowait()
            except queue.Empty: pass
            try: self.out_q.put(snap, timeout=0.05)
            except queue.Full:
                if self.debug: print("[Kafka] 출력 큐 full")
    def _run(self):
        try:
            print(f"[Kafka] connect {settings.bootstrap_servers}")
            consumer=KafkaConsumer(enable_auto_commit=True, value_deserializer=lambda v: v.decode(settings.value_encoding,"ignore"), consumer_timeout_ms=1000, **settings.kafka_kwargs)
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
                        if self.debug: print(f"[Kafka] JSON error: {e} :: {raw!r}")
                        continue
                    snap=_snapshot_from_payload(payload)
                    if snap is None:
                        if self.debug: print(f"[Kafka] unsupported payload: {payload}")
                        continue
                    snap.raw=payload; snap.ingested_at=time.time(); self._pub(snap)
        try: consumer.close()
        except Exception: pass


# -------------- Main --------------
def build_arg_parser():
    p=argparse.ArgumentParser(description="Circular sensor display (natural v3)")
    p.add_argument("--diameter", type=int, default=settings.diameter_pixels)
    p.add_argument("--font", type=str, default=settings.font_path)
    p.add_argument("--refresh-hz", type=float, default=settings.display_refresh_hz)
    p.add_argument("--frame-dump", type=str, default=None)
    p.add_argument("--debug", action="store_true")
    return p

def main():
    if KafkaConsumer is None: raise SystemExit(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")
    if Image is None: raise SystemExit(f"Pillow import 실패: {_PILLOW_IMPORT_ERROR}")
    args=build_arg_parser().parse_args()
    refresh=max(0.1, args.refresh_hz); period=1.0/refresh
    display=CircularNaturalDisplay(diameter=args.diameter, font_path=args.font, dump_dir=Path(args.frame_dump) if args.frame_dump else None)
    out_q:queue.Queue[SensorSnapshot]=queue.Queue(maxsize=16); stream=KafkaSensorStream(out_q, debug=args.debug); stream.start()
    latest=SensorSnapshot(); next_t=time.time()
    try:
        while True:
            try: latest = out_q.get(timeout=max(0.0, next_t-time.time()))
            except queue.Empty: pass
            now=time.time()
            if now>=next_t:
                img=display.render(latest)
                display.present(img)
                next_t=now+period
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()

if __name__=="__main__":
    main()
