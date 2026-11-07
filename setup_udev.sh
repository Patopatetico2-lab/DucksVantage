#!/usr/bin/env bash
# ====================================================================
# Script de Instalação de Regras UDEV Universais para o Ducksvantage
# Executar com permissões de administrador (sudo ./setup_udev.sh)
# ====================================================================

set -e

RULE_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/udev/99-ducksvantage.rules"
RULE_DEST="/etc/udev/rules.d/99-ducksvantage.rules"

if [ "$EUID" -ne 0 ]; then
    echo "[!] Este script precisa ser executado como root."
    echo "    Use: sudo $0"
    exit 1
fi

echo "[+] Instalando regras UDEV universais do Ducksvantage em $RULE_DEST..."
cp "$RULE_SRC" "$RULE_DEST"
chmod 644 "$RULE_DEST"

echo "[+] Recarregando o subsistema UDEV..."
udevadm control --reload-rules
udevadm trigger

echo "[+] Aplicando permissões imediatas nos nós /sys/..."
chmod 0666 /sys/firmware/acpi/platform_profile 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/conservation_mode 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/fn_lock 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/camera_power 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/usb_charging 2>/dev/null || true
chmod 0666 /sys/class/power_supply/BAT*/charge_types 2>/dev/null || true
chmod 0666 /sys/class/leds/*kbd_backlight*/brightness 2>/dev/null || true
chmod 0666 /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || true
chmod 0666 /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || true
chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null || true

echo "===================================================================="
echo " [OK] Regras UDEV do Ducksvantage instaladas e ativas com sucesso!"
echo "===================================================================="
