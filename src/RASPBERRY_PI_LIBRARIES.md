# 라즈베리파이용 라이브러리 종합 정리

이 문서는 DeepTree 프로젝트의 모든 모듈이 라즈베리파이에서 실행되기 위해 필요한 모든 라이브러리를 정리한 것입니다.

## 📋 목차

1. [핵심 데이터 처리](#1-핵심-데이터-처리)
2. [이미지 및 비디오 처리](#2-이미지-및-비디오-처리)
3. [오디오 처리](#3-오디오-처리)
4. [네트워크 통신](#4-네트워크-통신)
5. [시리얼 통신](#5-시리얼-통신)
6. [하드웨어 센서](#6-하드웨어-센서)
7. [AI/ML 서비스](#7-aiml-서비스)
8. [웹 프레임워크](#8-웹-프레임워크)
9. [유틸리티](#9-유틸리티)
10. [시스템 패키지](#10-시스템-패키지)

---

## 1. 핵심 데이터 처리

### numpy (>=1.21.0,<1.25.0)
- **용도**: 수치 연산, 배열 처리
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - 열화상 데이터 처리
  - `modules/carecall/stt_tts/stt.py` - 오디오 데이터 처리
  - `modules/carecall/stt_tts/utils.py` - 오디오 유틸리티
- **라즈베리파이 최적화**: 버전 제한으로 메모리 효율성 확보

### scipy (>=1.7.0,<1.11.0)
- **용도**: 신호 처리, 필터링
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - 신호 필터링, 주파수 분석
- **주요 기능**: `scipy.signal` - 신호 처리 함수

### scikit-learn (>=1.0.0,<1.3.0)
- **용도**: 머신러닝 모델 (앙상블 학습)
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - RandomForest, GradientBoosting
- **주요 기능**: 
  - `RandomForestRegressor` - 심박수 예측
  - `GradientBoostingRegressor` - 호흡수 예측
  - `StandardScaler` - 데이터 정규화

### PyWavelets (>=1.1.0,<1.4.0)
- **용도**: 웨이블릿 변환 (노이즈 제거)
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - 웨이블릿 디노이징
- **선택적**: AI Enhancement 기능 활성화 시 필요

---

## 2. 이미지 및 비디오 처리

### opencv-python (>=4.5.0,<4.9.0)
- **용도**: 컴퓨터 비전, 이미지 처리
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - 열화상 이미지 처리, 얼굴 검출
- **주요 기능**: 
  - 이미지 변환 및 필터링
  - 얼굴 검출 및 추적
  - 영상 처리

### pygame (>=2.0.0,<2.6.0)
- **용도**: 원형 디스플레이 GUI
- **사용 모듈**: 
  - `modules/display/sensor_display.py` - 센서 데이터 시각화
- **주요 기능**: 
  - 원형 디스플레이 렌더링
  - 실시간 센서 데이터 표시
  - 파도 애니메이션

---

## 3. 오디오 처리

### sounddevice (>=0.4.6)
- **용도**: 오디오 입출력
- **사용 모듈**: 
  - `modules/carecall/stt_tts/stt.py` - 마이크 입력
  - `modules/carecall/stt_tts/utils.py` - 오디오 디바이스 관리
- **시스템 의존성**: `portaudio19-dev` 필요

### webrtcvad (>=2.0.10)
- **용도**: WebRTC 기반 음성 활동 감지 (VAD)
- **사용 모듈**: 
  - `modules/carecall/stt_tts/stt.py` - 사람 목소리만 필터링
- **주요 기능**: 
  - 실시간 음성/무음 구분
  - 발화 시작/종료 감지

---

## 4. 네트워크 통신

### paho-mqtt (>=1.6.0,<2.0.0)
- **용도**: MQTT 프로토콜 (색 치료 추천 발행)
- **사용 모듈**: 
  - `networks/mqtt/mqtt_publisher.py` - 색 치료 데이터 발행
  - `networks/mqtt/mqtt_subscriber.py` - MQTT 메시지 구독
  - `test/connectors/mqtt/*` - 테스트 모듈
  - `test/pipelines/kafka/producers/mqtt_to_kafka.py` - MQTT→Kafka 브릿지

### kafka-python-ng (>=2.2.0) 또는 kafka-python (>=2.0.2)
- **용도**: Apache Kafka 클라이언트
- **사용 모듈**: 
  - `networks/kafka/kafka_producer.py` - 감정 이벤트 발행
  - `networks/kafka/uart_producer.py` - UART→Kafka 브릿지
  - `modules/display/display_for_carecall/mp4_player.py` - 비디오 재생 트리거
  - `modules/carecall/activation.py` - 센서 이벤트 구독
  - `modules/display/sensor_display.py` - 센서 데이터 구독
  - `test/pipelines/kafka/*` - 테스트 파이프라인
- **참고**: `kafka-python-ng`는 `kafka-python`의 최신 포크

### requests (>=2.28.0)
- **용도**: HTTP 클라이언트 (AI 서버 통신)
- **사용 모듈**: 
  - `modules/carecall/stt_tts/utils.py` - AI 서버 API 호출
- **주요 기능**: 
  - REST API 통신
  - OpenAI API 호출 (간접적)

---

## 5. 시리얼 통신

### pyserial (>=3.5)
- **용도**: 시리얼 포트 통신 (UART)
- **사용 모듈**: 
  - `networks/uart/uart_receiver.py` - Pico 센서 데이터 수신
  - `networks/kafka/uart_producer.py` - UART→Kafka 변환
  - `test/connectors/uart/uart_io.py` - 테스트용 UART 통신
- **주요 기능**: 
  - 라즈베리파이와 Pico 간 UART 통신
  - 센서 데이터 (온도, 습도, 소음, PIR, PM) 수신

---

## 6. 하드웨어 센서

### adafruit-circuitpython-mlx90640 (>=1.2.0)
- **용도**: MLX90640 열화상 센서 드라이버
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - 열화상 센서 인터페이스
- **해상도**: 24x32 픽셀

### adafruit-circuitpython-mlx90641 (>=1.2.0)
- **용도**: MLX90641 열화상 센서 드라이버
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - 열화상 센서 인터페이스 (대체)
- **해상도**: 12x16 픽셀

### adafruit-blinka (>=8.0.0)
- **용도**: CircuitPython을 일반 Python에서 사용 가능하게 함
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - I2C 통신 (`board`, `busio`)
- **주요 기능**: 
  - `board` - 하드웨어 핀 정의
  - `busio` - I2C, SPI, UART 통신
- **시스템 의존성**: I2C 활성화 필요 (`sudo raspi-config`)

### circuitpython-build-tools (>=7.0.0)
- **용도**: CircuitPython 빌드 도구 (선택적)
- **참고**: adafruit-blinka의 의존성으로 자동 설치됨

---

## 7. AI/ML 서비스

### openai (>=1.0.0)
- **용도**: OpenAI API 클라이언트 (Whisper STT, TTS)
- **사용 모듈**: 
  - `modules/carecall/stt_tts/stt.py` - Whisper API 음성 인식
  - `modules/carecall/stt_tts/tts.py` - OpenAI TTS 음성 합성
- **주요 기능**: 
  - `audio.transcriptions.create()` - 음성→텍스트
  - `audio.speech.create()` - 텍스트→음성
- **필수 설정**: OpenAI API 키 필요

---

## 8. 웹 프레임워크 (테스트/대시보드용, 선택적)

### fastapi (>=0.100.0,<0.116.0)
- **용도**: HTTP API 서버
- **사용 모듈**: 
  - `test/pipelines/kafka/producers/http_to_kafka.py` - HTTP→Kafka 브릿지
  - `test/pipelines/kafka/consumers/ws_dashboard.py` - WebSocket 대시보드
- **선택적**: 테스트 환경에서만 필요

### uvicorn[standard] (>=0.20.0,<0.31.0)
- **용도**: ASGI 서버 (FastAPI 실행)
- **사용 모듈**: 
  - `test/pipelines/kafka/producers/http_to_kafka.py`
  - `test/pipelines/kafka/consumers/ws_dashboard.py`
- **선택적**: FastAPI와 함께 사용

---

## 9. 유틸리티

### python-dotenv (>=1.0.0)
- **용도**: 환경 변수 관리 (.env 파일)
- **사용 모듈**: 
  - `test/pipelines/kafka/producers/*` - 환경 변수 로드
- **주요 기능**: `.env` 파일에서 설정 로드

### pyyaml (>=6.0)
- **용도**: YAML 파일 파싱
- **사용 모듈**: 
  - `test/pipelines/kafka/config/topics.yaml` - Kafka 토픽 설정
  - `test/pipelines/kafka/scripts/create_topics.py` - 토픽 생성

### jsonschema (>=4.17.0,<5.0.0)
- **용도**: JSON 스키마 검증
- **사용 모듈**: 
  - `networks/common/schema/schema_utils.py` - 스키마 검증
  - `test/common/schema/schema_utils.py` - 테스트용 스키마 검증
- **주요 기능**: Kafka 메시지 스키마 검증

### tenacity (>=8.0.0,<10.0.0)
- **용도**: 재시도 로직
- **사용 모듈**: 
  - `test/pipelines/kafka/*` - 네트워크 재시도
- **주요 기능**: 자동 재시도, 백오프 전략

### rich (>=13.0.0)
- **용도**: 터미널 출력 포맷팅
- **사용 모듈**: 
  - `test/pipelines/kafka/consumers/display_terminal.py` - 예쁜 터미널 출력
- **선택적**: 개발/테스트용

### psutil (>=5.8.0)
- **용도**: 시스템 리소스 모니터링
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - 메모리/CPU 모니터링 (선택적)
- **선택적**: 성능 모니터링이 필요한 경우

### joblib (>=1.2.0,<1.4.0)
- **용도**: 병렬 처리, 모델 저장
- **사용 모듈**: 
  - `modules/rppg/thermal_rppg.py` - 모델 직렬화 (선택적)
- **선택적**: 모델 저장/로드 기능 사용 시

---

## 10. 시스템 패키지

다음 패키지들은 `apt`로 설치해야 합니다:

### 필수 시스템 패키지

```bash
# Python 개발 환경
sudo apt install -y python3-pip python3-venv python3-dev

# 수치 연산 최적화 (NumPy/SciPy)
sudo apt install -y libopenblas-dev liblapack-dev libatlas-base-dev

# 이미지 처리 (OpenCV)
sudo apt install -y libjpeg-dev zlib1g-dev libpng-dev

# 비디오 재생 (ffmpeg/ffplay)
sudo apt install -y ffmpeg libavcodec-dev libavformat-dev libavutil-dev

# 오디오 처리 (PortAudio)
sudo apt install -y portaudio19-dev python3-pyaudio

# Pygame (SDL2)
sudo apt install -y libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev

# I2C 통신 (MLX 센서)
sudo apt install -y i2c-tools
```

### I2C 활성화

```bash
# 라즈베리파이 설정에서 I2C 활성화
sudo raspi-config
# Interface Options > I2C > Enable

# I2C 장치 확인
sudo i2cdetect -y 1
```

---

## 📦 설치 순서

### 1. 시스템 패키지 설치

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev
sudo apt install -y libopenblas-dev liblapack-dev libatlas-base-dev
sudo apt install -y libjpeg-dev zlib1g-dev libpng-dev
sudo apt install -y ffmpeg libavcodec-dev libavformat-dev libavutil-dev
sudo apt install -y portaudio19-dev python3-pyaudio
sudo apt install -y libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev
sudo apt install -y i2c-tools
```

### 2. I2C 활성화 (MLX 센서 사용 시)

```bash
sudo raspi-config
# Interface Options > I2C > Enable
sudo reboot
```

### 3. 가상환경 생성 및 활성화

```bash
cd src
python3 -m venv venv
source venv/bin/activate
```

### 4. Python 패키지 설치

```bash
pip install --upgrade pip
pip install --no-cache-dir -r requirements_raspberry_pi.txt
```

---

## 🔍 모듈별 필수 라이브러리

### thermal_rppg 모듈
- **필수**: numpy, scipy, scikit-learn, opencv-python, adafruit-circuitpython-mlx90640/90641, adafruit-blinka, paho-mqtt
- **선택**: PyWavelets, psutil, joblib

### carecall 모듈
- **필수**: numpy, sounddevice, webrtcvad, openai, requests, kafka-python-ng
- **선택**: (없음)

### display 모듈
- **필수**: pygame, kafka-python-ng
- **선택**: (없음)

### 네트워크 모듈
- **필수**: paho-mqtt, kafka-python-ng, pyserial
- **선택**: jsonschema, python-dotenv

---

## ⚠️ 주의사항

1. **메모리 제한**: 라즈베리파이 4GB 이하에서는 일부 기능 비활성화 권장
2. **버전 충돌**: `--no-cache-dir` 옵션 사용 권장
3. **가상환경**: 반드시 가상환경 사용
4. **I2C 권한**: 일반 사용자로 I2C 접근 시 그룹 추가 필요
   ```bash
   sudo usermod -a -G i2c $USER
   ```
5. **오디오 권한**: 오디오 디바이스 접근 권한 확인

---

## 📚 참고 문서

- [RASPBERRY_PI_GUIDE.md](./RASPBERRY_PI_GUIDE.md) - 라즈베리파이 설치 가이드
- [requirements_raspberry_pi.txt](./requirements_raspberry_pi.txt) - 전체 requirements 파일
- [requirements_pi.txt](./requirements_pi.txt) - AI Enhancement용 최적화 버전
- [requirements_ai.txt](./requirements_ai.txt) - AI Enhancement용 전체 버전

