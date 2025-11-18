# UART 통신 문제 해결 가이드

## 문제: UART에서 데이터를 받지 못함

### 증상
- `uart_receiver` 실행 시 "Listening..." 이후 아무것도 출력되지 않음
- `uart_producer` 실행 시 "Waiting for UART data..." 이후 데이터 수신 안 됨

---

## 진단 단계

### 1단계: UART 포트 확인

```bash
# 시리얼 포트 존재 확인
ls -l /dev/serial0
ls -l /dev/ttyAMA0

# 권한 확인
groups | grep dialout
# 없으면:
sudo usermod -aG dialout $USER
# 재로그인 필요
```

### 2단계: 다른 프로세스가 포트를 사용 중인지 확인

```bash
# 포트 사용 중인 프로세스 확인
lsof /dev/serial0
# 또는
fuser /dev/serial0

# 사용 중이면 종료
sudo kill <PID>
```

### 3단계: UART 직접 테스트

```bash
# 타임아웃 30초로 테스트
python -m networks.uart.uart_receiver --dev /dev/serial0 --baud 9600 --timeout 30
```

### 4단계: Pico 확인

#### Pico가 실행 중인지 확인
- Pico에 전원이 공급되고 있는지
- Pico 코드가 실행 중인지
- Pico 시리얼 모니터로 데이터 전송 확인

#### Pico 코드 확인
- `main.py`가 실행 중인지
- `uart_module.init_uart()`가 성공했는지
- `send_data()`가 호출되는지

---

## 하드웨어 연결 확인

### 라즈베리파이5 핀 연결

| 라즈베리파이5 | Pico | 설명 |
|--------------|------|------|
| GPIO 14 (TX) | GP1 (RX) | 라즈베리파이 → Pico |
| GPIO 15 (RX) | GP0 (TX) | Pico → 라즈베리파이 |
| GND | GND | 공통 접지 |

**중요**: 
- 라즈베리파이 TX → Pico RX
- 라즈베리파이 RX → Pico TX
- **교차 연결**이 맞습니다!

### 연결 다이어그램

```
라즈베리파이5          Pico
-----------          ----
GPIO 14 (TX) ──────> GP1 (RX)
GPIO 15 (RX) <────── GP0 (TX)
GND          ──────> GND
```

---

## 소프트웨어 확인

### 1. Baud Rate 확인
- Pico: 9600 (uart_module.py 8번째 줄)
- 라즈베리파이: 9600 (기본값)
- **일치해야 함!**

### 2. 데이터 형식 확인
- Pico는 JSON 문자열을 `\n`으로 끝내서 전송
- 라즈베리파이는 `readline()`으로 읽음
- **형식이 맞아야 함!**

### 3. Pico 코드 확인 사항

#### uart_module.py
```python
UART_TX_PIN = 0  # Pico GP0
UART_RX_PIN = 1  # Pico GP1
BAUD_RATE = 9600
LINE_ENDING = b"\n"
```

#### main.py
- 5초마다 데이터 전송 (`time.sleep(5)`)
- `uart_module.send_data(json_string)` 호출 확인

---

## 테스트 방법

### 방법 1: UART Receiver로 직접 테스트

```bash
python -m networks.uart.uart_receiver --dev /dev/serial0 --baud 9600 --timeout 30
```

예상 출력:
```
✓ UART port opened successfully
✓ Buffers cleared
Listening for data...

✓ Data received: {"pm": {...}, "dht22": {...}, ...}
✓ JSON parsed successfully
✓ Fields extracted: {...}
  → T=23.5°C | H=45% | noise=500 | ...
```

### 방법 2: 다른 시리얼 포트 시도

```bash
# /dev/ttyAMA0 시도
python -m networks.uart.uart_receiver --dev /dev/ttyAMA0 --baud 9600

# /dev/ttyUSB0 시도 (USB 시리얼 어댑터 사용 시)
python -m networks.uart.uart_receiver --dev /dev/ttyUSB0 --baud 9600
```

### 방법 3: Pico 시리얼 모니터 확인

Pico에 직접 연결된 시리얼 모니터로 데이터 전송 확인:
- Thonny IDE 사용
- 또는 다른 시리얼 모니터 도구

---

## 일반적인 문제와 해결책

### 문제 1: "Permission denied"

**원인**: 사용자가 dialout 그룹에 없음

**해결**:
```bash
sudo usermod -aG dialout $USER
# 재로그인 필요
```

### 문제 2: "Device not found"

**원인**: 시리얼 포트가 활성화되지 않음

**해결**:
```bash
sudo raspi-config
# Interface Options > Serial Port > Enable
# 재부팅 필요
```

### 문제 3: "Port already in use"

**원인**: 다른 프로세스가 포트 사용 중

**해결**:
```bash
lsof /dev/serial0
sudo kill <PID>
```

### 문제 4: 데이터는 오지만 파싱 실패

**원인**: JSON 형식 오류 또는 인코딩 문제

**해결**:
- Pico 코드에서 JSON 형식 확인
- 인코딩 확인 (UTF-8)
- `\n`으로 끝나는지 확인

### 문제 5: 연결은 되지만 데이터가 안 옴

**원인**: 
- Pico가 데이터를 보내지 않음
- UART 핀 연결 문제
- Baud rate 불일치

**해결**:
1. Pico 코드 실행 확인
2. 핀 연결 재확인
3. Baud rate 확인 (9600)

---

## 디버깅 체크리스트

- [ ] UART 포트 존재 확인 (`ls -l /dev/serial0`)
- [ ] 권한 확인 (`groups | grep dialout`)
- [ ] 다른 프로세스 사용 확인 (`lsof /dev/serial0`)
- [ ] Pico 전원 확인
- [ ] Pico 코드 실행 확인
- [ ] 핀 연결 확인 (TX↔RX 교차)
- [ ] GND 연결 확인
- [ ] Baud rate 확인 (9600)
- [ ] UART 활성화 확인 (`raspi-config`)
- [ ] 다른 시리얼 포트 시도

---

## 추가 리소스

- [RASPBERRY_PI_SETUP_GUIDE.md](./RASPBERRY_PI_SETUP_GUIDE.md) - 전체 설정 가이드
- [PICO_DATA_FORMAT_ANALYSIS.md](./PICO_DATA_FORMAT_ANALYSIS.md) - 데이터 형식 분석

