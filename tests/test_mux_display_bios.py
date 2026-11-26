#!/usr/bin/env python3
"""
Testes Automatizados para Ducksvantage: Recursos 1, 2 e 3
1. GPU MUX Switch (Modo Híbrido vs dGPU Direta vs iGPU Pura)
2. Taxa de Atualização Automática (144Hz/165Hz ↔ 60Hz com atalho Fn+R e transição AC/Bateria)
3. LCD Overdrive & Ajustes de BIOS / Lenovo WMI (Zero Hardcoding)
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock, mock_open

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.settings import SettingsManager
from core.permissions import PermissionsManager
from core.backend import HardwareBackend
from core.models import GpuMuxInfo, DisplayRefreshInfo, BiosAttribute


class TestMuxDisplayBios(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from core.qt_compat import QApplication
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        cls.app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])

    def setUp(self):
        self.backend = HardwareBackend()

    def tearDown(self):
        self.backend.close()

    # =========================================================================
    # RECURSO 1: GPU MUX Switch Tests
    # =========================================================================

    @patch("shutil.which")
    @patch("core.backend.subprocess.run")
    def test_gpu_mux_supergfxctl_query_and_set(self, mock_subproc, mock_which):
        """supergfxctl: consulta de modo, detecção de reinicialização e comutação."""
        mock_which.side_effect = lambda cmd: "/usr/bin/supergfxctl" if cmd == "supergfxctl" else None
        
        # Simula supergfxctl -g retornando "Dedicated" e -s informando reinicialização necessária
        def fake_run(cmd, **kwargs):
            if "-g" in cmd:
                return MagicMock(returncode=0, stdout="Dedicated\n", stderr="")
            if "-s" in cmd:
                return MagicMock(returncode=0, stdout="Action required: reboot to switch GPU mode\n", stderr="")
            if "-m" in cmd:
                return MagicMock(returncode=0, stdout="Switched to Hybrid. Reboot required.\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = fake_run

        info = self.backend.get_gpu_mux_info()
        self.assertTrue(info.available)
        self.assertEqual(info.backend_name, "supergfxctl")
        self.assertEqual(info.current_mode, "dedicated")
        self.assertTrue(info.requires_reboot)

        # Trocar para modo híbrido
        ok, msg, req_reboot = self.backend.set_gpu_mux_mode("hybrid")
        self.assertTrue(ok)
        self.assertTrue(req_reboot)
        self.assertIn("Hybrid", msg)

    @patch("shutil.which")
    @patch("core.backend.subprocess.run")
    def test_gpu_mux_envycontrol_query_and_set(self, mock_subproc, mock_which):
        """envycontrol: consulta de modo e comutação com reinicialização obrigatória."""
        mock_which.side_effect = lambda cmd: "/usr/bin/envycontrol" if cmd == "envycontrol" else None

        def fake_run(cmd, **kwargs):
            if "--query" in cmd:
                return MagicMock(returncode=0, stdout="nvidia\n", stderr="")
            if "-s" in cmd:
                return MagicMock(returncode=0, stdout="Switched to hybrid. Please reboot.\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = fake_run

        info = self.backend.get_gpu_mux_info()
        self.assertTrue(info.available)
        self.assertEqual(info.backend_name, "envycontrol")
        self.assertEqual(info.current_mode, "dedicated")  # 'nvidia' maps to 'dedicated'

        ok, msg, req_reboot = self.backend.set_gpu_mux_mode("hybrid")
        self.assertTrue(ok)
        self.assertTrue(req_reboot)
        self.assertIn("Reinicie o sistema", msg)

    @patch("shutil.which")
    @patch("core.backend.subprocess.run")
    def test_gpu_mux_prime_select_query_and_set(self, mock_subproc, mock_which):
        """prime-select: consulta de modo (on-demand -> hybrid, intel -> integrated)."""
        mock_which.side_effect = lambda cmd: "/usr/bin/prime-select" if cmd == "prime-select" else None

        def fake_run(cmd, **kwargs):
            if "query" in cmd:
                return MagicMock(returncode=0, stdout="on-demand\n", stderr="")
            return MagicMock(returncode=0, stdout="Done\n", stderr="")

        mock_subproc.side_effect = fake_run

        info = self.backend.get_gpu_mux_info()
        self.assertTrue(info.available)
        self.assertEqual(info.backend_name, "prime-select")
        self.assertEqual(info.current_mode, "hybrid")

        ok, msg, req_reboot = self.backend.set_gpu_mux_mode("integrated")
        self.assertTrue(ok)
        self.assertTrue(req_reboot)

    @patch("shutil.which", return_value=None)
    @patch("os.path.exists")
    @patch("core.permissions.PermissionsManager.write_sysfs_value")
    @patch("core.backend.HardwareBackend._read_file_text")
    def test_gpu_mux_lenovo_wmi_sysfs(self, mock_read, mock_write, mock_exists, mock_which):
        """Lenovo ACPI / WMI gpu_mode sysfs node: 0=hybrid, 1=dedicated, 2=integrated."""
        self.backend.paths.gpu_mode = "/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/gpu_mode"
        mock_exists.return_value = True
        mock_read.return_value = "1\n"
        mock_write.return_value = (True, "Escrito")

        info = self.backend.get_gpu_mux_info()
        self.assertEqual(info.backend_name, "lenovo-wmi")
        self.assertEqual(info.current_mode, "dedicated")

        ok, msg, req_reboot = self.backend.set_gpu_mux_mode("integrated")
        self.assertTrue(ok)
        self.assertTrue(req_reboot)
        mock_write.assert_called_with(self.backend.paths.gpu_mode, "2", allow_elevation=True)

    def test_gpu_mux_invalid_mode_rejected(self):
        """Modo inválido de GPU deve ser rejeitado com mensagem de erro amigável."""
        ok, msg, req_reboot = self.backend.set_gpu_mux_mode("modo_invalido_xyz")
        self.assertFalse(ok)
        self.assertIn("inválido", msg.lower())
        self.assertFalse(req_reboot)

    # =========================================================================
    # RECURSO 2: Taxa de Atualização de Tela Tests
    # =========================================================================

    @patch("shutil.which")
    @patch("core.backend.subprocess.run")
    def test_display_refresh_kscreen_doctor_kde(self, mock_subproc, mock_which):
        """KDE Plasma kscreen-doctor: detecção de resoluções, taxas (60 e 144Hz) e aplicação."""
        mock_which.side_effect = lambda cmd: "/usr/bin/kscreen-doctor" if cmd == "kscreen-doctor" else None

        kscreen_data = {
            "outputs": [
                {
                    "name": "eDP-1",
                    "connected": True,
                    "enabled": True,
                    "currentModeId": "mode-144",
                    "modes": [
                        {"id": "mode-60", "size": {"width": 1920, "height": 1080}, "refreshRate": 60000},
                        {"id": "mode-144", "size": {"width": 1920, "height": 1080}, "refreshRate": 144000},
                        {"id": "mode-other", "size": {"width": 1280, "height": 720}, "refreshRate": 60000}
                    ]
                }
            ]
        }

        def fake_run(cmd, **kwargs):
            if "-j" in cmd:
                return MagicMock(returncode=0, stdout=json.dumps(kscreen_data), stderr="")
            if any("@" in str(arg) for arg in cmd) or any("mode" in str(arg) for arg in cmd):
                return MagicMock(returncode=0, stdout="Mode applied\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = fake_run

        info = self.backend.get_display_refresh_info()
        self.assertTrue(info.available)
        self.assertEqual(info.backend_name, "kscreen-doctor")
        self.assertEqual(info.display_name, "eDP-1")
        self.assertEqual(info.current_hz, 144)
        self.assertEqual(info.available_rates, [60, 144])

        # Testar aplicação de 60 Hz
        ok, msg = self.backend.set_refresh_rate(60)
        self.assertTrue(ok)
        self.assertIn("60 Hz", msg)

    @patch("shutil.which")
    @patch("core.backend.subprocess.run")
    def test_display_refresh_xrandr_x11(self, mock_subproc, mock_which):
        """X11 xrandr: parsing de taxas com asterisco indicador da taxa atual."""
        mock_which.side_effect = lambda cmd: "/usr/bin/xrandr" if cmd == "xrandr" else None

        xrandr_stdout = """
