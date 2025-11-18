# 센서 디스플레이 문제 해결 가이드

## 문제: 센서 데이터가 디스플레이에 표시되지 않음

### 원인 분석

센서 데이터가 디스플레이에 표시되지 않는 주요 원인:

1. **UART Producer가 실행되지 않음**
   - `display-switcher`가 `--enable-uart-producer` 옵션 없이 실행됨
   - UART Producer가 실행되지 않으면 센서 데이터가 Kafka로 전송되지 않음

2. **Kafka가 실행되지 않음**
   - Kafka 브로커가 실행되지 않으면 데이터를 받을 수 없음

3. **토픽 불일치**
   - UART Producer는 `sensors.uart` 토픽에 발행
   - Sensor Display는 올바른 토픽을 구독해야 함

4. **센서 데이터 형식 불일치**
   - Pico에서 보내는 데이터 형식이 예상과 다를 수 있음

---

## 해결 방법

### 1. UART Producer 실행 확인

`launcher.py`를 실행할 때 `display-switcher`가 `--enable-uart-producer` 옵션으로 실행되는지 확인:

```bash
# launcher.py는 기본적으로 display-switcher를 --enable-uart-producer로 실행합니다
python -m apps.launcher
```

수동으로 확인:

```bash
# display-switcher가 UART Producer를 실행하는지 확인
ps aux | grep uart_producer
```

### 2. Kafka 실행 확인

```bash
# Kafka 브로커 실행 확인
sudo systemctl status kafka
# 또는
netstat -tlnp | grep 9092
```

로컬 Kafka가 실행되지 않은 경우:

```bash
# Kafka 설치 및 실행 (예시)
# 방법은 Kafka 설치 방법에 따라 다릅니다
```

### 3. 토픽 확인

센서 데이터가 올바른 토픽에 발행되는지 확인:

```bash
# Kafka 컨슈머로 토픽 확인 (kafka-console-consumer 사용)
kafka-console-consumer --bootstrap-server localhost:9092 --topic sensors.uart --from-beginning
```

또는 Python으로 확인:

```python
from kafka import KafkaConsumer
consumer = KafkaConsumer('sensors.uart', bootstrap_servers=['localhost:9092'])
for msg in consumer:
    print(msg.value)
```

### 4. 환경 변수 설정

`.env` 파일 또는 환경 변수로 토픽 설정:

```bash
# .env 파일에 추가
KAFKA_SENSOR_TOPIC=sensors.uart
DISPLAY_SENSOR_TOPICS=sensors.uart,display-data,sensor-events
```

### 5. 센서 데이터 형식 확인

Pico에서 보내는 데이터 형식 확인:

```bash
# UART 직접 확인
python -m networks.uart.uart_receiver --dev /dev/serial0 --baud 9600
```

예상 형식:
```json
{
  "ts": 1234567890,
  "device_id": "pico-001",
  "sensors": {
    "dht22": {"temp_c": 23.5, "hum": 45.0},
    "sound": {"noise": 500},
    "ir": {"pir": 1},
    "pm": {"pm25": 15, "pm10": 25}
  }
}
```

또는:
```json
{
  "ts": 1234567890,
  "device_id": "pico-001",
  "dht22": {"temp_c": 23.5, "hum": 45.0},
  "sound": {"noise": 500},
  "ir": {"pir": 1},
  "pm": {"pm25": 15, "pm10": 25}
}
```

### 6. 디버그 모드로 실행

각 컴포넌트를 디버그 모드로 실행하여 문제 확인:

```bash
# UART Producer 디버그 모드
python -m networks.kafka.uart_producer --debug

# Sensor Display는 자동으로 Kafka 연결 상태를 출력합니다
python -m modules.display.sensor_display
```

---

## 체크리스트

다음 항목을 순서대로 확인하세요:

- [ ] **UART 연결 확인**
  ```bash
  ls -l /dev/serial0
  # 또는
  ls -l /dev/ttyAMA0
  ```

