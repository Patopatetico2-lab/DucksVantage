#!/usr/bin/env python3
"""
Testes Automatizados dos 15 Novos Recursos e Correções de Auditoria do Ducksvantage (tests/test_new_features.py).
"""

import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.backend import HardwareBackend
from core.dbus_service import DucksvantageCommandRouter
from core.models import BatteryInfo, DisplayRefreshInfo, HardwareFeatures, HardwarePaths


def _isolated_backend() -> HardwareBackend:
    with patch.object(HardwareBackend, "scan_hardware", return_value=None), \
         patch.object(HardwareBackend, "record_battery_snapshot", return_value=[]), \
         patch.object(HardwareBackend, "_init_evdev_listeners", return_value=None):
        backend = HardwareBackend()
    backend.features = HardwareFeatures(
        platform_profile=True,
        available_profiles=["low-power", "balanced", "performance", "max-power"],
        max_power_profile=True,
        conservation_mode=True,
        kbd_backlight=True,
        kbd_max_brightness=2,
        camera_power=True,
        turbo_boost=True,
        cpu_governor=True,
        custom_tdp=True,
        fan_control=True,
        gpu_telemetry=True,
        refresh_rate=True,
        battery=True,
        wifi_power_save=True,
        eco_travel=True,
        cinema_mode=True,
        audio_control=True,
        usb_wakeup=True,
        external_monitor_dock=True,
        thermal_throttling=True,
    )
    backend.paths = HardwarePaths()
    return backend


