# Pico → 라즈베리파이 데이터 형식 분석

## 데이터 흐름

```
Pico → UART → 라즈베리파이 (uart_producer) → Kafka → Sensor Display
```

## 1. Pico가 보내는 형식

### Pico main.py
```python
all_data = {
    'pm': {...},
    'dht22': {...},
    'ir': {...},
    'sound': {...}
}
json_string = json.dumps(all_data)
uart_module.send_data(json_string)  # \n으로 끝남
```

**예상 JSON 형식:**
```json
{
  "pm": {"pm1": 10, "pm25": 15, "pm10": 25},
  "dht22": {"temp_c": 23.5, "hum": 45.0},
  "ir": {"pir": 1},
  "sound": {"noise": 500}
}
```

## 2. 라즈베리파이 uart_producer.py 처리

### extract_fields() 함수
- 입력: `{"dht22": {...}, "ir": {...}, "sound": {...}, "pm": {...}}`
- 출력: `{"temp_c": 23.5, "hum": 45.0, "noise": 500, "pir": 1, "pm25": 15, "pm10": 25}`

### Kafka로 전송하는 payload
```json
{
  "ts": 1234567890,
  "device_id": null,
  "temp_c": 23.5,
  "hum": 45.0,
  "noise": 500,
  "pir": 1,
  "pm1": 10,
  "pm25": 15,
  "pm10": 25,
  "raw": {
    "pm": {...},
    "dht22": {...},
    "ir": {...},
    "sound": {...}
  },
  "ingested_at": 1234567890
}
```

## 3. Sensor Display 파싱

### extract_sensor_values() 함수
- `_iter_dict_candidates()`로 payload의 모든 dict 레벨을 순회
- `apply_aliases()`로 필드명 매핑:
  - `temp_c` → `temperature` ✓ (추가됨)
  - `hum` → `humidity` ✓
  - `noise` → `noise_level` ✓
  - `pir` → `motion_detected` ✓
  - `pm25` → `pm2_5` ✓
  - `pm10` → `pm10` ✓

## 4. 잠재적 문제점

### 문제 1: 필드명 불일치
- ✅ 해결됨: `temp_c` → `temperature` 매핑 추가

### 문제 2: Pico가 데이터를 보내지 않음
- UART 연결 확인 필요
- Pico 코드 실행 확인 필요

### 문제 3: 데이터 형식 불일치
- Pico의 각 센서 모듈이 어떤 키를 사용하는지 확인 필요
- 예: `dht22` 모듈이 `temp_c` 대신 `temperature`를 보낼 수 있음

## 5. 확인 방법

### Pico 센서 모듈 확인
각 센서 모듈이 어떤 키를 사용하는지 확인:

```python
# dht22_sensor.py 확인
# - temp_c? temperature? temp?
# - hum? humidity? h?

# sound_sensor.py 확인  
# - noise? noise_raw? value? level?

# ir_sensor.py 확인
# - pir? motion? value? status?

# air.py (pm_sensor) 확인
# - pm25? pm2_5? pm2.5?
# - pm10? pm_10?
```

### 테스트 방법

1. **UART 직접 테스트:**
```bash
python -m networks.uart.uart_receiver --dev /dev/serial0 --baud 9600
```

2. **UART Producer 디버그:**
```bash
python -m networks.kafka.uart_producer --debug
```

3. **전체 흐름 테스트:**
```bash
# 터미널 1: UART Producer
python -m networks.kafka.uart_producer --debug

# 터미널 2: Sensor Display
python -m modules.display.sensor_display
```

## 6. 예상되는 문제와 해결책

### 문제: Pico가 데이터를 보내지 않음
**해결:**
- Pico 코드가 실행 중인지 확인
- UART 핀 연결 확인
- Pico 시리얼 모니터로 데이터 전송 확인

### 문제: 필드명이 매핑되지 않음
**해결:**
- `sensor_display.py`의 `ALIASES`에 필요한 매핑 추가
- Pico 센서 모듈의 실제 키 이름 확인

### 문제: 데이터는 오지만 디스플레이에 표시 안 됨
**해결:**
- Kafka 토픽 확인
- Sensor Display 로그 확인
- 데이터 파싱 로그 확인

