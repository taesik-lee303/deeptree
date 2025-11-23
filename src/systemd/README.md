# DeepTree systemd 서비스 설정

라즈베리파이 부팅 시 DeepTree 시스템을 자동으로 실행하는 systemd 서비스 설정입니다.

## 📋 파일 설명

- `deeptree.service`: 통합 Launcher 서비스 (모든 모듈을 한 번에 실행)
- `carecall.service`: 개별 CareCall 모듈 서비스
- `rppg.service`: 개별 rPPG 모듈 서비스
- `display_switcher.service`: 개별 Display Switcher 서비스
- `install_service.sh`: 통합 Launcher 서비스 설치 스크립트
- `install_module_service.sh`: 개별 모듈 서비스 설치 스크립트
- `uninstall_service.sh`: 모든 서비스 제거 스크립트
- `fix_service.sh`: 기존 서비스 파일의 경로를 수정하는 스크립트
- `check_service_conflicts.sh`: 서비스 충돌 확인 스크립트
- `SERVICE_CONFLICT_GUIDE.md`: 서비스 충돌 방지 가이드
- `README.md`: 이 문서

## ⚠️ 중요: 서비스 충돌 주의

**두 가지 실행 방식을 동시에 사용하면 안 됩니다!**

- **방식 1**: `deeptree.service` (통합 Launcher) - `apps/launcher.py` 실행
- **방식 2**: 개별 서비스들 (`deeptree-carecall.service`, `deeptree-rppg.service`, `deeptree-display-switcher.service`)

충돌 확인:
```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash check_service_conflicts.sh
```

자세한 내용은 [SERVICE_CONFLICT_GUIDE.md](SERVICE_CONFLICT_GUIDE.md)를 참조하세요.

## 🚀 빠른 설치

### ⚠️ 먼저 확인: 서비스 충돌 체크

설치 전에 충돌을 확인하세요:

```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash check_service_conflicts.sh
```

### 방법 1: 개별 서비스 설치 (권장)

각 모듈을 독립적인 서비스로 실행:

```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash install_module_service.sh carecall
sudo bash install_module_service.sh rppg
sudo bash install_module_service.sh display-switcher
```

**장점:**
- 모듈별 독립 재시작
- 한 모듈 실패가 다른 모듈에 영향 없음
- 개별 모듈 로그 확인 용이
- 모듈별 리소스 제한 설정 가능

### 방법 2: 통합 Launcher 설치

모든 모듈을 한 번에 실행:

```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash install_service.sh
```

**주의:** 개별 서비스와 동시에 사용하면 충돌이 발생합니다!

### 방법 1-1: 기존 서비스 파일 수정 (경로 오류 시)

```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash install_service.sh
```

스크립트가 다음을 자동으로 수행합니다:
1. 프로젝트 경로 자동 감지
2. 가상환경 경로 자동 감지 (프로젝트 상위 폴더의 venv 우선)
3. 서비스 파일 생성 및 경로 수정
4. systemd에 등록
5. 서비스 활성화

### 방법 1-1: 기존 서비스 파일 수정 (경로 오류 시)

서비스가 이미 설치되어 있지만 경로가 잘못된 경우:

```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash fix_service.sh
```

이 스크립트는:
1. 현재 서비스 파일을 백업
2. 가상환경 경로 자동 감지
3. 프로젝트 경로 자동 감지
4. 서비스 파일 경로 수정
5. systemd 재로드

### 방법 2: 수동 설치

#### 1. 서비스 파일 수정

`deeptree.service` 파일을 열어서 경로를 실제 프로젝트 경로로 수정:

```bash
nano deeptree.service
```

다음 항목들을 수정:
- `WorkingDirectory`: 프로젝트 src 폴더 경로
- `ExecStart`: 가상환경 Python 경로
- `User`: 실행할 사용자 이름 (기본: pi)
- `EnvironmentFile`: .env 파일 경로 (선택적)

예시:
```ini
WorkingDirectory=/home/pi/deeptree/src
ExecStart=/home/pi/deeptree/src/venv/bin/python -m apps.launcher
User=pi
EnvironmentFile=/home/pi/deeptree/src/.env
```

#### 2. 서비스 파일 복사

```bash
sudo cp deeptree.service /etc/systemd/system/
```

#### 3. systemd 재로드 및 활성화

```bash
sudo systemctl daemon-reload
sudo systemctl enable deeptree
sudo systemctl start deeptree
```

## 📊 서비스 관리

### 서비스 상태 확인

```bash
# 서비스 상태 확인 (자동 시작 포함)
cd ~/deepcare/deeptree/src/systemd
bash check_service.sh
```

