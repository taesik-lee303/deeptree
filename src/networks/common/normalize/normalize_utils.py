import logging

logger = logging.getLogger(__name__)

CANONICAL_MAP = {
    "noise": "noise",
    "noise_db": "noise",
    "sound": "noise",
    "sound_db": "noise",
    "pir": "pir",
    "motion": "pir",
    "motion_detected": "pir",
    "ir": "pir",
    "temp": "temp",
    "temperature": "temp",
    "t": "temp",
    "humid": "humid",
    "humidity": "humid",
    "h": "humid",
    "pm25": "pm25",
    "pm2_5": "pm25",
    "pm2.5": "pm25",
    "pm10": "pm10",
    "pm10_0": "pm10",
    "pm1": "pm1",
    "pm1_0": "pm1"
}

NUMERIC_KEYS = {"noise","temp","humid","pm25","pm10","pm1"}

def _coerce_value(canon_key, value):
    if canon_key == "pir":
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if value > 0 else 0
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("1","true","high","on","motion","detected"):
                return 1
            return 0
        return 0
    if canon_key in NUMERIC_KEYS:
        try:
            return float(value)
        except Exception:
            return None
    return value

def normalize_dict(parsed: dict):
    out = {}
    extras = {}
    for k, v in parsed.items():
        lk = str(k).strip().lower().replace(" ", "_")
        canon = CANONICAL_MAP.get(lk)
        if canon:
            cv = _coerce_value(canon, v)
            if cv is None:
                continue
            out[canon] = cv
        else:
            extras[lk] = v
    return out, extras
