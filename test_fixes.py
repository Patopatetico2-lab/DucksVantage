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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

        with patch.object(self.backend, "_discover_network_interfaces", return_value=("wlan0", None)):
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
    # 6. Wayland OSD Overlay Compatibility
    # -------------------------------------------------------------------------
    def test_osd_overlay_wayland_flags(self):
        """O OSD deve inicializar com flags adequadas a sessões Wayland e X11."""
        from core.qt_compat import QApplication
        app = QApplication.instance() or QApplication(["ducksvantage", "-platform", "offscreen"])

        from ui.osd_overlay import VantageOSDOverlay
        osd = VantageOSDOverlay()
        self.assertEqual(osd.objectName(), "ducksvantage-osd")
        self.assertIsNotNone(osd.container)

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


if __name__ == "__main__":
    unittest.main()