또는 직접 확인:

```bash
# 서비스 상태
sudo systemctl status deeptree

# 자동 시작 활성화 여부 확인
systemctl is-enabled deeptree
```

### 서비스 시작/중지/재시작

```bash
# 시작
sudo systemctl start deeptree

# 중지
sudo systemctl stop deeptree

# 재시작
sudo systemctl restart deeptree

# 상태 확인
sudo systemctl status deeptree
```

### 부팅 시 자동 시작 설정

```bash
# 자동 시작 활성화 (부팅 시 자동 실행)
sudo systemctl enable deeptree

# 자동 시작 비활성화
sudo systemctl disable deeptree

# 확인
systemctl is-enabled deeptree
# enabled = 자동 시작 활성화됨
# disabled = 자동 시작 비활성화됨
```

### 디스플레이 크기 조정

센서 디스플레이는 기본적으로 480x480 해상도로 실행됩니다. 다른 크기로 실행하려면 `DISPLAY_SENSOR_SIZE` 환경 변수를 설정하세요.

```ini
[Service]
Environment="DISPLAY_SENSOR_SIZE=480"   # 예: 480, 360, 240 등 원하는 해상도
Environment="DISPLAY_SENSOR_OFFSET_Y=-20"  # 디스플레이 위치 보정 (픽셀 단위, 음수는 위로)
```

또는 수동 실행 시:

```bash
DISPLAY_SENSOR_SIZE=360 python -m modules.display.sensor_display
# 위치만 조정할 때
DISPLAY_SENSOR_OFFSET_Y=-20 python -m modules.display.sensor_display
```

센서 디스플레이는 크기에 맞춰 자동으로 요소 배치를 조정합니다.

### 개별 모듈을 별도 서비스로 실행

케어콜, rPPG, 디스플레이 스위처를 각각 독립된 systemd 서비스로 등록하면, 특정 모듈이 실패했을 때만 자동으로 재시작할 수 있습니다.

```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash install_module_service.sh carecall
sudo bash install_module_service.sh rppg
sudo bash install_module_service.sh display-switcher
```

설치 후 상태 확인:

```bash
sudo systemctl status deeptree-carecall
sudo systemctl status deeptree-rppg
sudo systemctl status deeptree-display-switcher
```

각 서비스는 `Restart=always` 정책이 적용되어 있어 장애 발생 시 자동으로 재시작됩니다. 필요 시 `sudo systemctl disable <service>`로 비활성화할 수 있습니다.

### 로그 확인

```bash
# 실시간 로그 보기
sudo journalctl -u deeptree -f

# 최근 로그 (100줄)
sudo journalctl -u deeptree -n 100

# 오늘 로그
sudo journalctl -u deeptree --since today

# 특정 시간 이후 로그
sudo journalctl -u deeptree --since "2025-01-01 10:00:00"
```

### 서비스 비활성화 및 제거

#### 방법 1: 제거 스크립트 사용 (권장)

모든 DeepTree 서비스를 한 번에 제거:

```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash uninstall_service.sh
```

이 스크립트가 자동으로:
- ✅ 모든 서비스 중지
- ✅ 자동 시작 비활성화
- ✅ 서비스 파일 삭제
- ✅ systemd 재로드

#### 방법 2: 수동 제거

```bash
# 서비스 중지 및 비활성화
sudo systemctl stop deeptree
sudo systemctl disable deeptree

# 개별 서비스도 제거하려면
sudo systemctl stop deeptree-carecall
sudo systemctl stop deeptree-rppg
sudo systemctl stop deeptree-display-switcher
sudo systemctl disable deeptree-carecall
sudo systemctl disable deeptree-rppg
sudo systemctl disable deeptree-display-switcher

# 서비스 파일 삭제
sudo rm /etc/systemd/system/deeptree.service
sudo rm /etc/systemd/system/deeptree-carecall.service
sudo rm /etc/systemd/system/deeptree-rppg.service
sudo rm /etc/systemd/system/deeptree-display-switcher.service

# systemd 재로드
sudo systemctl daemon-reload
```

## ⚙️ 서비스 설정 커스터마이징

### 특정 모듈만 실행

서비스 파일의 `ExecStart` 줄을 수정:

```ini
# 기본 (carecall, rppg, display-switcher)
ExecStart=/home/pi/deeptree/src/venv/bin/python -m apps.launcher

# 특정 모듈만
ExecStart=/home/pi/deeptree/src/venv/bin/python -m apps.launcher -m carecall -m rppg

# 디스플레이 포함
ExecStart=/home/pi/deeptree/src/venv/bin/python -m apps.launcher --include-display
```

