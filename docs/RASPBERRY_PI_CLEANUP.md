# 라즈베리파이5 SD 카드 용량 확보 가이드

## 개요

라즈베리파이5의 SD 카드 용량이 부족할 때, 현재 프로젝트에 필요한 것 외에는 정리하는 방법입니다.

## 자동 정리 스크립트 사용

### 1. 정리 스크립트 실행

```bash
# 스크립트에 실행 권한 부여
chmod +x scripts/cleanup_raspberry_pi.sh

# 스크립트 실행
./scripts/cleanup_raspberry_pi.sh
```

### 2. 큰 파일 찾기

```bash
# 스크립트에 실행 권한 부여
chmod +x scripts/find_large_files.sh

# 큰 파일 찾기
./scripts/find_large_files.sh
```

## 수동 정리 방법

### 1. APT 패키지 캐시 정리

```bash
# 패키지 캐시 정리
sudo apt-get clean
sudo apt-get autoclean

# 사용하지 않는 패키지 제거
sudo apt-get autoremove -y
```

**예상 확보 용량**: 100-500MB

### 2. PIP 캐시 정리

```bash
# PIP 캐시 정리
pip cache purge
# 또는
python3 -m pip cache purge
```

**예상 확보 용량**: 50-200MB

### 3. 로그 파일 정리

```bash
# 시스템 로그 정리 (7일 이상 된 로그만 유지)
sudo journalctl --vacuum-time=7d

# 오래된 로그 파일 삭제
sudo find /var/log -type f -name "*.log" -mtime +7 -delete
sudo find /var/log -type f -name "*.gz" -delete
```

**예상 확보 용량**: 50-300MB

### 4. 임시 파일 정리

```bash
# 임시 파일 정리
sudo rm -rf /tmp/*
sudo rm -rf /var/tmp/*
rm -rf ~/.cache/*
```

**예상 확보 용량**: 10-100MB

### 5. Python 캐시 파일 정리

```bash
# __pycache__ 디렉토리 삭제
find ~ -type d -name "__pycache__" -exec rm -r {} +

# .pyc, .pyo 파일 삭제
find ~ -type f -name "*.pyc" -delete
find ~ -type f -name "*.pyo" -delete
```

**예상 확보 용량**: 10-50MB

### 6. Docker 정리 (Docker 사용 시)

```bash
# 사용하지 않는 Docker 이미지, 컨테이너, 볼륨 정리
docker system prune -af --volumes
```

**예상 확보 용량**: 500MB-2GB (Docker 사용 시)

### 7. Snap 패키지 정리 (Snap 사용 시)

```bash
# 비활성화된 Snap 패키지 제거
sudo snap list --all | awk '/disabled/{print $1, $3}' | while read snapname revision; do
    sudo snap remove "$snapname" --revision="$revision"
done
```

### 8. 큰 파일 찾기

```bash
# 홈 디렉토리에서 큰 파일 찾기
du -h ~ | sort -rh | head -20

# 전체 시스템에서 큰 디렉토리 찾기
sudo du -h / | sort -rh | head -20

# 100MB 이상 파일 찾기
find ~ -type f -size +100M -exec ls -lh {} \;
```

## 주의사항

### ⚠️ 삭제하지 말아야 할 것들

1. **프로젝트 파일**: `/home/pi/deeptree` 또는 프로젝트 경로
2. **설정 파일**: `~/.bashrc`, `~/.profile` 등
3. **SSH 키**: `~/.ssh/`
4. **필수 시스템 파일**: `/etc/`, `/usr/`, `/lib/` 등

### ✅ 안전하게 삭제 가능한 것들

1. 패키지 캐시 (`/var/cache/apt/`)
2. PIP 캐시 (`~/.cache/pip/`)
3. 임시 파일 (`/tmp/`, `/var/tmp/`)
4. 오래된 로그 파일 (`/var/log/`)
5. Python 캐시 (`__pycache__/`, `*.pyc`)
6. 사용하지 않는 패키지

## 용량 확인

### 현재 사용량 확인

```bash
# 디스크 사용량 확인
df -h /

# 특정 디렉토리 크기 확인
du -sh /path/to/directory
```

### 정리 전후 비교

```bash
# 정리 전
df -h / > before.txt

# 정리 후
df -h / > after.txt

# 비교
diff before.txt after.txt
```

## 예상 확보 용량

일반적으로 다음 작업으로 **500MB ~ 2GB** 정도 확보 가능:

- APT 캐시 정리: 100-500MB
- PIP 캐시 정리: 50-200MB
- 로그 파일 정리: 50-300MB
- 임시 파일 정리: 10-100MB
- Python 캐시 정리: 10-50MB
- Docker 정리 (있는 경우): 500MB-2GB

## 추가 최적화

### 1. 사용하지 않는 패키지 제거

```bash
# 사용하지 않는 패키지 목록 확인
sudo apt-get autoremove --dry-run

# 제거
sudo apt-get autoremove --purge
```

### 2. 로케일 파일 정리

```bash
# localepurge 설치
sudo apt-get install localepurge

# 설정 실행
sudo localepurge
```

### 3. 프로젝트 외 불필요한 파일 정리

```bash
# 홈 디렉토리에서 프로젝트 제외하고 큰 파일 찾기
PROJECT_PATH="${HOME}/deeptree"
find ~ -type f -size +50M ! -path "${PROJECT_PATH}/*" -exec ls -lh {} \;
```

## 문제 해결

### 용량이 여전히 부족한 경우

1. **큰 파일 확인**: `find_large_files.sh` 스크립트 실행
2. **미사용 패키지 확인**: `sudo apt list --installed | grep -v deeptree`
3. **홈 디렉토리 확인**: `du -sh ~/* | sort -rh`
4. **시스템 로그 확인**: `sudo journalctl --disk-usage`

### 스크립트 실행 오류

```bash
# 실행 권한 확인
ls -l scripts/cleanup_raspberry_pi.sh

# 실행 권한 부여
chmod +x scripts/cleanup_raspberry_pi.sh

# 직접 실행
bash scripts/cleanup_raspberry_pi.sh
```

## 정기적인 정리

주기적으로 다음 명령을 실행하여 용량을 유지:

```bash
# 주 1회 실행 권장
sudo apt-get clean && sudo apt-get autoremove -y
pip cache purge
sudo journalctl --vacuum-time=7d
```

## 참고

- 프로젝트 파일은 절대 삭제하지 마세요
- 중요한 설정 파일은 백업 후 진행하세요
- 불확실한 파일은 삭제 전에 확인하세요

