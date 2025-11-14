#!/bin/bash
# 라즈베리파이5 SD 카드 용량 확보 스크립트
# 현재 프로젝트에 필요한 것 외에는 정리

set -e

echo "=========================================="
echo "라즈베리파이5 SD 카드 용량 확보 스크립트"
echo "=========================================="
echo ""

# 현재 용량 확인
echo "=== 현재 디스크 사용량 ==="
df -h /
echo ""

# 1. APT 패키지 캐시 정리
echo "=== 1. APT 패키지 캐시 정리 ==="
sudo apt-get clean
sudo apt-get autoclean
sudo apt-get autoremove -y
echo "완료"
echo ""

# 2. PIP 캐시 정리
echo "=== 2. PIP 캐시 정리 ==="
pip cache purge 2>/dev/null || python3 -m pip cache purge 2>/dev/null || echo "PIP 캐시 없음"
echo "완료"
echo ""

# 3. 로그 파일 정리 (7일 이상 된 로그)
echo "=== 3. 오래된 로그 파일 정리 ==="
sudo journalctl --vacuum-time=7d 2>/dev/null || echo "journalctl 정리 완료"
sudo find /var/log -type f -name "*.log" -mtime +7 -delete 2>/dev/null || echo "로그 파일 정리 완료"
sudo find /var/log -type f -name "*.gz" -delete 2>/dev/null || echo "압축 로그 파일 정리 완료"
echo "완료"
echo ""

# 4. 임시 파일 정리
echo "=== 4. 임시 파일 정리 ==="
sudo rm -rf /tmp/* 2>/dev/null || echo "임시 파일 정리 완료"
sudo rm -rf /var/tmp/* 2>/dev/null || echo "var/tmp 정리 완료"
rm -rf ~/.cache/* 2>/dev/null || echo "사용자 캐시 정리 완료"
echo "완료"
echo ""

# 5. 사용하지 않는 패키지 제거 (선택적)
echo "=== 5. 사용하지 않는 패키지 확인 ==="
echo "다음 명령으로 확인 가능: sudo apt-get autoremove --purge"
echo "건너뜀 (수동 확인 권장)"
echo ""

# 6. Python __pycache__ 및 .pyc 파일 정리
echo "=== 6. Python 캐시 파일 정리 ==="
find ~ -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || echo "Python 캐시 정리 완료"
find ~ -type f -name "*.pyc" -delete 2>/dev/null || echo "pyc 파일 정리 완료"
find ~ -type f -name "*.pyo" -delete 2>/dev/null || echo "pyo 파일 정리 완료"
echo "완료"
echo ""

# 7. Docker 정리 (Docker가 설치되어 있는 경우)
echo "=== 7. Docker 정리 (있는 경우) ==="
if command -v docker &> /dev/null; then
    docker system prune -af --volumes 2>/dev/null || echo "Docker 정리 완료"
else
    echo "Docker 미설치"
fi
echo ""

# 8. Snap 패키지 정리 (있는 경우)
echo "=== 8. Snap 패키지 정리 (있는 경우) ==="
if command -v snap &> /dev/null; then
    sudo snap list --all | awk '/disabled/{print $1, $3}' | while read snapname revision; do
        sudo snap remove "$snapname" --revision="$revision" 2>/dev/null || true
    done
    echo "완료"
else
    echo "Snap 미설치"
fi
echo ""

# 9. 사용하지 않는 로케일 파일 정리
echo "=== 9. 사용하지 않는 로케일 파일 정리 ==="
sudo apt-get install -y localepurge 2>/dev/null || echo "localepurge 설치 실패 (선택적)"
echo ""

# 최종 용량 확인
echo "=========================================="
echo "=== 정리 후 디스크 사용량 ==="
df -h /
echo ""

# 용량 확보 요약
echo "=========================================="
echo "정리 완료!"
echo ""
echo "추가로 확인할 수 있는 항목:"
echo "1. 홈 디렉토리 큰 파일 찾기: du -h ~ | sort -rh | head -20"
echo "2. 전체 시스템 큰 파일 찾기: sudo du -h / | sort -rh | head -20"
echo "3. 사용하지 않는 패키지: sudo apt-get autoremove --purge"
echo "=========================================="

