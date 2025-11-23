# 서비스 충돌 방지 가이드

## ⚠️ 중요: 두 가지 실행 방식

DeepTree는 두 가지 방식으로 실행할 수 있습니다:

### 방식 1: 통합 Launcher (deeptree.service)
- `apps/launcher.py`가 모든 모듈을 한 번에 실행
- 기본적으로 실행: `carecall`, `rppg`, `display-switcher`
- 장점: 간단한 설정, 하나의 서비스로 관리
- 단점: 한 모듈이 실패하면 전체 재시작, 개별 모듈 제어 어려움

### 방식 2: 개별 서비스 (권장)
- 각 모듈을 독립적인 systemd 서비스로 실행
- `deeptree-carecall.service`, `deeptree-rppg.service`, `deeptree-display-switcher.service`
- 장점: 모듈별 독립 재시작, 개별 모듈 제어 가능, 장애 격리
- 단점: 서비스 파일이 여러 개

## 🚨 충돌 문제

**두 방식을 동시에 사용하면 안 됩니다!**

만약 `deeptree.service`와 개별 서비스들이 모두 활성화되면:

```
❌ carecall이 2번 실행됨
   - launcher.py에서 실행
   - deeptree-carecall.service에서 실행
   
❌ rppg가 2번 실행됨
   - launcher.py에서 실행
   - deeptree-rppg.service에서 실행
   
❌ display-switcher가 2번 실행됨
   - launcher.py에서 실행
   - deeptree-display-switcher.service에서 실행
```

### 발생 가능한 문제들

1. **Kafka Consumer Group 충돌**
   - 같은 consumer group ID로 여러 인스턴스가 실행되면 메시지가 분산되어 수신 실패

2. **오디오 장치 충돌**
   - 마이크를 여러 프로세스가 동시에 접근하면 `PaErrorCode -9998` 오류

3. **디스플레이 충돌**
   - 같은 디스플레이를 여러 프로세스가 제어하려고 하면 화면 깜빡임 또는 오류

4. **포트/리소스 충돌**
   - UART, I2C 등 하드웨어 리소스 충돌

5. **리소스 낭비**
   - CPU, 메모리 이중 사용

## ✅ 해결 방법

### 방법 1: 개별 서비스만 사용 (권장)

```bash
# 1. deeptree.service 비활성화
sudo systemctl disable deeptree.service
sudo systemctl stop deeptree.service

# 2. 개별 서비스 활성화
sudo systemctl enable deeptree-carecall.service
sudo systemctl enable deeptree-rppg.service
sudo systemctl enable deeptree-display-switcher.service

# 3. 재시작
sudo systemctl restart deeptree-carecall.service
sudo systemctl restart deeptree-rppg.service
sudo systemctl restart deeptree-display-switcher.service
```

### 방법 2: 통합 Launcher만 사용

```bash
# 1. 개별 서비스 비활성화
sudo systemctl disable deeptree-carecall.service
sudo systemctl disable deeptree-rppg.service
sudo systemctl disable deeptree-display-switcher.service
sudo systemctl stop deeptree-carecall.service
sudo systemctl stop deeptree-rppg.service
sudo systemctl stop deeptree-display-switcher.service

# 2. 통합 Launcher 활성화
sudo systemctl enable deeptree.service
sudo systemctl start deeptree.service
```

## 🔍 충돌 확인 방법

### 현재 활성화된 서비스 확인

```bash
# 통합 Launcher 상태
sudo systemctl is-enabled deeptree.service
sudo systemctl is-active deeptree.service

# 개별 서비스 상태
sudo systemctl is-enabled deeptree-carecall.service
sudo systemctl is-enabled deeptree-rppg.service
sudo systemctl is-enabled deeptree-display-switcher.service
```

### 중복 실행 확인

```bash
# carecall 프로세스 확인
ps aux | grep "modules.carecall.main" | grep -v grep

# rppg 프로세스 확인
ps aux | grep "modules.rppg.thermal_rppg" | grep -v grep

# display-switcher 프로세스 확인
ps aux | grep "apps.display_switcher" | grep -v grep
```

각 명령어가 **2개 이상의 프로세스**를 반환하면 충돌이 발생한 것입니다.

### 로그에서 충돌 확인

```bash
# Kafka consumer group 충돌 로그
journalctl -u deeptree-carecall -n 100 | grep -i "consumer\|group\|partition"

# 오디오 장치 충돌 로그
journalctl -u deeptree-carecall -n 100 | grep -i "audio\|device\|PaError"
```

## 📋 권장 설정

**개별 서비스 방식 (방식 2)을 권장합니다:**

1. ✅ 모듈별 독립 재시작 가능
2. ✅ 한 모듈 실패가 다른 모듈에 영향 없음
3. ✅ 개별 모듈 로그 확인 용이
4. ✅ 모듈별 리소스 제한 설정 가능
5. ✅ 더 나은 장애 격리

## 🛠️ 자동 충돌 해결 스크립트

`check_service_conflicts.sh` 스크립트를 실행하여 충돌을 자동으로 확인하고 해결할 수 있습니다:

```bash
cd ~/deepcare/deeptree/src/systemd
sudo bash check_service_conflicts.sh
```

이 스크립트는:
1. 활성화된 서비스 확인
2. 중복 실행 프로세스 확인
3. 충돌 발견 시 경고 및 해결 방법 제시

