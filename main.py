#!/usr/bin/env python3
"""
Ducksvantage
Substituto universal, leve e moderno do Lenovo Vantage para Linux (CachyOS / KDE Plasma).
Compatível com qualquer notebook Lenovo (linhas Legion, LOQ, IdeaPad Gaming, IdeaPad e Yoga,
processadores Intel e AMD, GPUs NVIDIA, AMD Radeon e Intel integradas).
"""

import sys
import os
import json
import argparse
import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.backend import HardwareBackend
from core.permissions import PermissionsManager
from core.qt_compat import is_qt_available


def _terminate_previous_instances() -> None:
    """Encerra instâncias GUI antigas do Ducksvantage evitando colisão com outros 'main.py' ou chamadas CLI."""
    my_pid = os.getpid()
    self_path = os.path.abspath(__file__)
    cli_flags = {
        "--status", "--json", "--diagnostic", "--list-presets",
        "--cycle-profile", "--cycle-hz", "--apply-preset",
        "--profile", "--conservation", "--install-udev", "--autostart",
        "--eco", "--reset-defaults",
    }
    terminated = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["pid"] == my_pid:
                continue
            cmd_list = proc.info.get("cmdline") or []
            cmdline = " ".join(cmd_list)
            pname = (proc.info.get("name") or "").lower()
            is_ducksvantage_proc = (
                self_path in cmd_list
                or "DucksVantage/main.py" in cmdline
                or "/bin/ducksvantage" in cmdline
                or "ducksvantage" in pname
            )
            if not is_ducksvantage_proc:
                continue
            if any(arg in cli_flags or any(arg.startswith(f + "=") for f in cli_flags) for arg in cmd_list):
                continue
            proc.terminate()
            terminated.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if terminated:
        _, alive = psutil.wait_procs(terminated, timeout=1.5)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


