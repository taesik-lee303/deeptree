# 환경변수 설정 예시 파일

> **참고용 예시입니다.** 실제 사용 시에는 `.env` 파일을 생성하고 필요한 값만 설정하세요.

## 사용 방법

1. 프로젝트 루트 또는 `src/` 폴더에 `.env` 파일 생성
2. 아래 예시에서 필요한 값만 복사하여 설정
3. **주의**: 현재 `mqtt_config.py`는 `load_dotenv()`를 사용하지 않으므로, 
   환경변수는 시스템 환경변수나 systemd의 `EnvironmentFile`로 설정해야 합니다.

---

## MQTT 설정

```bash
# MQTT 브로커 호스트 주소
MQTT_HOST=203.250.148.52

# MQTT 브로커 포트
MQTT_PORT=20516

# MQTT 토픽 베이스
# 최종 토픽: {MQTT_TOPIC_BASE}/total, {MQTT_TOPIC_BASE}/status
MQTT_TOPIC_BASE=taesik/therapy

# MQTT 인증 (선택사항)
# MQTT_USERNAME=your_username
# MQTT_PASSWORD=your_password

# MQTT TLS 사용 여부 (true/false)
MQTT_TLS=false

# Pico 디바이스용 토픽
MQTT_PICO_TOPIC=pico/color
```

**설정 위치**: `src/networks/mqtt/mqtt_config.py`

---

## Kafka 설정

```bash
# Kafka 브로커 서버 목록 (쉼표로 구분)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# 센서 데이터 토픽
KAFKA_SENSOR_TOPIC=sensors.uart

# Consumer 그룹 ID
KAFKA_GROUP_ID=uart-display

# 보안 프로토콜 (PLAINTEXT, SSL, SASL_PLAINTEXT, SASL_SSL)
KAFKA_SECURITY_PROTOCOL=PLAINTEXT

# SASL 인증 (선택사항)
# KAFKA_SASL_MECHANISM=PLAIN
# KAFKA_SASL_USERNAME=your_username
# KAFKA_SASL_PASSWORD=your_password

# 오프셋 리셋 정책 (earliest, latest)
KAFKA_OFFSET_RESET=latest

# 값 인코딩
KAFKA_VALUE_ENCODING=utf-8
```

**설정 위치**: `src/networks/kafka/kafka_config.py`

---

## Kafka - 케어콜 감정 이벤트 프로듀서

```bash
# 감정 이벤트 발행 활성화 (0=비활성, 1=활성)
KAFKA_EMO_ENABLED=1

# 감정 이벤트 토픽
KAFKA_EMO_TOPIC=carecall.emotion

# 클라이언트 ID
KAFKA_EMO_CLIENT_ID=carecall-edge

# ACK 설정 (0, 1, all)
KAFKA_EMO_ACKS=0

# 배치 지연 시간 (ms)
KAFKA_EMO_LINGER_MS=20

# 배치 크기
KAFKA_EMO_BATCH_SIZE=16384

# 압축 타입 (gzip, snappy, lz4, zstd)
# KAFKA_EMO_COMPRESSION=gzip
```

**설정 위치**: `src/networks/kafka/kafka_config.py`

---

## Display 설정

```bash
# 디스플레이 새로고침 주기 (Hz)
DISPLAY_REFRESH_HZ=1.0

# 폰트 경로 (선택사항)
# DISPLAY_FONT_PATH=/path/to/font.ttf

# 디스플레이 직경 (픽셀)
DISPLAY_DIAMETER_PIXELS=480
```

**설정 위치**: `src/networks/kafka/kafka_config.py`

---

## Thermal rPPG 설정

```bash
# 디버그 시각화 활성화 (0=비활성, 1=활성)
RPPG_DEBUG_VISUAL=1
```

**설정 위치**: `src/modules/rppg/thermal_rppg.py`

---

## Carecall 설정

```bash
# Whisper 모델 설정
# WHISPER_MODEL=base
# WHISPER_LANG=ko

# 오디오 설정
# VAD_AGGRESSIVENESS=2
# SD_RATE=16000
# SD_USE_RAW=0
# SD_INPUT_DEVICE=default

# OpenAI API 키
# OPENAI_API_KEY=sk-...

# 활성화 조건 설정
# CARECALL_NOISE_THRESHOLD=500
# CARECALL_MOTION_REQUIRED=true
# CARECALL_MOTION_WINDOW_SEC=2.0
# CARECALL_SENSOR_TIMEOUT_SEC=5.0
# CARECALL_WAKE_PHRASES=케어콜 불러줘,안녕
```

**설정 위치**: `src/modules/carecall/config.py`

---

## 로깅 설정

```bash
# 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO
```

---

## 라즈베리파이5에서 사용 방법

### 방법 1: Systemd 서비스의 EnvironmentFile 사용

```ini
# /etc/systemd/system/thermal-rppg.service
[Service]
EnvironmentFile=/opt/deepcare-edge/.env
ExecStart=/usr/bin/python3 -m modules.rppg.thermal_rppg
```

`.env` 파일을 `/opt/deepcare-edge/.env`에 생성하고 위 형식으로 작성

### 방법 2: 시스템 환경변수 설정

```bash
# /etc/environment 또는 ~/.bashrc에 추가
export MQTT_TOPIC_BASE=taesik/therapy
export MQTT_HOST=203.250.148.52
export MQTT_PORT=20516
```

### 방법 3: Python 코드에서 load_dotenv() 사용

현재는 사용하지 않지만, 추가하려면:

```python
# mqtt_config.py 상단에 추가
from dotenv import load_dotenv
load_dotenv()  # .env 파일 자동 로드
```

---

## 현재 기본값

환경변수가 설정되지 않으면 다음 기본값이 사용됩니다:

- `MQTT_HOST`: `203.250.148.52`
- `MQTT_PORT`: `20516`
- `MQTT_TOPIC_BASE`: `taesik/therapy`
- `MQTT_PICO_TOPIC`: `pico/color`
- `KAFKA_BOOTSTRAP_SERVERS`: `localhost:9092`
- `KAFKA_SENSOR_TOPIC`: `sensors.uart`
- `RPPG_DEBUG_VISUAL`: `1`

