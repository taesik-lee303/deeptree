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
def find_monitor_offset(prefer_size=(240,240), fallback=(3840,0)):
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

# ---------- 디스플레이 크기 설정 ----------
BASE_DISPLAY_SIZE = 240  # 디자인 기준
DEFAULT_DISPLAY_SIZE = 480  # 2.1인치 원형 디스플레이 기본값

def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or not str(val).strip():
        return default
    try:
        return int(val)
    except Exception:
        return default

DISPLAY_SIZE = max(180, _env_int("DISPLAY_SENSOR_SIZE", DEFAULT_DISPLAY_SIZE))
SCALE = max(0.5, DISPLAY_SIZE / BASE_DISPLAY_SIZE)

def scale(value: float, minimum: int = 1) -> int:
    return max(minimum, int(round(value * SCALE)))

offset_x = _env_int("DISPLAY_SENSOR_OFFSET_X", 0)
offset_y = _env_int("DISPLAY_SENSOR_OFFSET_Y", -scale(20, 8))

pos = find_monitor_offset(prefer_size=(DISPLAY_SIZE, DISPLAY_SIZE))
adj_x = pos[0] + offset_x
adj_y = max(0, pos[1] + offset_y)
os.environ["SDL_VIDEO_WINDOW_POS"] = f"{adj_x},{adj_y}"
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
SIZE = DISPLAY_SIZE
CENTER = SIZE // 2
RADIUS = CENTER - scale(11, 1)
WATER_RADIUS = CENTER - scale(20, 1)
FPS = 60

# 파도
WAVE_BASE_A = 4.0
WAVE_BASE_SPEED = 0.05
WAVE_FAST_A = 15.0
WAVE_FAST_SPEED = 0.25
WAVE_KS = (0.018, 0.028, 0.042)

# 카드 - 디스플레이 크기에 따라 자동 조정
CARD_SIZES = {
    "primary": (scale(65, 20), scale(32, 12)),
    "secondary": (scale(55, 18), scale(28, 10)),
    "tertiary": (scale(45, 16), scale(22, 8)),
}
CARD_RADIUS = max(4, scale(8, 4))
CARD_ALPHA = 230
CARD_SHADOW = (12, 36, 55, 100)
CARD_STROKE = (255, 255, 255, 120)
CARD_HILITE = (255, 255, 255, 80)
DOT_R = max(2, scale(4, 2))

# 상단 텍스트 위치
TOP_TIME_Y = scale(38, 20)
TOP_DATE_Y = scale(52, 28)

# 개선된 색상 팔레트
COL_BG_RING = (200, 210, 220)
COL_WATER = (240, 248, 255, 220)
COL_TEXT = (20, 30, 40)
COL_WAIT = (120, 180, 220)
COL_DEMO = (255, 120, 120)

# 센서 우선순위 및 색상
SENSOR_PRIORITY = {
    "temperature": 1,
    "humidity": 1,
    "noise_level": 2,
    "pm2_5": 2,
    "pm10": 3,
    "motion_detected": 0  # 모션은 별도 처리
}

# 개선된 색상 시스템
COLOR_SYSTEM = {
    "excellent": (80, 227, 194),    # 초록
    "good": (126, 211, 33),         # 연두
    "moderate": (255, 194, 62),     # 노랑
    "poor": (255, 142, 83),         # 주황
    "hazardous": (208, 2, 27),      # 빨강
    "neutral": (120, 140, 160)      # 회색
}

screen = pygame.display.set_mode((SIZE, SIZE))
pygame.display.set_caption("Smart Circular Display")
print(f"[SensorDisplay] Display size: {SIZE}x{SIZE} (scale={SCALE:.2f})")
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

