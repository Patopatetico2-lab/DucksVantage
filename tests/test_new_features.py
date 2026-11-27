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
from core.models import BatteryInfo, DisplayRefreshInfo, GpuMuxInfo, HardwareFeatures, HardwarePaths


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
        usb_wakeup=True,
        external_monitor_dock=True,
        thermal_throttling=True,
    )
    backend.paths = HardwarePaths()
    return backend


class TestNewFeatures(unittest.TestCase):

    def setUp(self):
        self._cfg_tmpdir = tempfile.TemporaryDirectory()
        cfg_dir = self._cfg_tmpdir.name
        cfg_file = os.path.join(cfg_dir, "settings.json")
        legacy_file = os.path.join(cfg_dir, "legacy_settings.json")
        self._cfg_patchers = [
            patch("core.settings.CONFIG_DIR", cfg_dir),
            patch("core.settings.CONFIG_FILE", cfg_file),
            patch("core.settings.LEGACY_CONFIG_FILE", legacy_file),
        ]
        for p in self._cfg_patchers:
            p.start()
        self.backend = _isolated_backend()

    def tearDown(self):
        try:
            self.backend.close()
        finally:
            for p in reversed(self._cfg_patchers):
                p.stop()
            self._cfg_tmpdir.cleanup()

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
        """Modo Básico mostra recursos cotidianos, oculta tuning técnico/arriscado e Avançado revela tudo."""
        from core.qt_compat import QApplication
        from ui_main import MainWindow

        _app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])
        self.backend.features.cpu_undervolt = True
        self.backend.features.wmi_gpu_ac_offset = True
        self.backend.features.screen_brightness = True
        self.backend.features.rgb_keyboard = True
        self.assertEqual(self.backend.get_ui_mode(), "basic")

        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_platform_profile_choices", return_value=["low-power", "balanced", "performance", "max-power"]), \
             patch.object(self.backend, "get_available_cpu_governors", return_value=["powersave", "performance"]), \
             patch.object(self.backend, "get_gpu_mux_info", return_value=GpuMuxInfo(
                 available=True, current_mode="hybrid", available_modes=["hybrid", "dedicated", "integrated"], backend_name="supergfxctl"
             )), \
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

            # Modo Básico ativo por padrão: mostra controles cotidianos/visuais e oculta técnicos/arriscados
            self.assertFalse(win.battery_tab.hist_card.isHidden())
            self.assertFalse(win.automation_tab.presets_card.isHidden())
            self.assertFalse(win.gpu_display_tab.vrr_box.isHidden())
            self.assertFalse(win.about_tab.brightness_prefs_box.isHidden())

            self.assertTrue(win.performance_tab.uv_card.isHidden())
            self.assertTrue(win.performance_tab.turbo_box.isHidden())
            self.assertTrue(win.performance_tab.gov_box.isHidden())
            self.assertTrue(win.performance_tab.fan_curve_widget.isHidden())
            self.assertTrue(win.performance_tab.sliders_box.isHidden())
            self.assertTrue(win.gpu_display_tab.gpu_stats_widget.isHidden())
            self.assertTrue(win.gpu_display_tab.mux_card.isHidden())
            self.assertTrue(win.gpu_display_tab.dock_adv_box.isHidden())
            self.assertTrue(win.automation_tab.add_rule_box.isHidden())
            self.assertTrue(win.automation_tab.session_hist_card.isHidden())
            self.assertTrue(win.automation_tab.btn_import_preset.isHidden())
            self.assertTrue(win.battery_tab.elec_adv_boxes[0].isHidden())
            self.assertTrue(win.lighting_tab.speed_widget.isHidden())
            self.assertTrue(win.lighting_tab.zones_custom_widget.isHidden())
            self.assertTrue(win.about_tab.backup_widget.isHidden())
            self.assertTrue(win.about_tab.btn_copy_diag.isHidden())
            self.assertTrue(win.about_tab.btn_copy_udev.isHidden())
            self.assertTrue(win.about_tab.dmi_adv_boxes[0].isHidden())

            # Sub-abas funcionam corretamente
            win.battery_tab.sub_tabs._on_button_clicked(1)
            self.assertEqual(win.battery_tab.sub_stack.currentIndex(), 1)
            win.automation_tab.sub_tabs._on_button_clicked(1)
            self.assertEqual(win.automation_tab.sub_stack.currentIndex(), 1)
            win.about_tab.sub_tabs._on_button_clicked(1)
            self.assertEqual(win.about_tab.sub_stack.currentIndex(), 1)

            # Botão contextual "Ativar Modo Avançado" revela todos os controles técnicos
            win.performance_tab.basic_hint_card.btn_switch.click()
            self.assertEqual(self.backend.get_ui_mode(), "advanced")
            self.assertFalse(win.performance_tab.uv_card.isHidden())
            self.assertFalse(win.performance_tab.turbo_box.isHidden())
            self.assertFalse(win.performance_tab.gov_box.isHidden())
            self.assertFalse(win.performance_tab.fan_curve_widget.isHidden())
            self.assertFalse(win.performance_tab.sliders_box.isHidden())
            self.assertFalse(win.gpu_display_tab.gpu_stats_widget.isHidden())
            self.assertFalse(win.gpu_display_tab.mux_card.isHidden())
            self.assertFalse(win.gpu_display_tab.dock_adv_box.isHidden())
            self.assertFalse(win.automation_tab.presets_card.isHidden())
            self.assertFalse(win.automation_tab.add_rule_box.isHidden())
            self.assertFalse(win.automation_tab.session_hist_card.isHidden())
            self.assertFalse(win.automation_tab.btn_import_preset.isHidden())
            self.assertFalse(win.battery_tab.hist_card.isHidden())
            self.assertFalse(win.battery_tab.elec_adv_boxes[0].isHidden())
            self.assertFalse(win.lighting_tab.speed_widget.isHidden())
            self.assertFalse(win.lighting_tab.zones_custom_widget.isHidden())
            self.assertFalse(win.about_tab.backup_widget.isHidden())
            self.assertFalse(win.about_tab.btn_copy_diag.isHidden())
            self.assertFalse(win.about_tab.btn_copy_udev.isHidden())
            self.assertFalse(win.about_tab.dmi_adv_boxes[0].isHidden())

            win._quit_app()
            win.close()

    # 18. Carga 100% Única + D-Bus/KRunner full_charge_once
    def test_one_time_full_charge_lifecycle_and_dbus(self):
        """Ativa Carga 100% Única e restaura Conservação 80% ao atingir 100% ou expirar timer."""
        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "set_conservation_mode", return_value=(True, "OK")) as m_cons, \
             patch.object(self.backend, "get_conservation_mode", side_effect=[False, False, False]):
            ok, _ = self.backend.start_one_time_full_charge("until_full")
            self.assertTrue(ok)
            self.assertTrue(self.backend.get_one_time_full_charge_status()["active"])
            m_cons.assert_called_with(False)

            # Em 85% ainda não restaura
            with patch.object(self.backend, "get_battery_info", return_value=BatteryInfo(available=True, capacity_percent=85, status="Charging")):
                self.assertIsNone(self.backend.check_one_time_full_charge_tick())

            # Em 100% restaura conservação 80%
            with patch.object(self.backend, "get_battery_info", return_value=BatteryInfo(available=True, capacity_percent=100, status="Full")):
                ev = self.backend.check_one_time_full_charge_tick()
                self.assertIsNotNone(ev)
                self.assertEqual(ev["type"], "one_time_full_charge_completed")
                self.assertFalse(self.backend.get_one_time_full_charge_status()["active"])
                m_cons.assert_called_with(True)

        # Expiração por tempo (2h) + roteador KRunner
        events = []
        router = DucksvantageCommandRouter(self.backend, ui_callback=lambda e, p: events.append((e, p)))
        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "set_conservation_mode", return_value=(True, "OK")), \
             patch.object(self.backend, "get_conservation_mode", return_value=False), \
             patch.object(self.backend, "get_battery_info", return_value=BatteryInfo(available=True, capacity_percent=72, status="Charging")):
            ok_cmd, _ = router.execute_command("full_charge_once")
            self.assertTrue(ok_cmd)
            self.assertEqual(events[-1][0], "full_charge_once")
            self.backend.settings._data["one_time_full_charge_until_ts"] = 1.0
            ev2 = self.backend.check_one_time_full_charge_tick()
            self.assertIsNotNone(ev2)

    # 19. Detector de Processos NVIDIA (Respeita D3cold + separa compositor vs offender)
    def test_nvidia_wakelock_detector_respects_d3cold_and_classifies(self):
        """Não executa nvidia-smi em D3cold; quando ativa, separa kwin_wayland de apps de usuário."""
        self.backend.features.nvidia_wakelock_detect = True
        self.backend.nvidia_available = True
        with tempfile.TemporaryDirectory() as td:
            rt_dir = os.path.join(td, "device", "power")
            os.makedirs(rt_dir)
            rt_file = os.path.join(rt_dir, "runtime_status")
            ctl_file = os.path.join(rt_dir, "control")
            with open(rt_file, "w") as f:
                f.write("suspended\n")
            with open(ctl_file, "w") as f:
                f.write("auto\n")
            self.backend.paths.nvidia_drm_card = td
            self.backend.paths.nvidia_pci_power_control = ctl_file

            with patch("core.mixins.smart_features.subprocess.run") as m_sub:
                res_sleep = self.backend.get_nvidia_wakelock_processes(force=True)
                self.assertFalse(res_sleep["gpu_awake"])
                self.assertEqual(res_sleep["runtime_state"], "D3cold")
                m_sub.assert_not_called()

            # GPU acordada com kwin_wayland (sistema) + firefox (usuário)
            with open(rt_file, "w") as f:
                f.write("active\n")
            self.backend._nvml_initialized = False
            smi_out = "111, kwin_wayland, 20\n222, firefox, 180\n"
            p_kwin = MagicMock(info={"pid": 111, "name": "kwin_wayland", "uids": MagicMock(real=os.getuid())})
            p_ff = MagicMock(info={"pid": 222, "name": "firefox", "uids": MagicMock(real=os.getuid())})

            def _fake_smi(cmd, **_kw):
                if "--query-compute-apps" in " ".join(cmd):
                    return MagicMock(returncode=0, stdout=smi_out)
                return MagicMock(returncode=0, stdout="")

            with patch("core.mixins.smart_features.shutil.which", return_value="/usr/bin/nvidia-smi"), \
                 patch("core.mixins.smart_features.subprocess.run", side_effect=_fake_smi), \
                 patch("core.mixins.smart_features.psutil.process_iter", return_value=[p_kwin, p_ff]):
                res_awake = self.backend.get_nvidia_wakelock_processes(force=True)
                self.assertTrue(res_awake["gpu_awake"])
                self.assertEqual([o["name"] for o in res_awake["offenders"]], ["firefox"])

                with patch("core.mixins.smart_features.psutil.Process") as m_proc:
                    ok_rel, _ = self.backend.release_nvidia_wakelocks(terminate_offenders=True)
                    self.assertTrue(ok_rel)
                    m_proc.assert_called_once_with(222)
                    m_proc.return_value.terminate.assert_called_once()

    # 20. Painel Dedicado Modo Custom Lenovo + Filtro de Duplicidade WMI
    def test_lenovo_custom_power_panel_and_dedup(self):
        """Lê e aplica cTGP/PPAB/PPT em perfil custom e exclui promovidos da lista genérica WMI."""
        with tempfile.TemporaryDirectory() as td:
            for name, cur, dval, mn, mx in [
                ("gpu_nv_ctgp", "55", "55", "0", "0"),
                ("gpu_nv_ppab", "10", "10", "0", "0"),
                ("ppt_pl1_spl", "45", "45", "15", "60"),
                ("flip_to_boot", "0", "0", "0", "1"),
            ]:
                adir = os.path.join(td, name)
                os.makedirs(adir)
                with open(os.path.join(adir, "current_value"), "w") as f:
                    f.write(cur)
                with open(os.path.join(adir, "default_value"), "w") as f:
                    f.write(dval)
                with open(os.path.join(adir, "min_value"), "w") as f:
                    f.write(mn)
                with open(os.path.join(adir, "max_value"), "w") as f:
                    f.write(mx)
                with open(os.path.join(adir, "type"), "w") as f:
                    f.write("integer")

            self.backend.paths.lenovo_wmi_attr_dir = td
            self.backend.features.wmi_custom_power = True

            ctrls = self.backend.get_lenovo_custom_power_controls()
            self.assertEqual([c["attr_id"] for c in ctrls], ["gpu_nv_ctgp", "gpu_nv_ppab", "ppt_pl1_spl"])
            ctgp_ctrl = ctrls[0]
            self.assertGreaterEqual(ctgp_ctrl["max"], 95)

            with patch.object(self.backend, "_ensure_custom_profile_for_wmi", return_value=True):
                ok_cool, _ = self.backend.apply_lenovo_custom_power_preset("cool_quiet", allow_elevation=False)
                self.assertTrue(ok_cool)
                self.assertEqual(self.backend._read_file_text(os.path.join(td, "gpu_nv_ctgp", "current_value")), "45")
                self.assertEqual(self.backend._read_file_text(os.path.join(td, "gpu_nv_ppab", "current_value")), "0")

            self.assertIn("gpu_nv_ctgp", self.backend.PROMOTED_BIOS_ATTR_IDS)
            self.assertNotIn("flip_to_boot", self.backend.PROMOTED_BIOS_ATTR_IDS)

    # 21. Brilho Automático de Tela (Eco-Mode)
    def test_screen_brightness_automation_eco(self):
        """Controla /sys/class/backlight/* e restaura brilho anterior ao sair do Modo Viagem."""
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "max_brightness"), "w") as f:
                f.write("1000\n")
            with open(os.path.join(td, "brightness"), "w") as f:
                f.write("800\n")
            with open(os.path.join(td, "actual_brightness"), "w") as f:
                f.write("800\n")

            self.backend.paths.backlight_dir = td
            self.backend.paths.backlight_brightness = os.path.join(td, "brightness")
            self.backend.paths.backlight_max_brightness = os.path.join(td, "max_brightness")
            self.backend.features.screen_brightness = True

            self.assertEqual(self.backend.get_screen_brightness_pct(), 80)

            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}), \
                 patch.object(self.backend.settings, "save", return_value=None), \
                 patch("core.mixins.cpu_thermal.PermissionsManager.write_multiple_sysfs_values", return_value=(True, "OK")), \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")), \
                 patch.object(self.backend, "_read_raw_platform_profile", return_value="low-power"):
                self.backend.set_brightness_automation_config(eco_dim_enabled=True, eco_brightness_pct=40)
                self.backend.set_eco_travel_mode(True)
                self.assertEqual(self.backend._read_file_text(self.backend.paths.backlight_brightness), "400")
                with open(os.path.join(td, "actual_brightness"), "w") as f:
                    f.write("400\n")

                self.backend.set_eco_travel_mode(False)
                self.assertEqual(self.backend._read_file_text(self.backend.paths.backlight_brightness), "800")
                with open(os.path.join(td, "actual_brightness"), "w") as f:
                    f.write("800\n")

                # Reentrada (True 2x) + desativar opção antes de desligar ainda restaura 80%
                self.backend.set_eco_travel_mode(True)
                self.assertEqual(self.backend._read_file_text(self.backend.paths.backlight_brightness), "400")
                with open(os.path.join(td, "actual_brightness"), "w") as f:
                    f.write("400\n")
                self.backend.set_eco_travel_mode(True)
                self.backend.set_brightness_automation_config(eco_dim_enabled=False, eco_brightness_pct=40)
                self.backend.set_eco_travel_mode(False)
                self.assertEqual(self.backend._read_file_text(self.backend.paths.backlight_brightness), "800")
                with open(os.path.join(td, "actual_brightness"), "w") as f:
                    f.write("800\n")

                # Sair do Modo Viagem via troca manual de perfil para performance restaura brilho original
                self.backend.features.platform_profile = True
                self.backend.paths.platform_profile = os.path.join(td, "platform_profile")
                with open(self.backend.paths.platform_profile, "w") as f:
                    f.write("balanced\n")
                self.backend.set_eco_travel_config(dim_brightness=True, brightness_pct=40, profile=True)
                self.backend.set_eco_travel_mode(True)
                self.assertEqual(self.backend._read_file_text(self.backend.paths.backlight_brightness), "400")
                self.backend.set_platform_profile("performance", allow_elevation=False)
                self.assertFalse(self.backend.get_eco_travel_mode())
                self.assertEqual(self.backend._read_file_text(self.backend.paths.backlight_brightness), "800")

                # Personalização do Modo Economia: desativar brilho/turbo evita alteração e atualiza resumo
                self.backend.set_eco_travel_config(dim_brightness=False, turbo_off=False, kbd_off=False)
                self.assertNotIn("Brilho", self.backend.get_eco_travel_summary())
                self.backend.set_eco_travel_mode(True)
                self.assertEqual(self.backend._read_file_text(self.backend.paths.backlight_brightness), "800")
                self.backend.set_eco_travel_mode(False)

        # KDE Plasma 6 org.kde.ScreenBrightness via qdbus6 (sem setBrightnessSilent)
        def _fake_kde6(cmd, **_kw):
            c_str = " ".join(str(x) for x in cmd)
            if "DisplaysDBusNames" in c_str:
                return MagicMock(returncode=0, stdout="display0\n")
            if "IsInternal" in c_str:
                return MagicMock(returncode=0, stdout="true\n")
            if "MaxBrightness" in c_str:
                return MagicMock(returncode=0, stdout="10000\n")
            if "Display.Brightness" in c_str:
                return MagicMock(returncode=0, stdout="7500\n")
            if "Display.SetBrightness" in c_str:
                return MagicMock(returncode=0, stdout="")
            return MagicMock(returncode=1, stdout="")

        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "wayland", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/fake"}), \
             patch.dict(sys.modules, {"dbus": None}), \
             patch("core.mixins.smart_features.shutil.which", side_effect=lambda c: "/usr/bin/qdbus6" if c == "qdbus6" else None), \
             patch("core.mixins.smart_features.subprocess.run", side_effect=_fake_kde6) as m_qdbus:
            self.assertEqual(self.backend.get_screen_brightness_pct(), 75)
            ok_set, _ = self.backend.set_screen_brightness_pct(80)
            self.assertTrue(ok_set)
            last_cmd = m_qdbus.call_args_list[-1][0][0]
            self.assertIn("org.kde.ScreenBrightness.Display.SetBrightness", last_cmd)
            self.assertEqual(last_cmd[-2:], ["8000", "0"])

    # 22. Saúde SSD NVMe SMART + Alerta Térmico
    def test_nvme_health_udisks_parser_and_thermal_alert(self):
        """Parses UDisks2 NVMe SMART attrs (TBW, health %, hours) e dispara alerta >= 68°C."""
        parsed = HardwareBackend._parse_udisks_nvme_smart_dict(
            {
                "percent_used": 17,
                "avail_spare": 100,
                "spare_thresh": 10,
                "total_data_written": 16986702336000,
                "total_data_read": 26144473088000,
                "power_cycles": 708,
                "unsafe_shutdowns": 79,
                "media_errors": 0,
                "temp_sensors": [342, 332],
            },
            power_on_hours=3191,
            smart_temp_k=332,
        )
        self.assertEqual(parsed["health_percent"], 83)
        self.assertEqual(parsed["wear_percent"], 17)
        self.assertAlmostEqual(parsed["tbw_tb"], 16.99, places=2)
        self.assertEqual(parsed["power_on_hours"], 3191)
        self.assertEqual(parsed["power_cycles"], 708)

        self.backend.features.nvme_health = True
        self.backend._last_nvme_temp_alert_ts = 0.0
        with patch.object(self.backend, "get_nvme_health_info", return_value=[{"device": "nvme0", "model": "SAMSUNG", "temp_c": 71.0}]):
            al = self.backend.check_nvme_thermal_alert()
            self.assertIsNotNone(al)
            self.assertEqual(al["urgency"], "critical")

    # 23. Auto-Ocultamento de Sub-Abas + Layout Zero Scroll Horizontal
    def test_automation_subtabs_and_layout_no_hscroll(self):
        """Oculta sub-aba vazia e mantém hbar_max == 0 em todas as 7 abas."""
        from core.qt_compat import QApplication
        from ui_main import MainWindow

        _app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])

        # Testa UI completa em Basic e Advanced + hbar_max == 0 nas 7 abas + auto-ocultamento em AutomationTab
        self.backend.features.wmi_custom_power = True
        self.backend.features.screen_brightness = True
        self.backend.features.nvme_health = True
        self.backend.features.nvidia_wakelock_detect = True

        fake_cp = [
            {"attr_id": "gpu_nv_ctgp", "label": "Potência Base da GPU (cTGP)", "unit": "W", "current": 55, "default": 55, "min": 35, "max": 95, "step": 1, "has_real_bounds": False, "path": "/dev/null"}
        ]
        fake_nvme = [
            {"device": "nvme0", "model": "SAMSUNG", "firmware": "EXB7", "temp_c": 45.0, "smart_available": True, "health_percent": 83, "wear_percent": 17, "avail_spare_percent": 100, "tbw_tb": 16.99, "tbr_tb": 26.14, "power_on_hours": 3191, "power_cycles": 708, "media_errors": 0, "critical_warning": "", "badge": "SAUDÁVEL", "color": "#00d2ff"}
        ]

        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_platform_profile_choices", return_value=["low-power", "balanced", "performance", "max-power"]), \
             patch.object(self.backend, "get_available_cpu_governors", return_value=["powersave", "performance"]), \
             patch.object(self.backend, "get_lenovo_custom_power_controls", return_value=fake_cp), \
             patch.object(self.backend, "get_nvme_health_info", return_value=fake_nvme), \
             patch.object(self.backend, "get_nvidia_wakelock_processes", return_value={"supported": True, "gpu_awake": True, "runtime_state": "active", "processes": [{"pid": 999, "name": "blender", "vram_mb": 400, "is_system": False}], "offenders": [{"pid": 999, "name": "blender", "vram_mb": 400, "is_system": False}]}), \
             patch.object(self.backend, "get_display_refresh_info", return_value=DisplayRefreshInfo(available=True, current_hz=144, available_rates=[60, 144], display_name="eDP-1", resolution="1920x1080", backend_name="kscreen-doctor", vrr_supported=True, vrr_policy="never")), \
             patch.object(self.backend, "get_battery_info", return_value=BatteryInfo(available=True, capacity_percent=75, ac_connected=False, energy_full_wh=56.0, energy_design_wh=60.0, health_percent=93.3)):
            win = MainWindow(self.backend)
            win.resize(1160, 770)
            win.show()
            _app.processEvents()

            # Modo Básico: Custom Power mostra botões rápidos e esconde sliders
            self.assertFalse(win.gpu_display_tab.custom_power_card.isHidden())
            self.assertTrue(win.gpu_display_tab.custom_power_adv_box.isHidden())

            # Verifica hbar_max == 0 nos dois modos em todas as 7 abas
            from core.qt_compat import QScrollArea
            for mode in ("basic", "advanced"):
                win.apply_ui_mode(mode)
                for tab_idx in range(win.stack.count()):
                    win._switch_tab(tab_idx)
                    _app.processEvents()
                    page = win.stack.widget(tab_idx)
                    for sc in page.findChildren(QScrollArea):
                        self.assertEqual(sc.horizontalScrollBar().maximum(), 0, f"Horizontal scroll on tab {tab_idx} in {mode}")

            # Auto-ocultamento de sub-aba vazia em AutomationTab quando sem jogos/sessões
            win.automation_tab.rules_card.setVisible(False)
            win.automation_tab.session_hist_card.setVisible(False)
            win.automation_tab._update_subtabs_visibility()
            self.assertTrue(win.automation_tab.sub_tabs.isHidden())
            self.assertEqual(win.automation_tab.sub_stack.currentIndex(), 1)

            win._quit_app()
            win.close()

    # 24. Regressão dos 8 Fixes: Undervolt Polkit Reset, KDE Session/D-Bus QML, Wi-Fi Game Auto-Switch e WMI Dedup
    def test_undervolt_polkit_reset_kde_session_wifi_game_and_bios_dedup(self):
        """Valida reset Polkit do Undervolt, detecção de sessão KDE, QML D-Bus, Wi-Fi Auto-Switch e PROMOTED_BIOS_ATTR_IDS."""
        # A. Reset de Undervolt usa Polkit quando hardware esteve ativo sem acesso direto MSR
        with patch.object(self.backend.settings, "save", return_value=None), \
             patch.object(self.backend, "get_cpu_vendor", return_value="Intel"), \
             patch("glob.glob", return_value=["/dev/cpu/0/msr"]), \
             patch("os.access", return_value=False), \
             patch("shutil.which", side_effect=lambda c: "/usr/bin/pkexec" if c == "pkexec" else None), \
             patch.dict(os.environ, {"DUCKSVANTAGE_ALLOW_TEST_PKEXEC": "1"}), \
             patch("core.backend.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as m_uv:
            ok_uv, _ = self.backend.apply_undervolt_offsets(-60, -50)
            self.assertTrue(ok_uv)
            self.assertTrue(self.backend._undervolt_active_in_hw)
            ok_rst, _ = self.backend.emergency_reset_undervolt("Teste Reset Polkit")
            self.assertTrue(ok_rst)
            self.assertFalse(self.backend._undervolt_active_in_hw)
            self.assertGreaterEqual(m_uv.call_count, 2)

        # B. Detecção KDE Plasma vs GNOME e main.qml via D-Bus
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE", "DESKTOP_SESSION": "plasma"}, clear=True):
            self.assertTrue(self.backend.is_kde_plasma_session())
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME", "DESKTOP_SESSION": "gnome"}, clear=True):
            self.assertFalse(self.backend.is_kde_plasma_session())

        qml_p = os.path.join(self.backend.get_plasmoid_source_dir(), "contents", "ui", "main.qml")
        with open(qml_p, "r", encoding="utf-8") as fh:
            qml_src = fh.read()
        self.assertIn("org.ducksvantage.Control.GetStatusJson", qml_src)
        self.assertIn("org.ducksvantage.Control.RunCommand", qml_src)

        # C. Game Auto-Switch ativa Baixa Latência no Wi-Fi (sem Polkit) e restaura Eco ao encerrar
        from core.models import NetworkPowerStatus
        with patch.object(self.backend.settings, "save", return_value=None):
            self.backend.set_game_auto_switch(True)
            self.backend.set_game_auto_wifi_low_latency(True)
            self.backend._active_game_name = None
            self.backend._game_changed_wifi = False

            with patch.object(self.backend, "detect_running_game", side_effect=["cs2", None]), \
                 patch.object(self.backend, "detect_running_app_rule", return_value=None), \
                 patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
                 patch.object(self.backend, "get_cpu_governor", return_value="powersave"), \
                 patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")), \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")), \
                 patch.object(self.backend, "get_network_power_status", return_value=NetworkPowerStatus(wifi_available=True, wifi_iface="wlan0", wifi_power_save_on=True)), \
                 patch.object(self.backend, "set_wifi_power_saving", return_value=(True, "OK")) as m_wifi:
                ev1 = self.backend.check_game_auto_switch()
                self.assertIn("Wi-Fi Baixa Latência", ev1["extras"])
                m_wifi.assert_called_with(False, allow_elevation=False)

                ev2 = self.backend.check_game_auto_switch()
                self.assertIn("Wi-Fi Eco", ev2["extras"])
                m_wifi.assert_called_with(True, allow_elevation=False)

        # D. PROMOTED_BIOS_ATTR_IDS inclui nós já promovidos e evita ativar bios_attributes sem extras
        for promoted_id in ("cpu_temp", "gpu_temp", "gpu_nv_ac_offset", "usb_charging", "usb_power_in_sleep", "gpu_mode"):
            self.assertIn(promoted_id, self.backend.PROMOTED_BIOS_ATTR_IDS)
        with patch("core.mixins.display_mux_bios.glob.glob", side_effect=lambda p: [
            "/sys/class/firmware-attributes/lenovo-wmi/attributes/cpu_temp/current_value",
            "/sys/class/firmware-attributes/lenovo-wmi/attributes/usb_charging/current_value",
        ] if "firmware-attributes" in p else []):
            self.backend._scan_bios_attributes()
            self.assertFalse(self.backend.features.bios_attributes)

    # 25. Controle Fácil de Ventoinhas WMI/EC & Alvos Térmicos (LOQ 15IAX9E) + hwmon fan*_target
    def test_cooling_controls_wmi_loq_basic_advanced_and_presets(self):
        """Mesmo sem pwm1 bruto, notebooks Lenovo WMI exibem Modo de Ventilação fácil e Alvos WMI no Avançado."""
        from core.qt_compat import QApplication
        from ui.tabs.performance_tab import PerformanceTab

        _app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])

        # A. Sistema mínimo sem hardware -> has_cooling_controls() é False
        blank = _isolated_backend()
        blank.features = HardwareFeatures()
        self.assertFalse(blank.has_cooling_controls())
        blank.close()

        # B. Perfil LOQ 15IAX9E real (fan_control=False, wmi_cpu_temp=True, wmi_gpu_temp=True, platform_profile=True)
        with tempfile.TemporaryDirectory() as td:
            pp_file = os.path.join(td, "profile")
            pp_choices = os.path.join(td, "choices")
            with open(pp_file, "w", encoding="utf-8") as fh:
                fh.write("balanced\n")
            with open(pp_choices, "w", encoding="utf-8") as fh:
                fh.write("low-power balanced performance max-power custom\n")

            wmi_dir = os.path.join(td, "wmi_attrs")
            for attr, (lo, hi, cur) in [("cpu_temp", (85, 100, 94)), ("gpu_temp", (75, 87, 87))]:
                ad = os.path.join(wmi_dir, attr)
                os.makedirs(ad, exist_ok=True)
                for fn, val in [("min_value", lo), ("max_value", hi), ("current_value", cur)]:
                    with open(os.path.join(ad, fn), "w", encoding="utf-8") as fh:
                        fh.write(f"{val}\n")

            self.backend.features.fan_control = False
            self.backend.features.wmi_cpu_temp = True
            self.backend.features.wmi_gpu_temp = True
            self.backend.features.platform_profile = True
            self.backend.features.max_power_profile = True
            self.backend.features.custom_tdp = False
            self.backend.features.cpu_undervolt = False
            self.backend.paths.platform_profile = pp_file
            self.backend.paths.platform_profile_choices = pp_choices
            self.backend.paths.lenovo_wmi_attr_dir = wmi_dir
            self.backend._platform_profile_paths = [pp_file]
            self.assertTrue(self.backend.has_cooling_controls())

            tab = PerformanceTab(self.backend)
            tab.set_advanced_mode(False)
            self.assertFalse(tab.tdp_card.isHidden())
            self.assertFalse(tab.fan_ctrl_box.isHidden())
            self.assertEqual(set(tab.cooling_mode_buttons.keys()), {"quiet", "auto", "cool", "max"})
            for btn in tab.cooling_mode_buttons.values():
                self.assertFalse(btn.isHidden())
            self.assertTrue(tab.wmi_temp_widget.isHidden())
            self.assertTrue(tab.fan_curve_widget.isHidden())

            tab.set_advanced_mode(True)
            self.assertFalse(tab.wmi_temp_widget.isHidden())
            self.assertFalse(tab.btn_apply_wmi_temps.isHidden())
            self.assertTrue(tab.fan_curve_widget.isHidden())
            tab.close()

            # apply_cooling_preset("cool") muda para custom e reduz cpu_temp/gpu_temp aos limites mínimos
            ok_cool, _ = self.backend.apply_cooling_preset("cool", allow_elevation=False)
            self.assertTrue(ok_cool)
            with open(pp_file, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "custom")
            with open(os.path.join(wmi_dir, "cpu_temp", "current_value"), "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "85")
            with open(os.path.join(wmi_dir, "gpu_temp", "current_value"), "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "75")
            self.assertEqual(self.backend.get_active_cooling_preset(), "cool")

            # apply_cooling_preset("max") ativa max-power
            ok_max, _ = self.backend.apply_cooling_preset("max", allow_elevation=False)
            self.assertTrue(ok_max)
            with open(pp_file, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "max-power")
            self.assertEqual(self.backend.get_active_cooling_preset(), "max")

    def test_hwmon_fan_target_discovery_and_curve_apply(self):
        """_scan_hwmon detecta fan*_target e apply_dynamic_fan_curve_tick grava RPM proporcional."""
        with tempfile.TemporaryDirectory() as td:
            hw = os.path.join(td, "hwmon9")
            os.makedirs(hw)
            with open(os.path.join(hw, "name"), "w", encoding="utf-8") as fh:
                fh.write("lenovo_wmi_other\n")
            for fn, val in [("fan1_target", "2000"), ("fan1_min", "1000"), ("fan1_max", "5000"), ("pwm1_enable", "2")]:
                with open(os.path.join(hw, fn), "w", encoding="utf-8") as fh:
                    fh.write(f"{val}\n")

            with patch("core.backend.glob.glob", side_effect=lambda p: [hw] if "hwmon" in p else []):
                self.backend._scan_hwmon()
            self.assertEqual(len(self.backend._hwmon_fan_targets), 1)

            self.backend.features.fan_control = True
            self.backend.paths.cpu_temp_input = "/dev/null"
            self.backend.settings.set("custom_fan_curve_enabled", True)
            self.backend.settings.set("custom_fan_curve_points", [[30, 0], [50, 50], [90, 100]])
            with patch.object(self.backend, "get_gpu_metrics", return_value=MagicMock(available=False)), \
                 patch.object(self.backend, "_read_file_int", return_value=50000):
                pwm_pct = self.backend.apply_dynamic_fan_curve_tick(force=True)
            self.assertEqual(pwm_pct, 50)
            with open(os.path.join(hw, "fan1_target"), "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "3000")
            with open(os.path.join(hw, "pwm1_enable"), "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "1")


if __name__ == "__main__":
    unittest.main()