### 환경 변수 추가

서비스 파일의 `[Service]` 섹션에 추가:

```ini
[Service]
Environment="OPENAI_API_KEY=your-api-key"
Environment="KAFKA_BOOTSTRAP_SERVERS=localhost:9092"
Environment="MQTT_HOST=203.250.148.52"
```

또는 `.env` 파일 사용:

```ini
EnvironmentFile=/home/pi/deeptree/src/.env
```

### 재시작 정책 조정

```ini
[Service]
# 항상 재시작 (기본)
Restart=always
RestartSec=10

# 실패 시에만 재시작
Restart=on-failure
RestartSec=5

# 재시작 안 함
Restart=no
```

### 리소스 제한 설정

```ini
[Service]
# 메모리 제한 (1GB)
MemoryLimit=1G

# CPU 사용률 제한 (80%)
CPUQuota=80%

# 프로세스 수 제한
TasksMax=50
```

## 🔍 문제 해결

### 서비스가 시작되지 않음

```bash
# 상태 확인
sudo systemctl status deeptree

# 상세 로그 확인
sudo journalctl -u deeptree -n 50

# 가상환경 확인
ls -l /home/pi/deeptree/src/venv/bin/python

# 프로젝트 경로 확인
ls -l /home/pi/deeptree/src/apps/launcher.py
```

### 권한 문제

```bash
# 프로젝트 폴더 권한 확인
ls -la /home/pi/deeptree/src

# 사용자 권한 확인
whoami
id

# 필요시 권한 수정
sudo chown -R pi:pi /home/pi/deeptree
```

### 네트워크 연결 문제

서비스가 네트워크 준비 전에 시작되는 경우:

```ini
[Unit]
After=network-online.target
Wants=network-online.target
```

### 가상환경 경로 설정

#### 방법 1: 설치 스크립트 사용 (자동 감지)

설치 스크립트가 다음 경로를 **우선순위 순서**로 확인합니다:
1. `프로젝트경로/../venv` (예: `/home/aisl/deepcare/venv` - 프로젝트 상위 폴더)
2. `~/deepcare/venv`
3. `프로젝트경로/venv` (프로젝트 내부)
4. `~/deeptree/venv`

자동으로 찾지 못하면 사용자 입력을 요청합니다.

**참고**: 가상환경과 프로젝트가 다른 위치에 있는 경우 (예: `/home/aisl/deepcare/venv`와 `/home/aisl/deepcare/deeptree/src`) 자동으로 감지됩니다.

#### 방법 2: 수동 설정

`deeptree.service` 파일에서 다음 두 곳을 수정:

1. **ExecStart** (가상환경 Python 경로):
```ini
ExecStart=/home/aisl/deepcare/venv/bin/python -m apps.launcher
```

2. **Environment PATH** (가상환경 bin 경로):
```ini
Environment="PATH=/home/aisl/deepcare/venv/bin:/usr/local/bin:/usr/bin:/bin"
```

#### 가상환경 경로 확인 방법

```bash
# 현재 활성화된 가상환경 경로 확인
which python
# 또는
echo $VIRTUAL_ENV

# 가상환경 Python 경로 확인
python -c "import sys; print(sys.executable)"
```

#### 예시: 다른 경로의 가상환경 사용

```ini
[Service]
# 가상환경이 /home/aisl/deepcare/venv에 있는 경우
WorkingDirectory=/home/aisl/deepcare/deeptree/src
ExecStart=/home/aisl/deepcare/venv/bin/python -m apps.launcher
Environment="PATH=/home/aisl/deepcare/venv/bin:/usr/local/bin:/usr/bin:/bin"
```

#### 시스템 Python 사용 (권장하지 않음)

가상환경을 사용하지 않는 경우:

```ini
ExecStart=/usr/bin/python3 -m apps.launcher
Environment="PYTHONPATH=/home/pi/deeptree/src"
```

## 📝 참고사항

1. **가상환경 필수**: 서비스는 가상환경의 Python을 사용합니다.
2. **네트워크 의존성**: Kafka, MQTT 등 네트워크 서비스가 필요합니다.
3. **하드웨어 접근**: I2C, UART 등 하드웨어 인터페이스 접근 권한이 필요합니다.
4. **로그 관리**: `journalctl`로 로그를 확인할 수 있습니다.
5. **자동 재시작**: 기본적으로 서비스가 종료되면 자동으로 재시작됩니다.

## ⚙️ 최적화 내용 (v2.0)

