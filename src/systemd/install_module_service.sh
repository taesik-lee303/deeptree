#!/bin/bash
# Install individual module services (carecall, rppg, display-switcher)

set -e

MODULE=${1:-}
if [ -z "$MODULE" ]; then
    echo "Usage: sudo bash install_module_service.sh <carecall|rppg|display-switcher>"
    exit 1
fi

VALID_MODULES=("carecall" "rppg" "display-switcher")
if [[ ! " ${VALID_MODULES[@]} " =~ " ${MODULE} " ]]; then
    echo "Invalid module: $MODULE"
    echo "Valid modules: ${VALID_MODULES[*]}"
    exit 1
fi

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run with sudo."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 모듈명을 파일명으로 변환 (하이픈 -> 언더스코어)
MODULE_FILE="${MODULE//-/_}"
SERVICE_TEMPLATE="$SCRIPT_DIR/${MODULE_FILE}.service"
SERVICE_NAME="deeptree-${MODULE}.service"
SYSTEMD_DIR="/etc/systemd/system"

if [ ! -f "$SERVICE_TEMPLATE" ]; then
    echo "Service template not found: $SERVICE_TEMPLATE"
    echo "Tried: $SERVICE_TEMPLATE"
    echo "Available service files:"
    ls -1 "$SCRIPT_DIR"/*.service 2>/dev/null | xargs -n1 basename || echo "  (none found)"
    exit 1
fi

# 통합 Launcher 서비스 충돌 확인
echo ""
echo "⚠️  Checking for conflicts with deeptree.service (launcher)..."
if systemctl is-enabled deeptree.service &>/dev/null; then
    echo "WARNING: deeptree.service (launcher) is enabled!"
    echo "This will cause conflicts with individual services."
    echo ""
    echo "Recommendation:"
    echo "  1. Disable deeptree.service: sudo systemctl disable deeptree.service"
    echo "  2. Stop deeptree.service: sudo systemctl stop deeptree.service"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi
fi

DEFAULT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-aisl}")
read -p "User to run service [$DEFAULT_USER]: " SERVICE_USER
SERVICE_USER=${SERVICE_USER:-$DEFAULT_USER}

if ! id "$SERVICE_USER" &>/dev/null; then
    echo "User not found: $SERVICE_USER"
    exit 1
fi

SERVICE_HOME_DIR=$(eval echo "~$SERVICE_USER")
SERVICE_HOME_DIR=${SERVICE_HOME_DIR:-/home/$SERVICE_USER}

VENV_DEFAULTS=(
    "$PROJECT_ROOT/venv"
    "$(dirname "$PROJECT_ROOT")/venv"
    "$SERVICE_HOME_DIR/venv"
    "$SERVICE_HOME_DIR/deepcare/venv"
)

for path in "${VENV_DEFAULTS[@]}"; do
    if [ -f "$path/bin/python" ]; then
        VENV_PATH="$path"
        break
    fi
done

if [ -z "$VENV_PATH" ]; then
    read -p "Virtualenv path (contains bin/python): " VENV_PATH
fi

if [ ! -f "$VENV_PATH/bin/python" ]; then
    echo "Python not found at $VENV_PATH/bin/python"
    exit 1
fi

# 오디오 그룹 확인 및 추가 (carecall 모듈의 경우)
if [ "$MODULE" = "carecall" ]; then
    if ! groups "$SERVICE_USER" | grep -q "\baudio\b"; then
        echo "Adding user $SERVICE_USER to audio group for microphone access..."
        usermod -a -G audio "$SERVICE_USER"
        echo "User added to audio group. Note: User may need to log out and back in for changes to take effect."
    else
        echo "User $SERVICE_USER is already in audio group."
    fi
    
    # dialout 그룹 확인 (UART 접근용)
    if ! groups "$SERVICE_USER" | grep -q "\bdialout\b"; then
        echo "Adding user $SERVICE_USER to dialout group for UART access..."
        usermod -a -G dialout "$SERVICE_USER"
    fi
fi

# netcat-openbsd 확인 (Kafka 포트 체크용)
if ! command -v nc &> /dev/null; then
    echo "Warning: 'nc' (netcat) not found. Installing netcat-openbsd..."
    apt-get update && apt-get install -y netcat-openbsd
fi

PROJECT_ROOT_ABS="$(realpath "$PROJECT_ROOT")"
VENV_PATH_ABS="$(realpath "$VENV_PATH")"
SERVICE_USER_UID=$(id -u "$SERVICE_USER")
XDG_RUNTIME_DIR="/run/user/$SERVICE_USER_UID"

echo "----------------------------------------"
echo "Module       : $MODULE"
echo "Service name : $SERVICE_NAME"
echo "User         : $SERVICE_USER"
echo "Project root : $PROJECT_ROOT_ABS"
echo "Virtualenv   : $VENV_PATH_ABS"
echo "XDG_RUNTIME  : $XDG_RUNTIME_DIR"
echo "----------------------------------------"

TEMP_SERVICE=$(mktemp)
PYTHON_BIN="$VENV_PATH_ABS/bin/python"
XAUTHORITY_PATH="$SERVICE_HOME_DIR/.Xauthority"
cat "$SERVICE_TEMPLATE" | \
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT_ABS|g" | \
sed "s|__VENV_ROOT__|$VENV_PATH_ABS|g" | \
sed "s|__PYTHON_BIN__|$PYTHON_BIN|g" | \
sed "s|__SERVICE_USER__|$SERVICE_USER|g" | \
sed "s|__XDG_RUNTIME_DIR__|$XDG_RUNTIME_DIR|g" | \
sed "s|__XAUTHORITY__|$XAUTHORITY_PATH|g" > "$TEMP_SERVICE"

# ExecStartPre에서 __SERVICE_USER__ 치환 (xhost 명령용)
sed -i "s|__SERVICE_USER__|$SERVICE_USER|g" "$TEMP_SERVICE"

sudo cp "$TEMP_SERVICE" "$SYSTEMD_DIR/$SERVICE_NAME"
rm "$TEMP_SERVICE"

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "Service installed: $SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager

