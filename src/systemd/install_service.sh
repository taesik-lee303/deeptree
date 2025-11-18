#!/bin/bash
# DeepTree systemd 서비스 설치 스크립트

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}DeepTree systemd 서비스 설치 스크립트${NC}"
echo "=========================================="

# 현재 스크립트 위치 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_FILE="$SCRIPT_DIR/deeptree.service"
SYSTEMD_DIR="/etc/systemd/system"

# 사용자 확인
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}이 스크립트는 sudo 권한이 필요합니다.${NC}"
    echo "사용법: sudo bash install_service.sh"
    exit 1
fi

# 프로젝트 경로 확인
if [ ! -f "$PROJECT_ROOT/apps/launcher.py" ]; then
    echo -e "${RED}오류: launcher.py를 찾을 수 없습니다.${NC}"
    echo "프로젝트 경로: $PROJECT_ROOT"
    exit 1
fi

# 가상환경 확인
if [ ! -f "$PROJECT_ROOT/venv/bin/python" ]; then
    echo -e "${YELLOW}경고: 가상환경을 찾을 수 없습니다.${NC}"
    echo "경로: $PROJECT_ROOT/venv"
    read -p "계속하시겠습니까? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 사용자 확인 (기본값: pi)
DEFAULT_USER="pi"
read -p "서비스를 실행할 사용자 이름 [$DEFAULT_USER]: " SERVICE_USER
SERVICE_USER=${SERVICE_USER:-$DEFAULT_USER}

# 사용자 존재 확인
if ! id "$SERVICE_USER" &>/dev/null; then
    echo -e "${RED}오류: 사용자 '$SERVICE_USER'가 존재하지 않습니다.${NC}"
    exit 1
fi

# 프로젝트 경로를 절대 경로로 변환
PROJECT_ROOT_ABS="$(realpath "$PROJECT_ROOT")"

echo ""
echo "설정 정보:"
echo "  프로젝트 경로: $PROJECT_ROOT_ABS"
echo "  사용자: $SERVICE_USER"
echo "  서비스 파일: $SERVICE_FILE"
echo ""

# 서비스 파일 복사 및 경로 수정
echo "서비스 파일 생성 중..."
TEMP_SERVICE=$(mktemp)
sed "s|/home/pi/deeptree/src|$PROJECT_ROOT_ABS|g" "$SERVICE_FILE" | \
sed "s|User=pi|User=$SERVICE_USER|g" | \
sed "s|Group=pi|Group=$SERVICE_USER|g" > "$TEMP_SERVICE"

# systemd 디렉토리에 복사
cp "$TEMP_SERVICE" "$SYSTEMD_DIR/deeptree.service"
rm "$TEMP_SERVICE"

echo -e "${GREEN}서비스 파일이 생성되었습니다: $SYSTEMD_DIR/deeptree.service${NC}"

# systemd 재로드
echo "systemd 재로드 중..."
systemctl daemon-reload

# 서비스 활성화
echo "서비스 활성화 중..."
systemctl enable deeptree.service

echo ""
echo -e "${GREEN}설치 완료!${NC}"
echo ""
echo "다음 명령어로 서비스를 관리할 수 있습니다:"
echo "  시작:   sudo systemctl start deeptree"
echo "  중지:   sudo systemctl stop deeptree"
echo "  재시작: sudo systemctl restart deeptree"
echo "  상태:   sudo systemctl status deeptree"
echo "  로그:   sudo journalctl -u deeptree -f"
echo ""
echo -e "${YELLOW}서비스를 지금 시작하시겠습니까? (y/n)${NC}"
read -p "" -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl start deeptree
    sleep 2
    systemctl status deeptree --no-pager
fi

