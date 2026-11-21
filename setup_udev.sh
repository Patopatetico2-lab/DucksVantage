#!/usr/bin/env bash
# ====================================================================
# Script de Configuração de Regras UDEV e Atalho KDE Plasma - Ducksvantage
# Instala o atalho .desktop do usuário com caminhos absolutos e ícone oficial
# e aplica as permissões de hardware no kernel (/etc/udev/rules.d/)
# ====================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_SRC="${SCRIPT_DIR}/packaging/99-ducksvantage.rules"
[ ! -f "$RULE_SRC" ] && RULE_SRC="${SCRIPT_DIR}/udev/99-ducksvantage.rules"
RULE_DEST="/etc/udev/rules.d/99-ducksvantage.rules"
DESKTOP_SRC="${SCRIPT_DIR}/packaging/ducksvantage.desktop"

# Determinar usuário e diretório de aplicativos (~/.local/share/applications/)
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    TARGET_USER="$SUDO_USER"
    USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
    TARGET_USER="$USER"
    USER_HOME="$HOME"
fi

USER_APP_DIR="${USER_HOME}/.local/share/applications"

# 1. Instalar o atalho do usuário (universal: /usr/bin/ducksvantage ou pasta clonada)
echo "[+] Instalando atalho Ducksvantage em ${USER_APP_DIR}/ducksvantage.desktop..."
mkdir -p "${USER_APP_DIR}"
if [ -x "/usr/bin/ducksvantage" ] && [ -f "$DESKTOP_SRC" ]; then
    cp "$DESKTOP_SRC" "${USER_APP_DIR}/ducksvantage.desktop"
else
    cat << EOF > "${USER_APP_DIR}/ducksvantage.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Ducksvantage
GenericName=Lenovo Hardware & Power Control
GenericName[pt_BR]=Controle de Hardware e Energia Lenovo
Comment=Universal Lenovo Vantage replacement for Linux (Legion, LOQ, IdeaPad Gaming, IdeaPad & Yoga)
Comment[pt_BR]=Substituto universal e leve do Lenovo Vantage para Linux (Legion, LOQ, IdeaPad Gaming, IdeaPad e Yoga)
Exec=/usr/bin/python3 ${SCRIPT_DIR}/main.py
Icon=${SCRIPT_DIR}/assets/app_icon.svg
Path=${SCRIPT_DIR}
Terminal=false
Categories=System;Settings;HardwareSettings;Utility;Qt;
Keywords=Lenovo;Legion;LOQ;IdeaPad;Vantage;Battery;Thermal;Performance;Max-Power;Ducksvantage;
StartupNotify=true
StartupWMClass=Ducksvantage
EOF
fi
chmod 0644 "${USER_APP_DIR}/ducksvantage.desktop"
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    chown -R "$TARGET_USER":"$TARGET_USER" "${USER_APP_DIR}/ducksvantage.desktop"
fi

# 2. Instalar regras UDEV se executado como root / sudo
if [ "$EUID" -eq 0 ]; then
    echo "[+] Instalando regras UDEV universais do Ducksvantage em $RULE_DEST..."
    mkdir -p /etc/udev/rules.d
    cp "$RULE_SRC" "$RULE_DEST"
    chmod 0644 "$RULE_DEST"

    echo "[+] Recarregando o subsistema UDEV..."
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger 2>/dev/null || true

    echo "[+] Aplicando permissões imediatas nos nós /sys/..."
    chmod 0666 /sys/firmware/acpi/platform_profile 2>/dev/null || true
    chmod 0666 /sys/class/platform-profile/*/profile 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/conservation_mode 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/rapid_charge 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/fn_lock 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/camera_power 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/usb_charging 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/touchpad 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/fan_mode 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/lcd_overdrive 2>/dev/null || true
    chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/gpu_mode 2>/dev/null || true
    chmod 0666 /sys/class/power_supply/BAT*/charge_types 2>/dev/null || true
    chmod 0666 /sys/class/leds/*kbd_backlight*/brightness 2>/dev/null || true
    chmod 0666 /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || true
    chmod 0666 /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || true
    chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null || true
    chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference 2>/dev/null || true
    chmod 0666 /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw 2>/dev/null || true
    chmod 0666 /sys/bus/pci/devices/*/power/control 2>/dev/null || true
    chmod 0666 /sys/class/firmware-attributes/*/attributes/*/current_value 2>/dev/null || true
    chmod 0666 /sys/class/hwmon/hwmon*/pwm* /sys/class/hwmon/hwmon*/fan*_target 2>/dev/null || true
    chmod 0666 /sys/class/net/*/device/power/control 2>/dev/null || true
    chmod 0644 /dev/input/by-path/*kbd* /dev/input/by-path/*VPC* 2>/dev/null || true
    for hdir in /sys/class/hidraw/hidraw*; do
        [ -f "$hdir/device/uevent" ] && grep -qi "048D" "$hdir/device/uevent" && chmod 0666 "/dev/$(basename "$hdir")" 2>/dev/null || true
    done
else
    echo "[i] Para instalar as regras de permissão UDEV em /etc/udev/rules.d/, execute: sudo $0"
fi

# 3. Atualizar cache do KDE Plasma e banco de dados de aplicativos
echo "[+] Atualizando cache do KDE Plasma (kbuildsycoca6) e desktop database..."
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    sudo -u "$TARGET_USER" update-desktop-database "${USER_APP_DIR}" 2>/dev/null || true
    sudo -u "$TARGET_USER" kbuildsycoca6 --noincremental 2>/dev/null || \
    sudo -u "$TARGET_USER" kbuildsycoca5 --noincremental 2>/dev/null || true
else
    update-desktop-database "${USER_APP_DIR}" 2>/dev/null || true
    kbuildsycoca6 --noincremental 2>/dev/null || \
    kbuildsycoca5 --noincremental 2>/dev/null || true
fi

echo "===================================================================="
echo " [OK] Atalho e ícone do Ducksvantage atualizados com sucesso no KDE!"
echo "  • Atalho: ${USER_APP_DIR}/ducksvantage.desktop"
echo "  • Ícone:  ${SCRIPT_DIR}/assets/app_icon.svg"
echo "===================================================================="
