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

# 가상환경 경로 자동 감지 (우선순위 순서)
VENV_PATHS=(
    "$(dirname "$PROJECT_ROOT")/venv"  # 프로젝트 상위 폴더의 venv (예: /home/aisl/deepcare/venv)
    "$HOME/deepcare/venv"              # ~/deepcare/venv
    "/home/aisl/deepcare/venv"         # 명시적 경로 (aisl 사용자용)
    "$PROJECT_ROOT/venv"                # 프로젝트 내부의 venv
    "$HOME/deeptree/venv"               # ~/deeptree/venv
)

VENV_PATH=""
for path in "${VENV_PATHS[@]}"; do
    if [ -f "$path/bin/python" ]; then
        VENV_PATH="$path"
        break
    fi
done

# 가상환경을 찾지 못한 경우 사용자 입력 요청
if [ -z "$VENV_PATH" ]; then
    echo -e "${YELLOW}가상환경을 자동으로 찾을 수 없습니다.${NC}"
    echo "다음 경로들을 확인했습니다:"
    for path in "${VENV_PATHS[@]}"; do
        echo "  - $path"
    done
    echo ""
    read -p "가상환경 경로를 직접 입력하세요 (예: /home/aisl/deepcare/venv): " VENV_PATH
    
    if [ -z "$VENV_PATH" ]; then
        echo -e "${RED}오류: 가상환경 경로가 입력되지 않았습니다.${NC}"
        exit 1
    fi
    
    # 경로 정규화
    if [[ ! "$VENV_PATH" =~ ^/ ]]; then
        if [[ "$VENV_PATH" =~ ^~ ]]; then
            # ~로 시작하는 경우
            VENV_PATH="${VENV_PATH/#\~/$HOME}"
        elif [[ "$VENV_PATH" =~ ^home/ ]]; then
            # home/로 시작하는 경우 (예: home/aisl/deepcare/venv)
            VENV_PATH="/$VENV_PATH"
            echo -e "${YELLOW}경로를 절대 경로로 변환: $VENV_PATH${NC}"
        else
            # 상대 경로인 경우 홈 디렉토리 기준
            VENV_PATH="$HOME/$VENV_PATH"
            echo -e "${YELLOW}경로를 홈 디렉토리 기준으로 변환: $VENV_PATH${NC}"
        fi
    fi
    
    # 가상환경 경로를 절대 경로로 변환
    VENV_PATH_ABS="$(realpath "$VENV_PATH" 2>/dev/null)"
    if [ -z "$VENV_PATH_ABS" ]; then
        VENV_PATH_ABS="$VENV_PATH"
    fi
    
    if [ ! -f "$VENV_PATH_ABS/bin/python" ]; then
        echo -e "${RED}오류: '$VENV_PATH_ABS/bin/python' 파일을 찾을 수 없습니다.${NC}"
        echo -e "${YELLOW}입력한 경로: $VENV_PATH${NC}"
        echo -e "${YELLOW}변환된 경로: $VENV_PATH_ABS${NC}"
        exit 1
    fi
    
    VENV_PATH="$VENV_PATH_ABS"
else
    echo -e "${GREEN}가상환경을 찾았습니다: $VENV_PATH${NC}"
fi

# 가상환경 경로를 절대 경로로 변환 (최종 확인)
VENV_PATH_ABS="$(realpath "$VENV_PATH" 2>/dev/null || echo "$VENV_PATH")"

# 사용자 확인 (현재 로그인 사용자 또는 SUDO_USER를 기본값으로)
if [ -n "$SUDO_USER" ]; then
    DEFAULT_USER="$SUDO_USER"
elif [ -n "$USER" ] && [ "$USER" != "root" ]; then
    DEFAULT_USER="$USER"
else
    # logname으로 실제 로그인 사용자 확인 시도
    DEFAULT_USER=$(logname 2>/dev/null || echo "aisl")
fi

read -p "서비스를 실행할 사용자 이름 [$DEFAULT_USER]: " SERVICE_USER
SERVICE_USER=${SERVICE_USER:-$DEFAULT_USER}

# 사용자 존재 확인
if ! id "$SERVICE_USER" &>/dev/null; then
    echo -e "${RED}오류: 사용자 '$SERVICE_USER'가 존재하지 않습니다.${NC}"
    exit 1
fi

# 오디오 그룹 확인 및 추가 (carecall 모듈 사용)
echo -e "${YELLOW}오디오 그룹 확인 중...${NC}"
if ! groups "$SERVICE_USER" | grep -q "\baudio\b"; then
    echo -e "${YELLOW}사용자 $SERVICE_USER를 audio 그룹에 추가합니다...${NC}"
    usermod -a -G audio "$SERVICE_USER"
    echo -e "${YELLOW}참고: 변경사항 적용을 위해 사용자가 로그아웃 후 다시 로그인해야 할 수 있습니다.${NC}"
else
    echo -e "${GREEN}사용자 $SERVICE_USER는 이미 audio 그룹에 있습니다.${NC}"
fi

# dialout 그룹 확인 (UART 접근용)
if ! groups "$SERVICE_USER" | grep -q "\bdialout\b"; then
    echo -e "${YELLOW}사용자 $SERVICE_USER를 dialout 그룹에 추가합니다...${NC}"
    usermod -a -G dialout "$SERVICE_USER"
