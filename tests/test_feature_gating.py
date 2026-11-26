#!/usr/bin/env python3
"""
Testes Automatizados de Feature-Gating Dinâmico do Ducksvantage (test_feature_gating.py).
Valida que a interface gráfica (Dashboard, Desempenho, Bateria, Sobre e Bandeja) exibe
EXCLUSIVAMENTE os recursos realmente detectados e liberados pelo notebook/sistema,
ocultando automaticamente funções não suportadas (como LCD Overdrive, luz de teclado,
dGPU exclusiva sem MUX, taxas de atualização fixas, Ethernet ausente, etc.).
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.backend import HardwareBackend
from core.models import (
    HardwareFeatures,
    HardwarePaths,
    GpuMuxInfo,
    DisplayRefreshInfo,
    BiosAttribute,
    NetworkPowerStatus,
    BatteryInfo,
)


def _make_blank_backend(features: HardwareFeatures, paths: HardwarePaths = None) -> HardwareBackend:
    """Cria um HardwareBackend isolado com um perfil customizado de HardwareFeatures."""
    with patch.object(HardwareBackend, "scan_hardware", return_value=None), \
         patch.object(HardwareBackend, "record_battery_snapshot", return_value=[]), \
         patch.object(HardwareBackend, "_init_evdev_listeners", return_value=None):
        backend = HardwareBackend()
    backend.features = features
    backend.paths = paths or HardwarePaths()
    backend._cached_gpu_mux_info = None
    backend._cached_refresh_info = None
    backend._cached_bios_attrs = None
    backend._cached_net_power_status = None
    with patch.object(backend.settings, "save", return_value=None):
        backend.set_ui_mode("advanced")
    return backend


class TestFeatureGating(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from core.qt_compat import QApplication
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        cls.app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])

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

    def tearDown(self):
        for p in reversed(self._cfg_patchers):
            p.stop()
        self._cfg_tmpdir.cleanup()

    # =========================================================================
    # 1. LCD Overdrive (Exemplo explícito: oculto quando não suportado!)
    # =========================================================================
    def test_lcd_overdrive_unsupported_hidden_in_dashboard_and_performance(self):
        """Quando LCD Overdrive não é suportado, deve sumir tanto do Dashboard quanto da aba Desempenho."""
        feat = HardwareFeatures(
            platform_profile=True,
            available_profiles=["low-power", "balanced", "performance"],
            lcd_overdrive=False,
            bios_attributes=True,
        )
        backend = _make_blank_backend(feat)
        fake_attr = BiosAttribute(
            attr_id="flip_to_boot",
            display_name="Ligar ao Abrir a Tampa",
            category="Energia & Boot",
            attr_type="boolean",
            current_value="1",
            possible_values=["0", "1"],
            path="/fake/flip_to_boot/current_value",
        )

        with patch.object(backend, "get_bios_attributes", return_value=[fake_attr]), \
             patch.object(backend, "get_gpu_mux_info", return_value=GpuMuxInfo(available=False, available_modes=[], backend_name="none")), \
             patch.object(backend, "get_display_refresh_info", return_value=DisplayRefreshInfo(available=False, current_hz=60, available_rates=[60], backend_name="drm-fallback")):
            from ui.tabs.gpu_display_tab import GpuDisplayTab

            gdisp = GpuDisplayTab(backend)
            self.assertTrue(gdisp.od_box.isHidden())
            self.assertFalse(gdisp.bios_card.isHidden())
            self.assertNotIn("LCD Overdrive", gdisp.bios_title_lbl.text())
            self.assertEqual(gdisp.bios_count_badge.label.text(), "1 ITEM")

            gdisp.close()
        backend.close()

    def test_bios_card_completely_hidden_when_no_overdrive_and_no_bios_attrs(self):
        """Se o notebook não libera nem LCD Overdrive nem atributos WMI da BIOS, o card inteiro some."""
        feat = HardwareFeatures(lcd_overdrive=False, bios_attributes=False)
        backend = _make_blank_backend(feat)

        with patch.object(backend, "get_bios_attributes", return_value=[]), \
             patch.object(backend, "get_gpu_mux_info", return_value=GpuMuxInfo(available=False, available_modes=[], backend_name="none")), \
             patch.object(backend, "get_display_refresh_info", return_value=DisplayRefreshInfo(available=False, current_hz=60, available_rates=[60], backend_name="drm-fallback")):
            from ui.tabs.gpu_display_tab import GpuDisplayTab
            gdisp = GpuDisplayTab(backend)
            self.assertTrue(gdisp.od_box.isHidden())
            self.assertTrue(gdisp.bios_card.isHidden())
            self.assertFalse(gdisp.has_any_supported_feature())
            gdisp.close()
        backend.close()

    def test_set_lcd_overdrive_fails_honestly_without_hardware_node(self):
        """set_lcd_overdrive não deve fingir sucesso quando não existe nó de hardware."""
        backend = _make_blank_backend(HardwareFeatures(lcd_overdrive=False))
        ok, msg = backend.set_lcd_overdrive(True)
        self.assertFalse(ok)
        self.assertIn("não suportado", msg.lower())
        backend.close()

    @patch("os.path.exists", return_value=True)
    @patch("core.permissions.PermissionsManager.write_sysfs_value", return_value=(True, "OK"))
    def test_set_lcd_overdrive_value_encoding_fix(self, mock_write, _mock_exists):
        """Quando possible_values não usa 'Enabled', ativar LCD Overdrive escreve '1' (e não 'Enabled')."""
        paths = HardwarePaths(lcd_overdrive="/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/lcd_overdrive")
        backend = _make_blank_backend(HardwareFeatures(lcd_overdrive=True), paths)

        with patch.object(backend, "_read_file_text", return_value=""):
            ok, _ = backend.set_lcd_overdrive(True)
            self.assertTrue(ok)
            mock_write.assert_called_with(paths.lcd_overdrive, "1", allow_elevation=True)

        with patch.object(backend, "_read_file_text", return_value="Disabled;Enabled"):
            ok2, _ = backend.set_lcd_overdrive(True)
            self.assertTrue(ok2)
            mock_write.assert_called_with(paths.lcd_overdrive, "Enabled", allow_elevation=True)
        backend.close()

    # =========================================================================
    # 2. Notebook Mínimo (Nenhum recurso opcional liberado -> tudo oculto)
    # =========================================================================
    def test_minimal_system_hides_all_unsupported_sections_across_app(self):
        """Em um sistema sem recursos proprietários, todos os cards/switches não suportados ficam ocultos."""
        feat = HardwareFeatures()  # Tudo False por padrão
        backend = _make_blank_backend(feat)

        with patch.object(backend, "get_bios_attributes", return_value=[]), \
             patch.object(backend, "get_gpu_mux_info", return_value=GpuMuxInfo(available=False, available_modes=[], backend_name="none")), \
             patch.object(backend, "get_display_refresh_info", return_value=DisplayRefreshInfo(available=False, current_hz=60, available_rates=[60], backend_name="drm-fallback")), \
             patch.object(backend, "get_network_power_status", return_value=NetworkPowerStatus(wifi_available=False)), \
             patch.object(backend, "get_battery_info", return_value=BatteryInfo(available=False)):
            from ui_main import MainWindow

            win = MainWindow(backend)
            dash = win.dashboard_tab
            perf = win.performance_tab
            gdisp = win.gpu_display_tab
            auto = win.automation_tab
            bat = win.battery_tab
            tray = win.tray_manager

            # Header bar
            self.assertTrue(win.header_profile_pill.isHidden())
            self.assertTrue(win.header_bat_pill.isHidden())
            self.assertTrue(win.header_eco_pill.isHidden())

            # Dashboard (Painel EDGE enxuto)
            self.assertTrue(dash.thermal_card.isHidden())
            self.assertTrue(dash.edge_card.isHidden())
            self.assertTrue(dash.item_eco_travel.isHidden())
            self.assertTrue(dash.item_game_auto.isHidden())
            self.assertTrue(dash.item_conservation.isHidden())
            self.assertTrue(dash.item_rapid_charge.isHidden())
            self.assertTrue(dash.item_camera.isHidden())
            self.assertTrue(dash.item_touchpad.isHidden())
            self.assertTrue(dash.item_kbd_backlight.isHidden())
            self.assertTrue(win.about_tab.fn_lock_row_widget.isHidden())
            self.assertTrue(win.about_tab.usb_row_widget.isHidden())

            # Performance Tab (CPU & Térmico)
            self.assertTrue(perf.cpu_card.isHidden())
            self.assertTrue(perf.tdp_card.isHidden())
            self.assertTrue(perf.uv_card.isHidden())

            # GPU & Tela Tab
            self.assertTrue(gdisp.gpu_card.isHidden())
            self.assertTrue(gdisp.mux_card.isHidden())
            self.assertTrue(gdisp.ref_card.isHidden())
            self.assertTrue(gdisp.bios_card.isHidden())
            self.assertTrue(win.gpu_display_nav_btn.isHidden())

            # Automação & Atalhos Tab
            self.assertTrue(auto.presets_card.isHidden())
            self.assertTrue(auto.rules_card.isHidden())

            # Battery Tab
            self.assertTrue(bat.cons_card.isHidden())
            self.assertTrue(bat.health_card.isHidden())
            self.assertTrue(bat.hist_card.isHidden())
            self.assertTrue(bat.net_card.isHidden())
            self.assertTrue(bat.alert_card.isHidden())

            # System Tray & Abas condicionais
            self.assertFalse(tray.profile_menu.menuAction().isVisible())
            self.assertFalse(tray.presets_menu.menuAction().isVisible())
            self.assertFalse(tray.refresh_menu.menuAction().isVisible())
            self.assertFalse(tray.action_game_auto.isVisible())
            self.assertFalse(tray.action_touchpad.isVisible())
            self.assertFalse(tray.action_eco_travel.isVisible())
            self.assertFalse(tray.action_conservation.isVisible())
            self.assertTrue(win.lighting_nav_btn.isHidden())
            self.assertTrue(win.about_tab.ac_bat_prefs_widget.isHidden())

            win._quit_app()
            win.close()
        backend.close()

    # =========================================================================
    # 3. Perfil Parcial (Ex: Lenovo LOQ com lenovo-wmi 2 modos, sem kbd_backlight, sem USB)
    # =========================================================================
    def test_partial_loq_profile_shows_only_supported_controls(self):
        """Exibe somente os controles realmente presentes e oculta modos/itens indisponíveis."""
        feat = HardwareFeatures(
            platform_profile=True,
            available_profiles=["low-power", "balanced", "performance"],
            max_power_profile=False,
            conservation_mode=True,
            rapid_charge=False,
            fn_lock=True,
            camera_power=True,
            usb_charging=False,
            kbd_backlight=False,
            turbo_boost=True,
            cpu_governor=True,
            custom_tdp=False,
            fan_control=True,
            wmi_cpu_temp=True,
            wmi_gpu_temp=False,
            cpu_undervolt=False,
            wmi_gpu_ac_offset=True,
            touchpad_control=True,
            gpu_telemetry=True,
            gpu_mux=True,
            refresh_rate=False,
            lcd_overdrive=False,
            bios_attributes=True,
            battery=True,
            wifi_power_save=True,
            eco_travel=True,
        )
        backend = _make_blank_backend(feat)

        mux_lenovo = GpuMuxInfo(
            available=True,
            current_mode="hybrid",
            available_modes=["hybrid", "integrated"],
            backend_name="lenovo-wmi",
        )
        ref_single = DisplayRefreshInfo(
            available=True,
            current_hz=60,
            available_rates=[60],
            display_name="eDP-1",
            resolution="1920x1080",
            backend_name="kscreen-doctor",
        )
        net_wifi_only = NetworkPowerStatus(
            wifi_available=True, wifi_iface="wlan0", wifi_driver="iwlwifi",
        )
        bat_ok = BatteryInfo(available=True, capacity_percent=80, energy_full_wh=55.0, energy_design_wh=57.5, health_percent=95.6)

        with patch.object(backend, "get_platform_profile_choices", return_value=["low-power", "balanced", "performance"]), \
             patch.object(backend, "get_available_cpu_governors", return_value=["powersave", "performance"]), \
             patch.object(backend, "get_gpu_mux_info", return_value=mux_lenovo), \
             patch.object(backend, "get_display_refresh_info", return_value=ref_single), \
             patch.object(backend, "get_network_power_status", return_value=net_wifi_only), \
             patch.object(backend, "get_battery_info", return_value=bat_ok), \
             patch.object(backend, "get_bios_attributes", return_value=[
                 BiosAttribute(attr_id="cpu_temp", display_name="CPU Temp", attr_type="integer", current_value="94", min_value=85, max_value=100)
             ]):
            from ui.dashboard import VantageDashboardView
            from ui.tabs.performance_tab import PerformanceTab
            from ui.tabs.gpu_display_tab import GpuDisplayTab
            from ui.tabs.automation_tab import AutomationTab
            from ui.tabs.battery_tab import BatteryTab
            from ui.tabs.about_tab import AboutTab

            dash = VantageDashboardView(backend)
            # Perfis suportados visíveis; max-power oculto
            self.assertFalse(dash.thermal_card.isHidden())
            self.assertFalse(dash.block_quiet.isHidden())
            self.assertFalse(dash.block_balanced.isHidden())
            self.assertFalse(dash.block_perf.isHidden())
            self.assertTrue(dash.block_max_power.isHidden())
            # EDGE: visíveis vs ocultos
            self.assertFalse(dash.item_conservation.isHidden())
            self.assertFalse(dash.item_camera.isHidden())
            self.assertFalse(dash.item_touchpad.isHidden())
            self.assertTrue(dash.item_rapid_charge.isHidden())
            self.assertTrue(dash.item_kbd_backlight.isHidden())

            perf = PerformanceTab(backend)
            # Fan curve visível com WMI CPU temp apenas; sliders TDP RAPL ocultos
            self.assertFalse(perf.tdp_card.isHidden())
            self.assertFalse(perf.fan_ctrl_box.isHidden())
            self.assertFalse(perf.wmi_cpu_temp_widget.isHidden())
            self.assertTrue(perf.wmi_gpu_temp_widget.isHidden())
            self.assertTrue(perf.sliders_box.isHidden())
            # Undervolt: apenas WMI GPU AC Offset visível; Core/Cache/Emergency Reset ocultos
            self.assertFalse(perf.uv_card.isHidden())
            self.assertTrue(perf.uv_core_row_widget.isHidden())
            self.assertTrue(perf.uv_cache_row_widget.isHidden())
            self.assertFalse(perf.uv_gpu_offset_widget.isHidden())

            gdisp = GpuDisplayTab(backend)
            # GPU MUX: hybrid e integrated visíveis, dedicated OCULTO!
            self.assertFalse(gdisp.mux_card.isHidden())
            self.assertFalse(gdisp.mux_blocks["hybrid"].isHidden())
            self.assertFalse(gdisp.mux_blocks["integrated"].isHidden())
            self.assertTrue(gdisp.mux_blocks["dedicated"].isHidden())
            # Refresh rate 60Hz fixo -> card OCULTO!
            self.assertTrue(gdisp.ref_card.isHidden())
            self.assertTrue(gdisp.has_any_supported_feature())

            auto = AutomationTab(backend)
            # App Rules combo não deve listar max-power
            combo_ids = [auto.combo_app_profile.itemData(i) for i in range(auto.combo_app_profile.count())]
            self.assertNotIn("max-power", combo_ids)
            self.assertIn("performance", combo_ids)
            # Presets e opções do Auto-Switch respeitam feature-gating
            self.assertFalse(auto.presets_card.isHidden())
            self.assertTrue(auto.game_refresh_row_widget.isHidden())
            self.assertFalse(auto.game_touchpad_row_widget.isHidden())
            game_target_ids = [auto.combo_game_target_profile.itemData(i) for i in range(auto.combo_game_target_profile.count())]
            self.assertNotIn("max-power", game_target_ids)
            self.assertIn("performance", game_target_ids)
            # Key Remapper não deve listar cycle_refresh_rate
            supported_acts = [a[0] for a in auto._get_supported_key_actions()]
            self.assertNotIn("cycle_refresh_rate", supported_acts)

            bat = BatteryTab(backend)
            self.assertFalse(bat.cons_card.isHidden())
            self.assertFalse(bat.cons_row_widget.isHidden())
            self.assertTrue(bat.rapid_row_widget.isHidden())
            self.assertTrue(bat.cons_div.isHidden())
            self.assertFalse(bat.net_card.isHidden())
            self.assertFalse(bat.wifi_box.isHidden())

            about = AboutTab(backend)
            self.assertFalse(about.fn_lock_row_widget.isHidden())
            self.assertTrue(about.usb_row_widget.isHidden())
            self.assertFalse(about.ac_bat_prefs_widget.isHidden())

            dash.close()
            perf.close()
            gdisp.close()
            auto.close()
            bat.close()
            about.close()
        backend.close()

    # =========================================================================
    # 4. Detecção rigorosa de Undervolt (Intel non-HX bloqueado vs HX vs AMD)
    # =========================================================================
    @patch("glob.glob", return_value=["/dev/cpu/0/msr"])
    @patch("shutil.which", return_value=None)
    def test_undervolt_detection_intel_non_hx_locked_vs_hx_unlocked(self, _mock_which, _mock_glob):
        """Intel 12ª/13ª/14ª Gen não-HX (ex: i5-12450H, Core Ultra 7 155H) não suporta undervolt; HX suporta."""
        backend = _make_blank_backend(HardwareFeatures())
        backend._cached_cpu_vendor = "Intel"

        backend.system_info.cpu_model = "12th Gen Intel(R) Core(TM) i5-12450H"
        backend._scan_undervolt()
        self.assertFalse(backend.features.cpu_undervolt)

        backend.system_info.cpu_model = "Intel(R) Core(TM) Ultra 7 155H"
        backend._scan_undervolt()
        self.assertFalse(backend.features.cpu_undervolt)

        backend.system_info.cpu_model = "12th Gen Intel(R) Core(TM) i5-12450HX"
        backend._scan_undervolt()
        self.assertTrue(backend.features.cpu_undervolt)

        # AMD sem ryzenadj -> False
        backend._cached_cpu_vendor = "AMD"
        backend.system_info.cpu_model = "AMD Ryzen 7 7840HS"
        backend._scan_undervolt()
        self.assertFalse(backend.features.cpu_undervolt)
        backend.close()

    # =========================================================================
    # 5. Perfil Completo (Ex: Legion Pro com LCD Overdrive, 165Hz, MUX completo e Max-Power)
    # =========================================================================
    def test_full_legion_profile_shows_all_supported_features(self):
        """Em um Legion Pro completo, LCD Overdrive, 165Hz, MUX 3 modos e Max-Power são exibidos."""
        feat = HardwareFeatures(
            platform_profile=True,
            available_profiles=["low-power", "balanced", "performance", "max-power"],
            max_power_profile=True,
            conservation_mode=True,
            rapid_charge=True,
            fn_lock=True,
            camera_power=True,
            usb_charging=True,
            kbd_backlight=True,
            kbd_max_brightness=2,
            turbo_boost=True,
            cpu_governor=True,
            custom_tdp=True,
            fan_control=True,
            wmi_cpu_temp=True,
            wmi_gpu_temp=True,
            cpu_undervolt=True,
            wmi_gpu_ac_offset=True,
            touchpad_control=True,
            gpu_telemetry=True,
            gpu_mux=True,
            refresh_rate=True,
            lcd_overdrive=True,
            bios_attributes=True,
            battery=True,
            wifi_power_save=True,
            eco_travel=True,
        )
        paths = HardwarePaths(lcd_overdrive="/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes/lcd_overdrive/current_value")
        backend = _make_blank_backend(feat, paths)

        mux_full = GpuMuxInfo(
            available=True,
            current_mode="dedicated",
            available_modes=["hybrid", "dedicated", "integrated"],
            backend_name="supergfxctl",
        )
        ref_high = DisplayRefreshInfo(
            available=True,
            current_hz=165,
            available_rates=[60, 165],
            display_name="eDP-1",
            resolution="2560x1600",
            backend_name="kscreen-doctor",
        )
        with patch.object(backend, "get_platform_profile_choices", return_value=["low-power", "balanced", "performance", "max-power"]), \
             patch.object(backend, "get_available_cpu_governors", return_value=["powersave", "performance"]), \
             patch.object(backend, "get_gpu_mux_info", return_value=mux_full), \
             patch.object(backend, "get_display_refresh_info", return_value=ref_high), \
             patch.object(backend, "get_bios_attributes", return_value=[
                 BiosAttribute(attr_id="flip_to_boot", display_name="Flip to Boot", attr_type="boolean", current_value="1")
             ]):
            from ui.dashboard import VantageDashboardView
            from ui.tabs.performance_tab import PerformanceTab
            from ui.tabs.gpu_display_tab import GpuDisplayTab
            from ui.tabs.automation_tab import AutomationTab

            dash = VantageDashboardView(backend)
            self.assertFalse(dash.block_max_power.isHidden())
            self.assertFalse(dash.item_kbd_backlight.isHidden())

            perf = PerformanceTab(backend)
            self.assertFalse(perf.current_badge.isHidden())

            gdisp = GpuDisplayTab(backend)
            self.assertFalse(gdisp.od_box.isHidden())
            self.assertFalse(gdisp.bios_card.isHidden())
            self.assertIn("LCD Overdrive", gdisp.bios_title_lbl.text())
            self.assertFalse(gdisp.ref_card.isHidden())
            self.assertFalse(gdisp.mux_card.isHidden())
            self.assertFalse(gdisp.mux_blocks["dedicated"].isHidden())

            auto = AutomationTab(backend)
            self.assertFalse(auto.presets_card.isHidden())
            self.assertFalse(auto.game_refresh_row_widget.isHidden())
            self.assertFalse(auto.game_touchpad_row_widget.isHidden())
            game_target_ids = [auto.combo_game_target_profile.itemData(i) for i in range(auto.combo_game_target_profile.count())]
            self.assertIn("max-power", game_target_ids)

            dash.close()
            perf.close()
            gdisp.close()
            auto.close()
        backend.close()

    def test_rgb_keyboard_tab_visible_only_when_supported(self):
        """Botão/Aba de Iluminação RGB só aparece na sidebar quando rgb_keyboard=True."""
        from ui_main import MainWindow

        backend_no_rgb = _make_blank_backend(HardwareFeatures(rgb_keyboard=False))
        with patch.object(backend_no_rgb, "get_bios_attributes", return_value=[]), \
             patch.object(backend_no_rgb, "get_gpu_mux_info", return_value=GpuMuxInfo(available=False, available_modes=[], backend_name="none")), \
             patch.object(backend_no_rgb, "get_display_refresh_info", return_value=DisplayRefreshInfo(available=False, current_hz=60, available_rates=[60], backend_name="drm-fallback")), \
             patch.object(backend_no_rgb, "get_network_power_status", return_value=NetworkPowerStatus(wifi_available=False)), \
             patch.object(backend_no_rgb, "get_battery_info", return_value=BatteryInfo(available=False)):
            win_off = MainWindow(backend_no_rgb)
            self.assertTrue(win_off.lighting_nav_btn.isHidden())
            win_off._quit_app()
            win_off.close()
        backend_no_rgb.close()

        backend_rgb = _make_blank_backend(HardwareFeatures(rgb_keyboard=True))
        with patch.object(backend_rgb, "get_bios_attributes", return_value=[]), \
             patch.object(backend_rgb, "get_gpu_mux_info", return_value=GpuMuxInfo(available=False, available_modes=[], backend_name="none")), \
             patch.object(backend_rgb, "get_display_refresh_info", return_value=DisplayRefreshInfo(available=False, current_hz=60, available_rates=[60], backend_name="drm-fallback")), \
             patch.object(backend_rgb, "get_network_power_status", return_value=NetworkPowerStatus(wifi_available=False)), \
             patch.object(backend_rgb, "get_battery_info", return_value=BatteryInfo(available=False)):
            win_on = MainWindow(backend_rgb)
            self.assertFalse(win_on.lighting_nav_btn.isHidden())
            win_on._quit_app()
            win_on.close()
        backend_rgb.close()


if __name__ == "__main__":
    unittest.main()
