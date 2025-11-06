# DeepTree 프로젝트 종합 분석 문서

## 📋 목차
1. [프로젝트 개요](#프로젝트-개요)
2. [시스템 아키텍처](#시스템-아키텍처)
3. [모듈별 상세 분석](#모듈별-상세-분석)
4. [데이터 흐름](#데이터-흐름)
5. [통신 프로토콜](#통신-프로토콜)
6. [설정 관리](#설정-관리)
7. [실행 방법](#실행-방법)
8. [주요 알고리즘](#주요-알고리즘)
9. [의존성 및 기술 스택](#의존성-및-기술-스택)

---

## 프로젝트 개요

**DeepTree**는 IoT 기반의 스마트 케어 시스템으로, 다음과 같은 핵심 기능을 제공합니다:

1. **케어콜 시스템 (CareCall)**: 음성 인식 및 대화형 AI 비서
2. **Thermal rPPG**: 열상 센서를 이용한 비접촉 생체신호 측정 (심박수, 호흡수)
3. **색채 치료**: 생체신호 기반 색상 추천 시스템
4. **센서 통합**: 온도, 습도, 소음, 미세먼지, 모션 센서 데이터 수집 및 표시
5. **디스플레이 시스템**: 상황에 따른 자동 전환 디스플레이

### 핵심 목적
- 노인 케어를 위한 통합 IoT 솔루션
- 비접촉 생체신호 모니터링
- 자연스러운 음성 대화 인터페이스
- 실시간 환경 데이터 시각화

---

## 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    DeepTree 시스템                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  CareCall    │  │ Thermal rPPG │  │  Display     │  │
│  │  (대화 시스템) │  │  (생체신호)  │  │  (시각화)     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │          │
│         └─────────────────┼─────────────────┘          │
│                           │                            │
│  ┌───────────────────────┴──────────────────────────┐ │
│  │           Kafka (메시지 브로커)                    │ │
│  └───────────────────────┬──────────────────────────┘ │
│                           │                            │
│  ┌───────────────────────┴──────────────────────────┐ │
│  │  센서 데이터 파이프라인                              │ │
│  │  - UART (Raspberry Pi Pico)                       │ │
│  │  - MQTT (색채 치료 데이터)                         │ │
│  │  - HTTP (외부 API)                                │ │
│  └───────────────────────────────────────────────────┘ │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 주요 컴포넌트

1. **Launcher** (`apps/launcher.py`): 여러 모듈을 병렬로 실행
2. **Display Switcher** (`apps/display_switcher.py`): 상황에 따른 디스플레이 전환
3. **CareCall** (`modules/carecall/`): 음성 대화 시스템
4. **Thermal rPPG** (`modules/rppg/`): 열상 센서 기반 생체신호 측정
5. **Display** (`modules/display/`): 센서 데이터 및 비디오 표시
6. **네트워크 레이어** (`networks/`): Kafka, MQTT, UART 통신

---

## 모듈별 상세 분석

### 1. CareCall 모듈 (`modules/carecall/`)

#### 1.1 구조
```
carecall/
├── main.py              # 진입점, DeepCareSystem 클래스
├── config.py            # 설정 관리 (Audio, Whisper, OpenAI, Server, Activation)
├── activation.py        # 센서 기반 활성화 조건 (SensorTriggerWatcher)
└── stt_tts/
    ├── stt.py           # 음성 인식 (Whisper)
    ├── tts.py           # 음성 합성 (OpenAI TTS)
    └── utils.py         # ConversationManager, AIServerClient
```

#### 1.2 주요 클래스

**DeepCareSystem** (`main.py`)
- 시스템 전체를 관리하는 메인 클래스
- 컴포넌트 초기화: STT, TTS, AI 클라이언트
- 활성화 조건 대기: 센서 트리거 또는 호출어 인식
- 실행 모드: interactive, stt-only, test

**ConversationManager** (`stt_tts/utils.py`)
- 대화 상태 관리: IDLE, LISTENING, PROCESSING, SPEAKING
- 필러 TTS 병렬 처리 (AI 응답 대기 중 자연스러운 피드백)
- 바지인 가드 (Barge-in Guard): TTS 후 잔향 방지
- 에코 필터: STT가 TTS 출력을 다시 인식하는 것 방지
- 감정 탐지 및 Kafka로 이벤트 전송

**SensorTriggerWatcher** (`activation.py`)
- Kafka에서 센서 데이터 구독
- 활성화 조건 평가:
  - 소음 ≥ threshold
  - PIR 모션 감지 (motion_window_sec 내)
  - 센서 타임아웃 (중복 트리거 방지)

#### 1.3 설정 항목

**AudioConfig**: 샘플레이트, 채널, VAD 설정
**WhisperConfig**: 모델, 언어
**OpenAIConfig**: API 키, TTS 모델/음성
**ServerConfig**: AI 서버 URL, 타임아웃, 재시도
**ActivationConfig**: 
- `noise_threshold`: 소음 임계값 (기본 1000)
- `motion_required`: PIR 모션 필수 여부
- `motion_window_sec`: 모션 감지 유효 시간 (기본 5초)
- `sensor_timeout_sec`: 트리거 간 최소 간격 (기본 30초)
- `wake_phrases`: 호출어 목록 (예: "케어콜 시작")

#### 1.4 데이터 흐름

```
사용자 음성 → STT → 텍스트
                     ↓
              ConversationManager
                     ↓
         ┌───────────┴───────────┐
         │                       │
    로컬 명령어?          AI 서버 요청
         │                       │
         └───────────┬───────────┘
                     ↓
                 TTS 출력
                     ↓
              Kafka 감정 이벤트
```

---

### 2. Thermal rPPG 모듈 (`modules/rppg/`)

#### 2.1 구조
```
rppg/
├── thermal_rppg.py      # 메인 파이프라인
└── color_therapy_adapter.py  # 색채 치료 추천
```

#### 2.2 주요 클래스

**ThermalrPPG** (`thermal_rppg.py`)
- MLX90640/90641 열상 센서 인터페이스
- 얼굴 감지 및 추적 (ThermalFaceDetector)
- 모션 보상 (MotionCompensator)
- ROI 추출 (이마, 볼, 코)
- HR/RR 계산 (SignalProc, RespEstimator)
- PresenceGate: 얼굴 인식 게이트
- AI 기반 향상 기능:
  - WaveletDenoiser: 웨이블릿 노이즈 제거
  - AdaptiveKalmanFilter: 칼만 필터로 HR 평활화
  - EnsembleROIOptimizer: ROI 가중치 최적화
  - PersonalizedBiometricModel: 개인화 모델

**ColorTherapist** (`color_therapy_adapter.py`)
- 생체신호 기반 색상 추천
- 스트레스 지수 계산
- 색상 모드: relax, energize, balance, focus, cooling, warming

#### 2.3 처리 파이프라인

```
열상 프레임 (16Hz)
    ↓
Super-Resolution (선택)
    ↓
얼굴 감지 (ThermalFaceDetector)
    ↓
모션 보상 (MotionCompensator)
    ↓
ROI 추출 (이마, 볼, 코)
    ↓
신호 처리 (웨이블릿 노이즈 제거)
    ↓
FFT 분석
    ↓
HR/RR 계산
    ↓
PresenceGate 검증
    ↓
색채 치료 추천
    ↓
MQTT 발행
```

#### 2.4 ROI (Region of Interest)

- **이마 (forehead)**: 주요 HR 측정 지점
- **왼쪽 볼 (l_cheek)**: 보조 측정
- **오른쪽 볼 (r_cheek)**: 보조 측정
- **코 (nose)**: RR 측정 및 온도 변화

#### 2.5 신호 처리

**HR 계산**:
- 최소 8초 데이터 필요 (기본 12초)
- 대역통과 필터: 0.7-4.0 Hz (42-240 BPM)
- FFT 피크 검출
- 하모닉 교정 (2배/반배 오류 보정)
- SNR 기반 품질 점수

**RR 계산**:
- 최소 12초 데이터 필요
- 대역통과 필터: 0.1-0.5 Hz (6-30 brpm)

**온도 차이 (ΔT)**:
- `ΔT_nose = nose_temp - forehead_temp`
- `ΔT_cheek = mean(cheeks) - forehead_temp`
- 스트레스 지표로 활용

#### 2.6 PresenceGate

얼굴 인식 게이트 조건:
- bbox 존재 여부
- 이마 온도: 26-42°C
- Ambient 델타 (선택)
- 스펙트럼 품질:
  - SNR ≥ 1.5인 ROI ≥ 2개
  - 하모닉 비율 ≥ 0.08
  - ROI 간 HR 일치 (차이 ≤ 10 BPM)

#### 2.7 AI 향상 기능

**웨이블릿 노이즈 제거**:
- PyWavelets 사용
- 적응형 임계값 (BayesShrink)
- 주파수 도메인 필터링

**칼만 필터**:
- HR 점프 억제
- 적응형 노이즈 공분산
- 혁신 시퀀스 기반 자동 조정

**앙상블 학습**:
- RandomForest + GradientBoosting
- ROI 가중치 최적화
- 온라인 학습 (주기적 재훈련)

**개인화 모델**:
- 사용자별 베이스라인 HR 추적
- HR 변동성 계산
- 개인 특성에 따른 보정

#### 2.8 Raspberry Pi 최적화

**RaspberryPiOptimizer**:
- 자동 감지 (cpuinfo 확인)
- 메모리 제한: 512MB
- CPU 스로틀링
- 정밀도 감소 (부동소수점 최적화)
- 모델 크기 축소 (앙상블 트리 수 감소)

#### 2.9 빠른 측정 모드

**FastMeasurementMode**:
- 최소 측정 시간: 6초 (기본 12초)
- HR 계산 주기: 0.5초 (기본 0.75초)
- 샘플링 레이트: 20Hz (기본 16Hz)
- 첫 HR/RR 측정 시간 기록

---

### 3. Display 모듈 (`modules/display/`)

#### 3.1 구조
```
display/
├── sensor_display.py    # 원형 디스플레이 (센서 데이터)
└── display_for_carecall/
    ├── mp4_player.py    # 비디오 플레이어
    └── video/           # 감정별 비디오 파일
```

#### 3.2 Sensor Display (`sensor_display.py`)

**기능**:
- 원형 디스플레이 (480x480, 라즈베리파이 5 원형 디스플레이)
- Kafka에서 센서 데이터 구독
- 실시간 시각화:
  - 온도: 배경 색상 틴트
  - 습도: 물결 애니메이션 (수위 표시)
  - 소음/PM: 글래스 카드
  - 시간/날짜 표시

**센서 필드**:
- `temperature`: 온도 (°C)
- `humidity`: 습도 (%)
- `noise_level`: 소음 (dB)
- `pm2_5`, `pm10`: 미세먼지
- `motion_detected`: 모션 감지

**카드 시스템**:
- 글래스모피즘 스타일
- 우선순위별 크기 조정
- 충돌 방지 알고리즘
- 파도 효과 (부표 애니메이션)

**색상 시스템**:
- excellent (초록)
- good (연두)
- moderate (노랑)
- poor (주황)
- hazardous (빨강)

#### 3.3 Display Switcher (`apps/display_switcher.py`)

**기능**:
- Kafka 감정 이벤트 감시
- 케어콜 이벤트 발생 시 → CareCall 비디오 표시
- 유휴 타임아웃 (기본 30초) 후 → 센서 디스플레이로 복귀

**프로세스 관리**:
- `ProcessController`: 서브프로세스 관리
- 자동 재시작
- 우아한 종료 (terminate → kill)

---

### 4. 네트워크 레이어 (`networks/`)

#### 4.1 Kafka (`networks/kafka/`)

**구조**:
```
kafka/
├── kafka_config.py      # 설정 (KafkaSettings, EmotionProducerSettings)
├── kafka_producer.py    # 감정 이벤트 프로듀서
└── uart_producer.py     # UART → Kafka 프로듀서
```

**토픽**:
- `sensors.uart`: 센서 데이터 (기본)
- `carecall.emotion`: 감정 이벤트
- `display-data`: 디스플레이 데이터

**설정**:
- `KAFKA_BOOTSTRAP_SERVERS`: 브로커 주소 (기본: localhost:9092)
- `KAFKA_SENSOR_TOPIC`: 센서 토픽
- `KAFKA_EMO_TOPIC`: 감정 이벤트 토픽
- 보안: SASL/PLAIN 지원

#### 4.2 MQTT (`networks/mqtt/`)

**구조**:
```
mqtt/
├── mqtt_config.py       # 설정 (MqttSettings)
├── mqtt_publisher.py     # 색채 치료 데이터 발행
└── mqtt_subscriber.py   # 구독자 (선택)
```

**토픽**:
- `taesik/therapy/color`: 색채 치료 추천
- `taesik/therapy/status`: 상태 메시지
- `pico/color`: Pico 호환 데이터

**설정**:
- `MQTT_HOST`: 브로커 주소 (기본: 203.250.148.52)
- `MQTT_PORT`: 포트 (기본: 20516)
- `MQTT_TOPIC_BASE`: 토픽 베이스

#### 4.3 UART (`networks/uart/`)

**구조**:
```
uart/
└── uart_receiver.py     # UART 데이터 수신 및 파싱
```

**프로토콜**:
- Baudrate: 9600 (기본)
- JSON 형식
- 디바이스: `/dev/serial0` (기본)

**필드 추출**:
- `temp_c`: 온도
- `hum`: 습도
- `noise`: 소음
- `pir`: 모션 (0/1)
- `pm1`, `pm25`, `pm10`: 미세먼지

**유연한 스키마**:
- `{"sensors": {...}}` 형태
- `{"dht22": {...}, "ir": {...}}` 형태
- 별칭(alias) 지원

---

## 데이터 흐름

### 1. 센서 데이터 흐름

```
Raspberry Pi Pico (UART)
    ↓
uart_receiver.py (파싱)
    ↓
Kafka (sensors.uart)
    ↓
┌───────────┬───────────┬───────────┐
│   Display │  CareCall │  외부 시스템 │
│ (sensor_  │ (activation│            │
│  display) │  .py)     │            │
└───────────┴───────────┴───────────┘
```

### 2. 케어콜 이벤트 흐름

```
사용자 음성
    ↓
STT (Whisper)
    ↓
ConversationManager
    ↓
┌───────────┬───────────┐
│  로컬 명령 │  AI 서버   │
└───────────┴───────────┘
    ↓
TTS (OpenAI)
    ↓
Kafka (carecall.emotion)
    ↓
Display Switcher
    ↓
CareCall 비디오 표시
```

### 3. Thermal rPPG 데이터 흐름

```
MLX90640/90641 센서
    ↓
thermal_rppg.py
    ↓
HR/RR 계산
    ↓
ColorTherapist
    ↓
┌───────────┬───────────┐
│   MQTT    │   UI      │
│ (색채 치료) │ (모니터)  │
└───────────┴───────────┘
```

---

## 통신 프로토콜

### Kafka 메시지 형식

**센서 이벤트** (`sensors.uart`):
```json
{
  "ts": 1234567890.123,
  "device_id": "pico-001",
  "temp_c": 23.5,
  "hum": 48.0,
  "noise": 45.2,
  "pir": 1,
  "pm25": 15,
  "pm10": 25
}
```

**감정 이벤트** (`carecall.emotion`):
```json
{
  "emotion": "happy",
  "start": true,
  "phase": "start",
  "timestamp": 1234567890.123
}
```

### MQTT 메시지 형식

**색채 치료** (`taesik/therapy/color`):
```json
{
  "rgb": [100, 149, 237],
  "intensity": 0.65,
  "mode": "relax",
  "duration": 600,
  "confidence": 0.85,
  "metrics": {
    "hr": 72.5,
    "rr": 16.0,
    "q": 0.75,
    "dT_nose": -0.05,
    "dT_cheek": 0.12
  },
  "ts": 1234567890
}
```

**Pico 호환** (`pico/color`):
```json
{
  "r": 100,
  "g": 149,
  "b": 237,
  "intensity": 0.65
}
```

---

## 설정 관리

### 환경 변수

**CareCall**:
- `CARECALL_NOISE_THRESHOLD`: 소음 임계값
- `CARECALL_MOTION_REQUIRED`: 모션 필수 여부
- `CARECALL_MOTION_WINDOW_SEC`: 모션 윈도우
- `CARECALL_WAKE_PHRASES`: 호출어 (쉼표 구분)
- `OPENAI_API_KEY`: OpenAI API 키
- `DEEPCARE_CONFIG`: 설정 파일 경로

**Thermal rPPG**:
- `RPPG_DEBUG_VISUAL`: 디버그 UI 활성화 (0/1)

**Display**:
- `DISPLAY_DEMO_MODE`: 데모 모드 (0/1)
- `NOISE_SENSOR_ASSUME_DB`: 소음 센서 단위 (dB/ADC)

**Kafka**:
- `KAFKA_BOOTSTRAP_SERVERS`: 브로커 주소
- `KAFKA_SENSOR_TOPIC`: 센서 토픽
- `KAFKA_EMO_TOPIC`: 감정 토픽
- `KAFKA_EMO_ENABLED`: 감정 이벤트 활성화

**MQTT**:
- `MQTT_HOST`: 브로커 주소
- `MQTT_PORT`: 포트
- `MQTT_TOPIC_BASE`: 토픽 베이스

### 설정 파일

**CareCall** (`config.json`):
```json
{
  "audio": {
    "sample_rate": 16000,
    "channels": 1,
    "vad_aggressiveness": 3
  },
  "whisper": {
    "model": "whisper-1",
    "language": "ko"
  },
  "openai": {
    "api_key": "...",
    "tts_model": "tts-1",
    "tts_voice": "nova"
  },
  "server": {
    "base_url": "https://deepcare-api.thedeeplabs.com/api",
    "timeout": 30
  },
  "activation": {
    "noise_threshold": 1000,
    "motion_required": true,
    "wake_phrases": ["케어콜 시작"]
  }
}
```

---

## 실행 방법

### 1. Launcher로 전체 시스템 실행

```bash
# 기본 모듈 (carecall, rppg, display-switcher)
python -m apps.launcher

# 특정 모듈만 실행
python -m apps.launcher -m carecall -m rppg

# 모듈별 인자 전달
python -m apps.launcher --module-arg carecall=--mode=test
```

### 2. 개별 모듈 실행

**CareCall**:
```bash
# 대화형 모드
python -m modules.carecall.main

# STT만 테스트
python -m modules.carecall.main --mode stt-only

# 시스템 테스트
python -m modules.carecall.main --mode test
```

**Thermal rPPG**:
```bash
python -m modules.rppg.thermal_rppg
```

**Display Switcher**:
```bash
python -m apps.display_switcher --idle-timeout 30
```

**Sensor Display**:
```bash
python -m modules.display.sensor_display
```

### 3. UART 수신 테스트

```bash
python -m networks.uart.uart_receiver --dev /dev/serial0 --baud 9600
```

---

## 주요 알고리즘

### 1. HR 계산 알고리즘

1. **ROI 추출**: 이마, 볼, 코에서 온도 시계열 추출
2. **전처리**:
   - Ambient 보정 (선택)
   - 웨이블릿 노이즈 제거 (선택)
   - 대역통과 필터 (0.7-4.0 Hz)
3. **FFT 분석**:
   - Hanning 윈도우
   - 주파수 도메인 변환
   - 피크 검출
4. **하모닉 교정**:
   - 2배 오류: f0 > 1.8Hz이고 f0/2 파워가 충분하면 → f0/2
   - 반배 오류: f0 < 1.2Hz이고 2*f0 파워가 크면 → 2*f0
5. **ROI 융합**:
   - SNR 기반 가중치
   - 앙상블 학습 가중치 (선택)
   - 품질 보정 (모션, 발한)
6. **평활화**:
   - 칼만 필터 (선택)
   - 속도 제한 (초당 최대 변화량)
   - EMA 평활

### 2. 얼굴 감지 알고리즘

1. **임계값 설정**:
   - Ambient + delta
   - 또는 상위 75% 백분위수
2. **이진화**: 임계값 이상 픽셀 추출
3. **형태학적 연산**: Opening, Closing
4. **연결 컴포넌트 분석**
5. **스코어링**:
   - 온도 점수
   - 면적 점수
   - 중심 거리 점수
   - 상단 편향 보너스
6. **템플릿 추적**: 이전 프레임과 유사도 비교

### 3. 색채 치료 추천 알고리즘

1. **스트레스 지수 계산**:
   - HR ≥ 95 BPM → +스트레스
   - RR ≥ 20 brpm → +스트레스
   - ΔT_nose ≤ -0.15°C → +스트레스 (비부 냉각)
   - 신호 품질 낮음 → +스트레스
2. **모드 선택**:
   - 발열 (forehead ≥ 37.5°C) → cooling
   - 저체온 (< 36°C) → warming
   - 고스트레스 (ΔT_nose ≤ -0.15 또는 HR ≥ 95) → relax/deep_relax
   - 저활성 (HR ≤ 58, RR ≤ 10, ΔT_cheek ≥ 0.1) → energize
   - 중간 → balance/focus
3. **강도 계산**:
   - 기본값: 0.8 - 0.4 * stress
   - 품질 보정: 0.7 + 0.3 * q
4. **지속시간 계산**:
   - 기본값: 600초
   - 스트레스 보정: 1 + 0.8 * stress
   - 품질 보정: 0.8 + 0.4 * (1 - |0.5 - q|)

---

## 의존성 및 기술 스택

### 핵심 라이브러리

**음성 처리**:
- `openai`: Whisper STT, TTS
- `sounddevice`: 오디오 입출력
- `torch`: Silero VAD (선택)

**영상 처리**:
- `opencv-python`: 이미지 처리, 얼굴 감지
- `numpy`: 수치 계산
- `scipy`: 신호 처리 (필터, FFT)

**머신러닝** (선택):
- `scikit-learn`: 앙상블 학습
- `pywavelets`: 웨이블릿 노이즈 제거

**통신**:
- `kafka-python-ng`: Kafka 클라이언트
- `paho-mqtt`: MQTT 클라이언트
- `pyserial`: UART 통신

**하드웨어**:
- `adafruit-circuitpython-mlx90640`: MLX90640 센서
- `adafruit-circuitpython-mlx90641`: MLX90641 센서
- `board`, `busio`: CircuitPython I2C

**디스플레이**:
- `pygame`: 원형 디스플레이

**기타**:
- `requests`: HTTP 클라이언트
- `psutil`: 시스템 모니터링

### 요구사항

**Python**: 3.8+

**시스템 요구사항**:
- Raspberry Pi (권장: Pi 5)
- MLX90640/90641 열상 센서
- 오디오 입출력 장치
- 원형 디스플레이 (480x480, 선택)

---

## 추가 정보

### 디버깅 팁

1. **Thermal rPPG 얼굴 인식 실패**:
   - `temp_face_min/max` 조정
   - `ambient_delta` 완화
   - 로그 확인: `logger.warning` 메시지

2. **CareCall 활성화 안 됨**:
   - Kafka 연결 확인
   - 센서 데이터 확인 (`kafka-console-consumer`)
   - 활성화 조건 로그 확인

3. **디스플레이 전환 안 됨**:
   - Kafka 감정 토픽 확인
   - Display Switcher 로그 확인
   - `--log-events` 옵션 사용

### 성능 최적화

1. **Raspberry Pi**:
   - `enable_pi_optimization=True`
   - `pi_reduced_precision=True`
   - 메모리 제한 설정

2. **빠른 측정**:
   - `enable_fast_mode=True`
   - 최소 측정 시간 감소

3. **UI 부하 감소**:
   - `debug_visual=False` (UI 비활성화)
   - `ui_stride` 증가

---

## 파일 구조 요약

```
deeptree/src/
├── apps/
│   ├── launcher.py              # 모듈 런처
│   └── display_switcher.py     # 디스플레이 전환
├── modules/
│   ├── carecall/
│   │   ├── main.py              # 메인 진입점
│   │   ├── config.py            # 설정
│   │   ├── activation.py        # 센서 활성화
│   │   └── stt_tts/            # 음성 처리
│   ├── rppg/
│   │   ├── thermal_rppg.py      # 메인 파이프라인
│   │   └── color_therapy_adapter.py  # 색채 치료
│   └── display/
│       ├── sensor_display.py    # 센서 디스플레이
│       └── display_for_carecall/ # 케어콜 비디오
├── networks/
│   ├── kafka/
│   │   ├── kafka_config.py      # Kafka 설정
│   │   ├── kafka_producer.py    # 프로듀서
│   │   └── uart_producer.py     # UART → Kafka
│   ├── mqtt/
│   │   ├── mqtt_config.py       # MQTT 설정
│   │   └── mqtt_publisher.py    # 발행자
│   └── uart/
│       └── uart_receiver.py     # UART 수신
└── test/                        # 테스트 코드
```

---

## 결론

DeepTree 프로젝트는 다음과 같은 특징을 가진 통합 IoT 케어 시스템입니다:

1. **모듈화된 구조**: 각 기능이 독립적으로 실행 가능
2. **확장 가능한 아키텍처**: Kafka를 통한 메시지 기반 통신
3. **AI 기반 향상 기능**: 머신러닝을 통한 신호 품질 개선
4. **실시간 처리**: 낮은 지연시간을 위한 최적화
5. **하드웨어 최적화**: Raspberry Pi 특화 최적화

이 문서는 프로젝트의 전체 구조와 각 모듈의 상세 기능을 이해하기 위한 참고 자료입니다.