# 2.1인치 디스플레이에 맞게 폰트 크기 조정
font_time  = make_font(max(12, scale(18, 12)), True)
font_date  = make_font(max(8, scale(9, 6)), True)
font_label = make_font(max(6, scale(7, 5)), True)
font_value = make_font(max(8, scale(10, 6)), True)
font_wait  = make_font(max(8, scale(9, 6)), False)

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
fallback_data = dict(sensor_data)
data_lock = threading.Lock()
last_sensor_update = 0.0
FALLBACK_TIMEOUT = float(os.getenv("DISPLAY_SENSOR_FALLBACK_TIMEOUT", "10"))
FORCE_DEMO_MODE = os.getenv("DISPLAY_DEMO_MODE", "0") == "1"

DEFAULT_KAFKA_TOPICS = ["sensors.uart", "display-data", "sensor-events"]
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
    "temp_c":"temperature",  # UART Producer가 보내는 형식
    "temperature":"temperature",
    "temperature_c":"temperature",
    "hum":"humidity",
    "humidity":"humidity",
    "humidity_pct":"humidity",
    "pm25":"pm2_5",
    "pm_2_5":"pm2_5",
    "pm2_5":"pm2_5",
    "pm10":"pm10",
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
    global last_sensor_update
    if not KAFKA_ENABLED:
        reason = f" ({_KAFKA_IMPORT_ERROR})" if "_KAFKA_IMPORT_ERROR" in globals() and _KAFKA_IMPORT_ERROR else ""
        print("[i] Kafka 라이브러리를 사용할 수 없습니다." + reason)
        return

    topics = resolve_kafka_topics()
    if not topics:
        print("[i] Kafka 토픽이 설정되지 않았습니다.")
        return

    if kafka_settings is None and "_KAFKA_SETTINGS_IMPORT_ERROR" in globals() and _KAFKA_SETTINGS_IMPORT_ERROR:
        print(f"[i] Kafka 설정 오류: {_KAFKA_SETTINGS_IMPORT_ERROR}. 기본값을 사용합니다.")

    encoding = resolve_value_encoding()
    kwargs = resolve_kafka_kwargs()
    kwargs = dict(kwargs)
    kwargs.pop("value_deserializer", None)
    kwargs.pop("key_deserializer", None)
    kwargs.setdefault("consumer_timeout_ms", 1000)
    kwargs.setdefault("enable_auto_commit", True)
    
    # Consumer Group ID 확인 및 로그
    group_id = kwargs.get("group_id")
    auto_offset_reset = kwargs.get("auto_offset_reset", "latest")

    bootstrap = kwargs.get("bootstrap_servers")
    # 한글 인코딩 문제 방지를 위해 영문으로 출력
    print(f"[SensorDisplay] Kafka connecting: topics={topics}, bootstrap={bootstrap}")
    print(f"[SensorDisplay] Consumer config: group_id={group_id}, auto_offset_reset={auto_offset_reset}")

    try:
        consumer = KafkaConsumer(*topics, value_deserializer=lambda x: x, **kwargs)
        print("[SensorDisplay] Kafka consumer created successfully")
        
        # Consumer가 실제로 할당된 파티션 확인
        assignment = consumer.assignment()
        if assignment:
            print(f"[SensorDisplay] Assigned partitions: {assignment}")
        else:
            print("[SensorDisplay] WARNING: No partitions assigned! Check if:")
            print("  - Topic exists: sensors.uart")
            print("  - UART Producer is running and sending data")
            print("  - Consumer group is not blocked by another consumer")
    except Exception as e:
        print(f"[SensorDisplay] Kafka connection failed: {e}")
        import traceback
        traceback.print_exc()
        return

    message_count = 0
    last_log_time = time.time()
    no_data_count = 0
    
    print("[SensorDisplay] Waiting for Kafka messages...")
    
    # Consumer가 파티션에 할당될 때까지 대기
    import time as time_module
    max_wait = 10
    waited = 0
    while not consumer.assignment() and waited < max_wait:
        time_module.sleep(0.5)
        waited += 0.5
        consumer.poll(timeout_ms=100)
    
    if not consumer.assignment():
        print("[SensorDisplay] ERROR: Consumer failed to get partition assignment!")
        print("[SensorDisplay] Possible causes:")
        print("  1. Topic 'sensors.uart' does not exist")
        print("  2. No data has been published to the topic yet")
        print("  3. Another consumer with same group_id is blocking")
        print("[SensorDisplay] Try:")
        print("  - Run UART Producer: python -m networks.kafka.uart_producer")
        print("  - Check topic exists: kafka-topics --list --bootstrap-server localhost:9092")
        print("  - Use different group_id or set KAFKA_OFFSET_RESET=earliest")
    
    try:
        while True:
            try:
                records = consumer.poll(timeout_ms=1000)
            except Exception as e:
                print(f"[SensorDisplay] Kafka poll error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1.0)
                continue
            
            if not records:
                no_data_count += 1
                # 10초마다 대기 중임을 알림 (더 자주 알림)
                if no_data_count % 10 == 0:
                    print(f"[SensorDisplay] No messages received yet... (waited {no_data_count} polls, ~{no_data_count} seconds)")
                    # 파티션 할당 상태 재확인
                    assignment = consumer.assignment()
                    if assignment:
                        print(f"[SensorDisplay] Still assigned to partitions: {assignment}")
                    else:
                        print("[SensorDisplay] WARNING: Lost partition assignment!")
                continue
            
            # 데이터 수신했으므로 카운터 리셋
            no_data_count = 0
            
            for batch in records.values():
                for msg in batch:
                    payload = decode_payload(msg.value, encoding)
                    if payload is None:
                        print("[SensorDisplay] Payload decode failed")
                        continue
                    
                    # 첫 메시지와 10개마다 원본 페이로드 로그
                    if message_count == 0 or message_count % 10 == 0:
                        print(f"[SensorDisplay] Message received ({message_count + 1}): {json.dumps(payload, ensure_ascii=False)[:200]}")
                    
                    updates = extract_sensor_values(payload)
                    if not updates:
                        # 디버그: 업데이트가 없는 경우 로그 출력
                        now = time.time()
                        if now - last_log_time > 10:
                            print(f"[SensorDisplay] Received but no updates extracted: {json.dumps(payload, ensure_ascii=False)[:200]}")
                            last_log_time = now
                        continue
                    
                    message_count += 1
                    # 첫 메시지와 이후 10개마다 로그 출력
                    if message_count <= 1 or message_count % 10 == 0:
                        print(f"[SensorDisplay] Sensor data updated ({message_count}): {updates}")
                    with data_lock:
                        sensor_data.update(updates)
                        global last_sensor_update
                        last_sensor_update = time.time()
    finally:
        try:
            consumer.close()
        except Exception:
            pass


def demo_feeder():
    t0 = time.time()
    while True:
        t = time.time() - t0
        with data_lock:
            fallback_data["temperature"] = 23.5 + 2.0 * math.sin(t * 0.12)
            fallback_data["humidity"] = 48 + 22 * (math.sin(t * 0.07) * 0.5 + 0.5)
            fallback_data["pm2_5"] = int(10 + 20 * (math.sin(t * 0.05) * 0.5 + 0.5))
            fallback_data["pm10"] = int(20 + 40 * (math.sin(t * 0.045 + 1.2) * 0.5 + 0.5))
            fallback_data["noise_level"] = int(35 + 25 * (math.sin(t * 0.35) * 0.5 + 0.5))
            fallback_data["motion_detected"] = (int(t) % 12 == 0)
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
    """개선된 배경 그리기"""
    surface.fill((255, 255, 255))
    
    # 그라데이션 배경 링
    for i in range(RADIUS-2, 0, -2):
        alpha = int(255 * (1 - i / RADIUS) * 0.3)
        color = (*COL_BG_RING, alpha)
        temp_surface = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
        pygame.draw.circle(temp_surface, color, (CENTER, CENTER), i, 2)
        surface.blit(temp_surface, (0, 0))
    
    # 메인 링
    pygame.draw.circle(surface, COL_BG_RING, (CENTER, CENTER), RADIUS-2, 3)

def draw_temp_tint(surface, data):
    """개선된 온도 배경 틴트"""
    t = data.get("temperature")
    if t is None: 
        return
    
    # 온도에 따른 그라데이션 색상
    if t <= 18:
        col = (230, 243, 255)
    elif t <= 22:
        col = (232, 245, 232)
    elif t <= 26:
        col = (255, 244, 230)
    elif t <= 30:
        col = (255, 230, 204)
    else:
        intensity = clamp((t-30)/10, 0, 1)
        rv = int(255 - intensity*50)
        col = (rv, int(rv*0.4), int(rv*0.4))
    
    # 그라데이션 원형 배경
    for i in range(RADIUS-3, 0, -3):
        alpha = int(180 * (1 - i / RADIUS))
        gradient_color = (*col, alpha)
        temp_surface = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
        pygame.draw.circle(temp_surface, gradient_color, (CENTER, CENTER), i)
        surface.blit(temp_surface, (0, 0))

def draw_water(surface, wave, data):
    """개선된 물결 효과 그리기"""
    radius = wave["radius"]
    surf_y = wave["surf_y"]
    min_x = CENTER - radius
    max_x = CENTER + radius
    steps = max(120, int(150 * SCALE))
    
    # 물 표면 포인트 계산
    pts = []
    for i in range(steps):
        x = lerp(min_x, max_x, i/(steps-1))
        y = surf_y(x)
        pts.append((x, y))
    
    # 아래쪽 원 경계
    bottom = []
    steps2 = 200
    for i in range(steps2):
        ang = math.pi - (i * math.pi / (steps2-1))
        bx = CENTER + math.cos(ang) * radius
        by = CENTER + math.sin(ang) * radius
        if by >= surf_y(bx) - 1.0:
            bottom.append((bx, by))
    
    if len(pts) < 3 or len(bottom) < 3:
        return
    
    # 물 표면 그리기 (그라데이션 효과)
    poly = pts + list(reversed(bottom))
    layer = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
    
    # 메인 물 표면
    pygame.draw.polygon(layer, COL_WATER, poly)
    
    # 물 표면 하이라이트 (빛 반사 효과)
    if len(pts) > 10:
        highlight_pts = []
        for i in range(0, len(pts), 3):  # 일부 포인트만 선택
            x, y = pts[i]
            highlight_pts.append((x, y - 2))
        if len(highlight_pts) > 2:
            pygame.draw.polygon(layer, (255, 255, 255, 60), highlight_pts)
    
    surface.blit(layer, (0, 0))

def get_health_status(value, thresholds):
    """값에 따른 건강 상태 반환"""
    if value is None:
        return "neutral"
    if value <= thresholds[0]:
        return "excellent"
    elif value <= thresholds[1]:
        return "good"
    elif value <= thresholds[2]:
        return "moderate"
    elif value <= thresholds[3]:
        return "poor"
    else:
        return "hazardous"

def color_temp(v):
    status = get_health_status(v, [18, 25, 30, 35])
    return COLOR_SYSTEM[status]

def color_noise(v):
    status = get_health_status(v, [40, 55, 70, 85])
    return COLOR_SYSTEM[status]

def color_pm25(v):
    status = get_health_status(v, [15, 35, 75, 150])
    return COLOR_SYSTEM[status]

def color_pm10(v):
    status = get_health_status(v, [30, 80, 150, 300])
    return COLOR_SYSTEM[status]

def color_humidity(v):
    status = get_health_status(v, [30, 50, 70, 80])
    return COLOR_SYSTEM[status]

def draw_glass_card(surface, rect, card_type="secondary", pulse_alpha=1.0):
    """개선된 글래스 카드 그리기"""
    x, y, w, h = rect
    center_x, center_y = x + w//2, y + h//2
    radius = min(w, h)//2
    
    # 카드 타입에 따른 크기 조정
    size_multiplier = {"primary": 1.1, "secondary": 1.0, "tertiary": 0.9}[card_type]
    radius = int(radius * size_multiplier)
    
    # 펄스 효과 (데이터 변화 시)
    alpha_multiplier = 0.8 + 0.2 * pulse_alpha
    
    # 그림자 (원형) - 더 부드러운 그림자
    shadow_size = radius*2+16
    shadow = pygame.Surface((shadow_size, shadow_size), pygame.SRCALPHA)
    shadow_color = (*CARD_SHADOW[:3], int(CARD_SHADOW[3] * alpha_multiplier))
    pygame.draw.circle(shadow, shadow_color, (radius+8, radius+8), radius)
    surface.blit(shadow, (center_x-radius-8, center_y-radius+8))
    
    # 본체 (원형) - 그라데이션 효과
    body = pygame.Surface((radius*2, radius*2), pygame.SRCALPHA)
    body_alpha = int(CARD_ALPHA * alpha_multiplier)
    pygame.draw.circle(body, (255, 255, 255, body_alpha), (radius, radius), radius)
    
    # 하이라이트 (더 자연스러운 그라데이션)
    hi_radius = max(6, radius//3)
    hi_alpha = int(CARD_HILITE[3] * alpha_multiplier)
    pygame.draw.circle(body, (*CARD_HILITE[:3], hi_alpha), 
                      (radius-radius//3, radius-radius//3), hi_radius)
    
    # 외곽선 (원형) - 더 선명한 테두리
    stroke_alpha = int(CARD_STROKE[3] * alpha_multiplier)
    pygame.draw.circle(body, (*CARD_STROKE[:3], stroke_alpha), 
                      (radius, radius), radius, width=2)
    surface.blit(body, (center_x-radius, center_y-radius))

def draw_time_and_date(surface):
    """개선된 시간/날짜 표시 (2.1인치 디스플레이용)"""
    now = datetime.now()
    
    # 시간 배경 (반투명)
    time_bg_w = scale(100, 40)
    time_bg_h = scale(25, 12)
    time_bg = pygame.Surface((time_bg_w, time_bg_h), pygame.SRCALPHA)
    pygame.draw.rect(time_bg, (255, 255, 255, 120), (0, 0, time_bg_w, time_bg_h), border_radius=scale(12, 6))
    surface.blit(time_bg, (CENTER - time_bg_w // 2, TOP_TIME_Y - time_bg_h // 2))
    
    # 시간 텍스트 (그림자 효과)
    time_text = now.strftime("%H:%M")
    time_surf = font_time.render(time_text, True, COL_TEXT)
    time_shadow = font_time.render(time_text, True, (0, 0, 0, 120))
    
    # 그림자 그리기
    blit_center(surface, time_shadow, CENTER + scale(1, 1), TOP_TIME_Y + scale(1, 1))
    blit_center(surface, time_surf, CENTER, TOP_TIME_Y)
    
    # 날짜 텍스트 (간소화)
    date_text = now.strftime("%m/%d")
    date_surf = font_date.render(date_text, True, COL_TEXT)
    blit_center(surface, date_surf, CENTER, TOP_DATE_Y)

def check_card_collision(rect1, rect2, margin=None):
    """두 카드 간 충돌 감지 - 마진 증가로 겹침 방지 (2.1인치에 맞게)"""
    if margin is None:
        margin = scale(8, 4)
    return (abs(rect1.centerx - rect2.centerx) < (rect1.width + rect2.width) // 2 + margin and
            abs(rect1.centery - rect2.centery) < (rect1.height + rect2.height) // 2 + margin)

def optimize_card_positions(items, base_radius=None):
    """카드 위치 최적화 - 겹침 방지 (2.1인치 디스플레이용)"""
    num_items = len(items)
    if num_items == 0:
        return []
    
    if base_radius is None:
        base_radius = scale(40, 16)
    
    # 카드 개수에 따른 동적 반지름 조정
    if num_items >= 4:
        base_radius = min(scale(80, 30), scale(30 + num_items * 8, 20))
    
    # 기본 위치 계산
    if num_items == 1:
        positions = [(CENTER, CENTER - scale(30, 15))]
    elif num_items == 2:
        positions = [
            (CENTER - scale(40, 20), CENTER - scale(20, 10)),
            (CENTER + scale(40, 20), CENTER - scale(20, 10)),
        ]
    elif num_items == 3:
        positions = [
            (CENTER - scale(45, 20), CENTER - scale(10, 5)),
            (CENTER, CENTER - scale(30, 15)),
            (CENTER + scale(45, 20), CENTER - scale(10, 5)),
        ]
    else:
        # 4개 이상일 때 원형 배치
        angle_step = 2 * math.pi / num_items
        positions = []
        for i in range(num_items):
            angle = i * angle_step - math.pi/2  # 12시부터 시작
            x = CENTER + base_radius * math.cos(angle)
            y = CENTER + base_radius * math.sin(angle)
            positions.append((x, y))
    
    # 카드 크기 정보 수집
    card_rects = []
    for i, (key, value, vcolor, card_type) in enumerate(items):
        card_w, card_h = CARD_SIZES[card_type]
        rect = pygame.Rect(0, 0, card_w, card_h)
        rect.center = positions[i]
        card_rects.append(rect)
    
    # 충돌 해결 알고리즘
    max_iterations = 50
    for iteration in range(max_iterations):
        collision_found = False
        
        for i in range(len(card_rects)):
            for j in range(i + 1, len(card_rects)):
                if check_card_collision(card_rects[i], card_rects[j]):
                    collision_found = True
                    
                    # 충돌 해결: 두 카드를 서로 멀리 이동
                    dx = card_rects[i].centerx - card_rects[j].centerx
                    dy = card_rects[i].centery - card_rects[j].centery
                    distance = math.sqrt(dx*dx + dy*dy)
                    
                    if distance < 1:  # 거의 같은 위치에 있을 때
                        # 랜덤 방향으로 분리
                        angle = random.random() * 2 * math.pi
                        dx = math.cos(angle)
                        dy = math.sin(angle)
                        distance = 1
                    
                    # 분리 거리 계산 - 더 큰 여유 공간 (2.1인치에 맞게)
                    min_distance = (card_rects[i].width + card_rects[j].width) // 2 + scale(15, 6)
                    move_distance = (min_distance - distance) / 2
                    
                    # 위치 조정
                    move_x = (dx / distance) * move_distance
                    move_y = (dy / distance) * move_distance
                    
                    # 새 위치 계산
                    new_x1 = card_rects[i].centerx + move_x
                    new_y1 = card_rects[i].centery + move_y
                    new_x2 = card_rects[j].centerx - move_x
                    new_y2 = card_rects[j].centery - move_y
                    
                    # 경계 내로 제한 - 더 엄격한 경계 체크 (2.1인치에 맞게)
                    max_distance = WATER_RADIUS - max(card_rects[i].height, card_rects[j].height) // 2 - scale(10, 4)
                    for new_x, new_y, rect in [(new_x1, new_y1, card_rects[i]), (new_x2, new_y2, card_rects[j])]:
                        distance_from_center = math.sqrt((new_x - CENTER)**2 + (new_y - CENTER)**2)
                        if distance_from_center > max_distance:
                            angle = math.atan2(new_y - CENTER, new_x - CENTER)
                            new_x = CENTER + max_distance * math.cos(angle)
                            new_y = CENTER + max_distance * math.sin(angle)
                        rect.center = (int(new_x), int(new_y))
        
        if not collision_found:
            break
    
    # 최종 위치 반환
    return [(rect.centerx, rect.centery) for rect in card_rects]

def draw_sensor_cards(surface, data, wave, wave_offset_local):
    """개선된 센서 카드 그리기 - 겹침 방지"""
    items = []
    t = data.get("temperature")
    n = data.get("noise_level")
    h = data.get("humidity")
    p25 = data.get("pm2_5")
    p10 = data.get("pm10")
    
    # 센서 데이터 수집 (우선순위 순으로)
    if t is not None: 
        items.append(("temp", f"{t:.1f}°C", color_temp(t), "primary"))
    if h is not None: 
        items.append(("humi", f"{h:.0f}%", color_humidity(h), "primary"))
    if n is not None: 
        items.append(("noise", f"{n:.1f} dB", color_noise(n), "secondary"))
    if p25 is not None: 
        items.append(("pm25", f"{p25}", color_pm25(p25), "secondary"))
    if p10 is not None: 
        items.append(("pm10", f"{p10}", color_pm10(p10), "tertiary"))

    if not items:
        blit_center(surface, font_wait.render("센서 데이터 대기중…", True, COL_WAIT), CENTER, CENTER + scale(50, 20))
        return

    # 최적화된 위치 계산
    positions = optimize_card_positions(items)

    for (key, value, vcolor, card_type), (x, y) in zip(items, positions):
        # 파도 효과 적용 (2.1인치에 맞게 조정)
        phase = buoy_phases.setdefault(key, random.random() * math.tau)
        wave_y = wave["surf_y"](x) if abs(x - CENTER) < wave["radius"] else y
        bob = math.sin(wave_offset_local * 1.2 + phase) * (wave["amplitude"] * 0.15 + 1.0)
        final_y = wave_y - scale(15, 6) + bob
        
        # 카드 크기 결정
        card_w, card_h = CARD_SIZES[card_type]
        rect = pygame.Rect(0, 0, card_w, card_h)
        rect.center = (int(x), int(final_y))
        
        # 경계 보정 - 더 엄격한 경계 체크 (2.1인치에 맞게)
        distance_from_center = math.sqrt((x - CENTER)**2 + (final_y - CENTER)**2)
        max_distance = WATER_RADIUS - card_h//2 - scale(8, 4)
        if distance_from_center > max_distance:
            # 카드가 원 밖으로 나가지 않도록 조정
            angle = math.atan2(final_y - CENTER, x - CENTER)
            x = CENTER + max_distance * math.cos(angle)
            y = CENTER + max_distance * math.sin(angle)
            rect.center = (int(x), int(y))

        # 펄스 효과 (데이터 변화 감지)
        pulse_alpha = 0.8 + 0.2 * math.sin(time.time() * 3.0)
        
        # 카드 그리기
        draw_glass_card(surface, rect, card_type, pulse_alpha)

        # 상태 표시 점 (2.1인치에 맞게 조정)
        status_dot_r = DOT_R + (1 if card_type == "primary" else 0)
        pygame.draw.circle(surface, vcolor, (rect.centerx, rect.centery - scale(8, 4)), status_dot_r)
        
        # 상태 표시 링 (위험 상태일 때)
        if vcolor == COLOR_SYSTEM["hazardous"]:
            pygame.draw.circle(surface, vcolor, (rect.centerx, rect.centery - scale(8, 4)), 
                             status_dot_r + 2, width=1)

        # 라벨/값 텍스트
        label_txt = LABELS.get(key, key.upper())
        label_surf = font_label.render(label_txt, True, COL_TEXT)
        value_surf = font_value.render(value, True, vcolor)
        
        # 텍스트 중앙 정렬 (2.1인치에 맞게 조정)
        blit_center(surface, label_surf, rect.centerx, rect.centery - scale(4, 2))
        blit_center(surface, value_surf, rect.centerx, rect.centery + scale(6, 3))

# ---------- 메인 루프 ----------
wave_offset = 0.0
running=True
while running:
    dt = clock.tick(FPS)/1000.0
    for ev in pygame.event.get():
        if ev.type==pygame.QUIT or (ev.type==pygame.KEYDOWN and ev.key==pygame.K_ESCAPE):
            running=False

    with data_lock:
        live_data = dict(sensor_data)
        demo_snapshot = dict(fallback_data)

    now = time.time()
    using_fallback = FORCE_DEMO_MODE or (now - last_sensor_update > FALLBACK_TIMEOUT)
    if using_fallback:
        data = demo_snapshot
    else:
        data = live_data

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

    if using_fallback:
        demo_text = font_wait.render("DEMO MODE", True, COL_DEMO)
        screen.blit(demo_text, (scale(10, 4), SIZE - scale(20, 8)))

    pygame.display.flip()

pygame.quit()