class TestNewFeatures(unittest.TestCase):

    def setUp(self):
        self.backend = _isolated_backend()

    def tearDown(self):
        self.backend.close()

    # 1 & 6. Remoção de MangoHud & Filtro Steam Runtime + VRR
    def test_steam_runtime_helpers_ignored_and_mangohud_removed(self):
        """Helpers do Steam Linux Runtime (steam-runtime-launch-client) são ignorados e MangoHud foi removido."""
        self.assertFalse(hasattr(self.backend, "_apply_mangohud_for_game"))
        self.assertFalse(hasattr(self.backend, "get_game_mangohud_preset"))

        fake_proc = MagicMock()
        fake_proc.info = {
            "name": "steam-runtime-launch-client",
            "exe": "/home/user/.local/share/Steam/steamapps/common/SteamLinuxRuntime_sniper/steam-runtime-launch-client",
            "cmdline": ["/home/user/.local/share/Steam/steamapps/common/SteamLinuxRuntime_sniper/steam-runtime-launch-client"],
            "cwd": "/home/user/.local/share/Steam/steamapps/common/SteamLinuxRuntime_sniper",
        }
        with patch("core.mixins.gaming.psutil.process_iter", return_value=[fake_proc]):
            self.assertIsNone(self.backend.detect_running_game(force=True))

    # 2. Histórico Persistente de Sessões de Jogo
    def test_game_session_history_persists_on_stop(self):
        """Encerrar jogo salva duração, pico CPU/GPU e potência média em game_session_history."""
        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
             patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")), \
             patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")), \
             patch.object(self.backend, "detect_running_game", side_effect=["Cyberpunk2077.exe", None]), \
             patch.object(self.backend, "detect_running_app_rule", return_value=None):
            self.backend.settings._data["game_session_history"] = []
            ev_start = self.backend.check_game_auto_switch()
            self.assertEqual(ev_start["type"], "game_started")

            # Simula 120s de sessão com picos e amostras de energia
            self.backend._game_session_start_ts -= 120.0
            self.backend.update_game_session_peaks(84.5, 76.0, 95.0)
            self.backend.update_game_session_peaks(88.0, 79.5, 105.0)

            ev_stop = self.backend.check_game_auto_switch()
            self.assertEqual(ev_stop["type"], "game_stopped")
            self.assertGreaterEqual(ev_stop["session_summary"]["duration_sec"], 119)
            self.assertEqual(ev_stop["session_summary"]["avg_power_w"], 100.0)

            hist = self.backend.get_game_session_history()
            self.assertEqual(len(hist), 1)
            self.assertEqual(hist[0]["game"], "Cyberpunk2077.exe")
            self.assertEqual(hist[0]["peak_cpu_c"], 88.0)
            self.assertEqual(hist[0]["peak_gpu_c"], 79.5)

            self.backend.clear_game_session_history()
            self.assertEqual(self.backend.get_game_session_history(), [])

    # 3. Modo Mesa / Monitor Externo Automático
    def test_external_monitor_dock_mode_triggers_and_restores(self):
        """Conectar HDMI-A-1 aplica perfil + 144Hz e desconectar restaura estado anterior."""
        ref_cur = DisplayRefreshInfo(available=True, current_hz=60, available_rates=[60, 144], display_name="eDP-1", backend_name="kscreen-doctor")
        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_external_monitors", side_effect=[[], ["HDMI-A-1"], []]), \
             patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
             patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")) as m_prof, \
             patch.object(self.backend, "get_display_refresh_info", return_value=ref_cur), \
             patch.object(self.backend, "set_refresh_rate", return_value=(True, "OK")) as m_hz:
            self.backend.set_dock_mode_config(True, target_profile="performance", keep_max_hz=True, inhibit_lid_sleep=False)
            self.backend._dock_active = None

            self.assertIsNone(self.backend.check_external_monitor_dock_mode())
            ev_enter = self.backend.check_external_monitor_dock_mode()
            self.assertIsNotNone(ev_enter)
            self.assertEqual(ev_enter["type"], "dock_mode_entered")
            m_prof.assert_called_with("performance", allow_elevation=False)
            m_hz.assert_called_with(144)

            ev_exit = self.backend.check_external_monitor_dock_mode()
            self.assertIsNotNone(ev_exit)
            self.assertEqual(ev_exit["type"], "dock_mode_exited")
            m_prof.assert_called_with("balanced", allow_elevation=False)
            m_hz.assert_called_with(60)

    # 4. Bloqueio de Wake-on-USB
    def test_usb_wakeup_discovery_and_block(self):
        """Ignora usb1 root hub, lista receptores reais e alterna disabled/enabled."""
        with tempfile.TemporaryDirectory() as td:
            d_usb1 = os.path.join(td, "usb1", "power")
            d_rx = os.path.join(td, "1-13", "power")
            os.makedirs(d_usb1)
            os.makedirs(d_rx)
            with open(os.path.join(d_usb1, "wakeup"), "w") as f:
                f.write("disabled\n")
            with open(os.path.join(d_rx, "wakeup"), "w") as f:
                f.write("enabled\n")
            with open(os.path.join(td, "1-13", "product"), "w") as f:
                f.write("USB Receiver\n")

            with patch.object(self.backend.settings, "save", return_value=None), \
                 patch("core.mixins.smart_features.glob.glob", return_value=[os.path.join(d_usb1, "wakeup"), os.path.join(d_rx, "wakeup")]):
                devs = self.backend.get_usb_wakeup_devices()
                self.assertEqual(len(devs), 1)
                self.assertEqual(devs[0]["name"], "USB Receiver")
                self.assertTrue(devs[0]["enabled"])

                ok, _ = self.backend.set_usb_wakeup_blocked(True, allow_elevation=False)
                self.assertTrue(ok)
                with open(os.path.join(d_rx, "wakeup"), "r") as f:
                    self.assertEqual(f.read().strip(), "disabled")

    # 5. Detector de Thermal / Power Throttling em Tempo Real
    def test_throttling_detector_cpu_delta_and_nvidia_reasons(self):
        """1ª leitura de CPU não gera falso positivo; incremento no contador ou GPU Active sinaliza throttling."""
        counts = {"/sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_count": 5}
        with patch("core.mixins.smart_features.glob.glob", return_value=list(counts.keys())), \
             patch.object(self.backend, "_read_file_int", side_effect=lambda p, default=0: counts.get(p, 0)):
            st1 = self.backend.get_throttling_status()
            self.assertFalse(st1["throttling_now"])
            self.assertEqual(st1["severity"], "ok")

            counts["/sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_count"] = 7
            st2 = self.backend.get_throttling_status()
            self.assertTrue(st2["throttling_now"])
            self.assertTrue(st2["cpu_throttling"])
            self.assertEqual(st2["severity"], "thermal")

        # GPU NVIDIA 12 colunas (sw_power_cap active)
        self.backend.nvidia_available = True
        self.backend._nvml_initialized = False
        self.backend.paths.nvidia_drm_card = None
        self.backend._cached_nvidia_metrics = None
        self.backend._last_nvidia_smi_time = 0.0
        fake_nv = "NVIDIA RTX 4050, 74, 98, 3000, 6144, 75.0, 2400, P0, Not Active, Not Active, Not Active, Active\n"
        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
             patch("core.mixins.telemetry_battery.subprocess.run", return_value=MagicMock(returncode=0, stdout=fake_nv)), \
             patch("core.mixins.smart_features.glob.glob", return_value=[]):
            gpu = self.backend.get_gpu_metrics()
            self.assertIn("power_cap", gpu.throttle_reasons)
            st3 = self.backend.get_throttling_status()
            self.assertEqual(st3["severity"], "power")
            self.assertTrue(st3["gpu_power_capped"])

    # 6. VRR via kscreen-doctor
    def test_vrr_read_and_apply_kscreen(self):
        """Lê vrrPolicy do JSON do kscreen-doctor e executa output.<disp>.vrrpolicy.<mode>."""
        k_json = json.dumps({
            "outputs": [{
                "id": 2, "name": "eDP-1", "connected": True, "enabled": True, "vrrPolicy": 2,
                "currentModeId": "1",
                "modes": [
                    {"id": "1", "size": {"width": 1920, "height": 1080}, "refreshRate": 144000},
                    {"id": "2", "size": {"width": 1920, "height": 1080}, "refreshRate": 60000},
                ],
            }]
        })
        with patch("core.mixins.display_mux_bios.shutil.which", return_value="/usr/bin/kscreen-doctor"), \
             patch("core.mixins.display_mux_bios.subprocess.run") as m_run:
            m_run.side_effect = [
                MagicMock(returncode=0, stdout=k_json, stderr=""),
                MagicMock(returncode=0, stdout=k_json, stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]
            info = self.backend.get_display_refresh_info()
            self.assertTrue(info.vrr_supported)
            self.assertEqual(info.vrr_policy, "automatic")

            ok, _ = self.backend.set_vrr_policy("always")
            self.assertTrue(ok)
            self.assertIn("output.eDP-1.vrrpolicy.always", m_run.call_args_list[-1][0][0])

    # 7 & 8. Modo Cinema & Presets de Áudio
    def test_cinema_mode_and_audio_presets(self):
        """Modo Cinema gerencia backlight + DND; Presets de Áudio aplicam wpctl/câmera."""
        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_kbd_backlight", return_value=2), \
             patch.object(self.backend, "set_kbd_backlight", return_value=(True, "OK")) as m_kbd, \
             patch.object(self.backend, "_set_kde_notifications_inhibited") as m_dnd:
            ok, _ = self.backend.set_cinema_mode(True)
            self.assertTrue(ok)
            self.assertTrue(self.backend.get_cinema_mode())
            m_kbd.assert_called_with(0)
            m_dnd.assert_called_with(True)

            self.backend.set_cinema_mode(False)
            self.assertFalse(self.backend.get_cinema_mode())
            m_kbd.assert_called_with(2)
            m_dnd.assert_called_with(False)

        with patch.object(self.backend.settings, "save", return_value=None), \
             patch("core.mixins.smart_features.shutil.which", side_effect=lambda c: f"/usr/bin/{c}" if c in ("wpctl", "pactl") else None), \
             patch("core.mixins.smart_features.subprocess.run", return_value=MagicMock(returncode=0, stdout="42\n")), \
             patch.object(self.backend, "get_camera_power", return_value=True), \
             patch.object(self.backend, "set_camera_power", return_value=(True, "OK")) as m_cam:
            ok_v, _ = self.backend.set_audio_preset("voice_call")
            self.assertTrue(ok_v)
            self.assertEqual(self.backend.get_audio_preset(), "voice_call")

            ok_p, _ = self.backend.set_audio_preset("privacy_mute")
            self.assertTrue(ok_p)
            m_cam.assert_called_with(False)

            ok_n, _ = self.backend.set_audio_preset("normal")
            self.assertTrue(ok_n)
            m_cam.assert_called_with(True)

    # 9. Checkup Térmico Rápido (Baseline)
    def test_thermal_checkup_baseline_and_degradation(self):
        """Registra baseline e detecta degradação térmica acima de +7.5°C."""
        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_cpu_metrics", return_value=MagicMock(temperature_c=68.0, usage_percent=80.0, pl1_w=45)), \
             patch.object(self.backend, "get_fan_metrics", return_value=MagicMock(rpm=3200, second_rpm=3100)), \
             patch.object(self.backend, "_read_rapl_package_watts", return_value=45.0):
            self.backend.settings._data["thermal_checkup_history"] = []
            self.backend.start_thermal_checkup(duration_sec=5, spawn_load=False)
            self.backend._checkup_state["start_ts"] -= 6.0
            res1 = self.backend.poll_thermal_checkup()
            self.assertTrue(res1["completed"])
            self.assertEqual(res1["verdict"], "BASELINE REGISTRADA")

        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_cpu_metrics", return_value=MagicMock(temperature_c=79.5, usage_percent=80.0, pl1_w=45)), \
             patch.object(self.backend, "get_fan_metrics", return_value=MagicMock(rpm=3200, second_rpm=3100)), \
             patch.object(self.backend, "_read_rapl_package_watts", return_value=45.0):
            self.backend.start_thermal_checkup(duration_sec=5, spawn_load=False)
            self.backend._checkup_state["start_ts"] -= 6.0
            res2 = self.backend.poll_thermal_checkup()
            self.assertTrue(res2["completed"])
            self.assertEqual(res2["verdict"], "LIMPEZA / PASTA RECOMENDADA")
            self.assertGreater(res2["delta_temp_c"], 7.5)

    # 10 & 13. Regras Wi-Fi SSID & Perfil Noturno
    def test_wifi_ssid_rules_and_night_schedule(self):
        """Aplica regra automática por SSID conectado e alterna Perfil Noturno cruzando meia-noite."""
        self.assertTrue(HardwareBackend.is_time_in_night_window((23, 30), "23:00", "07:00"))
        self.assertTrue(HardwareBackend.is_time_in_night_window((6, 59), "23:00", "07:00"))
        self.assertFalse(HardwareBackend.is_time_in_night_window((14, 0), "23:00", "07:00"))

        with patch.object(self.backend.settings, "save", return_value=None), \
             patch("core.mixins.smart_features.shutil.which", return_value="/usr/bin/nmcli"), \
             patch("core.mixins.smart_features.subprocess.run", return_value=MagicMock(returncode=0, stdout="802-11-wireless:AndroidAP\n")), \
             patch.object(self.backend, "set_eco_travel_mode", return_value=(True, "OK")) as m_eco, \
             patch.object(self.backend, "set_refresh_rate", return_value=(True, "OK")) as m_hz, \
             patch.object(self.backend, "get_active_game", return_value=None):
            self.backend.add_wifi_power_rule("AndroidAP", eco_mode=True, refresh_hz=60)
            ev = self.backend.check_wifi_ssid_rules()
            self.assertIsNotNone(ev)
            self.assertEqual(ev["ssid"], "AndroidAP")
            m_eco.assert_called_with(True)
            m_hz.assert_called_with(60)

        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_active_game", return_value=None), \
             patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
             patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")) as m_prof, \
             patch.object(self.backend, "set_kbd_backlight", return_value=(True, "OK")), \
             patch.object(self.backend, "set_conservation_mode", return_value=(True, "OK")):
            self.backend.set_night_schedule_config(True, "23:00", "07:00", "low-power", True, True)
            ev_in = self.backend.check_night_schedule(datetime.datetime(2026, 11, 25, 23, 15))
            self.assertEqual(ev_in["type"], "night_mode_entered")
            m_prof.assert_called_with("low-power", allow_elevation=False)

            ev_out = self.backend.check_night_schedule(datetime.datetime(2026, 11, 26, 8, 0))
            self.assertEqual(ev_out["type"], "night_mode_exited")
            m_prof.assert_called_with("balanced", allow_elevation=False)

    # 11 & 12. Roteador D-Bus / KRunner & Plasmoid Plasma 6
    def test_dbus_krunner_router_and_plasmoid_packaging(self):
        """KRunner Match/Run executam comandos e Plasmoid Plasma 6 possui metadados e QML válidos."""
        events = []
        router = DucksvantageCommandRouter(self.backend, ui_callback=lambda e, p: events.append((e, p)))
        matches = router.krunner_match("dv")
        self.assertGreaterEqual(len(matches), 5)

        with patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")) as m_p:
            ok, _ = router.krunner_run("profile:max-power")
            self.assertTrue(ok)
            m_p.assert_called_with("max-power", allow_elevation=False)
            self.assertEqual(events[-1][0], "profile")

        meta_p = os.path.join(self.backend.get_plasmoid_source_dir(), "metadata.json")
        qml_p = os.path.join(self.backend.get_plasmoid_source_dir(), "contents", "ui", "main.qml")
        self.assertTrue(os.path.exists(meta_p))
        self.assertTrue(os.path.exists(qml_p))
        with open(meta_p, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertEqual(meta.get("X-Plasma-API-Minimum-Version"), "6.0")

        with tempfile.TemporaryDirectory() as td:
            with patch("core.mixins.smart_features.os.path.expanduser", side_effect=lambda p: p.replace("~", td)), \
                 patch("core.mixins.smart_features.shutil.which", return_value=None):
                ok_pl, _ = self.backend.install_kde_plasmoid()
                self.assertTrue(ok_pl)
                ok_kr, _ = self.backend.install_krunner_plugin()
                self.assertTrue(ok_kr)
                self.assertTrue(self.backend.is_kde_plasmoid_installed())
                self.assertTrue(self.backend.is_krunner_plugin_installed())

    # 14. Top 5 Processos
    def test_top_power_processes_sorted_with_watts(self):
        """Lista Top processos ordenados por CPU% e calcula estimativa em Watts."""
        p1 = MagicMock()
        p1.info = {"pid": 101, "name": "chrome", "memory_info": MagicMock(rss=400 * 1024 * 1024)}
        p1.cpu_percent.return_value = 80.0
        p2 = MagicMock()
        p2.info = {"pid": 102, "name": "blender", "memory_info": MagicMock(rss=900 * 1024 * 1024)}
        p2.cpu_percent.return_value = 240.0

        self.backend._proc_cpu_map = {101: p1, 102: p2}
        with patch("core.mixins.smart_features.psutil.cpu_count", return_value=8), \
             patch("core.mixins.smart_features.psutil.process_iter", return_value=[p1, p2]), \
             patch.object(self.backend, "get_battery_info", return_value=BatteryInfo(available=True, ac_connected=False, power_draw_w=20.0)):
            top = self.backend.get_top_power_processes(limit=5, force=True)
            self.assertEqual(len(top), 2)
            self.assertEqual(top[0]["name"], "blender")
            self.assertGreater(top[0]["est_watts"], top[1]["est_watts"])

    # 15. Exportação/Importação de Preset + Curva EC + App Rule com preset_id
    def test_preset_export_import_with_fan_curve_and_app_rule_preset(self):
        """Presets salvam/exportam/importam Curva EC + TDP e App Rules aceitam preset_id."""
        with tempfile.TemporaryDirectory() as td, \
             patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_platform_profile", return_value="max-power"), \
             patch.object(self.backend, "get_cpu_governor", return_value="performance"), \
             patch.object(self.backend, "get_cpu_turbo", return_value=True), \
             patch.object(self.backend, "get_cpu_tdp_limits", return_value=(55, 85)), \
             patch.object(self.backend, "get_custom_fan_curve", return_value={"enabled": True, "points": [[40, 20], [80, 95]], "cpu_temp_limit": 92, "gpu_temp_limit": 85}), \
             patch.object(self.backend, "get_display_refresh_info", return_value=DisplayRefreshInfo(available=True, current_hz=144, available_rates=[60, 144])):
            self.backend.settings._data["user_presets"] = []
            ok, _, preset = self.backend.save_current_as_preset("Modo Turbo EC")
            self.assertTrue(ok)
            self.assertTrue(preset["fan_curve_enabled"])
            self.assertIn("Curva EC", self.backend.format_user_preset_summary(preset))

            dst = os.path.join(td, "turbo.json")
            ok_exp, _ = self.backend.export_user_preset_to_file(preset["id"], dst)
            self.assertTrue(ok_exp)
            self.backend.delete_user_preset(preset["id"])

            ok_imp, _, imp_p = self.backend.import_user_preset_from_file(dst)
            self.assertTrue(ok_imp)
            self.assertEqual(imp_p["pl1_w"], 55)

            ok_r, _ = self.backend.add_app_power_rule("blender", "performance", "Blender EC", preset_id=imp_p["id"])
            self.assertTrue(ok_r)
            rules = self.backend.get_app_power_rules()
            bl = next(r for r in rules if r["executable"] == "blender")
            self.assertEqual(bl["preset_id"], imp_p["id"])

    # 16. Bugfix main._terminate_previous_instances
    def test_terminate_previous_instances_safety(self):
        """_terminate_previous_instances nunca mata outros scripts main.py nem chamadas CLI."""
        import main as app_main

        other_app = MagicMock()
        other_app.info = {"pid": 9001, "name": "python3", "cmdline": ["/usr/bin/python3", "/home/user/outro_projeto/main.py"]}
        cli_dv = MagicMock()
        cli_dv.info = {"pid": 9002, "name": "python3", "cmdline": ["/usr/bin/python3", "/home/notebook/Downloads/DucksVantage/main.py", "--status", "--json"]}
        old_gui_dv = MagicMock()
        old_gui_dv.info = {"pid": 9003, "name": "python3", "cmdline": ["/usr/bin/python3", os.path.abspath(app_main.__file__), "--minimized"]}

        with patch("main.psutil.process_iter", return_value=[other_app, cli_dv, old_gui_dv]):
            app_main._terminate_previous_instances()

        other_app.terminate.assert_not_called()
        cli_dv.terminate.assert_not_called()
        old_gui_dv.terminate.assert_called_once()

    # 17. Redesign UI: Modo Básico vs Avançado, Sub-abas e Painel EDGE enxuto
    def test_ui_redesign_basic_advanced_subtabs_and_clean_edge(self):
        """Modo Básico oculta tuning avançado, painéis duplicados foram removidos e sub-abas funcionam."""
        from core.qt_compat import QApplication
        from ui_main import MainWindow

        _app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])
        self.backend.features.cpu_undervolt = True
        self.backend.features.wmi_gpu_ac_offset = True
        self.assertEqual(self.backend.get_ui_mode(), "basic")

        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_platform_profile_choices", return_value=["low-power", "balanced", "performance", "max-power"]), \
             patch.object(self.backend, "get_available_cpu_governors", return_value=["powersave", "performance"]), \
             patch.object(self.backend, "get_display_refresh_info", return_value=DisplayRefreshInfo(
                 available=True, current_hz=144, available_rates=[60, 144], display_name="eDP-1",
                 resolution="1920x1080", backend_name="kscreen-doctor", vrr_supported=True, vrr_policy="never"
             )), \
             patch.object(self.backend, "get_battery_info", return_value=BatteryInfo(
                 available=True, capacity_percent=85, energy_full_wh=56.0, energy_design_wh=60.0, health_percent=93.3
             )):
            win = MainWindow(self.backend)

            # Painel EDGE enxuto & blocos duplicados removidos
            self.assertFalse(hasattr(win.dashboard_tab, "item_audio_preset"))
            self.assertFalse(hasattr(win.dashboard_tab, "item_cinema_mode"))
            self.assertFalse(hasattr(win.performance_tab, "prof_card"))
            self.assertFalse(hasattr(win.about_tab, "caps_card"))

            # Modo Básico ativo por padrão: tuning avançado oculto
            self.assertTrue(win.performance_tab.uv_card.isHidden())
            self.assertTrue(win.performance_tab.gov_box.isHidden())
            self.assertTrue(win.performance_tab.sliders_box.isHidden())
            self.assertTrue(win.performance_tab.checkup_card.isHidden())
            self.assertTrue(win.battery_tab.hist_card.isHidden())
            self.assertTrue(win.battery_tab.wifi_rules_box.isHidden())
            self.assertTrue(win.battery_tab.top_procs_card.isHidden())
            self.assertTrue(win.automation_tab.presets_card.isHidden())
            self.assertTrue(win.automation_tab.session_hist_card.isHidden())

            # Sub-abas funcionam corretamente
            win.battery_tab.sub_tabs._on_button_clicked(1)
            self.assertEqual(win.battery_tab.sub_stack.currentIndex(), 1)
            win.automation_tab.sub_tabs._on_button_clicked(2)
            self.assertEqual(win.automation_tab.sub_stack.currentIndex(), 2)
            win.about_tab.sub_tabs._on_button_clicked(1)
            self.assertEqual(win.about_tab.sub_stack.currentIndex(), 1)

            # Alternar para Modo Avançado revela tudo
            win.apply_ui_mode("advanced")
            self.assertEqual(self.backend.get_ui_mode(), "advanced")
            self.assertFalse(win.performance_tab.uv_card.isHidden())
            self.assertFalse(win.performance_tab.gov_box.isHidden())
            self.assertFalse(win.performance_tab.sliders_box.isHidden())
            self.assertFalse(win.performance_tab.checkup_card.isHidden())
            self.assertFalse(win.battery_tab.hist_card.isHidden())
            self.assertFalse(win.battery_tab.top_procs_card.isHidden())
            self.assertFalse(win.automation_tab.presets_card.isHidden())
            self.assertFalse(win.automation_tab.session_hist_card.isHidden())

            win._quit_app()
            win.close()


if __name__ == "__main__":
    unittest.main()
