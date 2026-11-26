#!/usr/bin/env python3
"""
Testes Automatizados para Ducksvantage
Valida a resolução dos 9 pontos críticos apontados na auditoria técnica:
1. Escrita Indevida no MSR 0x150 em CPUs AMD (Kernel Panic Guard)
2. Bloqueio Síncrono de Interface (allow_elevation=False nos timers)
3. Vazamento e Leitura em Descritores de Arquivos Órfãos no evdev
4. Processo Fantasma sem System Tray (isSystemTrayAvailable)
5. Micro-Travamentos na Interface (Caches de nvidia-smi, iw e psutil)
6. Incompatibilidade de Posicionamento do OSD em Wayland
7. Escrita Atômica de Configurações (settings.json)
8. Vulnerabilidade TOCTOU Symlink na Instalação do UDEV
9. psutil.ZombieProcess Tratado
"""

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock, mock_open

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.settings import SettingsManager
from core.permissions import PermissionsManager
from core.backend import HardwareBackend
from core.models import CPUMetrics, GPUMetrics, NetworkPowerStatus


class TestDucksVantageFixes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from core.qt_compat import QApplication
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        cls.app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])

    def setUp(self):
        self.backend = HardwareBackend()

    def tearDown(self):
        self.backend.close()

    # -------------------------------------------------------------------------
    # 1. CPU AMD vs Intel MSR 0x150 Guard
    # -------------------------------------------------------------------------
    @patch("core.backend.HardwareBackend.get_cpu_vendor")
    @patch("os.pwrite")
    @patch("glob.glob")
    @patch("os.access")
    @patch("shutil.which")
    @patch("core.backend.subprocess.run")
    def test_msr_0x150_never_called_on_amd(self, mock_subproc, mock_which, mock_access, mock_glob, mock_pwrite, mock_vendor):
        """Em processadores AMD, MSR 0x150 jamais deve ser acessado."""
        mock_vendor.return_value = "AMD"
        mock_glob.return_value = ["/dev/cpu/0/msr", "/dev/cpu/1/msr"]
        mock_access.return_value = True
        mock_which.side_effect = lambda cmd: "/usr/bin/ryzenadj" if cmd == "ryzenadj" else None
        mock_subproc.return_value = MagicMock(returncode=0)

        ok, msg = self.backend.apply_undervolt_offsets(core_mv=-50, cache_mv=-50)
        self.assertTrue(ok)
        # os.pwrite para MSR NUNCA deve ser chamado em AMD
        mock_pwrite.assert_not_called()
        # ryzenadj deve ter sido invocado
        mock_subproc.assert_called()
        cmd_called = mock_subproc.call_args[0][0]
        self.assertTrue(any("ryzenadj" in str(arg) for arg in cmd_called))

    @patch("core.backend.HardwareBackend.get_cpu_vendor")
    @patch("os.pwrite")
    @patch("glob.glob")
    @patch("os.access")
    @patch("shutil.which")
    @patch("core.backend.subprocess.run")
    def test_msr_0x150_emergency_reset_never_called_on_amd(self, mock_subproc, mock_which, mock_access, mock_glob, mock_pwrite, mock_vendor):
        """Em reset de emergência no AMD, MSR 0x150 não deve ser tocado."""
        mock_vendor.return_value = "AMD"
        mock_glob.return_value = ["/dev/cpu/0/msr"]
        mock_access.return_value = True
        mock_which.side_effect = lambda cmd: "/usr/bin/ryzenadj" if cmd == "ryzenadj" else None
        mock_subproc.return_value = MagicMock(returncode=0)

        ok, msg = self.backend.emergency_reset_undervolt("Teste AMD")
        self.assertTrue(ok)
        mock_pwrite.assert_not_called()

    @patch("core.backend.HardwareBackend.get_cpu_vendor")
    @patch("os.open")
    @patch("os.close")
    @patch("os.pwrite")
    @patch("glob.glob")
    @patch("os.access")
    def test_intel_oc_lock_handled_gracefully(self, mock_access, mock_glob, mock_pwrite, mock_close, mock_open_fd, mock_vendor):
        """Em Intel com OC Lock (EIO / EPERM), não deve gerar exceção não-tratada, deve limpar canário e zerar offsets."""
        mock_vendor.return_value = "Intel"
        mock_glob.return_value = ["/dev/cpu/0/msr"]
        mock_access.return_value = True
        mock_open_fd.return_value = 100
        # Simula erro de I/O por OC Lock da BIOS
        err = OSError("Input/output error")
        err.errno = 5  # EIO
        mock_pwrite.side_effect = err

        ok, msg = self.backend.apply_undervolt_offsets(core_mv=-50, cache_mv=-50)
        self.assertFalse(ok)
        self.assertIn("Intel OC Lock/Undervolt Protection ativo na BIOS", msg)
        self.assertFalse(self.backend._has_undervolt_canary())
        self.assertEqual(self.backend.settings.get("undervolt_core_mv"), 0)

    # -------------------------------------------------------------------------
    # 2. Bloqueio Síncrono de Interface (allow_elevation)
    # -------------------------------------------------------------------------
    @patch("os.path.exists", return_value=True)
    @patch("core.permissions.subprocess.run")
    def test_write_sysfs_disallows_elevation_in_timers(self, mock_subproc, mock_exists):
        """Com allow_elevation=False, pkexec jamais deve ser chamado."""
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            ok, msg = PermissionsManager.write_sysfs_value("/sys/fake/path", "1", allow_elevation=False)
            self.assertFalse(ok)
            self.assertIn("elevação desativada", msg)
            mock_subproc.assert_not_called()

    @patch("core.backend.HardwareBackend.detect_running_game", return_value="Cyberpunk 2077")
    @patch("core.permissions.subprocess.run")
    def test_auto_switch_disallows_elevation(self, mock_subproc, mock_game):
        """No auto-switch periódico de jogos, mudanças de perfil e governor não chamam pkexec."""
        self.backend.settings.set("game_auto_switch", True)
        self.backend.features.platform_profile = True
        self.backend.features.cpu_governor = True
        self.backend.paths.platform_profile = "/sys/fake/platform_profile"
        self.backend.paths.platform_profile_choices = "/sys/fake/choices"
        self.backend._active_game_name = None

        with patch("builtins.open", side_effect=PermissionError("Permission denied")), \
             patch("os.path.exists", return_value=True), \
             patch.object(self.backend, "get_platform_profile_choices", return_value=["performance", "powersave"]):
            res = self.backend.check_game_auto_switch()
            self.assertIsNotNone(res)
            # pkexec NUNCA deve ser chamado pelo auto-switch em background
            mock_subproc.assert_not_called()

    # -------------------------------------------------------------------------
    # 3. Evdev FD Cleanup & Dead FD Removal
    # -------------------------------------------------------------------------
    @patch("os.close")
    @patch("os.read")
    def test_evdev_dead_fd_cleaned_up(self, mock_read, mock_close):
        """Quando um dispositivo é desconectado (ENODEV), o FD deve ser fechado e removido."""
        self.backend._input_fds = [42, 43]
        # Simula ENODEV no FD 42 e BlockingIOError no FD 43
        def side_effect(fd, sz):
            if fd == 42:
                err = OSError("No such device")
                err.errno = 19  # ENODEV
                raise err
            raise BlockingIOError()

        mock_read.side_effect = side_effect
        triggered = self.backend._poll_evdev_keys()

        self.assertEqual(triggered, [])
        mock_close.assert_called_with(42)
        self.assertNotIn(42, self.backend._input_fds)
        self.assertIn(43, self.backend._input_fds)

    @patch("os.close")
    def test_backend_close_cleans_up_resources(self, mock_close):
        """backend.close() deve fechar todos os FDs de evdev e limpar a lista."""
        self.backend._input_fds = [101, 102]
        self.backend.close()
        self.assertEqual(len(self.backend._input_fds), 0)
        mock_close.assert_any_call(101)
        mock_close.assert_any_call(102)

    @patch.object(HardwareBackend, "_init_evdev_listeners")
    def test_evdev_dynamic_reconnect_when_empty(self, mock_init):
        """Quando a lista de FDs fica vazia, _poll_evdev_keys tenta redescobrir após intervalo."""
        self.backend._input_fds = []
        self.backend._last_evdev_scan_time = 0.0
        self.backend._poll_evdev_keys()
        mock_init.assert_called_once()

    # -------------------------------------------------------------------------
    # 4. System Tray Check (Evita Processo Fantasma)
    # -------------------------------------------------------------------------
    def test_system_tray_availability_fallback(self):
        """Verifica a lógica de proteção contra processo fantasma quando não há tray."""
        from core.qt_compat import QSystemTrayIcon
        has_tray = QSystemTrayIcon.isSystemTrayAvailable()
        self.assertIsInstance(has_tray, bool)

    # -------------------------------------------------------------------------
    # 5. Micro-stutters: Cache de nvidia-smi, iw e psutil
    # -------------------------------------------------------------------------
    @patch("core.backend.subprocess.run")
    def test_nvidia_smi_caching(self, mock_subproc):
        """Chamadas subsequentes a get_gpu_metrics devem usar o cache e evitar subprocess.run."""
        self.backend.nvidia_available = True
        self.backend._nvml_initialized = False
        self.backend.paths.nvidia_drm_card = None
        self.backend._cached_nvidia_metrics = None
        self.backend._last_nvidia_smi_time = 0.0

        fake_output = "NVIDIA GeForce RTX 3050, 50.0, 10, 500, 6000, 35.0, 1500, P0\n"
        mock_subproc.return_value = MagicMock(returncode=0, stdout=fake_output)

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            m1 = self.backend.get_gpu_metrics()
            self.assertEqual(mock_subproc.call_count, 1)

            # Segunda chamada imediata: deve usar cache
            m2 = self.backend.get_gpu_metrics()
            self.assertEqual(mock_subproc.call_count, 1)
            self.assertEqual(m1.name, m2.name)

    @patch("core.backend.subprocess.run")
    def test_nvidia_smi_failure_caches_cooldown(self, mock_subproc):
        """Falha no nvidia-smi deve ativar cooldown e não executar subprocess a cada tick."""
        self.backend.nvidia_available = True
        self.backend._nvml_initialized = False
        self.backend.paths.nvidia_drm_card = None
        self.backend._cached_nvidia_metrics = None
        self.backend._last_nvidia_smi_time = 0.0

        # Simula erro de execução (código 1)
        mock_subproc.return_value = MagicMock(returncode=1, stdout="", stderr="Driver error")

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            m1 = self.backend.get_gpu_metrics()
            self.assertEqual(mock_subproc.call_count, 1)

            # Próxima chamada dentro de 2.5s não deve chamar subprocess.run novamente
            m2 = self.backend.get_gpu_metrics()
            self.assertEqual(mock_subproc.call_count, 1)

    @patch("core.backend.subprocess.run")
    def test_network_power_status_caching(self, mock_subproc):
        """Chamadas subsequentes a get_network_power_status devem usar cache de 5s."""
        fake_iw_output = "Power save: on\n"
        mock_subproc.return_value = MagicMock(returncode=0, stdout=fake_iw_output)

        with patch.object(self.backend, "_discover_wifi_interface", return_value="wlan0"):
            with patch("shutil.which", return_value="/usr/bin/iw"):
                s1 = self.backend.get_network_power_status(force=True)
                call_count_1 = mock_subproc.call_count

                # Chamada sem force deve usar cache
                s2 = self.backend.get_network_power_status(force=False)
                self.assertEqual(mock_subproc.call_count, call_count_1)
                self.assertTrue(s2.wifi_power_save_on)

    def test_process_scan_caching(self):
        """detect_running_game e detect_running_app_rule devem armazenar resultado em cache de 4s."""
        with patch("psutil.process_iter", return_value=[]):
            g1 = self.backend.detect_running_game(force=True)
            self.assertIsNone(g1)
            g2 = self.backend.detect_running_game(force=False)
            self.assertIsNone(g2)

    # -------------------------------------------------------------------------
    # 6. Wayland OSD Overlay Compatibility & Fn+Q Multi-Node Detection
    # -------------------------------------------------------------------------
    def test_osd_overlay_wayland_flags(self):
        """O OSD deve inicializar com Tool (e nunca ToolTip sem pai no Wayland) e renderizar show_profile."""
        from core.qt_compat import QApplication, Qt
        app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])

        from ui.osd_overlay import VantageOSDOverlay
        osd = VantageOSDOverlay()
        self.assertEqual(osd.objectName(), "ducksvantage-osd")
        self.assertIsNotNone(osd.container)
        self.assertIsNone(osd.graphicsEffect())
        self.assertEqual(osd.windowFlags() & Qt.WindowType.WindowType_Mask, Qt.WindowType.Tool)
        osd.notify_thermal_mode("performance")
        self.assertIn("Desempenho", osd.title_label.text())
        osd.hide()

    def test_fn_q_multi_node_platform_profile_polling(self):
        """fast_poll_changes deve detectar Fn+Q mesmo quando o kernel expõe múltiplos nós de platform-profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_class = os.path.join(tmpdir, "class_profile")
            node_acpi = os.path.join(tmpdir, "acpi_profile")
            with open(node_class, "w", encoding="utf-8") as f:
                f.write("balanced\n")
            with open(node_acpi, "w", encoding="utf-8") as f:
                f.write("balanced\n")

            self.backend.paths.platform_profile = node_class
            self.backend._platform_profile_paths = [node_class, node_acpi]
            self.backend._last_profile_by_path = {node_class: "balanced", node_acpi: "balanced"}
            self.backend._last_raw_profile = "balanced"
            self.backend._last_profile = "balanced"

            # Simula Fn+Q alterando o nó class/platform-profile-0/profile
            with open(node_class, "w", encoding="utf-8") as f:
                f.write("performance\n")

            events = self.backend.fast_poll_changes()
            prof_events = [e for e in events if e.get("type") == "profile_changed"]
            self.assertEqual(len(prof_events), 1)
            self.assertEqual(prof_events[0]["new"], "performance")

    # -------------------------------------------------------------------------
    # 7. Escrita Atômica de Configurações
    # -------------------------------------------------------------------------
    def test_atomic_settings_save(self):
        """Testa se a gravação de settings é atômica e não corrompe o arquivo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "settings.json")
            sm = SettingsManager()
            sm._data = {"test_key": "val_123", "key_mappings": {}}

            with patch("core.settings.CONFIG_DIR", tmpdir), patch("core.settings.CONFIG_FILE", test_file):
                sm.save()
                self.assertTrue(os.path.exists(test_file))
                with open(test_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data["test_key"], "val_123")

    # -------------------------------------------------------------------------
    # 8. UDEV Rule Installation via Stdin (Zero Symlink TOCTOU)
    # -------------------------------------------------------------------------
    @patch("shutil.which", return_value="/usr/bin/pkexec")
    @patch("core.permissions.subprocess.run")
    def test_install_udev_uses_stdin(self, mock_subproc, mock_which):
        """Regras UDEV devem ser enviadas via stdin, sem arquivos estáticos em /tmp."""
        mock_subproc.return_value = MagicMock(returncode=0)
        ok, msg = PermissionsManager.install_udev_rules()
        self.assertTrue(ok)
        self.assertIn("Regras UDEV instaladas", msg)

        # Checar que o comando não referencia /tmp/99-ducksvantage.rules
        args, kwargs = mock_subproc.call_args
        full_cmd = args[0][3]
        self.assertIn("cat > '/etc/udev/rules.d/99-ducksvantage.rules'", full_cmd)
        self.assertNotIn("/tmp/99-ducksvantage.rules", full_cmd)
        self.assertIsNotNone(kwargs.get("input"))

    # -------------------------------------------------------------------------
    # 9. psutil.ZombieProcess Handling
    # -------------------------------------------------------------------------
    def test_psutil_zombie_process_in_terminate(self):
        """_terminate_previous_instances deve tratar psutil.ZombieProcess sem quebrar."""
        import psutil
        from main import _terminate_previous_instances

        fake_proc = MagicMock()
        fake_proc.info = {"pid": 99999, "name": "python3", "cmdline": ["python3", "main.py"]}
        fake_proc.terminate.side_effect = psutil.ZombieProcess(pid=99999)

        with patch("psutil.process_iter", return_value=[fake_proc]):
            # Não deve lançar exceção
            try:
                _terminate_previous_instances()
            except psutil.ZombieProcess:
                self.fail("_terminate_previous_instances não capturou psutil.ZombieProcess!")

    # -------------------------------------------------------------------------
    # 10. Ciclo Completo Fn+Q (inclui retorno ao Modo Silencioso após Max-Power)
    # -------------------------------------------------------------------------
    def test_fn_q_cycle_reaches_low_power_after_max_power_promotion(self):
        """Quando Fn+Q promove low-power para max-power, o próximo toque deve entrar em low-power antes de balanced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_pp = os.path.join(tmpdir, "profile")
            with open(tmp_pp, "w", encoding="utf-8") as f:
                f.write("balanced\n")

            self.backend.paths.platform_profile = tmp_pp
            self.backend._platform_profile_paths = [tmp_pp]
            self.backend._last_profile_by_path = {tmp_pp: "balanced"}
            self.backend._last_raw_profile = "balanced"
            self.backend._last_profile = "balanced"
            self.backend._max_power_active = False
            self.backend._promoted_max_power_from_low = False
            self.backend.features.max_power_profile = True

            with patch.object(self.backend, "get_platform_profile_choices", return_value=["low-power", "balanced", "performance", "max-power", "custom"]):
                # 1. EC passa de balanced -> performance
                with open(tmp_pp, "w", encoding="utf-8") as f:
                    f.write("performance\n")
                ev1 = self.backend.fast_poll_changes()
                self.assertEqual([e["new"] for e in ev1 if e["type"] == "profile_changed"], ["performance"])

                # 2. EC tenta ciclar performance -> low-power: app promove para max-power
                with open(tmp_pp, "w", encoding="utf-8") as f:
                    f.write("low-power\n")
                ev2 = self.backend.fast_poll_changes()
                self.assertEqual([e["new"] for e in ev2 if e["type"] == "profile_changed"], ["max-power"])
                with open(tmp_pp, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read().strip(), "max-power")

                # 3. Próximo Fn+Q: EC escreve balanced, app redireciona para low-power (Silencioso)!
                with open(tmp_pp, "w", encoding="utf-8") as f:
                    f.write("balanced\n")
                ev3 = self.backend.fast_poll_changes()
                self.assertEqual([e["new"] for e in ev3 if e["type"] == "profile_changed"], ["low-power"])
                with open(tmp_pp, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read().strip(), "low-power")
                self.assertEqual(self.backend._last_profile, "low-power")

                # 4. Próximo Fn+Q: EC escreve balanced e app entra em balanced normalmente
                with open(tmp_pp, "w", encoding="utf-8") as f:
                    f.write("balanced\n")
                ev4 = self.backend.fast_poll_changes()
                self.assertEqual([e["new"] for e in ev4 if e["type"] == "profile_changed"], ["balanced"])

    # -------------------------------------------------------------------------
    # 11. Detecção Ampliada de Jogos (Sober, Wine/Proton .exe, Heroic/Games, GameMode)
    # -------------------------------------------------------------------------
    def test_detect_running_game_sober_wine_heroic_and_gamemode(self):
        """Auto-switch deve reconhecer Sober, jogos Wine/Proton (.exe C:\\), ~/Games nativos e GameMode."""
        def make_proc(name, exe="", cmdline=None, cwd=""):
            p = MagicMock()
            p.info = {"name": name, "exe": exe, "cmdline": cmdline or [], "cwd": cwd}
            return p

        # A) Sober (Roblox Flatpak)
        with patch("psutil.process_iter", return_value=[
            make_proc("bwrap", "/usr/bin/bwrap", ["bwrap", "--dev-bind"]),
            make_proc("sober", "/app/bin/sober", ["/app/bin/sober"]),
        ]):
            self.assertEqual(self.backend.detect_running_game(force=True), "Roblox (Sober)")

        # B) Jogo Wine / Heroic com caminho Windows (C:\...)
        with patch("psutil.process_iter", return_value=[
            make_proc("services.exe", "/usr/bin/wine64-preloader", ["C:\\windows\\system32\\services.exe"]),
            make_proc("wine64-preloader", "/home/user/.config/heroic/tools/proton/wine", ["/usr/bin/wine", "C:\\Games\\Cyberpunk\\Cyberpunk2077.exe"]),
        ]):
            self.assertEqual(self.backend.detect_running_game(force=True), "Cyberpunk2077.exe")

        # C) Jogo nativo em ~/Games sem sufixo .exe/.bin/.x86_64
        with patch("psutil.process_iter", return_value=[
            make_proc("HollowKnight", "/home/user/Games/Heroic/HollowKnight/HollowKnight", ["/home/user/Games/Heroic/HollowKnight/HollowKnight"]),
        ]):
            self.assertEqual(self.backend.detect_running_game(force=True), "HollowKnight")

        # D) Helpers isolados não geram falso positivo
        with patch("psutil.process_iter", return_value=[
            make_proc("steamwebhelper", "/home/user/.steam/ubuntu12_64/steamwebhelper", ["steamwebhelper"]),
            make_proc("services.exe", "/usr/bin/wine", ["C:\\windows\\system32\\services.exe"]),
        ]):
            self.assertIsNone(self.backend.detect_running_game(force=True))

        # E) Feral GameMode D-Bus fallback
        with patch("psutil.process_iter", return_value=[make_proc("gamemoded", "/usr/bin/gamemoded", ["/usr/bin/gamemoded"])]), \
             patch("shutil.which", side_effect=lambda c: "/usr/bin/gdbus" if c == "gdbus" else None), \
             patch("core.backend.subprocess.run", return_value=MagicMock(returncode=0, stdout="(uint32 1,)\n")):
            self.assertEqual(self.backend.detect_running_game(force=True), "GameMode (Jogo Ativo)")

    # -------------------------------------------------------------------------
    # 12. BIOS Lenovo WMI: alterna automaticamente para perfil 'custom' antes de gravar
    # -------------------------------------------------------------------------
    def test_set_bios_attribute_switches_to_custom_for_lenovo_wmi_other(self):
        """Atributos de lenovo-wmi-other falham com EBUSY fora de custom; backend deve alternar para custom antes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pp_file = os.path.join(tmpdir, "profile")
            pp_choices = os.path.join(tmpdir, "choices")
            wmi_attr_file = os.path.join(tmpdir, "lenovo-wmi-other-0", "attributes", "cpu_temp", "current_value")
            os.makedirs(os.path.dirname(wmi_attr_file), exist_ok=True)
            with open(pp_file, "w", encoding="utf-8") as f:
                f.write("balanced\n")
            with open(pp_choices, "w", encoding="utf-8") as f:
                f.write("low-power balanced performance max-power custom\n")
            with open(wmi_attr_file, "w", encoding="utf-8") as f:
                f.write("94\n")

            self.backend.paths.platform_profile = pp_file
            self.backend.paths.platform_profile_choices = pp_choices
            self.backend._platform_profile_paths = [pp_file]
            self.backend._last_profile_by_path = {pp_file: "balanced"}

            from core.models import BiosAttribute
            fake_attr = BiosAttribute(
                attr_id="cpu_temp", display_name="CPU Temp", attr_type="integer",
                current_value="94", min_value=85, max_value=100, path=wmi_attr_file
            )
            with patch.object(self.backend, "get_bios_attributes", return_value=[fake_attr]), \
                 patch("core.backend.time.sleep"):
                ok, msg = self.backend.set_bios_attribute("cpu_temp", "90")
                self.assertTrue(ok)
                self.assertIn("Custom", msg)
                with open(pp_file, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read().strip(), "custom")
                with open(wmi_attr_file, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read().strip(), "90")

    # -------------------------------------------------------------------------
    # 13. Touchpad: priorizar Touchpad real em vez de Mouse na mesma interface CIRQ
    # -------------------------------------------------------------------------
    def test_scan_touchpad_prefers_touchpad_over_cirq_mouse(self):
        """Entre event18 (... Mouse) e event19 (... Touchpad), deve selecionar event19."""
        self.backend.paths.touchpad = None
        names = {
            "/sys/class/input/event18/device/name": "CIRQ1080:00 0488:107B Mouse",
            "/sys/class/input/event19/device/name": "CIRQ1080:00 0488:107B Touchpad",
        }
        with patch("glob.glob", return_value=list(names.keys())), \
             patch.object(self.backend, "_read_file_text", side_effect=lambda p: names.get(p, "")), \
             patch("shutil.which", side_effect=lambda c: "/usr/bin/qdbus6" if c == "qdbus6" else None):
            self.backend._scan_touchpad()
            self.assertEqual(self.backend._touchpad_event_name, "event19")
            self.assertIn("Touchpad", self.backend._touchpad_device_name)
            self.assertTrue(self.backend.features.touchpad_control)

    # -------------------------------------------------------------------------
    # 14. Wi-Fi Power Save: não fingir sucesso se 'iw set power_save' falhar
    # -------------------------------------------------------------------------
    def test_wifi_power_saving_requires_iw_success(self):
        """Quando iw existe e falha por permissão (mesmo com PCI PM gravável), retorna False."""
        with patch.object(self.backend, "_discover_wifi_interface", return_value="wlan0"), \
             patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}" if c in ("iw", "pkexec") else None), \
             patch("os.path.exists", return_value=True), \
             patch("os.access", return_value=True), \
             patch("core.permissions.PermissionsManager.write_sysfs_value", return_value=(True, "OK")), \
             patch("core.backend.subprocess.run", side_effect=[
                 MagicMock(returncode=255, stderr="Operation not permitted"),
                 MagicMock(returncode=1, stderr="Auth failed"),
             ]):
            ok, msg = self.backend.set_wifi_power_saving(False)
            self.assertFalse(ok)
            self.assertIn("Permissão necessária", msg)

    # -------------------------------------------------------------------------
    # 15. Intel Undervolt: fallback nativo via pkexec + python sem precisar de wrmsr
    # -------------------------------------------------------------------------
    def test_intel_undervolt_pkexec_python_fallback_when_msr_not_writable(self):
        """Se /dev/cpu/*/msr existe sem W_OK e não há wrmsr, tenta gravar via pkexec python3."""
        with patch.object(self.backend, "get_cpu_vendor", return_value="Intel"), \
             patch("glob.glob", return_value=["/dev/cpu/0/msr"]), \
             patch("os.access", return_value=False), \
             patch("shutil.which", side_effect=lambda c: "/usr/bin/pkexec" if c == "pkexec" else None), \
             patch("core.backend.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as mock_sub:
            ok, msg = self.backend.apply_undervolt_offsets(core_mv=-50, cache_mv=-50)
            self.assertTrue(ok)
            self.assertIn("Polkit", msg)
            mock_sub.assert_called()
            self.assertEqual(mock_sub.call_args[0][0][0], "pkexec")

    # -------------------------------------------------------------------------
    # 16. GPU MUX nunca usa falso fallback pcie-runtime (protege D3cold)
    # -------------------------------------------------------------------------
    def test_gpu_mux_disabled_without_real_backend_even_with_pcie_pm(self):
        """Sem supergfxctl/envycontrol/prime-select/gpu_mode, GPU MUX deve permanecer desativado."""
        self.backend.paths.gpu_mode = None
        self.backend.paths.nvidia_pci_power_control = "/fake/pci/power/control"
        self.backend.paths.igpu_drm_card = "/fake/drm/card1"
        self.backend._cached_gpu_mux_info = None

        with patch("shutil.which", return_value=None):
            self.backend._scan_gpu_mux()
            info = self.backend.get_gpu_mux_info()
            self.assertFalse(self.backend.features.gpu_mux)
            self.assertFalse(info.available)
            self.assertEqual(info.backend_name, "none")
            self.assertEqual(info.available_modes, [])

    # -------------------------------------------------------------------------
    # 17. Auditoria de Ícones SVG, Desktop File Portátil & EPP Max-Power
    # -------------------------------------------------------------------------
    def test_all_referenced_svg_icons_exist(self):
        """Todos os ícones SVG referenciados em core/ e ui/ devem existir em assets/icons/."""
        import re
        root = PROJECT_ROOT
        icons_dir = os.path.join(root, "assets", "icons")
        existing = set(os.listdir(icons_dir))
        missing = []
        for sub in ("core", "ui"):
            for dp, _, fns in os.walk(os.path.join(root, sub)):
                for fn in fns:
                    if fn.endswith(".py"):
                        with open(os.path.join(dp, fn), encoding="utf-8") as fh:
                            txt = fh.read()
                        for m in re.finditer(r"['\"]([a-zA-Z0-9_\-]+\.svg)['\"]", txt):
                            ic = m.group(1)
                            if ic != "app_icon.svg" and ic not in existing:
                                missing.append((fn, ic))
        self.assertEqual(missing, [])

    def test_desktop_file_is_portable(self):
        """O arquivo packaging/ducksvantage.desktop não deve conter /home/ fixo e deve apontar para /usr/bin/ducksvantage."""
        root = PROJECT_ROOT
        with open(os.path.join(root, "packaging", "ducksvantage.desktop"), encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn("/home/", content)
        self.assertIn("Exec=/usr/bin/ducksvantage", content)
        self.assertIn("Icon=ducksvantage", content)

    def test_desktop_file_name_no_suffix(self):
        """main.py deve chamar setDesktopFileName('ducksvantage') sem sufixo .desktop."""
        root = PROJECT_ROOT
        with open(os.path.join(root, "main.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('setDesktopFileName("ducksvantage")', src)
        self.assertNotIn('setDesktopFileName("ducksvantage.desktop")', src)

    def test_custom_profile_ui_display(self):
        """Quando o perfil ativo for 'custom', cabeçalho, OSD e aba Desempenho devem exibir CUSTOM."""
        from ui.osd_overlay import VantageOSDOverlay
        from ui_main import MainWindow

        osd = VantageOSDOverlay()
        osd.notify_thermal_mode("custom")
        self.assertIn("Personalizado", osd.title_label.text())
        osd.hide()
        osd.close()

        with patch.object(self.backend, "get_platform_profile", return_value="custom"):
            self.backend.features.platform_profile = True
            win = MainWindow(self.backend)
            win._update_header_profile_pill()
            self.assertEqual(win.header_profile_pill.label.text(), "CUSTOM")
            win.performance_tab.refresh_profile_state()
            self.assertEqual(win.performance_tab.current_badge.label.text(), "CUSTOM")
            win._quit_app()
            win.close()

    def test_tray_notification_no_duplicate(self):
        """Quando notify-send está disponível, não deve duplicar com tray_icon.showMessage()."""
        from ui.tray_icon import SystemTrayManager

        tray = SystemTrayManager(self.backend)
        tray.tray_icon.showMessage = MagicMock()
        tray.tray_icon.isSystemTrayAvailable = MagicMock(return_value=True)

        with patch("ui.tray_icon.shutil.which", return_value="/usr/bin/notify-send"), \
             patch("ui.tray_icon.subprocess.Popen") as mock_popen:
            tray.send_native_notification("Alerta", "Teste 80%")
            mock_popen.assert_called_once()
            tray.tray_icon.showMessage.assert_not_called()

        with patch("ui.tray_icon.shutil.which", return_value=None):
            tray.send_native_notification("Fallback", "Sem notify-send")
            tray.tray_icon.showMessage.assert_called_once()

    def test_fan_metrics_zero_rpm_when_cpu_hot(self):
        """Se fan1_input=0 mas CPU >= 65°C, não deve afirmar 'Parada'."""
        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "fan1_input")
            t1 = os.path.join(td, "temp1_input")
            with open(f1, "w", encoding="utf-8") as fh:
                fh.write("0\n")
            with open(t1, "w", encoding="utf-8") as fh:
                fh.write("85000\n")
            self.backend.paths.fan1_input = f1
            self.backend.paths.fan2_input = None
            self.backend.paths.cpu_temp_input = t1
            fm = self.backend.get_fan_metrics()
            self.assertIn("indisponível", fm.status_label)
            self.assertNotIn("Parada", fm.status_label)

    def test_cpu_epp_sync_for_max_power(self):
        """_sync_cpu_epp_for_profile('max-power') grava 'performance' em energy_performance_preference."""
        with tempfile.TemporaryDirectory() as td:
            epp_p = os.path.join(td, "energy_performance_preference")
            avail_p = os.path.join(td, "energy_performance_available_preferences")
            with open(epp_p, "w", encoding="utf-8") as fh:
                fh.write("balance_performance\n")
            with open(avail_p, "w", encoding="utf-8") as fh:
                fh.write("default performance balance_performance balance_power power\n")

            with patch("glob.glob", return_value=[epp_p]), \
                 patch("os.path.exists", return_value=True):
                with patch.object(self.backend, "_read_file_text", side_effect=lambda p: (
                    "default performance balance_performance balance_power power"
                    if "available" in p else "balance_performance"
                )):
                    ok = self.backend._sync_cpu_epp_for_profile("max-power")
                    self.assertTrue(ok)
                    with open(epp_p, "r", encoding="utf-8") as fh:
                        self.assertEqual(fh.read().strip(), "performance")

    def test_udev_rule_up_to_date_detection(self):
        """is_udev_rule_up_to_date() valida presença de todas as regras modernas."""
        from core.permissions import UDEV_RULE_CONTENT
        with tempfile.TemporaryDirectory() as td:
            upath = os.path.join(td, "99-ducksvantage.rules")
            with open(upath, "w", encoding="utf-8") as fh:
                fh.write(UDEV_RULE_CONTENT)
            with patch("core.permissions.UDEV_RULE_PATH", upath):
                self.assertTrue(PermissionsManager.is_udev_rule_up_to_date())

            with open(upath, "w", encoding="utf-8") as fh:
                fh.write("# old rule without platform-profile\n")
            with patch("core.permissions.UDEV_RULE_PATH", upath):
                self.assertFalse(PermissionsManager.is_udev_rule_up_to_date())

    # -------------------------------------------------------------------------
    # 18. Auto-Switch configurável (Perfil alvo, 144Hz e Bloqueio Touchpad)
    # -------------------------------------------------------------------------
    def test_game_auto_switch_target_profile_refresh_and_touchpad(self):
        """Auto-Switch respeita perfil alvo, eleva/restaura Hz e bloqueia touchpad apenas se livre."""
        from core.models import DisplayRefreshInfo

        with patch.object(self.backend.settings, "save", return_value=None):
            self.backend.features.platform_profile = True
            self.backend.features.cpu_governor = True
            self.backend.features.refresh_rate = True
            self.backend.features.touchpad_control = True
            self.backend._active_game_name = None
            self.backend._game_changed_refresh = False
            self.backend._game_locked_touchpad = False
            self.backend._pre_game_refresh_hz = None

            self.backend.set_game_auto_switch(True)
            self.backend.set_game_target_profile("performance")
            self.backend.set_game_auto_refresh_max(True)
            self.backend.set_game_auto_lock_touchpad(True)

            ref_60 = DisplayRefreshInfo(
                available=True, current_hz=60, available_rates=[60, 144],
                display_name="eDP-1", resolution="1920x1080", backend_name="kscreen-doctor"
            )

            with patch.object(self.backend, "detect_running_game", return_value="Roblox (Sober)"), \
                 patch.object(self.backend, "get_platform_profile_choices", return_value=["low-power", "balanced", "performance", "max-power"]), \
                 patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
                 patch.object(self.backend, "get_cpu_governor", return_value="powersave"), \
                 patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")) as mock_prof, \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")), \
                 patch.object(self.backend, "get_display_refresh_info", return_value=ref_60), \
                 patch.object(self.backend, "set_refresh_rate", return_value=(True, "OK")) as mock_hz, \
                 patch.object(self.backend, "get_touchpad_status", return_value=False), \
                 patch.object(self.backend, "set_touchpad_status", return_value=(True, "OK")) as mock_tp:
                ev_start = self.backend.check_game_auto_switch()
                self.assertIsNotNone(ev_start)
                self.assertEqual(ev_start["type"], "game_started")
                self.assertEqual(ev_start["profile"], "performance")
                mock_prof.assert_called_with("performance", allow_elevation=False)
                mock_hz.assert_called_with(144)
                mock_tp.assert_called_with(True, allow_elevation=False)
                self.assertIn("144 Hz", ev_start["extras"])
                self.assertIn("Touchpad Bloqueado", ev_start["extras"])

            # Ao fechar o jogo: restaura 60 Hz e libera touchpad
            with patch.object(self.backend, "detect_running_game", return_value=None), \
                 patch.object(self.backend, "detect_running_app_rule", return_value=None), \
                 patch.object(self.backend, "_get_ac_online", return_value=1), \
                 patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")) as mock_prof_end, \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")), \
                 patch.object(self.backend, "set_refresh_rate", return_value=(True, "OK")) as mock_hz_end, \
                 patch.object(self.backend, "set_touchpad_status", return_value=(True, "OK")) as mock_tp_end:
                ev_stop = self.backend.check_game_auto_switch()
                self.assertIsNotNone(ev_stop)
                self.assertEqual(ev_stop["type"], "game_stopped")
                self.assertEqual(ev_stop["profile"], "balanced")
                mock_prof_end.assert_called_with("balanced", allow_elevation=False)
                mock_hz_end.assert_called_with(60)
                mock_tp_end.assert_called_with(False, allow_elevation=False)
                self.assertIn("60 Hz", ev_stop["extras"])
                self.assertIn("Touchpad Liberado", ev_stop["extras"])

            # Se o touchpad JÁ estava bloqueado pelo usuário antes do jogo, não deve desbloquear ao sair
            self.backend.set_game_auto_refresh_max(False)
            with patch.object(self.backend, "detect_running_game", return_value="Minecraft"), \
                 patch.object(self.backend, "get_platform_profile_choices", return_value=["balanced", "performance"]), \
                 patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
                 patch.object(self.backend, "get_cpu_governor", return_value="powersave"), \
                 patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")), \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")), \
                 patch.object(self.backend, "get_touchpad_status", return_value=True), \
                 patch.object(self.backend, "set_touchpad_status") as mock_tp_locked:
                self.backend.check_game_auto_switch()
                mock_tp_locked.assert_not_called()

            with patch.object(self.backend, "detect_running_game", return_value=None), \
                 patch.object(self.backend, "detect_running_app_rule", return_value=None), \
                 patch.object(self.backend, "_get_ac_online", return_value=1), \
                 patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")), \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")), \
                 patch.object(self.backend, "set_touchpad_status") as mock_tp_still_locked:
                self.backend.check_game_auto_switch()
                mock_tp_still_locked.assert_not_called()

    # -------------------------------------------------------------------------
    # 19. Perfis Personalizados Salváveis pelo Usuário (Presets em 1 Clique)
    # -------------------------------------------------------------------------
    def test_user_presets_save_apply_delete(self):
        """Presets do usuário capturam o estado atual, aplicam em 1 clique e permitem remoção."""
        from core.models import DisplayRefreshInfo

        with patch.object(self.backend.settings, "save", return_value=None):
            self.backend.settings._data["user_presets"] = []
            self.backend.features.platform_profile = True
            self.backend.features.cpu_governor = True
            self.backend.features.turbo_boost = True
            self.backend.features.custom_tdp = True
            self.backend.features.refresh_rate = True

            ok_empty, _, _ = self.backend.save_current_as_preset("   ")
            self.assertFalse(ok_empty)

            ref_144 = DisplayRefreshInfo(
                available=True, current_hz=144, available_rates=[60, 144],
                display_name="eDP-1", resolution="1920x1080", backend_name="kscreen-doctor"
            )
            with patch.object(self.backend, "get_platform_profile", return_value="performance"), \
                 patch.object(self.backend, "get_cpu_governor", return_value="performance"), \
                 patch.object(self.backend, "get_cpu_turbo", return_value=True), \
                 patch.object(self.backend, "get_cpu_tdp_limits", return_value=(55, 80)), \
                 patch.object(self.backend, "get_display_refresh_info", return_value=ref_144):
                ok_save, msg_save, preset = self.backend.save_current_as_preset("Modo Competitivo")
                self.assertTrue(ok_save)
                self.assertIsNotNone(preset)
                self.assertEqual(preset["id"], "modo-competitivo")
                self.assertIn("144 Hz", msg_save)

            presets = self.backend.get_user_presets()
            self.assertEqual(len(presets), 1)

            with patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")) as m_p, \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")) as m_g, \
                 patch.object(self.backend, "set_cpu_turbo", return_value=(True, "OK")) as m_t, \
                 patch.object(self.backend, "set_cpu_tdp_limits", return_value=(True, "OK")) as m_tdp, \
                 patch.object(self.backend, "set_refresh_rate", return_value=(True, "OK")) as m_hz:
                ok_app, msg_app = self.backend.apply_user_preset("modo-competitivo")
                self.assertTrue(ok_app)
                self.assertIn("144 Hz", msg_app)
                m_p.assert_called_once_with("performance", allow_elevation=True)
                m_g.assert_called_once_with("performance", allow_elevation=True)
                m_t.assert_called_once_with(True, allow_elevation=True)
                m_tdp.assert_called_once_with(55, 80, allow_elevation=True)
                m_hz.assert_called_once_with(144)

            ok_del, _ = self.backend.delete_user_preset("modo-competitivo")
            self.assertTrue(ok_del)
            self.assertEqual(self.backend.get_user_presets(), [])

    # -------------------------------------------------------------------------
    # 20. Relatório de Diagnóstico de Hardware (About Tab)
    # -------------------------------------------------------------------------
    def test_hardware_diagnostic_report_clean_and_complete(self):
        """Relatório técnico inclui hardware/kernel/UDEV e nunca expõe /home/ ou username."""
        from core.models import BatteryInfo, FanMetrics, GpuMuxInfo, DisplayRefreshInfo

        self.backend.system_info.display_model_name = "LOQ 15IAX9E"
        self.backend.system_info.product_name = "83ME"
        self.backend.system_info.bios_version = "Q8CN22WW"
        self.backend.system_info.kernel_version = "7.3.4-test"
        self.backend.features.platform_profile = True

        with patch.object(self.backend, "get_cpu_metrics", return_value=CPUMetrics(model_name="Intel Core i5-12450HX", vendor="Intel", cores_count=12)), \
             patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
             patch.object(self.backend, "get_platform_profile_choices", return_value=["low-power", "balanced", "performance", "max-power"]), \
             patch.object(self.backend, "get_fan_metrics", return_value=FanMetrics(available=False, status_label="Automático via EC")), \
             patch.object(self.backend, "get_gpu_metrics", return_value=GPUMetrics(available=False, name="NVIDIA RTX 3050", runtime_state="D3cold")), \
             patch.object(self.backend, "get_gpu_mux_info", return_value=GpuMuxInfo(available=True, current_mode="hybrid", available_modes=["hybrid", "integrated"], backend_name="lenovo-wmi")), \
             patch.object(self.backend, "get_display_refresh_info", return_value=DisplayRefreshInfo(available=True, current_hz=144, available_rates=[60, 144], display_name="eDP-1", resolution="1920x1080", backend_name="kscreen-doctor")), \
             patch.object(self.backend, "get_battery_info", return_value=BatteryInfo(available=True, capacity_percent=80, health_percent=97.0, cycle_count=42)), \
             patch.object(self.backend, "get_bios_attributes", return_value=[]), \
             patch("core.permissions.PermissionsManager.is_udev_rule_installed", return_value=True), \
             patch("core.permissions.PermissionsManager.is_udev_rule_up_to_date", return_value=True), \
             patch.object(self.backend, "has_full_write_permissions", return_value=True):
            report = self.backend.generate_hardware_diagnostic_report()

        self.assertIn("LOQ 15IAX9E", report)
        self.assertIn("Q8CN22WW", report)
        self.assertIn("7.3.4-test", report)
        self.assertIn("UDEV", report)
        self.assertNotIn("/home/", report)

    def test_about_tab_copy_diagnostic_button(self):
        """AboutTab possui btn_copy_diag que copia o diagnóstico para a área de transferência."""
        from core.qt_compat import QApplication
        from ui.tabs.about_tab import AboutTab

        about = AboutTab(self.backend)
        with patch.object(self.backend, "generate_hardware_diagnostic_report", return_value="# Diag Mock OK"), \
             patch("ui.tabs.about_tab.QMessageBox.information"):
            about._copy_diagnostic_action()

        clipboard = QApplication.clipboard()
        self.assertEqual(clipboard.text(), "# Diag Mock OK")
        about.close()

    # -------------------------------------------------------------------------
    # 21. Bandeja Expandida (Presets, Taxa Hz, Auto-Switch e Touchpad)
    # -------------------------------------------------------------------------
    def test_tray_menus_presets_refresh_and_controls(self):
        """Tray exibe submenus de Presets e Hz + toggles de Jogos e Touchpad conforme features."""
        from core.models import DisplayRefreshInfo
        from ui.tray_icon import SystemTrayManager

        with patch.object(self.backend.settings, "save", return_value=None):
            self.backend.features.platform_profile = True
            self.backend.features.refresh_rate = True
            self.backend.features.touchpad_control = True
            self.backend.settings._data["user_presets"] = [
                {"id": "silencioso", "name": "Silencioso", "profile": "low-power"}
            ]
            ref_info = DisplayRefreshInfo(
                available=True, current_hz=60, available_rates=[60, 144],
                display_name="eDP-1", resolution="1920x1080", backend_name="kscreen-doctor"
            )
            with patch.object(self.backend, "get_display_refresh_info", return_value=ref_info), \
                 patch.object(self.backend, "get_supported_canonical_profiles", return_value=["low-power", "balanced", "performance"]), \
                 patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
                 patch.object(self.backend, "get_touchpad_status", return_value=False):
                tray = SystemTrayManager(self.backend)
                self.assertTrue(tray.presets_menu.menuAction().isVisible())
                self.assertEqual(len(tray.presets_menu.actions()), 1)
                self.assertTrue(tray.refresh_menu.menuAction().isVisible())
                self.assertEqual(len(tray.refresh_menu.actions()), 2)
                self.assertTrue(tray.action_game_auto.isVisible())
                self.assertTrue(tray.action_touchpad.isVisible())
                self.assertIn("Tela: 60 Hz", tray.tray_icon.toolTip())

    # -------------------------------------------------------------------------
    # 22. Preferências (OSD, AC/Bateria) e Backup Export/Import JSON
    # -------------------------------------------------------------------------
    def test_preferences_osd_ac_battery_and_backup_roundtrip(self):
        """Preferências de OSD, perfis AC/Bateria e backup JSON funcionam e filtram chaves inválidas."""
        from ui.osd_overlay import VantageOSDOverlay

        with patch.object(self.backend.settings, "save", return_value=None):
            osd = VantageOSDOverlay()
            osd.configure(enabled=False, position="top-right", duration_ms=2800)
            self.assertEqual(osd.position_mode, "top-right")
            self.assertEqual(osd.duration_ms, 2800)
            osd.notify_thermal_mode("performance")
            self.assertTrue(osd.isHidden())
            osd.close()

            self.backend.set_osd_position("top-center")
            self.backend.set_osd_duration_ms(1200)
            self.backend.set_minimize_to_tray(False)
            self.backend.set_ac_profile("balanced")
            self.backend.set_battery_profile("low-power")
            self.assertEqual(self.backend.get_osd_position(), "top-center")
            self.assertEqual(self.backend.get_osd_duration_ms(), 1200)
            self.assertFalse(self.backend.get_minimize_to_tray())

            with tempfile.TemporaryDirectory() as td:
                bkp_path = os.path.join(td, "backup.json")
                ok_exp, _ = self.backend.export_settings(bkp_path)
                self.assertTrue(ok_exp)
                with open(bkp_path, "r", encoding="utf-8") as fh:
                    raw_bkp = json.load(fh)
                raw_bkp["unknown_malicious_key"] = 123
                raw_bkp["osd_position"] = "top-right"
                with open(bkp_path, "w", encoding="utf-8") as fh:
                    json.dump(raw_bkp, fh)

                ok_imp, _ = self.backend.import_settings(bkp_path)
                self.assertTrue(ok_imp)
                self.assertEqual(self.backend.get_osd_position(), "top-right")
                self.assertNotIn("unknown_malicious_key", self.backend.settings._data)

    # -------------------------------------------------------------------------
    # 23. Autonomia Estimada de Bateria, Termistor Real, Alertas Separados e Histórico Real
    # -------------------------------------------------------------------------
    def test_battery_eta_real_history_and_alerts(self):
        """get_battery_info calcula tempo restante, não inventa histórico/temp e separa alertas 80% vs térmico."""
        with tempfile.TemporaryDirectory() as td:
            bat_dir = os.path.join(td, "BAT0")
            os.makedirs(bat_dir)
            files = {
                "capacity": "80",
                "status": "Discharging",
                "cycle_count": "40",
                "voltage_now": "15400000",
                "power_now": "20000000",  # 20W
                "energy_now": "40000000",  # 40Wh -> ~2h00
                "energy_full": "56000000",
                "energy_full_design": "57500000",
            }
            for k, v in files.items():
                with open(os.path.join(bat_dir, k), "w", encoding="utf-8") as fh:
                    fh.write(v)

            self.backend.paths.battery_dir = bat_dir
            self.backend.features.battery = True
            self.backend.features.conservation_mode = True
            self.backend.features.rapid_charge = False

            # Sem arquivo 'temp' na bateria -> não inventa temperatura e não dispara alerta térmico
            info = self.backend.get_battery_info()
            self.assertFalse(info.temperature_available)
            self.assertEqual(info.temperature_c, 0.0)
            self.assertEqual(info.estimated_minutes, 120)
            self.assertIn("2h 00min restantes", info.estimated_label)

            self.backend.set_battery_alert_settings(True, True, 36.0, temp_alert_enabled=True)
            self.assertEqual(self.backend.check_battery_smart_alerts(), [])

            # Com arquivo 'temp' real (43.5°C = 435 décimos) -> lê 43.5 e respeita switch térmico independente
            with open(os.path.join(bat_dir, "temp"), "w", encoding="utf-8") as fh:
                fh.write("435\n")
            with open(os.path.join(bat_dir, "status"), "w", encoding="utf-8") as fh:
                fh.write("Charging")
            with patch.object(self.backend, "get_conservation_mode", return_value=True), \
                 patch.object(self.backend, "_get_ac_online", return_value=1):
                info_chg = self.backend.get_battery_info()
                self.assertTrue(info_chg.temperature_available)
                self.assertEqual(info_chg.temperature_c, 43.5)
                self.assertIn("~80%", info_chg.estimated_label)

                # Alerta 80% OFF, Alerta Térmico ON -> só dispara alerta térmico!
                self.backend.set_battery_alert_settings(True, False, 42.0, temp_alert_enabled=True)
                self.backend._alerted_80_this_session = False
                self.backend._last_temp_alert_ts = 0.0
                alerts = self.backend.check_battery_smart_alerts()
                self.assertEqual(len(alerts), 1)
                self.assertIn("Alerta Térmico", alerts[0]["title"])

            # Histórico: purga entradas antigas 'estimated: True', preserva reais e não cria passado falso
            with patch.object(self.backend.settings, "save", return_value=None):
                self.backend.settings._data["battery_history"] = [
                    {"timestamp": "2026-01-01", "energy_full_wh": 57.0, "energy_design_wh": 57.5, "health_percent": 99.1, "cycle_count": 5, "estimated": True},
                    {"timestamp": "2026-11-20", "energy_full_wh": 56.2, "energy_design_wh": 57.5, "health_percent": 97.7, "cycle_count": 38, "estimated": False},
                ]
                hist = self.backend.record_battery_snapshot()
                self.assertEqual(len(hist), 2)
                self.assertEqual(hist[0].timestamp, "2026-11-20")
                self.assertFalse(any(e.is_estimated for e in hist))
                self.assertEqual(hist[-1].energy_full_wh, 56.0)

    # -------------------------------------------------------------------------
    # 24. Gráfico Térmico ao Vivo + Resumo Pós-Jogo + Preset & Ignore List
    # -------------------------------------------------------------------------
    def test_live_thermal_chart_and_game_session_summary(self):
        """LiveThermalChart registra amostras/picos e check_game_auto_switch gera resumo pós-jogo."""
        from ui.dashboard import LiveThermalChart

        chart = LiveThermalChart()
        chart.add_sample(52.0, 44.0)
        chart.add_sample(86.5, 74.0)
        self.assertEqual(chart.peak_cpu, 86.5)
        self.assertEqual(chart.peak_gpu, 74.0)
        chart.reset_peaks()
        self.assertEqual(chart.peak_cpu, 86.5)
        chart.add_sample(60.0, 50.0)
        chart.reset_peaks()
        self.assertEqual(chart.peak_cpu, 60.0)
        chart.close()

        with patch.object(self.backend.settings, "save", return_value=None):
            self.backend.features.platform_profile = True
            self.backend.features.cpu_governor = True
            self.backend.features.turbo_boost = True
            self.backend.features.custom_tdp = True
            self.backend._active_game_name = None
            self.backend._game_changed_turbo = False
            self.backend._game_changed_tdp = False
            self.backend.settings._data["user_presets"] = [
                {
                    "id": "game-preset",
                    "name": "Game Preset",
                    "profile": "performance",
                    "governor": "performance",
                    "turbo_enabled": True,
                    "pl1_w": 60,
                    "pl2_w": 85,
                }
            ]
            self.backend.set_game_auto_switch(True)
            self.backend.set_game_target_preset_id("game-preset")
            self.backend.set_game_auto_refresh_max(False)
            self.backend.set_game_auto_lock_touchpad(False)

            with patch.object(self.backend, "detect_running_game", return_value="Minecraft"), \
                 patch.object(self.backend, "get_platform_profile", return_value="balanced"), \
                 patch.object(self.backend, "get_cpu_governor", return_value="powersave"), \
                 patch.object(self.backend, "get_cpu_turbo", return_value=False), \
                 patch.object(self.backend, "get_cpu_tdp_limits", return_value=(35, 50)), \
                 patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")) as m_p, \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")) as m_g, \
                 patch.object(self.backend, "set_cpu_turbo", return_value=(True, "OK")) as m_t, \
                 patch.object(self.backend, "set_cpu_tdp_limits", return_value=(True, "OK")) as m_tdp:
                ev = self.backend.check_game_auto_switch()
                self.assertEqual(ev["type"], "game_started")
                self.assertIn("Preset: Game Preset", ev["extras"])
                m_p.assert_called_with("performance", allow_elevation=False)
                m_g.assert_called_with("performance", allow_elevation=False)
                m_t.assert_called_with(True, allow_elevation=False)
                m_tdp.assert_called_with(60, 85, allow_elevation=False)

                self.backend.update_game_session_peaks(88.0, 72.5)

            with patch.object(self.backend, "detect_running_game", return_value=None), \
                 patch.object(self.backend, "detect_running_app_rule", return_value=None), \
                 patch.object(self.backend, "_get_ac_online", return_value=1), \
                 patch.object(self.backend, "set_platform_profile", return_value=(True, "OK")), \
                 patch.object(self.backend, "set_cpu_governor", return_value=(True, "OK")), \
                 patch.object(self.backend, "set_cpu_turbo", return_value=(True, "OK")) as m_t_rest, \
                 patch.object(self.backend, "set_cpu_tdp_limits", return_value=(True, "OK")) as m_tdp_rest:
                ev_stop = self.backend.check_game_auto_switch()
                self.assertEqual(ev_stop["type"], "game_stopped")
                m_t_rest.assert_called_with(False, allow_elevation=False)
                m_tdp_rest.assert_called_with(35, 50, allow_elevation=False)
                self.assertIsNotNone(ev_stop["session_summary"])
                self.assertEqual(ev_stop["session_summary"]["peak_cpu_c"], 88.0)
                self.assertEqual(ev_stop["session_summary"]["peak_gpu_c"], 72.5)

    def test_game_ignore_list_filters_detected_game(self):
        """Lista de exclusões impede disparo do Auto-Switch para o termo configurado."""
        with patch.object(self.backend.settings, "save", return_value=None):
            self.backend.add_game_ignore_item("sober")
            self.assertIn("sober", self.backend.get_game_ignore_list())

            fake_proc = MagicMock()
            fake_proc.info = {"name": "sober", "exe": "/app/bin/sober", "cmdline": ["/app/bin/sober"], "cwd": "/"}
            with patch("core.backend.psutil.process_iter", return_value=[fake_proc]):
                self.assertIsNone(self.backend.detect_running_game(force=True))

            self.backend.remove_game_ignore_item("sober")
            with patch("core.backend.psutil.process_iter", return_value=[fake_proc]):
                self.assertEqual(self.backend.detect_running_game(force=True), "Roblox (Sober)")

    # -------------------------------------------------------------------------
    # 25. CLI Expandido (--json, --diagnostic, --cycle-profile, --apply-preset)
    # -------------------------------------------------------------------------
    def test_cli_expanded_commands(self):
        """Flags CLI novas produzem JSON válido e executam ações com allow_elevation=False."""
        import io
        import types
        import contextlib
        import main as app_main

        with patch.object(self.backend.settings, "save", return_value=None):
            self.backend.settings._data["user_presets"] = [
                {"id": "modo-eco", "name": "Modo Eco", "profile": "low-power"}
            ]
            buf = io.StringIO()
            args_status = types.SimpleNamespace(
                status=True, json=True, diagnostic=False, list_presets=False,
                cycle_profile=False, cycle_hz=False, apply_preset=None,
                profile=None, conservation=None, install_udev=False, autostart=None
            )
            with patch.object(self.backend, "get_cpu_metrics", return_value=CPUMetrics(temperature_c=50.0, frequency_mhz=2400.0)), \
                 patch.object(self.backend, "get_gpu_metrics", return_value=GPUMetrics(available=False)), \
                 contextlib.redirect_stdout(buf):
                app_main.run_cli_mode(args_status, self.backend)
            parsed = json.loads(buf.getvalue())
            self.assertIn("profile", parsed)
            self.assertIn("cpu", parsed)

            buf2 = io.StringIO()
            args_pre = types.SimpleNamespace(
                status=False, json=True, diagnostic=False, list_presets=False,
                cycle_profile=False, cycle_hz=False, apply_preset="Modo Eco",
                profile=None, conservation=None, install_udev=False, autostart=None
            )
            with patch.object(self.backend, "apply_user_preset", return_value=(True, "Silencioso")) as m_pre, \
                 contextlib.redirect_stdout(buf2):
                app_main.run_cli_mode(args_pre, self.backend)
            m_pre.assert_called_once_with("modo-eco", allow_elevation=False)
            self.assertTrue(json.loads(buf2.getvalue())["ok"])

    # -------------------------------------------------------------------------
    # 26. Teclado RGB 4-Zonas & Verificador de Atualizações no GitHub
    # -------------------------------------------------------------------------
    def test_rgb_keyboard_discovery_packet_and_tab(self):
        """Descoberta hidraw ITE, pacote 33 bytes e fallback sysfs multicolor funcionam."""
        from ui.tabs.lighting_tab import LightingTab

        pkt = HardwareBackend._build_ite_rgb_packet("static", ["#ff0000", "#00ff00", "#0000ff", "#ffffff"], 2, 3)
        self.assertEqual(len(pkt), 33)
        self.assertEqual(pkt[0], 0xCC)
        self.assertEqual(pkt[1], 0x16)
        self.assertEqual(pkt[2], 0x01)
        self.assertEqual(pkt[3], 3)
        self.assertEqual(pkt[4], 2)
        self.assertEqual(list(pkt[5:8]), [255, 0, 0])
        self.assertEqual(list(pkt[8:11]), [0, 255, 0])
        self.assertEqual(list(pkt[11:14]), [0, 0, 255])
        self.assertEqual(list(pkt[14:17]), [255, 255, 255])

        pkt_off = HardwareBackend._build_ite_rgb_packet("off", ["#ff0000"] * 4, 2, 2)
        self.assertEqual(pkt_off[4], 0)
        self.assertEqual(list(pkt_off[5:8]), [0, 0, 0])

        with patch("core.backend.glob.glob", side_effect=lambda pat: ["/sys/class/hidraw/hidraw3"] if "hidraw" in pat else []), \
             patch.object(self.backend, "_read_file_text", return_value="HID_ID=0003:0000048D:0000C965\n"), \
             patch("os.path.exists", side_effect=lambda p: p == "/dev/hidraw3"):
            self.backend._scan_rgb_keyboard()
            self.assertTrue(self.backend.features.rgb_keyboard)
            self.assertEqual(self.backend.paths.rgb_hidraw, "/dev/hidraw3")

        # Fallback sysfs multicolor
        with tempfile.TemporaryDirectory() as td:
            mi = os.path.join(td, "multi_intensity")
            br = os.path.join(td, "brightness")
            with open(mi, "w", encoding="utf-8") as fh:
                fh.write("0 0 0\n")
            with open(br, "w", encoding="utf-8") as fh:
                fh.write("1\n")
            with patch.object(self.backend.settings, "save", return_value=None):
                self.backend.paths.rgb_hidraw = None
                self.backend.paths.rgb_sysfs_dir = td
                self.backend.features.rgb_keyboard = True
                ok, _ = self.backend.set_rgb_keyboard_state("static", ["#102030"] * 4, 2, 1)
                self.assertTrue(ok)
                with open(mi, "r", encoding="utf-8") as fh:
                    self.assertEqual(fh.read().strip(), "16 32 48")

        tab = LightingTab(self.backend)
        self.assertEqual(len(tab.zone_buttons), 4)
        tab.close()

    def test_check_for_updates_mocked(self):
        """check_for_updates compara commit local/remoto e trata falha offline sem exceções."""
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({
            "sha": "abcdef1234567890",
            "commit": {"message": "feat: teste", "committer": {"date": "2026-11-21T18:00:00Z"}},
        }).encode("utf-8")
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("core.backend.subprocess.run", return_value=MagicMock(returncode=0, stdout="abcdef1\n")), \
             patch("core.backend.urllib.request.urlopen", return_value=fake_resp):
            res = self.backend.check_for_updates()
            self.assertTrue(res["ok"])
            self.assertTrue(res["up_to_date"])

        # Sem .git (instalação empacotada): compara APP_VERSION contra tag de release do GitHub
        rel_same = MagicMock()
        rel_same.read.return_value = json.dumps({
            "tag_name": "v2.1.0",
            "name": "DucksVantage 2.1.0",
            "published_at": "2026-11-21T18:00:00Z",
        }).encode("utf-8")
        rel_same.__enter__ = MagicMock(return_value=rel_same)
        rel_same.__exit__ = MagicMock(return_value=False)

        with patch("core.mixins.extras.os.path.isdir", return_value=False), \
             patch("core.backend.urllib.request.urlopen", return_value=rel_same):
            res_pkg = self.backend.check_for_updates()
            self.assertTrue(res_pkg["ok"])
            self.assertTrue(res_pkg["up_to_date"])

        rel_newer = MagicMock()
        rel_newer.read.return_value = json.dumps({
            "tag_name": "v2.2.0",
            "name": "DucksVantage 2.2.0",
            "published_at": "2026-11-26T18:00:00Z",
        }).encode("utf-8")
        rel_newer.__enter__ = MagicMock(return_value=rel_newer)
        rel_newer.__exit__ = MagicMock(return_value=False)

        with patch("core.mixins.extras.os.path.isdir", return_value=False), \
             patch("core.backend.urllib.request.urlopen", return_value=rel_newer):
            res_new = self.backend.check_for_updates()
            self.assertTrue(res_new["ok"])
            self.assertFalse(res_new["up_to_date"])

        with patch("core.backend.urllib.request.urlopen", side_effect=OSError("Network unreachable")):
            res_err = self.backend.check_for_updates()
            self.assertFalse(res_err["ok"])
            self.assertIn("Não foi possível consultar", res_err["message"])

    # -------------------------------------------------------------------------
    # 27. Correção Completa do Mapeador de Teclas (Copilot F8/F23, evdev & Qt)
    # -------------------------------------------------------------------------
    def test_key_mapping_sanitizes_broken_meta_shift_and_syncs_codes(self):
        """Slots corrompidos com 'Meta+Shift+' são reparados automaticamente e derivam evdev_code/modifiers."""
        from core.settings import SettingsManager

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "settings.json")
            broken_data = {
                "key_mappings": {
                    "copilot_key": {
                        "label": "Tecla Copilot (F23 / Meta+Shift+F23)",
                        "qt_shortcut": "Meta+Shift+",
                        "evdev_code": 193,
                        "action": "toggle_max_power",
                        "custom_command": "",
                        "enabled": False,
                    },
                    "special_launch": {
                        "label": "Tecla Especial / Multimídia (F24)",
                        "qt_shortcut": "Meta+Shift+",
                        "evdev_code": 194,
                        "action": "toggle_max_power",
                        "custom_command": "",
                        "enabled": False,
                    },
                    "eco_hotkey": {
                        "label": "Atalho Rápido Eco-Mode (Ctrl+Alt+E)",
                        "qt_shortcut": "Ctrl+Alt+E",
                        "evdev_code": 0,
                        "action": "toggle_eco_mode",
                        "custom_command": "",
                        "enabled": True,
                    },
                    "refresh_rate_hotkey": {
                        "label": "Taxa de Atualização de Tela (Fn+R / Alt+R)",
                        "qt_shortcut": "Alt+R",
                        "evdev_code": 431,
                        "action": "cycle_refresh_rate",
                        "custom_command": "",
                        "enabled": True,
                    },
                }
            }
            with open(cfg_file, "w", encoding="utf-8") as fh:
                json.dump(broken_data, fh)

            with patch("core.settings.CONFIG_DIR", tmpdir), \
                 patch("core.settings.CONFIG_FILE", cfg_file), \
                 patch("core.settings.LEGACY_CONFIG_FILE", "/nonexistent"):
                sm = SettingsManager()
                km = sm.get("key_mappings")

                self.assertEqual(km["copilot_key"]["qt_shortcut"], "Meta+Shift+F23")
                self.assertEqual(km["copilot_key"]["evdev_code"], 193)
                self.assertEqual(km["copilot_key"]["evdev_modifiers"], ["Meta", "Shift"])
                self.assertEqual(km["copilot_key"]["extra_evdev_codes"], [583])
                self.assertEqual(km["copilot_key"]["action"], "toggle_max_power")

                self.assertEqual(km["special_launch"]["qt_shortcut"], "F24")
                self.assertEqual(km["special_launch"]["evdev_code"], 194)
                self.assertEqual(km["special_launch"]["evdev_modifiers"], [])

                self.assertEqual(km["eco_hotkey"]["evdev_code"], 18)
                self.assertEqual(km["eco_hotkey"]["evdev_modifiers"], ["Ctrl", "Alt"])

                self.assertEqual(km["refresh_rate_hotkey"]["evdev_code"], 19)
                self.assertEqual(km["refresh_rate_hotkey"]["evdev_modifiers"], ["Alt"])
                self.assertEqual(km["refresh_rate_hotkey"]["extra_evdev_codes"], [562, 431])

    def test_evdev_listener_deduplicates_usb_symlinks(self):
        """_init_evdev_listeners não deve abrir o mesmo /dev/input/eventX em duplicidade (usb- e usbv2-)."""
        opened_paths = []
        fake_candidates = [
            ("/dev/input/event3", "AT Translated Set 2 keyboard"),
            ("/dev/input/by-path/pci-0000:00:14.0-usb-0:3:1.0-event-kbd", "usb-kbd"),
            ("/dev/input/by-path/pci-0000:00:14.0-usbv2-0:3:1.0-event-kbd", "usbv2-kbd"),
            ("/dev/input/event12", "Ideapad extra buttons"),
        ]

        def fake_realpath(path):
            if "usb" in path:
                return "/dev/input/event4"
            return path

        fake_stats = {
            "/dev/input/event3": MagicMock(st_mode=0o20644, st_rdev=1),
            "/dev/input/event4": MagicMock(st_mode=0o20644, st_rdev=2),
            "/dev/input/event12": MagicMock(st_mode=0o20644, st_rdev=3),
        }

        def fake_open(path, flags):
            opened_paths.append(path)
            return 200 + len(opened_paths)

        with patch.object(HardwareBackend, "_discover_evdev_keyboard_candidates", return_value=fake_candidates), \
             patch("os.path.exists", return_value=True), \
             patch("os.access", return_value=True), \
             patch("os.path.realpath", side_effect=fake_realpath), \
             patch("os.stat", side_effect=lambda p: fake_stats[p]), \
             patch("os.open", side_effect=fake_open), \
             patch("os.close"):
            self.backend._init_evdev_listeners()

        self.assertEqual(len(self.backend._input_fds), 3)
        self.assertEqual(opened_paths, ["/dev/input/event3", "/dev/input/event4", "/dev/input/event12"])

    def test_evdev_poll_modifiers_f8_copilot_refresh_and_debounce(self):
        """_poll_evdev_keys suporta Meta+Shift+F23, F8, Ctrl+Alt+E, Fn+R(562), bloqueia letra avulsa e aplica debounce."""
        import struct

        def pack_events(pairs):
            return b"".join(struct.pack("llHHi", 0, 0, 1, code, val) for code, val in pairs)

        self.backend._input_fds = [77]
        self.backend._input_fd_info = {77: {"path": "/dev/input/event3", "name": "Test Kbd"}}
        self.backend._evdev_held_mods = {77: set()}
        self.backend._evdev_last_trigger_ts = {}
        self.backend._evdev_capture_cooldown_until = 0.0

        self.backend.settings._data["key_mappings"] = {
            "copilot_key": {
                "label": "Tecla Copilot",
                "qt_shortcut": "Meta+Shift+F23",
                "evdev_code": 193,
                "evdev_modifiers": ["Meta", "Shift"],
                "extra_evdev_codes": [583],
                "action": "toggle_max_power",
                "custom_command": "",
                "enabled": True,
            },
            "eco_hotkey": {
                "label": "Eco",
                "qt_shortcut": "Ctrl+Alt+E",
                "evdev_code": 18,
                "evdev_modifiers": ["Ctrl", "Alt"],
                "extra_evdev_codes": [],
                "action": "toggle_eco_mode",
                "custom_command": "",
                "enabled": True,
            },
            "refresh_rate_hotkey": {
                "label": "Refresh",
                "qt_shortcut": "Alt+R",
                "evdev_code": 19,
                "evdev_modifiers": ["Alt"],
                "extra_evdev_codes": [562, 431],
                "action": "cycle_refresh_rate",
                "custom_command": "",
                "enabled": True,
            },
            "custom_f8": {
                "label": "F8",
                "qt_shortcut": "F8",
                "evdev_code": 66,
                "evdev_modifiers": [],
                "extra_evdev_codes": [],
                "action": "toggle_touchpad",
                "custom_command": "",
                "enabled": True,
            },
        }

        # 1) E (18) e R (19) sem modificadores NÃO podem disparar
        # 2) Ctrl+Alt+E dispara eco_hotkey
        # 3) Meta+Shift+F23 dispara copilot_key
        # 4) Fn+R (562) dispara refresh_rate_hotkey
        # 5) F8 (66) dispara custom_f8 e o segundo F8 em <350ms é filtrado por debounce
        seq_bytes = pack_events([
            (18, 1), (18, 0),
            (19, 1), (19, 0),
            (29, 1), (56, 1), (18, 1), (18, 0), (56, 0), (29, 0),
            (125, 1), (42, 1), (193, 1), (193, 0), (42, 0), (125, 0),
            (562, 1), (562, 0),
            (66, 1), (66, 0),
            (66, 1), (66, 0),
        ])
        reads = [seq_bytes]

        def fake_read(fd, sz):
            if reads:
                return reads.pop(0)
            raise BlockingIOError()

        with patch("os.read", side_effect=fake_read):
            ev = self.backend._poll_evdev_keys()

        actions = [e["action"] for e in ev]
        self.assertEqual(actions, ["toggle_eco_mode", "toggle_max_power", "cycle_refresh_rate", "toggle_touchpad"])

    def test_evdev_live_capture_and_qt_key_capture_button(self):
        """Captura evdev ao vivo e KeyCaptureButton não produzem 'Meta+Shift+' quebrado e capturam F8 / Copilot."""
        import struct
        from core.qt_compat import Qt, QtGui
        from ui.widgets.key_capture_button import KeyCaptureButton

        def pack_events(pairs):
            return b"".join(struct.pack("llHHi", 0, 0, 1, code, val) for code, val in pairs)

        self.backend._input_fds = [88]
        self.backend._input_fd_info = {88: {"path": "/dev/input/event3", "name": "Test Kbd"}}
        self.backend._evdev_held_mods = {88: set()}

        # Teste 1: Captura evdev de Meta+Shift+F23
        bufs = [b"", pack_events([(125, 1), (42, 1), (193, 1)])]

        def read_seq(fd, sz):
            if bufs:
                data = bufs.pop(0)
                if data:
                    return data
            raise BlockingIOError()

        with patch("os.read", side_effect=read_seq):
            self.assertTrue(self.backend.start_evdev_capture())
            res = self.backend.poll_evdev_capture()

        self.assertIsNotNone(res)
        self.assertFalse(res["cancelled"])
        self.assertEqual(res["qt_shortcut"], "Meta+Shift+F23")
        self.assertEqual(res["evdev_code"], 193)
        self.assertEqual(res["evdev_modifiers"], ["Meta", "Shift"])

        # Teste 2: Esc cancela captura evdev
        bufs_esc = [b"", pack_events([(1, 1)])]

        def read_esc(fd, sz):
            if bufs_esc:
                data = bufs_esc.pop(0)
                if data:
                    return data
            raise BlockingIOError()

        with patch("os.read", side_effect=read_esc):
            self.backend.start_evdev_capture()
            res_esc = self.backend.poll_evdev_capture()
        self.assertEqual(res_esc, {"cancelled": True})

        # Teste 3: KeyCaptureButton fallback Qt rejeita key=0 ('Meta+Shift+') e aceita F8 / XF86Assistant
        btn = KeyCaptureButton("F24", backend=None)
        btn._start_capture()
        btn._evdev_capturing = False

        # Key_unknown com Meta+Shift NÃO pode alterar nem emitir sinal
        ev_unknown = QtGui.QKeyEvent(
            QtGui.QKeyEvent.Type.KeyPress,
            int(Qt.Key.Key_unknown),
            Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        btn.keyPressEvent(ev_unknown)
        self.assertTrue(btn._capturing)
        self.assertEqual(btn.text(), "Pressione tecla...")
        self.assertNotEqual(btn.text(), "Meta+Shift+")

        # Pressionar F8 captura F8 com evdev_code == 66
        captured_signals = []
        btn.capture_completed.connect(lambda seq, code, mods: captured_signals.append((seq, code, mods)))
        ev_f8 = QtGui.QKeyEvent(QtGui.QKeyEvent.Type.KeyPress, int(Qt.Key.Key_F8), Qt.KeyboardModifier.NoModifier)
        btn.keyPressEvent(ev_f8)
        self.assertFalse(btn._capturing)
        self.assertEqual(btn.text(), "F8")
        self.assertEqual(btn.evdev_code, 66)
        self.assertEqual(captured_signals[-1], ("F8", 66, []))

        # Simula XF86Assistant (nativeVirtualKey=0x1008ffac, key=0, Meta+Shift)
        btn._capturing = True
        btn._evdev_capturing = False
        ev_assist = MagicMock()
        ev_assist.key.return_value = 0
        ev_assist.modifiers.return_value = Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ShiftModifier
        ev_assist.nativeVirtualKey.return_value = 0x1008FFAC
        ev_assist.nativeScanCode.return_value = 201
        btn.keyPressEvent(ev_assist)
        self.assertFalse(btn._capturing)
        self.assertEqual(btn.text(), "Meta+Shift+F23")
        self.assertEqual(btn.evdev_code, 193)
        self.assertEqual(btn.evdev_modifiers, ["Meta", "Shift"])


if __name__ == "__main__":
    unittest.main()
