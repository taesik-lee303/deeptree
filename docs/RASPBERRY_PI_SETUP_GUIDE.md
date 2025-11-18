# 라즈베리파이5 DEEPTREE 전체 시스템 설정 가이드

라즈베리파이5에서 DEEPTREE/src 폴더의 모든 모듈을 실행하기 위한 완전한 설정 가이드입니다.

---

## 📋 목차

1. [시스템 요구사항](#시스템-요구사항)
2. [시스템 설정](#시스템-설정)
3. [시스템 패키지 설치](#시스템-패키지-설치)
4. [Python 환경 설정](#python-환경-설정)
5. [환경 변수 설정](#환경-변수-설정)
6. [CareCall 설정 파일](#carecall-설정-파일)
7. [실행 방법](#실행-방법)
8. [문제 해결](#문제-해결)

---

## 시스템 요구사항

- **라즈베리파이5**: 4GB RAM 이상 권장 (8GB 최적)
- **OS**: Raspberry Pi OS 64-bit (Bullseye 이상)
- **Python**: 3.9 이상
- **저장공간**: 최소 5GB 여유공간
- **네트워크**: 인터넷 연결 (패키지 설치 및 API 호출용)

---

## 시스템 설정

### 1. I2C 활성화 (MLX90640/90641 열화상 센서용)

```bash
sudo raspi-config
```

메뉴에서:
1. `Interface Options` → `I2C` → `Enable`
2. 재부팅: `sudo reboot`

확인:
```bash
sudo apt install i2c-tools -y
i2cdetect -y 1
```

### 2. UART 활성화 (Pico 센서 통신용)

```bash
sudo raspi-config
```

메뉴에서:
1. `Interface Options` → `Serial Port` → `Enable`
2. `Would you like a login shell to be accessible over serial?` → `No`
3. `Would you like the serial port hardware to be enabled?` → `Yes`
4. 재부팅: `sudo reboot`

확인:
```bash
ls -l /dev/serial0
# 또는
ls -l /dev/ttyAMA0
```

### 3. SPI 활성화 (필요한 경우)

```bash
sudo raspi-config
```

메뉴에서:
1. `Interface Options` → `SPI` → `Enable`
2. 재부팅: `sudo reboot`

---

## 시스템 패키지 설치

### 필수 시스템 패키지

```bash
# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 기본 개발 도구
sudo apt install -y python3-pip python3-venv python3-dev

# 수학 라이브러리 (NumPy/SciPy 최적화)
sudo apt install -y libopenblas-dev liblapack-dev libatlas-base-dev

# 이미지 처리 라이브러리
sudo apt install -y libjpeg-dev zlib1g-dev libpng-dev

# 비디오 처리 (ffmpeg)
sudo apt install -y ffmpeg libavcodec-dev libavformat-dev libavutil-dev

# 오디오 처리
sudo apt install -y portaudio19-dev python3-pyaudio

# Pygame 디스플레이용 SDL2
sudo apt install -y libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev

# I2C 도구
sudo apt install -y i2c-tools

# 웨이블릿 변환 (선택적, 시스템 패키지)
sudo apt install -y python3-pywt

# 시스템 모니터링 (선택적)
sudo apt install -y python3-psutil
```

---

## Python 환경 설정

### 1. 가상환경 생성 및 활성화

```bash
cd ~/deeptree/src  # 또는 프로젝트 경로
python3 -m venv venv
source venv/bin/activate
```

### 2. Python 패키지 설치

```bash
# pip 업그레이드
pip install --upgrade pip

# 전체 패키지 설치 (라즈베리파이 최적화 버전)
pip install --no-cache-dir -r requirements_raspberry_pi.txt
```

또는 단계별 설치:

```bash
# 핵심 데이터 처리
pip install --no-cache-dir "numpy>=1.21.0,<1.25.0" "scipy>=1.7.0,<1.11.0" "scikit-learn>=1.0.0,<1.3.0"

# 웨이블릿 변환
pip install --no-cache-dir "PyWavelets>=1.1.0,<1.4.0"

# 이미지/비디오 처리
pip install --no-cache-dir "opencv-python>=4.5.0,<4.9.0" "mediapipe>=0.10.0,<0.11.0" "pygame>=2.0.0,<2.6.0"

# 오디오 처리
pip install --no-cache-dir "sounddevice>=0.4.6" "webrtcvad>=2.0.10"

# 네트워크 통신
pip install --no-cache-dir "paho-mqtt>=1.6.0,<2.0.0" "kafka-python-ng>=2.2.0" "requests>=2.28.0"

# 시리얼 통신
pip install --no-cache-dir "pyserial>=3.5"

# 하드웨어 센서 (MLX90640/90641)
pip install --no-cache-dir "adafruit-circuitpython-mlx90640>=1.2.0" "adafruit-circuitpython-mlx90641>=1.2.0" "adafruit-blinka>=8.0.0"

# AI/ML 서비스
pip install --no-cache-dir "openai>=1.0.0"

# 유틸리티
pip install --no-cache-dir "python-dotenv>=1.0.0" "pyyaml>=6.0" "jsonschema>=4.17.0,<5.0.0" "tenacity>=8.0.0,<10.0.0"

# 선택적 패키지
pip install --no-cache-dir "psutil>=5.8.0" "joblib>=1.2.0,<1.4.0"
```

---

## 환경 변수 설정

### .env 파일 생성

`src/` 폴더에 `.env` 파일을 생성합니다:

```bash
cd ~/deeptree/src
nano .env
```

### MQTT 설정

```bash
# MQTT 브로커 설정
MQTT_HOST=203.250.148.52
MQTT_PORT=20516
MQTT_TOPIC_BASE=taesik/therapy
MQTT_PICO_TOPIC=pico/color

# MQTT 인증 (필요한 경우)
# MQTT_USERNAME=your_username
# MQTT_PASSWORD=your_password
# MQTT_TLS=false
```

### Kafka 설정

```bash
# Kafka 브로커 서버 (쉼표로 구분)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# 센서 데이터 토픽
KAFKA_SENSOR_TOPIC=sensors.uart

# Consumer 그룹 ID
KAFKA_GROUP_ID=uart-display

# 보안 프로토콜
KAFKA_SECURITY_PROTOCOL=PLAINTEXT

# SASL 인증 (필요한 경우)
# KAFKA_SASL_MECHANISM=PLAIN
# KAFKA_SASL_USERNAME=your_username
# KAFKA_SASL_PASSWORD=your_password

# 오프셋 리셋 정책
KAFKA_OFFSET_RESET=latest

# 값 인코딩
KAFKA_VALUE_ENCODING=utf-8

# 케어콜 감정 이벤트 프로듀서
KAFKA_EMO_ENABLED=1
KAFKA_EMO_TOPIC=carecall.emotion
KAFKA_EMO_CLIENT_ID=carecall-edge
KAFKA_EMO_ACKS=0
KAFKA_EMO_LINGER_MS=20
KAFKA_EMO_BATCH_SIZE=16384
# KAFKA_EMO_COMPRESSION=gzip
```

### Display 설정

```bash
# 디스플레이 새로고침 주기 (Hz)
DISPLAY_REFRESH_HZ=1.0

# 디스플레이 직경 (픽셀)
DISPLAY_DIAMETER_PIXELS=480

# 폰트 경로 (선택사항)
# DISPLAY_FONT_PATH=/path/to/font.ttf
```

### Thermal rPPG 설정

```bash
# 디버그 시각화 활성화 (0=비활성, 1=활성)
RPPG_DEBUG_VISUAL=0
```

### CareCall 환경 변수 (선택적)

```bash
# OpenAI API 키 (config.json에도 설정 가능)
OPENAI_API_KEY=sk-proj-...

# 활성화 조건
CARECALL_NOISE_THRESHOLD=1000
CARECALL_MOTION_REQUIRED=true
CARECALL_MOTION_WINDOW_SEC=5.0
CARECALL_SENSOR_TIMEOUT_SEC=10.0
CARECALL_WAKE_PHRASES=케어콜 시작,케어콜 불러줘

# 오디오 설정
VAD_AGGRESSIVENESS=3
SD_RATE=16000
SD_USE_RAW=0
SD_INPUT_DEVICE=1

# Whisper 설정
WHISPER_MODEL=whisper-1
WHISPER_LANG=ko
```

---

## CareCall 설정 파일

### config.json 생성

`src/modules/carecall/` 폴더에 `config.json` 파일을 생성합니다:

```bash
cd ~/deeptree/src/modules/carecall
nano config.json
```

### 기본 설정 예시

```json
{
  "audio": {
    "sample_rate": 16000,
    "channels": 1,
    "frame_ms": 20,
    "vad_aggressiveness": 3,
    "pre_silence_ms": 300,
    "min_utterance_ms": 250,
    "end_silence_ms": 800,
    "device_rate": 0,
    "use_raw_stream": false,
    "input_device": "1"
  },
  "whisper": {
    "model": "whisper-1",
    "language": "ko"
  },
  "openai": {
    "api_key": "sk-proj-...",
    "tts_model": "tts-1",
    "tts_voice": "nova",
    "whisper_model": "whisper-1"
  },
  "server": {
    "base_url": "https://deepcare-api.thedeeplabs.com/api",
    "timeout": 30,
    "max_retries": 3,
    "retry_delay": 1
  },
  "activation": {
    "noise_threshold": 1000,
    "motion_required": true,
    "motion_window_sec": 5.0,
    "sensor_timeout_sec": 10.0,
    "wake_phrases": [
      "케어콜 시작",
      "케어콜 불러줘"
    ]
  }
}
```

**참고**: `api_key`는 환경 변수 `OPENAI_API_KEY`로도 설정 가능합니다.

---

## 실행 방법

### 1. Launcher로 전체 시스템 실행 (권장)

```bash
cd ~/deeptree/src
source venv/bin/activate  # 가상환경 활성화

# 기본 모듈 실행 (carecall, rppg, display-switcher)
python -m apps.launcher

# 특정 모듈만 실행
python -m apps.launcher -m carecall -m rppg

# 디스플레이 포함
python -m apps.launcher --include-display

# 모듈별 인자 전달
python -m apps.launcher --module-arg carecall=--mode=test

# 사용 가능한 모듈 목록 확인
python -m apps.launcher --list
```

### 2. 개별 모듈 실행

#### CareCall 모듈

```bash
cd ~/deeptree/src
source venv/bin/activate

# 대화형 모드
python -m modules.carecall.main

# STT만 테스트
python -m modules.carecall.main --mode stt-only

# 시스템 테스트
python -m modules.carecall.main --mode test
```

#### Thermal rPPG 모듈

```bash
cd ~/deeptree/src
source venv/bin/activate

python -m modules.rppg.thermal_rppg
```

#### Display Switcher

```bash
cd ~/deeptree/src
source venv/bin/activate

python -m apps.display_switcher --idle-timeout 30 --enable-uart-producer
```

#### Sensor Display

```bash
cd ~/deeptree/src
source venv/bin/activate

python -m modules.display.sensor_display
```

#### UART Receiver (Pico 센서 데이터 수신)

```bash
cd ~/deeptree/src
source venv/bin/activate

# 기본 설정 (/dev/serial0, 9600 baud)
python -m networks.uart.uart_receiver

# 커스텀 설정
python -m networks.uart.uart_receiver --dev /dev/ttyAMA0 --baud 9600
```

#### UART Producer (UART → Kafka)

```bash
cd ~/deeptree/src
source venv/bin/activate

python -m networks.kafka.uart_producer
```

### 3. 백그라운드 실행 (systemd 서비스)

#### 방법 1: 설치 스크립트 사용 (권장)

프로젝트에 포함된 설치 스크립트를 사용하면 자동으로 설정됩니다:

```bash
cd ~/deeptree/src/systemd
sudo bash install_service.sh
```

스크립트가 다음을 자동으로 수행합니다:
- 프로젝트 경로 자동 감지
- 가상환경 확인
- 서비스 파일 생성 및 경로 수정
- systemd에 등록 및 활성화

#### 방법 2: 수동 설치

서비스 파일이 이미 준비되어 있습니다 (`src/systemd/deeptree.service`):

```bash
# 서비스 파일 복사
sudo cp ~/deeptree/src/systemd/deeptree.service /etc/systemd/system/

# 경로 수정 (필요한 경우)
sudo nano /etc/systemd/system/deeptree.service
# WorkingDirectory와 ExecStart 경로를 실제 경로로 수정

# systemd 재로드 및 활성화
sudo systemctl daemon-reload
sudo systemctl enable deeptree
sudo systemctl start deeptree
```

#### 서비스 관리

```bash
# 시작
sudo systemctl start deeptree

# 중지
sudo systemctl stop deeptree

# 재시작
sudo systemctl restart deeptree

# 상태 확인
sudo systemctl status deeptree

# 로그 확인 (실시간)
sudo journalctl -u deeptree -f

# 최근 로그 (100줄)
sudo journalctl -u deeptree -n 100
```

#### 서비스 비활성화

```bash
sudo systemctl stop deeptree
sudo systemctl disable deeptree
```

**자세한 내용**: `src/systemd/README.md` 참조

---

## 문제 해결

### 1. I2C 센서 인식 안 됨

```bash
# I2C 활성화 확인
sudo raspi-config  # Interface Options > I2C > Enable

# I2C 디바이스 스캔
i2cdetect -y 1

# 권한 확인
sudo usermod -aG i2c $USER
# 재로그인 필요
```

### 2. UART 통신 안 됨

```bash
# UART 활성화 확인
sudo raspi-config  # Interface Options > Serial Port > Enable

# 시리얼 포트 확인
ls -l /dev/serial0
ls -l /dev/ttyAMA0

# 권한 확인
sudo usermod -aG dialout $USER
# 재로그인 필요

# 블루투스 비활성화 (UART 충돌 방지)
sudo systemctl disable bluetooth
```

### 3. 메모리 부족 오류

```bash
# 스왑 파일 생성
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# CONF_SWAPSIZE=1024  # 1GB 스왑
sudo dphys-swapfile setup
sudo dphys-swapfile swapon

# 메모리 사용량 확인
free -h
```

### 4. Python 패키지 설치 오류

```bash
# 컴파일러 설치
sudo apt install build-essential -y

# Python 개발 헤더 설치
sudo apt install python3-dev -y

# 다시 설치 시도
pip install --no-cache-dir --force-reinstall [패키지명]
```

### 5. 오디오 디바이스 인식 안 됨

```bash
# 오디오 디바이스 목록 확인
python3 -c "import sounddevice; print(sounddevice.query_devices())"

# ALSA 설정 확인
aplay -l
arecord -l
```

### 6. Kafka 연결 오류

```bash
# Kafka 브로커 실행 확인
# 로컬 Kafka인 경우:
# sudo systemctl status kafka
# 또는
# netstat -tlnp | grep 9092

# 환경 변수 확인
echo $KAFKA_BOOTSTRAP_SERVERS
```

### 7. MQTT 연결 오류

```bash
# 네트워크 연결 확인
ping 203.250.148.52

# 포트 확인
telnet 203.250.148.52 20516

# 환경 변수 확인
echo $MQTT_HOST
echo $MQTT_PORT
```

### 8. Pygame 디스플레이 오류

```bash
# 디스플레이 환경 변수 설정 (SSH 접속 시)
export DISPLAY=:0

# 또는 X11 포워딩 활성화
xhost +local:
```

---

## 성능 최적화

### 라즈베리파이 최적화 설정

Thermal rPPG 모듈은 자동으로 라즈베리파이를 감지하고 최적화를 적용합니다. 수동 설정이 필요한 경우:

```python
# thermal_rppg.py에서
cfg = ThermalrPPGConfig(
    enable_pi_optimization=True,
    pi_memory_limit_mb=512,
    pi_cpu_throttle=True,
    pi_reduced_precision=True,
)
```

### GPU 메모리 분할 조정

```bash
sudo raspi-config
# Advanced Options > Memory Split > 16
```

### CPU 클럭 속도 확인

```bash
vcgencmd measure_clock arm
vcgencmd measure_temp
```

---

## 체크리스트

설정 완료 후 다음 항목을 확인하세요:

- [ ] I2C 활성화됨 (`i2cdetect -y 1`로 확인)
- [ ] UART 활성화됨 (`ls -l /dev/serial0`로 확인)
- [ ] 시스템 패키지 설치 완료
- [ ] Python 가상환경 생성 및 활성화
- [ ] Python 패키지 설치 완료
- [ ] `.env` 파일 생성 및 설정
- [ ] `config.json` 파일 생성 및 설정 (CareCall용)
- [ ] 네트워크 연결 확인 (MQTT, Kafka)
- [ ] 하드웨어 연결 확인 (MLX 센서, Pico, 카메라)
- [ ] 테스트 실행 성공

---

## 추가 리소스

- [RASPBERRY_PI_GUIDE.md](../src/RASPBERRY_PI_GUIDE.md) - Thermal rPPG 상세 가이드
- [RASPBERRY_PI_LIBRARIES.md](../src/RASPBERRY_PI_LIBRARIES.md) - 라이브러리 종합 정리
- [ENV_EXAMPLE.md](../src/ENV_EXAMPLE.md) - 환경 변수 예시
- [PROJECT_ANALYSIS.md](../src/PROJECT_ANALYSIS.md) - 프로젝트 구조 분석

---

**마지막 업데이트**: 2025-01-XX

