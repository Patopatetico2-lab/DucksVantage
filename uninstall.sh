#!/usr/bin/env bash
# =============================================================================
# Desinstalador Universal do Ducksvantage (uninstall.sh)
# Remove arquivos instalados no sistema e no usuário.
# Use --purge para remover também ~/.config/ducksvantage/settings.json.
# =============================================================================

set -e

PURGE=0
if [ "${1:-}" = "--purge" ]; then
    PURGE=1
fi

echo "====================================================================="
echo "   Ducksvantage - Desinstalador Universal Linux"
echo "====================================================================="

# Encerrar processos em execução
pkill -f "DucksVantage/main.py" 2>/dev/null || true
pkill -f "/opt/ducksvantage/main.py" 2>/dev/null || true

# Remover arquivos do usuário
USER_HOME="${HOME}"
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
fi

rm -f "${USER_HOME}/.local/bin/ducksvantage"
rm -rf "${USER_HOME}/.local/share/ducksvantage"
rm -f "${USER_HOME}/.local/share/applications/ducksvantage.desktop"
rm -f "${USER_HOME}/.config/autostart/ducksvantage.desktop"
rm -rf "${USER_HOME}/.local/share/plasma/plasmoids/org.ducksvantage.plasmoid"
rm -f "${USER_HOME}/.local/share/krunner/dbusplugins/plasma-runner-ducksvantage.desktop"
rm -f "${USER_HOME}/.local/share/dbus-1/services/org.ducksvantage.Control.service"
if [ "$PURGE" -eq 1 ]; then
    rm -rf "${USER_HOME}/.config/ducksvantage"
    echo "[+] Configurações do usuário removidas (--purge)."
else
    echo "[i] Preferências em ${USER_HOME}/.config/ducksvantage preservadas (use --purge para apagar)."
fi

# Remover arquivos globais se existir permissão de root
if [ "$EUID" -eq 0 ]; then
    rm -rf /opt/ducksvantage
    rm -f /usr/bin/ducksvantage
    rm -f /usr/share/applications/ducksvantage.desktop
    rm -f /usr/share/icons/hicolor/scalable/apps/ducksvantage.svg
    rm -f /etc/udev/rules.d/99-ducksvantage.rules
    rm -f /etc/udev/rules.d/99-lenovo-loq-control.rules
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules 2>/dev/null || true
    fi
    echo "[+] Instalação global e regras UDEV removidas."
elif [ -d /opt/ducksvantage ] || [ -f /etc/udev/rules.d/99-ducksvantage.rules ]; then
    echo "[!] Arquivos globais (/opt/ducksvantage ou UDEV) exigem: sudo $0"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${USER_HOME}/.local/share/applications" 2>/dev/null || true
fi

echo "[OK] Desinstalação concluída."
