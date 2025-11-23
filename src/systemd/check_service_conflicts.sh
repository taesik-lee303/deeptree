#!/bin/bash
# Check for service conflicts between launcher and individual services

set -e

echo "=========================================="
echo "DeepTree Service Conflict Checker"
echo "=========================================="
echo ""

CONFLICT_FOUND=0

# Check if deeptree.service is enabled/active
LAUNCHER_ENABLED=$(systemctl is-enabled deeptree.service 2>/dev/null || echo "disabled")
LAUNCHER_ACTIVE=$(systemctl is-active deeptree.service 2>/dev/null || echo "inactive")

echo "1. Checking launcher service (deeptree.service)..."
echo "   Enabled: $LAUNCHER_ENABLED"
echo "   Active:  $LAUNCHER_ACTIVE"
echo ""

# Check individual services
INDIVIDUAL_SERVICES=("deeptree-carecall" "deeptree-rppg" "deeptree-display-switcher")
INDIVIDUAL_ENABLED=0
INDIVIDUAL_ACTIVE=0

echo "2. Checking individual services..."
for service in "${INDIVIDUAL_SERVICES[@]}"; do
    enabled=$(systemctl is-enabled "$service.service" 2>/dev/null || echo "disabled")
    active=$(systemctl is-active "$service.service" 2>/dev/null || echo "inactive")
    
    echo "   $service.service:"
    echo "      Enabled: $enabled"
    echo "      Active:  $active"
    
    if [ "$enabled" = "enabled" ]; then
        INDIVIDUAL_ENABLED=1
    fi
    if [ "$active" = "active" ]; then
        INDIVIDUAL_ACTIVE=1
    fi
done
echo ""

# Check for duplicate processes
echo "3. Checking for duplicate processes..."

check_process() {
    local pattern=$1
    local name=$2
    local count=$(ps aux | grep -E "$pattern" | grep -v grep | wc -l)
    
    if [ "$count" -gt 1 ]; then
        echo "   ⚠️  WARNING: $name has $count running instances!"
        echo "      Processes:"
        ps aux | grep -E "$pattern" | grep -v grep | sed 's/^/         /'
        CONFLICT_FOUND=1
        return 1
    elif [ "$count" -eq 1 ]; then
        echo "   ✅ $name: 1 instance (OK)"
        return 0
    else
        echo "   ⚠️  $name: 0 instances (not running)"
        return 0
    fi
}

check_process "modules\.carecall\.main" "carecall"
check_process "modules\.rppg\.thermal_rppg" "rppg"
check_process "apps\.display_switcher" "display-switcher"
echo ""

# Conflict detection
echo "4. Conflict Analysis..."
if [ "$LAUNCHER_ACTIVE" = "active" ] && [ "$INDIVIDUAL_ACTIVE" -eq 1 ]; then
    echo "   ❌ CONFLICT DETECTED: Both launcher and individual services are active!"
    CONFLICT_FOUND=1
elif [ "$LAUNCHER_ENABLED" = "enabled" ] && [ "$INDIVIDUAL_ENABLED" -eq 1 ]; then
    echo "   ⚠️  WARNING: Both launcher and individual services are enabled (may conflict on next boot)"
    CONFLICT_FOUND=1
elif [ "$LAUNCHER_ACTIVE" = "active" ]; then
    echo "   ✅ Using launcher mode (deeptree.service)"
elif [ "$INDIVIDUAL_ACTIVE" -eq 1 ]; then
    echo "   ✅ Using individual services mode"
else
    echo "   ⚠️  No services are running"
fi
echo ""

# Recommendations
if [ "$CONFLICT_FOUND" -eq 1 ]; then
    echo "=========================================="
    echo "⚠️  CONFLICT RESOLUTION REQUIRED"
    echo "=========================================="
    echo ""
    echo "Choose one of the following options:"
    echo ""
    echo "Option 1: Use individual services (RECOMMENDED)"
    echo "  sudo systemctl disable deeptree.service"
    echo "  sudo systemctl stop deeptree.service"
    echo "  sudo systemctl enable deeptree-carecall.service"
    echo "  sudo systemctl enable deeptree-rppg.service"
    echo "  sudo systemctl enable deeptree-display-switcher.service"
    echo ""
    echo "Option 2: Use launcher mode"
    echo "  sudo systemctl disable deeptree-carecall.service"
    echo "  sudo systemctl disable deeptree-rppg.service"
    echo "  sudo systemctl disable deeptree-display-switcher.service"
    echo "  sudo systemctl stop deeptree-carecall.service"
    echo "  sudo systemctl stop deeptree-rppg.service"
    echo "  sudo systemctl stop deeptree-display-switcher.service"
    echo "  sudo systemctl enable deeptree.service"
    echo ""
    exit 1
else
    echo "=========================================="
    echo "✅ No conflicts detected"
    echo "=========================================="
    exit 0
fi