fi

# netcat-openbsd 확인 (Kafka 포트 체크용)
if ! command -v nc &> /dev/null; then
    echo -e "${YELLOW}netcat-openbsd가 없습니다. 설치합니다...${NC}"
    apt-get update && apt-get install -y netcat-openbsd
fi

# 개별 서비스 충돌 확인
echo ""
echo -e "${YELLOW}⚠️  충돌 확인 중...${NC}"
INDIVIDUAL_SERVICES=("deeptree-carecall" "deeptree-rppg" "deeptree-display-switcher")
CONFLICT_FOUND=0

for service in "${INDIVIDUAL_SERVICES[@]}"; do
    if systemctl is-enabled "$service.service" &>/dev/null; then
        echo -e "${YELLOW}경고: $service.service가 활성화되어 있습니다.${NC}"
        CONFLICT_FOUND=1
    fi
    if systemctl is-active "$service.service" &>/dev/null; then
        echo -e "${YELLOW}경고: $service.service가 실행 중입니다.${NC}"
        CONFLICT_FOUND=1
    fi
done

if [ "$CONFLICT_FOUND" -eq 1 ]; then
    echo ""
    echo -e "${RED}⚠️  충돌 경고!${NC}"
    echo "개별 서비스들(deeptree-carecall, deeptree-rppg, deeptree-display-switcher)이"
    echo "활성화되어 있으면 이 통합 Launcher 서비스와 충돌할 수 있습니다."
    echo ""
    echo "권장 사항:"
    echo "  1. 개별 서비스만 사용 (권장) - 이 스크립트를 취소하고 install_module_service.sh 사용"
    echo "  2. 통합 Launcher만 사용 - 개별 서비스를 비활성화한 후 이 스크립트 계속"
    echo ""
    read -p "계속하시겠습니까? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "설치가 취소되었습니다."
        exit 1
    fi
fi

# 사용자 홈 디렉터리
SERVICE_HOME_DIR=$(eval echo "~$SERVICE_USER")
if [ ! -d "$SERVICE_HOME_DIR" ]; then
    echo -e "${YELLOW}경고: 홈 디렉터리를 찾지 못했습니다: $SERVICE_HOME_DIR${NC}"
    SERVICE_HOME_DIR="/home/$SERVICE_USER"
fi

# 프로젝트 경로를 절대 경로로 변환
PROJECT_ROOT_ABS="$(realpath "$PROJECT_ROOT")"

# 사용자 UID 확인 (XDG_RUNTIME_DIR용)
SERVICE_USER_UID=$(id -u "$SERVICE_USER" 2>/dev/null || echo "1000")
XDG_RUNTIME_DIR="/run/user/$SERVICE_USER_UID"

echo ""
echo "설정 정보:"
echo "  프로젝트 경로: $PROJECT_ROOT_ABS"
echo "  가상환경 경로: $VENV_PATH_ABS"
echo "  사용자: $SERVICE_USER (UID: $SERVICE_USER_UID)"
echo "  XDG_RUNTIME_DIR: $XDG_RUNTIME_DIR"
echo "  서비스 파일: $SERVICE_FILE"
echo ""

# 서비스 파일 복사 및 경로 수정
echo "서비스 파일 생성 중..."
TEMP_SERVICE=$(mktemp)

PYTHON_BIN="$VENV_PATH_ABS/bin/python"
XAUTHORITY_PATH="$SERVICE_HOME_DIR/.Xauthority"

cat "$SERVICE_FILE" | \
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT_ABS|g" | \
sed "s|__VENV_ROOT__|$VENV_PATH_ABS|g" | \
sed "s|__PYTHON_BIN__|$PYTHON_BIN|g" | \
sed "s|__SERVICE_USER__|$SERVICE_USER|g" | \
sed "s|__XDG_RUNTIME_DIR__|$XDG_RUNTIME_DIR|g" | \
sed "s|__XAUTHORITY__|$XAUTHORITY_PATH|g" > "$TEMP_SERVICE"

# ExecStartPre에서 __SERVICE_USER__ 치환 (xhost 명령용 - 이미 치환되었지만 확실히 하기 위해)
sed -i "s|__SERVICE_USER__|$SERVICE_USER|g" "$TEMP_SERVICE"

# 생성된 서비스 파일 확인 (디버그용)
echo ""
echo -e "${GREEN}생성된 서비스 파일 내용 확인:${NC}"
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
    echo -e "${YELLOW}경고: WorkingDirectory가 존재하지 않습니다: $FINAL_WORKING_DIR${NC}"
fi
if [ ! -f "$FINAL_PYTHON" ]; then
    echo -e "${YELLOW}경고: Python 실행 파일이 존재하지 않습니다: $FINAL_PYTHON${NC}"
fi
if [ ! -f "$FINAL_WORKING_DIR/apps/launcher.py" ]; then
    echo -e "${YELLOW}경고: launcher.py가 존재하지 않습니다: $FINAL_WORKING_DIR/apps/launcher.py${NC}"
fi
echo ""

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