def run_cli_mode(args, backend: HardwareBackend):
    """Executa ações via linha de comando (sem interface gráfica)."""
    use_json = bool(getattr(args, "json", False))

    if args.status:
        if use_json:
            cpu = backend.get_cpu_metrics()
            gpu = backend.get_gpu_metrics()
            bat = backend.get_battery_info()
            ref = backend.get_display_refresh_info()
            payload = {
                "model": backend.system_info.display_model_name,
                "profile": backend.get_platform_profile(),
                "active_game": backend.get_active_game(),
                "eco_mode": backend.get_eco_travel_mode(),
                "cpu": {"temp_c": cpu.temperature_c, "freq_mhz": cpu.frequency_mhz, "governor": cpu.governor},
                "gpu": {"available": gpu.available, "temp_c": gpu.temperature_c, "power_w": gpu.power_draw_w, "state": gpu.runtime_state},
                "battery": {"available": bat.available, "percent": bat.capacity_percent, "status": bat.status, "ac": bat.ac_connected, "eta": bat.estimated_label},
                "display": {"available": ref.available, "hz": ref.current_hz, "vrr": ref.vrr_policy},
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        from test_backend import main as run_test
        run_test()
        return

    if getattr(args, "diagnostic", False):
        print(backend.generate_hardware_diagnostic_report())
        return

    if getattr(args, "list_presets", False):
        presets = backend.get_user_presets()
        if use_json:
            print(json.dumps(presets, ensure_ascii=False, indent=2))
        elif not presets:
            print("Nenhum preset personalizado salvo.")
        else:
            for p in presets:
                print(f"- {p.get('id')}: {p.get('name')} ({backend.format_user_preset_summary(p)})")
        return

    if getattr(args, "cycle_profile", False):
        ok, new_prof = backend.cycle_next_profile()
        if use_json:
            print(json.dumps({"ok": ok, "profile": new_prof}, ensure_ascii=False))
        else:
            print(f"[{'OK' if ok else 'ERRO'}] Perfil: {new_prof}")
        if not ok:
            sys.exit(1)
        return

    if getattr(args, "cycle_hz", False):
        ok, new_hz, msg = backend.cycle_refresh_rate()
        if use_json:
            print(json.dumps({"ok": ok, "hz": new_hz, "message": msg}, ensure_ascii=False))
        else:
            print(f"[{'OK' if ok else 'ERRO'}] {new_hz} Hz: {msg}")
        if not ok:
            sys.exit(1)
        return

    if getattr(args, "apply_preset", None):
        query = str(args.apply_preset).strip()
        presets = backend.get_user_presets()
        match = next(
            (p for p in presets if p.get("id") == query or str(p.get("name", "")).lower() == query.lower()),
            None,
        )
        if not match:
            msg = f"Preset '{query}' não encontrado."
            print(json.dumps({"ok": False, "message": msg}, ensure_ascii=False) if use_json else f"[ERRO] {msg}")
            sys.exit(1)
        ok, msg = backend.apply_user_preset(str(match["id"]), allow_elevation=False)
        if use_json:
            print(json.dumps({"ok": ok, "preset": match["name"], "message": msg}, ensure_ascii=False))
        else:
            print(f"[{'OK' if ok else 'ERRO'}] Preset '{match['name']}': {msg}")
        if not ok:
            sys.exit(1)
        return

    had_error = False
    if getattr(args, "reset_defaults", False):
        ok, msg = backend.reset_all_settings_to_default(allow_elevation=False)
        print(json.dumps({"ok": ok, "message": msg}, ensure_ascii=False) if use_json else f"[{'OK' if ok else 'ERRO'}] Reset: {msg}")
        if not ok:
            had_error = True

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
        print(json.dumps({"ok": ok, "profile": prof, "message": msg}, ensure_ascii=False) if use_json else f"[{'OK' if ok else 'ERRO'}] Perfil '{prof}': {msg}")
        if not ok:
            had_error = True

    if args.conservation:
        enable = args.conservation.lower() in ("1", "true", "on", "sim", "ativar")
        ok, msg = backend.set_conservation_mode(enable)
        print(json.dumps({"ok": ok, "conservation": enable, "message": msg}, ensure_ascii=False) if use_json else f"[{'OK' if ok else 'ERRO'}] Modo de Conservação ({'Ativado' if enable else 'Desativado'}): {msg}")
        if not ok:
            had_error = True

    if args.install_udev:
        ok, msg = PermissionsManager.install_udev_rules(backend.get_active_writable_paths())
        print(json.dumps({"ok": ok, "message": msg}, ensure_ascii=False) if use_json else f"[{'OK' if ok else 'ERRO'}] Instalação UDEV: {msg}")
        if not ok:
            had_error = True

    if args.autostart:
        enable = args.autostart.lower() in ("1", "true", "on", "sim", "ativar")
        ok, msg = backend.set_autostart_enabled(enable)
        print(json.dumps({"ok": ok, "autostart": enable, "message": msg}, ensure_ascii=False) if use_json else f"[{'OK' if ok else 'ERRO'}] Autostart XDG ({'Ativado' if enable else 'Desativado'}): {msg}")
        if not ok:
            had_error = True

    if getattr(args, "eco", None):
        arg_e = str(args.eco).lower()
        target_e = (not backend.get_eco_travel_mode()) if arg_e == "toggle" else (arg_e in ("1", "true", "on"))
        ok, msg = backend.set_eco_travel_mode(target_e)
        print(json.dumps({"ok": ok, "eco_mode": target_e, "message": msg}, ensure_ascii=False) if use_json else f"[{'OK' if ok else 'ERRO'}] Eco-Mode: {msg}")
        if not ok:
            had_error = True

    if had_error:
        sys.exit(1)


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
    parser.add_argument("--cycle-profile", action="store_true", help="Cicla para o próximo perfil térmico (Fn+Q)")
    parser.add_argument("--cycle-hz", action="store_true", help="Alterna a taxa de atualização do painel (Fn+R)")
    parser.add_argument("--apply-preset", type=str, help="Aplica um preset personalizado pelo nome ou ID")
    parser.add_argument("--list-presets", action="store_true", help="Lista todos os presets personalizados salvos")
    parser.add_argument("--diagnostic", action="store_true", help="Imprime o relatório técnico de diagnóstico de hardware")
    parser.add_argument("--eco", type=str, choices=["on", "off", "toggle"], help="Ativa/desativa/alterna o Modo Viagem")
    parser.add_argument("--reset-defaults", action="store_true", help="Restaura configurações e hardware ao padrão de fábrica")
    parser.add_argument("--json", action="store_true", help="Formata saída CLI compatível em JSON (status, presets, ações)")
    args = parser.parse_args()

    if (
        args.status or args.profile or args.conservation or args.install_udev or args.autostart
        or args.cycle_profile or args.cycle_hz or args.apply_preset or args.list_presets or args.diagnostic
        or args.eco or getattr(args, "reset_defaults", False)
    ):
        backend = HardwareBackend()
        try:
            run_cli_mode(args, backend)
        finally:
            backend.close()
        return

    if not is_qt_available():
        print("=" * 65)
        print(" [!] PyQt6 ou PySide6 não foi encontrado no sistema.")
        print("=" * 65)
        print(" Para rodar a interface gráfica no CachyOS / Arch Linux, instale:")
        print("   sudo pacman -S python-pyqt6")
        print("=" * 65)
        sys.exit(1)

    from core.qt_compat import QApplication, QIcon, QSystemTrayIcon
    from ui_main import MainWindow

    _terminate_previous_instances()

    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if os.path.exists(os.path.join(base_dir, "assets", "app_icon.svg")):
        os.chdir(base_dir)

    app = QApplication(sys.argv)
    app.setApplicationName("Ducksvantage")
    app.setDesktopFileName("ducksvantage")
    app.setWindowIcon(QIcon(os.path.join(base_dir, "assets", "app_icon.svg")))

    # Verifica suporte à bandeja do sistema (evita processo fantasma em GNOME puro ou Wayland sem tray)
    tray_available = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not tray_available)

    qss_file = os.path.join(base_dir, "styles.qss")
    if os.path.exists(qss_file):
        with open(qss_file, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    backend = HardwareBackend()
    app.aboutToQuit.connect(backend.close)
    window = MainWindow(backend)

    if args.minimized:
        if tray_available:
            pass  # Permanece em segundo plano minimizado na bandeja
        else:
            print("[Ducksvantage] Aviso: Nenhuma bandeja do sistema (System Tray) detectada neste ambiente desktop.")
            print("[Ducksvantage] Abrindo a janela principal para evitar processo fantasma.")
            window.show()
    else:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
