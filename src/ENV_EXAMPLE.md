
MQTT_HOST=203.250.148.52


MQTT_PORT=20516


MQTT_TOPIC_BASE=taesik/therapy


# Pico 디바이스용 토픽
MQTT_PICO_TOPIC=pico/color
```


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




## 현재 기본값

환경변수가 설정되지 않으면 다음 기본값이 사용됩니다:

- `MQTT_HOST`: `203.250.148.52`
- `MQTT_PORT`: `20516`
- `MQTT_TOPIC_BASE`: `taesik/therapy`
- `MQTT_PICO_TOPIC`: `pico/color`
- `KAFKA_BOOTSTRAP_SERVERS`: `localhost:9092`
- `KAFKA_SENSOR_TOPIC`: `sensors.uart`
- `RPPG_DEBUG_VISUAL`: `1`

