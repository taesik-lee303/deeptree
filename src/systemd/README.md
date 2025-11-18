# DeepTree systemd 서비스 설정

라즈베리파이 부팅 시 DeepTree 시스템을 자동으로 실행하는 systemd 서비스 설정입니다.

## 📋 파일 설명

- `deeptree.service`: systemd 서비스 파일
- `install_service.sh`: 서비스 설치 스크립트
- `README.md`: 이 문서

## 🚀 빠른 설치

### 방법 1: 설치 스크립트 사용 (권장)

```bash
cd ~/deeptree/src/systemd
sudo bash install_service.sh
```

스크립트가 다음을 자동으로 수행합니다:
1. 프로젝트 경로 자동 감지
2. 가상환경 확인
3. 서비스 파일 생성 및 경로 수정
4. systemd에 등록
5. 서비스 활성화

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

### 서비스 비활성화

```bash
# 서비스 중지 및 비활성화
sudo systemctl stop deeptree
sudo systemctl disable deeptree

# 서비스 파일 삭제 (선택적)
sudo rm /etc/systemd/system/deeptree.service
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

### 가상환경 문제

가상환경이 활성화되지 않은 경우, `ExecStart`에서 직접 경로 지정:

```ini
ExecStart=/home/pi/deeptree/src/venv/bin/python -m apps.launcher
```

또는 시스템 Python 사용 (권장하지 않음):

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

## 🔗 관련 문서

- [RASPBERRY_PI_SETUP_GUIDE.md](../../docs/RASPBERRY_PI_SETUP_GUIDE.md) - 전체 설정 가이드
- [launcher.py](../apps/launcher.py) - 런처 모듈