Screen 0: minimum 8 x 8, current 1920 x 1080, maximum 32767 x 32767
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 194mm
   1920x1080    144.00*+  60.00  
   1280x720      60.00  
HDMI-1 disconnected (normal left inverted right x axis y axis)
"""
        def fake_run(cmd, **kwargs):
            if "--current" in cmd:
                return MagicMock(returncode=0, stdout=xrandr_stdout, stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_subproc.side_effect = fake_run

        info = self.backend.get_display_refresh_info()
        self.assertTrue(info.available)
        self.assertEqual(info.backend_name, "xrandr")
        self.assertEqual(info.current_hz, 144)
        self.assertEqual(info.available_rates, [60, 144])

    @patch("core.backend.HardwareBackend.get_display_refresh_info")
    @patch("core.backend.HardwareBackend.set_refresh_rate")
    def test_display_refresh_cycle_fn_r(self, mock_set_rate, mock_get_info):
        """Ciclo Fn + R: de 144Hz vai para 60Hz; de 60Hz vai para 144Hz."""
        mock_get_info.return_value = DisplayRefreshInfo(
            available=True, current_hz=144, available_rates=[60, 144], display_name="eDP-1"
        )
        mock_set_rate.return_value = (True, "OK")

        # Quando está em 144Hz, deve ciclar para 60Hz
        ok, next_hz, msg = self.backend.cycle_refresh_rate()
        self.assertTrue(ok)
        self.assertEqual(next_hz, 60)
        mock_set_rate.assert_called_with(60)

        # Quando está em 60Hz, deve ciclar para 144Hz
        mock_get_info.return_value = DisplayRefreshInfo(
            available=True, current_hz=60, available_rates=[60, 144], display_name="eDP-1"
        )
        ok, next_hz, msg = self.backend.cycle_refresh_rate()
        self.assertTrue(ok)
        self.assertEqual(next_hz, 144)
        mock_set_rate.assert_called_with(144)

    @patch("core.backend.HardwareBackend.get_display_refresh_info")
    @patch("core.backend.HardwareBackend.set_refresh_rate")
    @patch("core.backend.HardwareBackend._get_ac_online")
    def test_auto_refresh_rate_ac_battery_transition(self, mock_ac, mock_set_rate, mock_get_info):
        """Ao desconectar tomada AC -> 60Hz (economia); ao reconectar tomada -> 144Hz (fluidez)."""
        self.backend.features.refresh_rate = True
        self.backend.set_auto_refresh_rate_transition(True)
        mock_set_rate.return_value = (True, "Ajustado")
        self.backend._last_ac_online = 1  # Estava no AC

        # 1. Desconectar o carregador (Bateria)
        mock_ac.return_value = 0
        mock_get_info.return_value = DisplayRefreshInfo(
            available=True, current_hz=144, available_rates=[60, 144], display_name="eDP-1"
        )
        events = self.backend.poll_hardware_events()
        
        # Deve ter evento de ac_changed e refresh_rate_changed para 60Hz
        ref_ev = next((e for e in events if e.get("type") == "refresh_rate_changed"), None)
        self.assertIsNotNone(ref_ev)
        self.assertEqual(ref_ev.get("hz"), 60)
        self.assertEqual(ref_ev.get("reason"), "battery")

        # 2. Reconectar o carregador (Tomada AC)
        mock_ac.return_value = 1
        mock_get_info.return_value = DisplayRefreshInfo(
            available=True, current_hz=60, available_rates=[60, 144], display_name="eDP-1"
        )
        events2 = self.backend.poll_hardware_events()
        ref_ev2 = next((e for e in events2 if e.get("type") == "refresh_rate_changed"), None)
        self.assertIsNotNone(ref_ev2)
        self.assertEqual(ref_ev2.get("hz"), 144)
        self.assertEqual(ref_ev2.get("reason"), "ac")

    @patch("core.backend.HardwareBackend.cycle_refresh_rate")
    def test_execute_mapped_action_cycle_refresh_rate(self, mock_cycle):
        """execute_mapped_action com 'cycle_refresh_rate' retorna metadados completos para o OSD."""
        mock_cycle.return_value = (True, 144, "Taxa ajustada para 144 Hz")
        res = self.backend.execute_mapped_action("cycle_refresh_rate")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("osd_type"), "refresh_rate")
        self.assertEqual(res.get("hz"), 144)
        self.assertIn("144 Hz", res.get("title"))

    # =========================================================================
    # RECURSO 3: LCD Overdrive & Ajustes de BIOS Lenovo Tests
    # =========================================================================

    @patch("os.path.exists", return_value=True)
    @patch("core.backend.HardwareBackend._read_file_text")
    @patch("core.permissions.PermissionsManager.write_sysfs_value")
    def test_lcd_overdrive_get_and_set(self, mock_write, mock_read, mock_exists):
        """LCD Overdrive: leitura e gravação no nó sysfs correspondente."""
        self.backend.paths.lcd_overdrive = "/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes/lcd_overdrive/current_value"
        mock_read.return_value = "1\n"
        mock_write.return_value = (True, "Sucesso")

        self.assertTrue(self.backend.get_lcd_overdrive())

        ok, msg = self.backend.set_lcd_overdrive(False)
        self.assertTrue(ok)
        mock_write.assert_called_with(self.backend.paths.lcd_overdrive, "0", allow_elevation=True)

    @patch("glob.glob")
    @patch("os.listdir")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch("core.backend.HardwareBackend._read_file_text")
    @patch("core.backend.HardwareBackend._read_file_int")
    def test_bios_attributes_dynamic_discovery(self, mock_read_int, mock_read_txt, mock_exists, mock_isdir, mock_listdir, mock_glob):
        """Inspeção dinâmica da BIOS Lenovo WMI sem hardcoding de atributos."""
        mock_glob.return_value = ["/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes"]
        mock_listdir.return_value = ["cpu_temp", "flip_to_boot", "custom_fan_mode"]

        def fake_read_txt(path):
            if "type" in path:
                if "cpu_temp" in path:
                    return "integer"
                if "flip_to_boot" in path:
                    return "enumeration"
                return "enumeration"
            if "current_value" in path:
                if "cpu_temp" in path:
                    return "94"
                if "flip_to_boot" in path:
                    return "1"
                return "Auto"
            if "possible_values" in path:
                if "flip_to_boot" in path:
                    return "0;1"
                return "Quiet;Auto;Full"
            if "display_name" in path:
                return "Display Name"
            return ""

        def fake_read_int(path, default):
            if "min_value" in path:
                return 85
            if "max_value" in path:
                return 100
            return default

        mock_read_txt.side_effect = fake_read_txt
        mock_read_int.side_effect = fake_read_int

        attrs = self.backend.get_bios_attributes()
        self.assertEqual(len(attrs), 3)

        attr_map = {a.attr_id: a for a in attrs}
        self.assertIn("cpu_temp", attr_map)
        self.assertIn("flip_to_boot", attr_map)
        self.assertIn("custom_fan_mode", attr_map)

        # cpu_temp deve ser integer com min/max
        self.assertEqual(attr_map["cpu_temp"].attr_type, "integer")
        self.assertEqual(attr_map["cpu_temp"].min_value, 85)
        self.assertEqual(attr_map["cpu_temp"].max_value, 100)

        # flip_to_boot com opções 0/1 deve ser classificado como boolean
        self.assertEqual(attr_map["flip_to_boot"].attr_type, "boolean")

        # custom_fan_mode deve ser enumeration com lista de possíveis valores
        self.assertEqual(attr_map["custom_fan_mode"].attr_type, "enumeration")
        self.assertEqual(attr_map["custom_fan_mode"].possible_values, ["Quiet", "Auto", "Full"])

    @patch("core.backend.HardwareBackend.get_bios_attributes")
    @patch("core.permissions.PermissionsManager.write_sysfs_value")
    def test_set_bios_attribute(self, mock_write, mock_get_attrs):
        """Escrita de atributos de BIOS via PermissionsManager."""
        mock_get_attrs.return_value = [
            BiosAttribute(attr_id="flip_to_boot", display_name="Flip to Boot", path="/fake/flip/current_value")
        ]
        mock_write.return_value = (True, "OK")

        ok, msg = self.backend.set_bios_attribute("flip_to_boot", "0")
        self.assertTrue(ok)
        mock_write.assert_called_with("/fake/flip/current_value", "0", allow_elevation=True)

    # =========================================================================
    # RECURSOS VISUAIS: OSD & PerformanceTab UI Tests
    # =========================================================================

    @patch("shutil.which")
    @patch("core.backend.subprocess.run")
    def test_display_refresh_xrandr_multi_monitor(self, mock_subproc, mock_which):
        """X11 multi-monitor: prioriza o painel interno (eDP-1 144Hz) e ignora HDMI externo (60Hz)."""
        mock_which.side_effect = lambda cmd: "/usr/bin/xrandr" if cmd == "xrandr" else None

        xrandr_stdout = """