- [ ] **UART Producer 실행 확인**
  ```bash
  ps aux | grep uart_producer
  ```

- [ ] **Kafka 브로커 실행 확인**
  ```bash
  netstat -tlnp | grep 9092
  ```

- [ ] **Kafka 토픽에 데이터 발행 확인**
  ```bash
  kafka-console-consumer --bootstrap-server localhost:9092 --topic sensors.uart --from-beginning
  ```

- [ ] **Sensor Display가 올바른 토픽 구독 확인**
  - `sensor_display.py` 실행 시 로그에서 토픽 확인
  - `[i] Kafka 연결: topics=..., bootstrap=...` 메시지 확인

- [ ] **환경 변수 확인**
  ```bash
  echo $KAFKA_SENSOR_TOPIC
  echo $DISPLAY_SENSOR_TOPICS
  echo $KAFKA_BOOTSTRAP_SERVERS
  ```

- [ ] **센서 데이터 형식 확인**
  - Pico에서 보내는 JSON 형식이 올바른지 확인
  - `uart_receiver.py`로 직접 확인

---

## 일반적인 문제와 해결책

### 문제 1: "Kafka 연결 실패"

**원인**: Kafka 브로커가 실행되지 않음

**해결**:
```bash
# Kafka 브로커 시작
sudo systemctl start kafka
# 또는
# Kafka 설치 및 실행 방법에 따라 다름
```

### 문제 2: "UART 포트 열기 실패"

**원인**: UART 권한 문제 또는 포트가 사용 중

**해결**:
```bash
# 사용자를 dialout 그룹에 추가
sudo usermod -aG dialout $USER
# 재로그인 필요

# 포트 확인
ls -l /dev/serial0
```

### 문제 3: "센서 데이터는 수신되지만 디스플레이에 표시 안 됨"

**원인**: 토픽 불일치 또는 데이터 형식 불일치

**해결**:
1. 토픽 확인: `sensors.uart` 토픽에 데이터가 발행되는지 확인
2. 데이터 형식 확인: Pico에서 보내는 데이터가 올바른 형식인지 확인
3. 환경 변수 설정: `DISPLAY_SENSOR_TOPICS=sensors.uart` 설정

### 문제 4: "데모 모드만 작동"

**원인**: Kafka 연결 실패로 데모 모드로 전환됨

**해결**:
1. Kafka 연결 확인
2. 환경 변수 `DISPLAY_DEMO_MODE=0` 설정 (또는 설정하지 않음)

---

## 테스트 방법

### 1. 개별 컴포넌트 테스트

```bash
# 1. UART 수신 테스트
python -m networks.uart.uart_receiver --dev /dev/serial0 --baud 9600

# 2. UART Producer 테스트
python -m networks.kafka.uart_producer --debug

# 3. Sensor Display 테스트
python -m modules.display.sensor_display
```

### 2. 통합 테스트

```bash
# 1. UART Producer 실행 (터미널 1)
python -m networks.kafka.uart_producer --debug

# 2. Sensor Display 실행 (터미널 2)
python -m modules.display.sensor_display

# 3. Kafka 토픽 확인 (터미널 3)
kafka-console-consumer --bootstrap-server localhost:9092 --topic sensors.uart --from-beginning
```

### 3. Launcher로 전체 테스트

```bash
# 모든 모듈 실행
python -m apps.launcher

# 로그 확인
# 각 모듈의 출력을 확인하여 문제 파악
```

---

## 추가 리소스

- [RASPBERRY_PI_SETUP_GUIDE.md](./RASPBERRY_PI_SETUP_GUIDE.md) - 전체 설정 가이드
- [ENV_EXAMPLE.md](../src/ENV_EXAMPLE.md) - 환경 변수 예시
- [PROJECT_ANALYSIS.md](../src/PROJECT_ANALYSIS.md) - 프로젝트 구조 분석

