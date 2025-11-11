# Kafka-Driven MP4 Player Module

카프카 이벤트를 받아서 해당 데이터에 따라 다른 MP4 파일을 재생하는 모듈입니다.

## 주요 기능

- **카프카 소비자**: 실시간으로 카프카 토픽에서 이벤트를 수신
- **조건부 비디오 재생**: 수신된 데이터에 따라 적절한 MP4 파일 선택 및 재생
- **우선순위 기반 선택**: 여러 조건이 맞을 때 우선순위에 따라 비디오 선택
- **플레이어 제어**: 재생, 중지, 상태 모니터링
- **이벤트 핸들러**: 커스텀 이벤트 처리 로직 추가 가능

## 설치 요구사항

```bash
pip install kafka-python-ng
```

비디오 재생을 위해 다음 중 하나가 설치되어 있어야 합니다:
- ffplay (FFmpeg에 포함)
- VLC media player
- mplayer

## 사용법

### 기본 사용법

```python
 modules.display.display_for_carecall import MP4Player, PlayerConfig

# 플레이어 설정
config = PlayerConfig(
    bootstrap_servers="localhost:9092",
    topic="carecall.emotion",
    video_directory="./videos",
    group_id="mp4-player"
)

# 플레이어 생성 및 시작
player = MP4Player(config)
player.start()

# 이벤트 핸들러 추가 (선택사항)
def event_handler(data):
    print(f"Received event: {data}")

player.add_event_handler(event_handler)
```

### 커스텀 비디오 설정

```python
from modules.display.display_for_carecall import VideoConfig

# 커스텀 비디오 설정 추가
custom_video = VideoConfig(
    file_path="./videos/special.mp4",
    trigger_conditions={"emotion": "happy", "intensity": "high"},
    priority=5,
    volume=1.0
)

player.add_video_config("special_happy", custom_video)
```

## 설정 옵션

### PlayerConfig

- `bootstrap_servers`: 카프카 브로커 주소 (기본값: "localhost:9092")
- `topic`: 구독할 카프카 토픽 (기본값: "carecall.emotion")
- `group_id`: 카프카 소비자 그룹 ID
- `video_directory`: 비디오 파일이 있는 디렉토리 경로
- `default_video`: 기본 비디오 파일 경로 (선택사항)
- `player_command`: 사용할 플레이어 명령어 (기본값: "ffplay")
- `fullscreen`: 전체화면 재생 여부 (기본값: True)
- `volume`: 기본 볼륨 (0.0-1.0, 기본값: 0.8)
- `debounce_ms`: 중복 이벤트 필터링 시간 (밀리초, 기본값: 1000)

### VideoConfig

- `file_path`: 비디오 파일 경로
- `trigger_conditions`: 재생 조건 (딕셔너리)
- `priority`: 우선순위 (높은 숫자가 우선, 기본값: 0)
- `loop`: 반복 재생 여부 (기본값: False)
- `volume`: 볼륨 설정 (0.0-1.0, 기본값: 1.0)

## 기본 비디오 매핑

모듈은 다음과 같은 기본 감정별 비디오 매핑을 제공합니다:

- `happy.mp4`: 기쁜 감정 (`{"emotion": "happy"}`)
- `sad.mp4`: 슬픈 감정 (`{"emotion": "sad"}`)
- `angry.mp4`: 화난 감정 (`{"emotion": "angry"}`)
- `neutral.mp4`: 중성 감정 (`{"emotion": "neutral"}`)
- `default.mp4`: 기본 비디오 (조건이 맞지 않을 때)

## 카프카 메시지 형식

예상되는 카프카 메시지 형식:

```json
{
    "emotion": "happy",
    "timestamp": 1640995200.0,
    "confidence": 0.85,
    "intensity": "high",
    "context": "conversation"
}
```

## 예제

### 1. 기본 실행

```bash
cd src/modules/media
python example_usage.py
```

### 2. 직접 플레이어 실행

```bash
cd src/modules/media
python mp4_player.py --kafka localhost:9092 --topic carecall.emotion --videos ./videos
```

### 3. 프로그래밍 방식

```python
from modules.display.display_for_carecall import MP4Player, create_default_config

# 기본 설정으로 플레이어 생성
config = create_default_config(
    kafka_servers="localhost:9092",
    topic="carecall.emotion",
    video_dir="./videos"
)

player = MP4Player(config)
player.start()

try:
    # 메인 로직
    while True:
        time.sleep(1)
finally:
    player.stop()
```

## 디렉토리 구조

```
src/modules/display/display_for_carecall
├── __init__.py              # 모듈 초기화
├── mp4_player.py           # 메인 플레이어 클래스
├── example_usage.py        # 사용 예제
├── README.md              # 이 문서
└── videos/                # 비디오 파일 디렉토리 (사용자 생성)
    ├── happy.mp4
    ├── sad.mp4
    ├── angry.mp4
    ├── neutral.mp4
    └── default.mp4
```

## 상태 모니터링

플레이어 상태는 다음과 같이 확인할 수 있습니다:

```python
status = player.get_status()
print(status)
# 출력: {
#     "state": "playing",
#     "current_video": "./videos/happy.mp4",
#     "video_configs": 5,
#     "running": True
# }
```

## 로깅

모듈은 표준 Python logging을 사용합니다:

```python
import logging
logging.basicConfig(level=logging.INFO)

# 또는 파일로 로그 저장
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mp4_player.log'),
        logging.StreamHandler()
    ]
)
```

## 문제 해결

### 비디오가 재생되지 않는 경우

1. 비디오 파일 경로 확인
2. ffplay/vlc 설치 확인
3. 파일 권한 확인
4. 로그에서 오류 메시지 확인

### 카프카 연결 문제

1. 카프카 브로커가 실행 중인지 확인
2. bootstrap_servers 주소 확인
3. 토픽이 존재하는지 확인
4. 네트워크 연결 확인

### 성능 최적화

- `debounce_ms` 값 조정으로 이벤트 필터링
- 비디오 파일 크기 최적화
- SSD 사용으로 I/O 성능 향상
- 카프카 소비자 설정 튜닝

## 기여

이 모듈에 기여하려면:

1. 기능 추가 또는 버그 수정
2. 테스트 코드 작성
3. 문서 업데이트
4. Pull Request 제출