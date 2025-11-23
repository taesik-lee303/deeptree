#!/bin/bash
# DeepTree systemd 서비스 제거 스크립트

# set -e 제거 (오류 발생 시에도 계속 진행)
set +e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}DeepTree systemd 서비스 제거 스크립트${NC}"
echo "=========================================="

# 사용자 확인
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}이 스크립트는 sudo 권한이 필요합니다.${NC}"
    echo "사용법: sudo bash uninstall_service.sh"
    exit 1
fi

SYSTEMD_DIR="/etc/systemd/system"

# 제거할 서비스 목록
SERVICES=(
    "deeptree.service"
    "deeptree-carecall.service"
    "deeptree-rppg.service"
    "deeptree-display-switcher.service"
)

echo ""
echo "다음 서비스들을 제거합니다:"
for service in "${SERVICES[@]}"; do
    if [ -f "$SYSTEMD_DIR/$service" ]; then
        echo "  - $service"
    fi
done

echo ""
read -p "계속하시겠습니까? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "취소되었습니다."
    exit 0
fi

echo ""
echo "서비스 제거 중..."

# 각 서비스 제거
for service in "${SERVICES[@]}"; do
    SERVICE_NAME=$(basename "$service" .service)
    
    if [ -f "$SYSTEMD_DIR/$service" ]; then
        echo -e "${YELLOW}제거 중: $SERVICE_NAME${NC}"
        
        # 서비스 중지 (강제 종료 포함)
        if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
            echo "  서비스 중지 중..."
            systemctl stop "$SERVICE_NAME" 2>/dev/null || true
            sleep 1
            # 여전히 실행 중이면 강제 종료
            if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
                echo "  강제 종료 중..."
                systemctl kill "$SERVICE_NAME" 2>/dev/null || true
                sleep 1
            fi
        fi
        
        # 실행 중인 프로세스 확인 및 종료 (서비스 이름 기반)
        PROCESS_NAMES=("python.*carecall" "python.*rppg" "python.*display" "python.*launcher")
        for proc_name in "${PROCESS_NAMES[@]}"; do
            PIDS=$(pgrep -f "$proc_name" 2>/dev/null)
            if [ -n "$PIDS" ]; then
                echo "  실행 중인 프로세스 종료 중: $proc_name"
                kill -TERM $PIDS 2>/dev/null || true
                sleep 1
                # 여전히 실행 중이면 강제 종료
                REMAINING=$(pgrep -f "$proc_name" 2>/dev/null)
                if [ -n "$REMAINING" ]; then
                    kill -KILL $REMAINING 2>/dev/null || true
                fi
            fi
        done
        
        # 자동 시작 비활성화
        if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
            echo "  자동 시작 비활성화 중..."
            systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        fi
        
        # 서비스 파일 삭제
        echo "  서비스 파일 삭제 중..."
        rm -f "$SYSTEMD_DIR/$service"
        
        echo -e "${GREEN}  ✓ $SERVICE_NAME 제거 완료${NC}"
    else
        echo -e "  $SERVICE_NAME: 서비스 파일이 없습니다 (이미 제거됨)"
    fi
done

# systemd 재로드
echo ""
echo "systemd 재로드 중..."
systemctl daemon-reload

echo ""
echo -e "${GREEN}모든 서비스 제거 완료!${NC}"
echo ""
echo "제거된 서비스:"
for service in "${SERVICES[@]}"; do
    SERVICE_NAME=$(basename "$service" .service)
    if [ ! -f "$SYSTEMD_DIR/$service" ]; then
        echo "  ✓ $SERVICE_NAME"
    fi
done

echo ""
echo "확인:"
echo "  sudo systemctl list-units | grep deeptree"
echo ""
echo "서비스 파일 확인:"
echo "  ls -la $SYSTEMD_DIR/deeptree*"
echo ""
echo "실행 중인 프로세스 확인:"
echo "  ps aux | grep -E '(carecall|rppg|display|launcher)' | grep -v grep"
echo ""
echo -e "${YELLOW}참고:${NC}"
echo "  서비스 제거 후에도 프로세스가 남아있을 수 있습니다."
echo "  위 명령어로 확인 후 필요시 수동으로 종료하세요."