### 해결된 문제점들

#### 1. 재부팅 후 두 번째 발화 트리거 미응답
**문제**: 첫 번째 대화 후 두 번째 호출어에 응답하지 않음
**원인**: STT Manager와 오디오 장치가 완전히 정리되지 않음
**해결**:
- `ExecStartPre`에서 Kafka 포트 체크 추가 (최대 60초 대기)
- 오디오 그룹 자동 추가 (`install_module_service.sh`)
- STT Manager 완전 정리 로직 강화 (Python 코드)

#### 2. 디스플레이 전환 실패
**문제**: 재부팅 후 케어콜 시작 시 디스플레이가 전환되지 않음
**원인**: Kafka 이벤트 수신 실패, 서비스 시작 순서 문제
**해결**:
- `display_switcher.service`에 Kafka 포트 체크 추가
- 이벤트 처리 로직 개선 (`start=True`, `emotion` 필드 감지)
- 상세한 로그 추가로 디버깅 용이

#### 3. Kafka 연결 실패
**문제**: 재부팅 직후 Kafka가 준비되기 전에 서비스 시작
**원인**: Docker Compose Kafka 시작 지연
**해결**:
- `ExecStartPre`에서 `nc -z localhost 9092`로 포트 체크
- 최대 60초 대기 (1초 간격)
- `netcat-openbsd` 자동 설치

#### 4. 오디오 장치 접근 권한
**문제**: 마이크 접근 실패 (`PaErrorCode -9998`)
**원인**: 사용자가 `audio` 그룹에 없음
**해결**:
- `install_module_service.sh`에서 자동으로 `audio` 그룹 추가
- `dialout` 그룹도 자동 추가 (UART 접근용)

### 추가된 최적화 기능

#### 1. 재시작 정책 개선
```ini
Restart=always
RestartSec=5
StartLimitIntervalSec=300  # 5분 내 최대 5회 재시작
StartLimitBurst=5
```
- 지수 백오프로 무한 재시작 방지
- 5분 내 5회 실패 시 재시작 중단 (시스템 보호)

#### 2. 타임아웃 설정
```ini
TimeoutStartSec=120   # 시작 타임아웃 2분
TimeoutStopSec=30     # 종료 타임아웃 30초
```
- 무한 대기 방지
- 정상 종료 보장

#### 3. 리소스 제한
```ini
MemoryLimit=2G        # 최대 메모리 2GB
MemoryHigh=1.5G       # 경고 임계값 1.5GB
```
- 메모리 누수 방지
- 시스템 안정성 향상

#### 4. 프로세스 종료 정책
```ini
KillMode=mixed        # 메인 프로세스와 자식 프로세스 모두 종료
KillSignal=SIGTERM    # 우아한 종료 시도
```
- 디스플레이 프로세스 완전 종료 보장
- 좀비 프로세스 방지

### 서비스별 최적화

#### carecall.service
- Kafka 포트 체크 (`ExecStartPre`)
- 오디오 그룹 자동 추가
- 메모리 제한 2GB
- 시작 타임아웃 120초

#### display_switcher.service
- Kafka 포트 체크 (`ExecStartPre`)
- 메모리 제한 1GB
- 독립 실행 (carecall과 의존성 없음)

### 설치 시 자동 처리

`install_module_service.sh`가 자동으로 처리:
1. ✅ 오디오 그룹 추가 (carecall 모듈)
2. ✅ dialout 그룹 추가 (UART 접근)
3. ✅ netcat-openbsd 설치 (Kafka 포트 체크)
4. ✅ 경로 자동 감지 및 설정

### 문제 해결 체크리스트

재부팅 후 문제가 발생하면:

1. **서비스 상태 확인**
   ```bash
   sudo systemctl status deeptree-carecall
   sudo systemctl status deeptree-display-switcher
   ```

2. **로그 확인**
   ```bash
   journalctl -u deeptree-carecall -n 100 -f
   journalctl -u deeptree-display-switcher -n 100 -f
   ```

3. **Kafka 연결 확인**
   ```bash
   nc -z localhost 9092 && echo "Kafka is ready" || echo "Kafka not ready"
   ```

4. **오디오 그룹 확인**
   ```bash
   groups $USER | grep audio
   ```

5. **오디오 장치 확인**
   ```bash
   arecord -l
   ```

## 🔗 관련 문서

- [RASPBERRY_PI_SETUP_GUIDE.md](../../docs/RASPBERRY_PI_SETUP_GUIDE.md) - 전체 설정 가이드
- [launcher.py](../apps/launcher.py) - 런처 모듈

