#!/bin/bash
# 기존 systemd 서비스 파일의 경로를 수정하는 스크립트

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}DeepTree systemd 서비스 경로 수정 스크립트${NC}"
echo "=========================================="

# 사용자 확인
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}이 스크립트는 sudo 권한이 필요합니다.${NC}"
    echo "사용법: sudo bash fix_service.sh"
    exit 1
fi

SERVICE_FILE="/etc/systemd/system/deeptree.service"

if [ ! -f "$SERVICE_FILE" ]; then
    echo -e "${RED}오류: 서비스 파일을 찾을 수 없습니다: $SERVICE_FILE${NC}"
    echo "먼저 install_service.sh를 실행하세요."
    exit 1
fi

# 현재 스크립트 위치 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT_ABS="$(realpath "$PROJECT_ROOT")"

# 가상환경 경로 자동 감지
VENV_PATHS=(
    "$(dirname "$PROJECT_ROOT")/venv"
    "$HOME/deepcare/venv"
    "$PROJECT_ROOT/venv"
    "$HOME/deeptree/venv"
)

VENV_PATH=""
for path in "${VENV_PATHS[@]}"; do
    if [ -f "$path/bin/python" ]; then
        VENV_PATH="$path"
        break
    fi
done

if [ -z "$VENV_PATH" ]; then
    echo -e "${YELLOW}가상환경을 자동으로 찾을 수 없습니다.${NC}"
    read -p "가상환경 경로를 직접 입력하세요 (예: /home/aisl/deepcare/venv): " VENV_PATH
    
    if [ -z "$VENV_PATH" ] || [ ! -f "$VENV_PATH/bin/python" ]; then
        echo -e "${RED}오류: 가상환경 경로가 올바르지 않습니다.${NC}"
        exit 1
    fi
fi

VENV_PATH_ABS="$(realpath "$VENV_PATH" 2>/dev/null || echo "$VENV_PATH")"

# 현재 사용자 확인 (SUDO_USER 우선, 없으면 USER, 없으면 logname)
if [ -n "$SUDO_USER" ]; then
    DEFAULT_USER="$SUDO_USER"
elif [ -n "$USER" ] && [ "$USER" != "root" ]; then
    DEFAULT_USER="$USER"
else
    DEFAULT_USER=$(logname 2>/dev/null || echo "aisl")
fi

read -p "서비스를 실행할 사용자 이름 [$DEFAULT_USER]: " SERVICE_USER
SERVICE_USER=${SERVICE_USER:-$DEFAULT_USER}

# 사용자 홈 디렉터리
SERVICE_HOME_DIR=$(eval echo "~$SERVICE_USER")
if [ ! -d "$SERVICE_HOME_DIR" ]; then
    echo -e "${YELLOW}경고: 홈 디렉터리를 찾지 못했습니다: $SERVICE_HOME_DIR${NC}"
    SERVICE_HOME_DIR="/home/$SERVICE_USER"
fi

# 사용자 UID 확인 (XDG_RUNTIME_DIR용)
SERVICE_USER_UID=$(id -u "$SERVICE_USER" 2>/dev/null || echo "1000")
XDG_RUNTIME_DIR="/run/user/$SERVICE_USER_UID"

echo ""
echo "수정할 설정:"
echo "  프로젝트 경로: $PROJECT_ROOT_ABS"
echo "  가상환경 경로: $VENV_PATH_ABS"
echo "  사용자: $SERVICE_USER"
echo ""

# 백업 생성
BACKUP_FILE="${SERVICE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$SERVICE_FILE" "$BACKUP_FILE"
echo -e "${GREEN}백업 생성: $BACKUP_FILE${NC}"

# 서비스 파일 수정
TEMP_SERVICE=$(mktemp)
cat "$SERVICE_FILE" | \
sed "s|WorkingDirectory=.*|WorkingDirectory=$PROJECT_ROOT_ABS|g" | \
sed "s|ExecStart=.*python|ExecStart=$VENV_PATH_ABS/bin/python|g" | \
sed "s|Environment=\"PATH=.*venv/bin|Environment=\"PATH=$VENV_PATH_ABS/bin|g" | \
sed "s|User=.*|User=$SERVICE_USER|g" | \
sed "s|Group=.*|Group=$SERVICE_USER|g" | \
sed "s|/home/pi/.Xauthority|$SERVICE_HOME_DIR/.Xauthority|g" | \
sed "s|/run/user/[0-9]*|$XDG_RUNTIME_DIR|g" > "$TEMP_SERVICE"

# 수정된 내용 확인
echo ""
echo -e "${GREEN}수정된 서비스 파일 내용:${NC}"
echo "----------------------------------------"
grep -E "(WorkingDirectory|ExecStart|Environment.*PATH|User|Group)" "$TEMP_SERVICE"
echo "----------------------------------------"
echo ""

# 경로 검증
FINAL_WORKING_DIR=$(grep "^WorkingDirectory=" "$TEMP_SERVICE" | cut -d'=' -f2)
FINAL_EXEC_START=$(grep "^ExecStart=" "$TEMP_SERVICE" | cut -d'=' -f2-)
FINAL_PYTHON=$(echo "$FINAL_EXEC_START" | awk '{print $1}')

echo "경로 검증:"
echo "  WorkingDirectory: $FINAL_WORKING_DIR"
echo "  Python 경로: $FINAL_PYTHON"
echo "  ExecStart: $FINAL_EXEC_START"
echo ""

# 경로 존재 확인
if [ ! -d "$FINAL_WORKING_DIR" ]; then
    echo -e "${RED}오류: WorkingDirectory가 존재하지 않습니다: $FINAL_WORKING_DIR${NC}"
    read -p "계속하시겠습니까? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        rm "$TEMP_SERVICE"
        exit 1
    fi
fi
if [ ! -f "$FINAL_PYTHON" ]; then
    echo -e "${RED}오류: Python 실행 파일이 존재하지 않습니다: $FINAL_PYTHON${NC}"
    read -p "계속하시겠습니까? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        rm "$TEMP_SERVICE"
        exit 1
    fi
fi
if [ ! -f "$FINAL_WORKING_DIR/apps/launcher.py" ]; then
    echo -e "${RED}오류: launcher.py가 존재하지 않습니다: $FINAL_WORKING_DIR/apps/launcher.py${NC}"
    read -p "계속하시겠습니까? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        rm "$TEMP_SERVICE"
        exit 1
    fi
fi
echo ""

read -p "이 설정으로 수정하시겠습니까? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "취소되었습니다."
    rm "$TEMP_SERVICE"
    exit 0
fi

# 서비스 파일 교체
cp "$TEMP_SERVICE" "$SERVICE_FILE"
rm "$TEMP_SERVICE"

echo -e "${GREEN}서비스 파일이 수정되었습니다.${NC}"

# systemd 재로드
echo "systemd 재로드 중..."
systemctl daemon-reload

echo ""
echo -e "${GREEN}완료!${NC}"
echo ""
echo "서비스 상태 확인:"
systemctl status deeptree --no-pager -l || true
echo ""
echo "서비스를 시작하려면: sudo systemctl start deeptree"

