#!/usr/bin/env bash
# =============================================================================
# Instalador Universal Multi-Distribuição do Ducksvantage (install.sh)
# Compatível com:
#   - Arch Linux / CachyOS / Manjaro / EndeavourOS (pacman)
#   - Debian / Ubuntu / Pop!_OS / Linux Mint / Zorin (apt)
#   - Fedora / Nobara / RHEL / CentOS (dnf)
#   - openSUSE Tumbleweed / Leap (zypper)
#
# O que este script faz:
#   1. Verifica e instala as dependências nativas (PyQt6, psutil, pynvml).
#   2. Copia os arquivos do Ducksvantage para /opt/ducksvantage.
#   3. Cria o executável global /usr/bin/ducksvantage.
#   4. Instala o ícone vetorial em /usr/share/icons/hicolor/scalable/apps/ducksvantage.svg
#      e o atalho de menu em /usr/share/applications/ducksvantage.desktop.
#   5. Instala automaticamente as regras UDEV em /etc/udev/rules.d/99-ducksvantage.rules
#      e recarrega o udevadm para que o app opere SEM SENHA ROOT em qualquer distro.
# =============================================================================

set -e

APP_NAME="ducksvantage"
INSTALL_DIR="/opt/ducksvantage"
BIN_PATH="/usr/bin/ducksvantage"
UDEV_RULE_SRC="packaging/99-ducksvantage.rules"
UDEV_RULE_DST="/etc/udev/rules.d/99-ducksvantage.rules"
DESKTOP_SRC="packaging/ducksvantage.desktop"
DESKTOP_DST="/usr/share/applications/ducksvantage.desktop"
ICON_SRC="assets/app_icon.svg"
ICON_DST="/usr/share/icons/hicolor/scalable/apps/ducksvantage.svg"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ "$EUID" -ne 0 ]; then
    echo "====================================================================="
    echo " [!] Elevando privilégios com sudo para instalar regras UDEV e ícone..."
    echo "====================================================================="
    exec sudo bash "$0" "$@"
fi

echo "====================================================================="
echo "   Ducksvantage - Instalador Universal Linux (Legion / LOQ / IdeaPad)"
echo "====================================================================="

# 1. Detectar Gerenciador de Pacotes da Distribuição e Instalar Dependências
install_dependencies() {
    echo "[1/5] Verificando dependências do sistema (Python3, PyQt6, psutil, pynvml)..."
    if command -v pacman >/dev/null 2>&1; then
        echo "  -> Distribuição baseada em Arch Linux / CachyOS detectada (pacman)."
        pacman -S --needed --noconfirm python python-pyqt6 python-psutil python-pynvml || true
    elif command -v apt-get >/dev/null 2>&1; then
        echo "  -> Distribuição baseada em Debian / Ubuntu / Pop!_OS detectada (apt)."
        apt-get update -qq
        apt-get install -y python3 python3-pyqt6 python3-psutil python3-pynvml || \
        apt-get install -y python3 python3-pyqt6 python3-psutil python3-pip
    elif command -v dnf >/dev/null 2>&1; then
        echo "  -> Distribuição baseada em Fedora / Nobara detectada (dnf)."
        dnf install -y python3 python3-pyqt6 python3-psutil python3-pynvml || \
        dnf install -y python3 python3-pyqt6 python3-psutil python3-pip
    elif command -v zypper >/dev/null 2>&1; then
        echo "  -> Distribuição baseada em openSUSE detectada (zypper)."
        zypper --non-interactive install python3 python3-qt6 python3-psutil || true
    else
        echo "  -> Gerenciador de pacotes não reconhecido. Verificando módulos via Python..."
    fi
}

if [ "${SKIP_DEPS:-0}" != "1" ]; then
    install_dependencies
fi

# 2. Instalar Arquivos da Aplicação em /opt/ducksvantage
echo "[2/5] Instalando arquivos do Ducksvantage em ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
cp -r main.py ui_main.py test_backend.py styles.qss core ui assets packaging "${INSTALL_DIR}/"
chmod -R a+rX "${INSTALL_DIR}"
chmod +x "${INSTALL_DIR}/main.py"

# 3. Criar Executável Global /usr/bin/ducksvantage
echo "[3/5] Criando lançador global em ${BIN_PATH}..."
cat << 'EOF' > "${BIN_PATH}"
#!/usr/bin/env bash
cd /opt/ducksvantage
exec python3 /opt/ducksvantage/main.py "$@"
EOF
chmod 0755 "${BIN_PATH}"

# 4. Instalar Ícone Vetorial e Atalho .desktop (KDE Plasma / GNOME / XFCE)
echo "[4/5] Instalando ícone vetorial e atalho no menu de aplicativos..."
mkdir -p "$(dirname "${ICON_DST}")"
cp "${ICON_SRC}" "${ICON_DST}"
chmod 0644 "${ICON_DST}"

mkdir -p "$(dirname "${DESKTOP_DST}")"
cp "${DESKTOP_SRC}" "${DESKTOP_DST}"
chmod 0644 "${DESKTOP_DST}"

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

# 5. Instalar e Ativar Regras UDEV para Acesso Direto ao Kernel sem Sudo
echo "[5/5] Configurando regras UDEV universais em ${UDEV_RULE_DST}..."
mkdir -p /etc/udev/rules.d
cp "${UDEV_RULE_SRC}" "${UDEV_RULE_DST}"
chmod 0644 "${UDEV_RULE_DST}"

# Aplicar permissões imediatas na sessão atual sem exigir reboot
chmod 0666 /sys/firmware/acpi/platform_profile 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/conservation_mode 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/fn_lock 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/camera_power 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/usb_charging 2>/dev/null || true
chmod 0666 /sys/bus/platform/drivers/ideapad_acpi/VPC*/fan_mode 2>/dev/null || true
chmod 0666 /sys/class/leds/*kbd_backlight*/brightness 2>/dev/null || true
chmod 0666 /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || true
chmod 0666 /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || true
chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null || true
chmod 0666 /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw 2>/dev/null || true
chmod 0666 /sys/class/power_supply/BAT*/charge_types 2>/dev/null || true

if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi

echo "====================================================================="
echo " [OK] Ducksvantage instalado com sucesso!"
echo "  • Comando no terminal:  ducksvantage"
echo "  • Menu de Aplicativos:  Ducksvantage (com ícone oficial)"
echo "  • Regras UDEV ativas:   ${UDEV_RULE_DST} (Zero senha root em execução)"
echo "====================================================================="

