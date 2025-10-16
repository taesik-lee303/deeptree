#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pygame 버전 (라즈베리파이5 원형 디스플레이):
- 한글 폰트 자동 탐색 & 없으면 영문 라벨 자동 대체
- 습도값 없어도 기본 수면 표시 + 물결 애니메이션
- 센서 키 별칭(alias) 매핑으로 여러 값 동시 표시
- 상단 시간/날짜, 글래스 카드 스타일
"""

import os, re, math, json, time, random, threading, subprocess, sys
from datetime import datetime
from typing import Any, Dict, Optional

# ---------- 모니터 좌표 탐색 ----------
def find_monitor_offset(prefer_size=(480,480), fallback=(3840,0)):
    try:
        out = subprocess.run(["xrandr","--listmonitors"], capture_output=True, text=True, timeout=3)
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                m = re.search(r"(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)", line)
                if m:
                    w,h,x,y = map(int,[m.group(2),m.group(3),m.group(4),m.group(5)])
                    if (w,h)==prefer_size: return (x,y)
    except Exception:
        pass
    try:
        out = subprocess.run(["xrandr","--query"], capture_output=True, text=True, timeout=3)
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                m = re.search(r"^(\S+)\s+connected\s+(\d+)x(\d+)\+(\d+)\+(\d+)", line)
                if m:
                    w,h,x,y = map(int,[m.group(2),m.group(3),m.group(4),m.group(5)])
                    if (w,h)==prefer_size: return (x,y)
    except Exception:
        pass
    return fallback

pos = find_monitor_offset()
os.environ["SDL_VIDEO_WINDOW_POS"] = f"{pos[0]},{pos[1]}"
# Wayland에서 위치 무시되면 필요 시: os.environ["SDL_VIDEODRIVER"] = "x11"

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from networks.kafka.kafka_config import settings as kafka_settings
except Exception as exc:
    kafka_settings = None
    _KAFKA_SETTINGS_IMPORT_ERROR = exc
else:
    _KAFKA_SETTINGS_IMPORT_ERROR = None

import pygame
pygame.init()

# ---------- 설정 ----------
SIZE = 480
CENTER = SIZE//2
RADIUS = CENTER-22
WATER_RADIUS = CENTER-40
FPS = 60

# 파도
WAVE_BASE_A = 4.0
WAVE_BASE_SPEED = 0.05
WAVE_FAST_A = 15.0
WAVE_FAST_SPEED = 0.25
WAVE_KS = (0.018, 0.028, 0.042)

# 카드
CARD_W, CARD_H = 128, 56
CARD_RADIUS = 14
CARD_ALPHA = 208
CARD_SHADOW = (16,48,73,72)
CARD_STROKE = (255,255,255,80)
CARD_HILITE = (255,255,255,40)
DOT_R = 6

# 상단 텍스트 위치 (아래로 이동)
TOP_TIME_Y = 80
TOP_DATE_Y = 110

# 색
COL_BG_RING = (184,194,204)
COL_WATER   = (230,243,255,215)
COL_TEXT    = (25,39,52)
COL_WAIT    = (102,170,204)

screen = pygame.display.set_mode((SIZE, SIZE))
pygame.display.set_caption("Smart Circular Display")
clock = pygame.time.Clock()

# ---------- 폰트: 한글 자동 탐색 ----------
def pick_font_path():
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/unifont/unifont.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p): return p
    return None

FONT_PATH = pick_font_path()
KR_FONT = FONT_PATH and any(s in FONT_PATH.lower() for s in ["noto", "nanum", "unifont"])
def make_font(size, bold=False):
    if FONT_PATH:
        f = pygame.font.Font(FONT_PATH, size)
        if bold: f.set_bold(True)
        return f
    return pygame.font.SysFont("Arial", size, bold=bold)

font_time  = make_font(36, True)
font_date  = make_font(18, True)
font_label = make_font(14, True)
font_value = make_font(20, True)
font_wait  = make_font(18, False)

# 라벨 (항상 한글로 표시)
LABELS_KR = {"temp":"온도","noise":"소음","humi":"습도","pm25":"PM2.5","pm10":"PM10"}
LABELS_EN = {"temp":"온도","noise":"소음","humi":"습도","pm25":"PM2.5","pm10":"PM10"}
LABELS = LABELS_KR

def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or not str(val).strip():
        return default
    try:
        return float(val)
    except Exception:
        return default

def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "t", "yes", "y", "on")

NOISE_SENSOR_ASSUME_DB = _env_bool("NOISE_SENSOR_ASSUME_DB", False)
NOISE_SENSOR_DB_CUTOFF = _env_float("NOISE_SENSOR_DB_CUTOFF", 180.0)
NOISE_SENSOR_ADC_BASELINE = max(1e-6, _env_float("NOISE_SENSOR_ADC_BASELINE", 400.0))
NOISE_SENSOR_DB_BASELINE = _env_float("NOISE_SENSOR_DB_BASELINE", 35.0)
NOISE_SENSOR_DB_GAIN = _env_float("NOISE_SENSOR_DB_GAIN", 20.0)
NOISE_SENSOR_DB_MIN = _env_float("NOISE_SENSOR_DB_MIN", 20.0)
NOISE_SENSOR_DB_MAX = _env_float("NOISE_SENSOR_DB_MAX", 120.0)

def convert_noise_reading(raw: Optional[float]) -> Optional[float]:
    if raw is None:
        return None
    value = float(raw)
    if NOISE_SENSOR_ASSUME_DB or value <= NOISE_SENSOR_DB_CUTOFF:
        return value
    baseline = max(NOISE_SENSOR_ADC_BASELINE, 1e-6)
    ratio = max(value, 1e-6) / baseline
    db = NOISE_SENSOR_DB_BASELINE + NOISE_SENSOR_DB_GAIN * math.log10(max(ratio, 1e-6))
    if NOISE_SENSOR_DB_MIN is not None:
        db = max(NOISE_SENSOR_DB_MIN, db)
    if NOISE_SENSOR_DB_MAX is not None:
        db = min(NOISE_SENSOR_DB_MAX, db)
    return db

# ---------- 데이터 / Kafka ----------
sensor_data = {
    "temperature": None,
    "humidity": None,
    "pm2_5": None,
    "pm10": None,
    "noise_level": None,
    "motion_detected": False,
}
data_lock = threading.Lock()

DEFAULT_KAFKA_TOPICS = ["display-data", "sensor-events"]
DEFAULT_BOOTSTRAP_SERVERS = ["localhost:9092"]

try:
    from kafka import KafkaConsumer  # type: ignore
except Exception as exc:
    KafkaConsumer = None  # type: ignore
    _KAFKA_IMPORT_ERROR = exc
    KAFKA_ENABLED = False
else:
    _KAFKA_IMPORT_ERROR = None
    KAFKA_ENABLED = True

ALIASES = {
    "temp":"temperature",
    "temperature_c":"temperature",
    "hum":"humidity",
    "humidity_pct":"humidity",
    "pm25":"pm2_5",
    "pm_2_5":"pm2_5",
    "noise":"noise_level",
    "sound":"noise_level",
    "pir":"motion_detected",
    "pir_alert":"motion_detected",
    "pir_state":"motion_detected",
    "motion":"motion_detected",
    "motion_alert":"motion_detected",
}

def apply_aliases(d):
    out = {}
    for k,v in d.items():
        key = ALIASES.get(k, k)
        out[key]=v
    return out

SENSOR_FIELDS = ("temperature", "humidity", "pm2_5", "pm10", "noise_level", "motion_detected")

def _dedupe(seq):
    seen = set()
    ordered = []
    for item in seq:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered

def resolve_kafka_topics():
    topics = []
    env_topics = os.getenv("DISPLAY_SENSOR_TOPICS")
    if env_topics:
        topics.extend([t.strip() for t in env_topics.split(",") if t.strip()])
    if kafka_settings and getattr(kafka_settings, "sensor_topic", None):
        topics.append(kafka_settings.sensor_topic)
    if not topics:
        topics.extend(DEFAULT_KAFKA_TOPICS)
    return _dedupe(topics)

def resolve_kafka_kwargs():
    if kafka_settings:
        return dict(kafka_settings.kafka_kwargs)
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", ",".join(DEFAULT_BOOTSTRAP_SERVERS))
    servers = [item.strip() for item in bootstrap.split(",") if item.strip()]
    return {
        "bootstrap_servers": servers or DEFAULT_BOOTSTRAP_SERVERS,
        "auto_offset_reset": os.getenv("KAFKA_OFFSET_RESET", "latest"),
    }

def resolve_value_encoding():
    if kafka_settings and getattr(kafka_settings, "value_encoding", None):
        return kafka_settings.value_encoding or "utf-8"
    return os.getenv("KAFKA_VALUE_ENCODING", "utf-8")

def decode_payload(raw: Any, encoding: str):
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode(encoding, errors="ignore")
        except Exception:
            return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None

def _iter_dict_candidates(obj: Any, depth: int = 0, max_depth: int = 3):
    if not isinstance(obj, dict):
        return
    yield obj
    if depth >= max_depth:
        return
    for value in obj.values():
        if isinstance(value, dict):
            yield from _iter_dict_candidates(value, depth + 1, max_depth)

def _to_float(value: Any):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None

def _normalize_sensor_value(key: str, value: Any):
    if value is None:
        return None
    if key == "motion_detected":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "t", "yes", "y", "on", "motion", "active", "detected")
        return None
    num = _to_float(value)
    if num is None:
        return None
    if key in ("pm2_5", "pm10"):
        return int(round(num))
    if key == "noise_level":
        return convert_noise_reading(num)
    if key in ("temperature", "humidity"):
        return float(num)
    return num

def extract_sensor_values(payload: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    for segment in _iter_dict_candidates(payload):
        alias_segment = apply_aliases(segment)
        for key in SENSOR_FIELDS:
            if key in alias_segment and alias_segment[key] is not None:
                normalized = _normalize_sensor_value(key, alias_segment[key])
                if normalized is not None:
                    updates[key] = normalized
    return updates

def kafka_consume():
    if not KAFKA_ENABLED:
        reason = f" ({_KAFKA_IMPORT_ERROR})" if "_KAFKA_IMPORT_ERROR" in globals() and _KAFKA_IMPORT_ERROR else ""
        print("[i] Kafka ??? ?? ? ?? ?? ???? ?????." + reason)
        return

    topics = resolve_kafka_topics()
    if not topics:
        print("[i] Kafka ?? ??? ?? ?? ???? ?????.")
        return

    if kafka_settings is None and "_KAFKA_SETTINGS_IMPORT_ERROR" in globals() and _KAFKA_SETTINGS_IMPORT_ERROR:
        print(f"[i] Kafka ?? ?? ??: {_KAFKA_SETTINGS_IMPORT_ERROR}. ????? ?????.")

    encoding = resolve_value_encoding()
    kwargs = resolve_kafka_kwargs()
    kwargs = dict(kwargs)
    kwargs.pop("value_deserializer", None)
    kwargs.pop("key_deserializer", None)
    kwargs.setdefault("consumer_timeout_ms", 1000)
    kwargs.setdefault("enable_auto_commit", True)

    bootstrap = kwargs.get("bootstrap_servers")
    print(f"[i] Kafka ?? ??: topics={topics}, bootstrap={bootstrap}")

    try:
        consumer = KafkaConsumer(*topics, value_deserializer=lambda x: x, **kwargs)
    except Exception as e:
        print("[!] Kafka ?? ??:", e)
        return

    try:
        while True:
            try:
                records = consumer.poll(timeout_ms=1000)
            except Exception as e:
                print("[!] Kafka poll ??:", e)
                time.sleep(1.0)
                continue
            if not records:
                continue
            for batch in records.values():
                for msg in batch:
                    payload = decode_payload(msg.value, encoding)
                    if payload is None:
                        continue
                    updates = extract_sensor_values(payload)
                    if not updates:
                        continue
                    with data_lock:
                        sensor_data.update(updates)
    finally:
        try:
            consumer.close()
        except Exception:
            pass


def demo_feeder():
    t0=time.time()
    force_demo = os.getenv("DISPLAY_DEMO_MODE", "0") == "1"
    while True:
        if not force_demo and KAFKA_ENABLED and resolve_kafka_topics():
            return
        t=time.time()-t0
        with data_lock:
            sensor_data["temperature"]=23.5+2.0*math.sin(t*0.12)
            sensor_data["humidity"]=48+22*(math.sin(t*0.07)*0.5+0.5)
            sensor_data["pm2_5"]=int(10+20*(math.sin(t*0.05)*0.5+0.5))
            sensor_data["pm10"] =int(20+40*(math.sin(t*0.045+1.2)*0.5+0.5))
            sensor_data["noise_level"]=int(35+25*(math.sin(t*0.35)*0.5+0.5))
            sensor_data["motion_detected"]=(int(t)%12==0)
        time.sleep(0.2)

threading.Thread(target=kafka_consume, daemon=True).start()
threading.Thread(target=demo_feeder,  daemon=True).start()

# ---------- 유틸 ----------
def clamp(v, lo, hi): return lo if v<lo else hi if v>hi else v
def lerp(a,b,t): return a+(b-a)*t
def blit_center(surface, surf, cx, cy):
    r=surf.get_rect(center=(cx,cy)); surface.blit(surf, r)

# ---------- 파도 / 부표 ----------
random.seed(42)
buoy_phases={}
wave_offset=0.0
motion_boost_until=0.0

def compute_wave_params(data, wave_offset_local):
    # 습도 없으면 기본 수위(20%)
    h = data.get("humidity")
    if h is None:
        water_ratio = 0.20
    else:
        water_ratio = clamp((h/100.0)*0.82, 0.0, 0.82)

    radius = WATER_RADIUS
    water_height = (radius*2)*water_ratio
    surface_base = CENTER + radius - water_height

    if time.time() < motion_boost_until:
        A = WAVE_FAST_A
        speed = WAVE_FAST_SPEED
    else:
        A = 0.0
        speed = 0.0

    ks = WAVE_KS
    def surf_y(x):
        y=surface_base
        for i,k in enumerate(ks):
            w = A*(0.6 if i==0 else 0.27 if i==1 else 0.13)
            y += math.sin(k*(x-CENTER) + wave_offset_local*(1.0+i*0.35))*w
        dymax = math.sqrt(max(0.0, radius**2 - (x-CENTER)**2))
        return clamp(y, CENTER-dymax, CENTER+dymax)
    return dict(radius=radius, amplitude=A, speed=speed, surf_y=surf_y)

# ---------- 그리기 ----------
def draw_ring(surface):
    surface.fill((255,255,255))
    pygame.draw.circle(surface, COL_BG_RING, (CENTER,CENTER), RADIUS-2, 1)

def draw_temp_tint(surface, data):
    t = data.get("temperature")
    if t is None: return
    if t<=18: col=(230,243,255)
    elif t<=22: col=(232,245,232)
    elif t<=26: col=(255,244,230)
    elif t<=30: col=(255,230,204)
    else:
        intensity = clamp((t-30)/10,0,1)
        rv=int(255-intensity*50); col=(rv, int(rv*0.4), int(rv*0.4))
    pygame.draw.circle(surface, col, (CENTER,CENTER), RADIUS-3)

def draw_water(surface, wave, data):
    # 항상 물을 그림 (습도 없으면 기본 수위)
    radius = wave["radius"]; surf_y=wave["surf_y"]
    min_x=CENTER-radius; max_x=CENTER+radius
    steps=220
    pts=[]
    for i in range(steps):
        x = lerp(min_x, max_x, i/(steps-1))
        y = surf_y(x); pts.append((x,y))
    # 아래쪽 원 경계
    bottom=[]
    steps2=150
    for i in range(steps2):
        ang = math.pi - (i*math.pi/(steps2-1))
        bx = CENTER + math.cos(ang)*radius
        by = CENTER + math.sin(ang)*radius
        if by >= surf_y(bx)-1.0: bottom.append((bx,by))
    if len(pts)<3 or len(bottom)<3: return
    poly = pts + list(reversed(bottom))
    layer = pygame.Surface((SIZE,SIZE), pygame.SRCALPHA)
    pygame.draw.polygon(layer, COL_WATER, poly)
    surface.blit(layer,(0,0))

def color_temp(v):  return (78,205,196) if v<=25 else (255,107,107)
def color_noise(v):
    if v is None:
        return (126,211,33)
    if v <= 55:
        return (126,211,33)
    if v <= 70:
        return (255,194,62)
    if v <= 85:
        return (255,142,83)
    return (208,2,27)
def color_pm25(v):
    if v<=15: return (80,227,194)
    if v<=35: return (245,166,35)
    return (208,2,27)
def color_pm10(v):
    if v<=30: return (80,227,194)
    if v<=80: return (245,166,35)
    return (208,2,27)

def draw_glass_card(surface, rect):
    x,y,w,h = rect
    # 원형 카드로 변경 - 중심점과 반지름 계산
    center_x, center_y = x + w//2, y + h//2
    radius = min(w, h)//2
    
    # 그림자 (원형)
    shadow = pygame.Surface((radius*2+12, radius*2+12), pygame.SRCALPHA)
    pygame.draw.circle(shadow, CARD_SHADOW, (radius+6, radius+6), radius)
    surface.blit(shadow, (center_x-radius-6, center_y-radius+6))
    
    # 본체 (원형)
    body = pygame.Surface((radius*2, radius*2), pygame.SRCALPHA)
    pygame.draw.circle(body, (255,255,255,CARD_ALPHA), (radius, radius), radius)
    
    # 하이라이트 (작은 원형)
    hi_radius = max(4, radius//4)
    pygame.draw.circle(body, CARD_HILITE, (radius-radius//3, radius-radius//3), hi_radius)
    
    # 외곽선 (원형)
    pygame.draw.circle(body, CARD_STROKE, (radius, radius), radius, width=1)
    surface.blit(body, (center_x-radius, center_y-radius))

def draw_time_and_date(surface):
    now = datetime.now()
    blit_center(surface, font_time.render(now.strftime("%H:%M:%S"), True, COL_TEXT), CENTER, TOP_TIME_Y)
    blit_center(surface, font_date.render(now.strftime("%m/%d"), True, COL_TEXT), CENTER, TOP_DATE_Y)

def draw_sensor_cards(surface, data, wave, wave_offset_local):
    items=[]
    t  = data.get("temperature");    n = data.get("noise_level")
    h  = data.get("humidity");       p25= data.get("pm2_5"); p10=data.get("pm10")
    if t  is not None: items.append(("temp",  f"{t:.1f}°C", color_temp(t)))
    if n  is not None: items.append(("noise", f"{n:.1f} dB",  color_noise(n)))
    if h  is not None: items.append(("humi",  f"{h:.0f}%",  (30,144,255)))
    if p25 is not None:items.append(("pm25",  f"{p25}",     color_pm25(p25)))
    if p10 is not None:items.append(("pm10",  f"{p10}",     color_pm10(p10)))

    if not items:
        blit_center(surface, font_wait.render("센서 데이터 대기중…", True, COL_WAIT), CENTER, CENTER+100)
        return

    left_x  = CENTER - wave["radius"] + 28
    right_x = CENTER + wave["radius"] - 28
    xs = [lerp(left_x, right_x, (i+0.5)/len(items)) for i in range(len(items))]

    for (key, value, vcolor), x in zip(items, xs):
        phase = buoy_phases.setdefault(key, random.random()*math.tau)
        y0 = wave["surf_y"](x)
        buoyancy = 34
        bob = math.sin(wave_offset_local*1.2 + phase) * (wave["amplitude"]*0.25 + 1.5)
        y = y0 - buoyancy + bob

        rect = pygame.Rect(0,0, CARD_W, CARD_H); rect.center=(int(x), int(y))
        # 경계 보정
        if (x-CENTER)**2 + (y-CENTER)**2 > (WATER_RADIUS - CARD_H//2 - 4)**2:
            rect.y -= 6

        draw_glass_card(surface, rect)

        # 중심점 색점 (원형 카드 중앙 상단)
        pygame.draw.circle(surface, vcolor, (rect.centerx, rect.centery-12), DOT_R)

        # 라벨/값 (원형 카드 중앙에 정렬)
        label_txt = LABELS.get(key, key.upper())
        label_surf = font_label.render(label_txt, True, COL_TEXT)
        value_surf = font_value.render(value, True, vcolor)
        
        # 라벨과 값을 중앙 정렬
        blit_center(surface, label_surf, rect.centerx, rect.centery-8)
        blit_center(surface, value_surf, rect.centerx, rect.centery+10)

# ---------- 메인 루프 ----------
wave_offset = 0.0
running=True
while running:
    dt = clock.tick(FPS)/1000.0
    for ev in pygame.event.get():
        if ev.type==pygame.QUIT or (ev.type==pygame.KEYDOWN and ev.key==pygame.K_ESCAPE):
            running=False

    with data_lock:
        data = dict(sensor_data)

    # 모션 부스트
    if data.get("motion_detected"):
        motion_boost_until = max(motion_boost_until, time.time()+3.0)

    wave = compute_wave_params(data, wave_offset)
    wave_offset += wave["speed"]

    # 그리기
    draw_ring(screen)
    draw_temp_tint(screen, data)
    draw_water(screen, wave, data)   # ← 데이터 기반 (기본 수위 포함)
    draw_time_and_date(screen)
    draw_sensor_cards(screen, data, wave, wave_offset)

    pygame.display.flip()

pygame.quit()