Screen 0: minimum 8 x 8, current 3840 x 1080, maximum 32767 x 32767
HDMI-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+  50.00  
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 194mm
   1920x1080    144.00*+  60.00  
   1280x720      60.00  
DP-1 disconnected (normal left inverted right x axis y axis)
"""
        mock_subproc.return_value = MagicMock(returncode=0, stdout=xrandr_stdout, stderr="")

        info = self.backend.get_display_refresh_info()
        self.assertTrue(info.available)
        self.assertEqual(info.backend_name, "xrandr")
        self.assertEqual(info.display_name, "eDP-1")
        self.assertEqual(info.current_hz, 144)
        self.assertEqual(info.available_rates, [60, 144])

    def test_settings_migration_adds_missing_refresh_rate_hotkey(self):
        """SettingsManager mescla atalhos novos (ex: refresh_rate_hotkey) mesmo com arquivo existente."""
        import tempfile
        from core.settings import SettingsManager
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "settings.json")
            # Configuração existente de versão anterior sem refresh_rate_hotkey
            old_data = {
                "key_mappings": {
                    "copilot_key": {"action": "cycle_profile", "enabled": True}
                }
            }
            with open(cfg_file, "w") as f:
                json.dump(old_data, f)

            with patch("core.settings.CONFIG_DIR", tmpdir), patch("core.settings.CONFIG_FILE", cfg_file), patch("core.settings.LEGACY_CONFIG_FILE", "/nonexistent"):
                sm = SettingsManager()
                km = sm.get("key_mappings")
                self.assertIn("copilot_key", km)
                self.assertIn("refresh_rate_hotkey", km)
                self.assertEqual(km["refresh_rate_hotkey"]["action"], "cycle_refresh_rate")

    def test_gpu_mux_unsupported_mode_rejected_for_backend(self):
        """Backend pcie-runtime rejeita 'dedicated' pois não possui comutação física de MUX."""
        with patch.object(self.backend, "get_gpu_mux_info") as mock_info:
            mock_info.return_value = GpuMuxInfo(
                available=True, current_mode="hybrid", available_modes=["hybrid", "integrated"], backend_name="pcie-runtime"
            )
            ok, msg, req_reboot = self.backend.set_gpu_mux_mode("dedicated")
            self.assertFalse(ok)
            self.assertIn("não é suportado", msg.lower())
            self.assertFalse(req_reboot)

    @patch("core.backend.HardwareBackend.get_bios_attributes")
    @patch("core.permissions.PermissionsManager.write_sysfs_value")
    def test_set_bios_attribute_boolean_string_translation(self, mock_write, mock_get_attrs):
        """Atributos booleanos que exigem 'Enabled'/'Disabled' são traduzidos a partir de '1'/'0'."""
        mock_get_attrs.return_value = [
            BiosAttribute(
                attr_id="flip_to_boot",
                display_name="Flip to Boot",
                attr_type="boolean",
                possible_values=["Disabled", "Enabled"],
                path="/fake/flip/current_value"
            )
        ]
        mock_write.return_value = (True, "OK")

        # Tenta escrever "1" -> Deve traduzir para "Enabled"
        ok, msg = self.backend.set_bios_attribute("flip_to_boot", "1")
        self.assertTrue(ok)
        mock_write.assert_called_with("/fake/flip/current_value", "Enabled", allow_elevation=True)

        # Tenta escrever "0" -> Deve traduzir para "Disabled"
        ok2, msg2 = self.backend.set_bios_attribute("flip_to_boot", "0")
        self.assertTrue(ok2)
        mock_write.assert_called_with("/fake/flip/current_value", "Disabled", allow_elevation=True)

    @patch("glob.glob")
    @patch("os.listdir")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch("core.backend.HardwareBackend._read_file_text")
    @patch("core.backend.HardwareBackend._read_file_int")
    def test_bios_integer_zero_bounds_fallback(self, mock_read_int, mock_read_txt, mock_exists, mock_isdir, mock_listdir, mock_glob):
        """Quando a BIOS expõe min=0 max=0 para cTGP (como em Lenovo LOQ), o range do slider deve ser corrigido."""
        mock_glob.return_value = ["/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes"]
        mock_listdir.return_value = ["gpu_nv_ctgp"]

        def fake_read_txt(path):
            if "type" in path:
                return "integer"
            if "current_value" in path:
                return "55"
            return ""

        def fake_read_int(path, default):
            if "min_value" in path:
                return 0
            if "max_value" in path:
                return 0
            return default

        mock_read_txt.side_effect = fake_read_txt
        mock_read_int.side_effect = fake_read_int

        attrs = self.backend.get_bios_attributes()
        self.assertEqual(len(attrs), 1)
        a = attrs[0]
        self.assertEqual(a.attr_id, "gpu_nv_ctgp")
        self.assertEqual(a.current_value, "55")
        self.assertEqual(a.min_value, 0)
        self.assertGreater(a.max_value, 55)

    @patch("core.backend.HardwareBackend.get_display_refresh_info")
    @patch("core.backend.HardwareBackend.set_refresh_rate")
    @patch("core.backend.HardwareBackend._get_ac_online")
    def test_auto_refresh_rate_does_not_fire_when_ac_unchanged(self, mock_ac, mock_set_rate, mock_get_info):
        """Quando o cabo AC não é alterado, o polling periódico NÃO deve disparar troca de taxa nem subprocessos."""
        self.backend.features.refresh_rate = True
        self.backend.set_auto_refresh_rate_transition(True)
        self.backend._last_ac_online = 1  # Estava no AC
        mock_ac.return_value = 1  # Continua no AC

        # Usuário definiu manualmente 60 Hz no AC
        mock_get_info.return_value = DisplayRefreshInfo(
            available=True, current_hz=60, available_rates=[60, 144], display_name="eDP-1"
        )
        events = self.backend.poll_hardware_events()

        # Não deve haver evento de refresh_rate_changed
        ref_ev = next((e for e in events if e.get("type") == "refresh_rate_changed"), None)
        self.assertIsNone(ref_ev)
        mock_set_rate.assert_not_called()

    def test_ui_main_dashboard_lcd_overdrive_toggled(self):
        """Ao clicar no switch de LCD Overdrive no Dashboard, ui_main chama set_lcd_overdrive e atualiza OSD."""
        from ui_main import MainWindow
        win = MainWindow(self.backend)
        with patch.object(self.backend, "set_lcd_overdrive", return_value=(True, "OK")) as mock_set_od, \
             patch.object(win.osd, "notify_lcd_overdrive") as mock_osd:
            win._apply_lcd_overdrive(True)
            mock_set_od.assert_called_with(True)
            mock_osd.assert_called_with(True)
        win.close()

    def test_osd_notifications_smoke(self):
        """Verifica se as notificações OSD de taxa, GPU MUX e LCD Overdrive formatam sem erros."""
        from ui.osd_overlay import VantageOSDOverlay
        osd = VantageOSDOverlay()

        # OSD Taxa de Atualização
        osd.notify_refresh_rate(144, reason="ac")
        self.assertIn("144 Hz", osd.title_label.text())

        osd.notify_refresh_rate(60, reason="battery")
        self.assertIn("60 Hz", osd.title_label.text())

        # OSD GPU MUX
        osd.notify_gpu_mux("dedicated", requires_reboot=True)
        self.assertIn("dGPU", osd.title_label.text())

        # OSD LCD Overdrive
        osd.notify_lcd_overdrive(True)
        self.assertIn("Ativado", osd.title_label.text())
        osd.close()

    def test_performance_tab_ui_initialization(self):
        """Verifica se PerformanceTab, GpuDisplayTab e AutomationTab instanciam corretamente."""
        from ui.tabs.performance_tab import PerformanceTab
        from ui.tabs.gpu_display_tab import GpuDisplayTab
        from ui.tabs.automation_tab import AutomationTab

        tab = PerformanceTab(self.backend)
        gdisp = GpuDisplayTab(self.backend)
        auto = AutomationTab(self.backend)

        # Recurso 1: Cartão GPU MUX Switch presente e com 3 blocos
        self.assertIn("hybrid", gdisp.mux_blocks)
        self.assertIn("dedicated", gdisp.mux_blocks)
        self.assertIn("integrated", gdisp.mux_blocks)

        # Recurso 2: Display refresh rate widgets inicializados
        self.assertIsNotNone(gdisp.ref_rate_badge)
        self.assertIsNotNone(gdisp.ref_auto_switch)

        # Recurso 3: LCD Overdrive e container dinâmico de BIOS
        self.assertIsNotNone(gdisp.lcd_overdrive_switch)
        self.assertIsNotNone(gdisp.bios_dyn_container)

        # Automação & Atalhos
        self.assertIsNotNone(auto.presets_card)
        self.assertIsNotNone(auto.rules_card)
        self.assertIsNotNone(auto.remap_card)

        tab.refresh_profile_state()
        gdisp.refresh_all()
        auto.refresh_automation_state()
        tab.close()
        gdisp.close()
        auto.close()


if __name__ == "__main__":
    unittest.main()
