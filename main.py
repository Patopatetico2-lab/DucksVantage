#!/usr/bin/env python3
"""
Ducksvantage
Substituto universal, leve e moderno do Lenovo Vantage para Linux (CachyOS / KDE Plasma).
Compatível com qualquer notebook Lenovo (linhas Legion, LOQ, IdeaPad Gaming, IdeaPad e Yoga,
processadores Intel e AMD, GPUs NVIDIA, AMD Radeon e Intel integradas).
"""

import sys
import os
import argparse
import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.backend import HardwareBackend
from core.permissions import PermissionsManager
from core.qt_compat import is_qt_available


def _terminate_previous_instances() -> None:
    """Encerra instâncias antigas minimizadas na bandeja para evitar conflito de timers do Fn+Q."""
    my_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["pid"] == my_pid:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if ("main.py" in cmdline or "ducksvantage" in cmdline) and "python" in (proc.info.get("name") or "").lower():
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def run_cli_mode(args, backend: HardwareBackend):
    """Executa ações via linha de comando (sem interface gráfica)."""
    if args.status:
        from test_backend import main as run_test
        run_test()
        return

    if args.profile:
        target = args.profile.lower().strip()
        mapping = {
            "quiet": "low-power",
            "low-power": "low-power",
            "silencioso": "low-power",
            "balanced": "balanced",
            "equilibrado": "balanced",
            "performance": "performance",
            "desempenho": "performance",
            "max-power": "max-power",
            "extremo": "max-power",
            "desempenho-maximo": "max-power",
        }
        prof = mapping.get(target, backend.normalize_profile(target))
        ok, msg = backend.set_platform_profile(prof)
        print(f"[{'OK' if ok else 'ERRO'}] Perfil '{prof}': {msg}")

    if args.conservation:
        enable = args.conservation.lower() in ("1", "true", "on", "sim", "ativar")
        ok, msg = backend.set_conservation_mode(enable)
        print(f"[{'OK' if ok else 'ERRO'}] Modo de Conservação ({'Ativado' if enable else 'Desativado'}): {msg}")

    if args.install_udev:
        ok, msg = PermissionsManager.install_udev_rules(backend.get_active_writable_paths())
        print(f"[{'OK' if ok else 'ERRO'}] Instalação UDEV: {msg}")

    if args.autostart:
        enable = args.autostart.lower() in ("1", "true", "on", "sim", "ativar")
        ok, msg = backend.set_autostart_enabled(enable)
        print(f"[{'OK' if ok else 'ERRO'}] Autostart XDG ({'Ativado' if enable else 'Desativado'}): {msg}")


def main():
    parser = argparse.ArgumentParser(
        description="Ducksvantage - Gerenciador Universal de Hardware Lenovo no Linux"
    )
    parser.add_argument("--status", action="store_true", help="Exibe o relatório universal de hardware no terminal")
    parser.add_argument(
        "--profile",
        type=str,
        choices=["quiet", "balanced", "performance", "low-power", "max-power"],
        help="Define o perfil térmico ACPI"
    )
    parser.add_argument(
        "--conservation",
        type=str,
        choices=["on", "off", "1", "0"],
        help="Ativa ou desativa o Modo de Conservação (~80%%)"
    )
    parser.add_argument(
        "--autostart",
        type=str,
        choices=["on", "off", "1", "0"],
        help="Ativa ou desativa a inicialização automática com o sistema (XDG Autostart)"
    )
    parser.add_argument(
        "--minimized", "--tray",
        dest="minimized",
        action="store_true",
        help="Inicia o aplicativo silenciosamente na bandeja do sistema (System Tray) sem abrir a janela principal"
    )
    parser.add_argument("--install-udev", action="store_true", help="Instala as regras UDEV para operar sem sudo")
    args = parser.parse_args()

    if args.status or args.profile or args.conservation or args.install_udev or args.autostart:
        backend = HardwareBackend()
        run_cli_mode(args, backend)
        return

    if not is_qt_available():
        print("=" * 65)
        print(" [!] PyQt6 ou PySide6 não foi encontrado no sistema.")
        print("=" * 65)
        print(" Para rodar a interface gráfica no CachyOS / Arch Linux, instale:")
        print("   sudo pacman -S python-pyqt6")
        print("=" * 65)
        sys.exit(1)

    from core.qt_compat import QApplication, QIcon
    from ui_main import MainWindow

    _terminate_previous_instances()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(base_dir, "assets", "app_icon.svg")):
        os.chdir(base_dir)

    app = QApplication(sys.argv)
    app.setApplicationName("Ducksvantage")
    app.setDesktopFileName("ducksvantage.desktop")
    app.setWindowIcon(QIcon("assets/app_icon.svg"))
    app.setQuitOnLastWindowClosed(False)

    qss_file = os.path.join(base_dir, "styles.qss")
    if os.path.exists(qss_file):
        with open(qss_file, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    backend = HardwareBackend()
    window = MainWindow(backend)
    if not args.minimized:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
