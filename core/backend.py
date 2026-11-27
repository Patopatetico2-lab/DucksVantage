"""
Backend Universal de Hardware para o Ducksvantage (core/backend.py).
Arquitetura agnóstica para toda a linha Lenovo (Legion, LOQ, IdeaPad Gaming, IdeaPad, Yoga)
com suporte a Intel e AMD, NVIDIA (pynvml + nvidia-smi) e GPUs integradas/Radeon via DRM/hwmon,
além dos 6 Recursos Exclusivos de Elite:
  1. Descoberta Dinâmica de Perfis do Kernel (incluindo max-power)
  2. Auto-Switching Inteligente por Jogo (Steam / Heroic / Proton / Wine / Gamescope)
  3. Battery Health Historian (Histórico de Saúde e Degradação em Wh)
  4. Modos de Desempenho Customizados (TDP PL1/PL2 via Intel RAPL e Curva de Fans)
  5. Mapeador de Teclas Personalizadas (Tecla Copilot F23 / evdev e Atalhos Globais)
  6. Modo Viagem / Eco-Mode Extremo (1-Clique: Conservação + D3cold + No-Turbo + Kbd Off + Low TDP)
"""

import os
import re
import glob
import struct
import time
import platform
import subprocess
import shutil
import urllib.request
import psutil
from typing import List, Dict, Optional, Tuple, Any, Set

from core.key_mapper import (
    MODIFIER_EVDEV_MAP,
    normalize_modifiers,
    format_shortcut,
    matches_evdev_trigger,
)

from core.models import (
    CPUMetrics, GPUMetrics, RAMMetrics, StorageDevice, FanMetrics,
    BatteryInfo, BatteryHistoryEntry, SystemInfo, HardwareFeatures, HardwarePaths,
    UndervoltStatus, NetworkPowerStatus,
    GpuMuxInfo, DisplayRefreshInfo, BiosAttribute
)
from core.permissions import PermissionsManager
from core.settings import SettingsManager, DEFAULT_FAN_CURVE_POINTS, DEFAULT_APP_POWER_RULES
from core.mixins import (
    GamingAutoSwitchMixin,
    CpuThermalUndervoltMixin,
    TelemetryBatteryNetworkMixin,
    DisplayMuxBiosMixin,
    PresetsDiagnosticsRgbMixin,
    SmartFeaturesMixin,
)
from core.mixins.cpu_thermal import (
    UNDERVOLT_CANARY_FILE,
    UNDERVOLT_CANARY_FALLBACK,
    UNDERVOLT_CANARY_PATHS,
)
from core.mixins.telemetry_battery import HAS_PYNVML, pynvml
from core.mixins.extras import APP_VERSION, GITHUB_REPO


# =============================================================================
# Dicionários Universais de Tradução e Metadados de Perfis ACPI (Incluindo 'max-power')
# =============================================================================
ACPI_PROFILE_MAP: Dict[str, str] = {
    "quiet": "low-power",
    "low-power": "low-power",
    "low_power": "low-power",
    "silencioso": "low-power",
    "economia": "low-power",
    "power-saver": "low-power",
    "balanced": "balanced",
    "balanced_performance": "balanced",
    "equilibrado": "balanced",
    "performance": "performance",
    "desempenho": "performance",
    "max-power": "max-power",
    "max_power": "max-power",
    "maxpower": "max-power",
    "extreme": "max-power",
    "extremo": "max-power",
    "desempenho-maximo": "max-power",
    "custom": "custom",
}

ACPI_PROFILE_DETAILS: Dict[str, Dict[str, str]] = {
    "low-power": {
        "id": "low-power",
        "title": "Modo Silencioso",
        "short_title": "Silencioso",
        "osd_title": "Modo Silencioso",
        "osd_subtitle": "Fn + Q • Ventoinhas e Clocks Baixos",
        "badge": "SILENCIOSO",
        "badge_bg": "#0369a1",
        "icon": "thermal_quiet.svg",
        "color": "#00d2ff",
    },
    "quiet": {
        "id": "low-power",
        "title": "Modo Silencioso",
        "short_title": "Silencioso",
        "osd_title": "Modo Silencioso",
        "osd_subtitle": "Fn + Q • Ventoinhas e Clocks Baixos",
        "badge": "SILENCIOSO",
        "badge_bg": "#0369a1",
        "icon": "thermal_quiet.svg",
        "color": "#00d2ff",
    },
    "balanced": {
        "id": "balanced",
        "title": "Modo Equilibrado",
        "short_title": "Equilibrado",
        "osd_title": "Modo Equilibrado",
        "osd_subtitle": "Fn + Q • Ajuste Automático Inteligente",
        "badge": "EQUILIBRADO",
        "badge_bg": "#155e75",
        "icon": "thermal_balanced.svg",
        "color": "#2ec5eb",
    },
    "performance": {
        "id": "performance",
        "title": "Modo Desempenho",
        "short_title": "Desempenho",
        "osd_title": "Modo Desempenho",
        "osd_subtitle": "Fn + Q • Envelope Térmico Elevado",
        "badge": "DESEMPENHO",
        "badge_bg": "#7f1d1d",
        "icon": "thermal_performance.svg",
        "color": "#ff3b30",
    },
    "max-power": {
        "id": "max-power",
        "title": "Desempenho Máximo (Max-Power)",
        "short_title": "Max-Power",
        "osd_title": "Desempenho Máximo (Max-Power)",
        "osd_subtitle": "Fn + Q • Rotação Máxima & Potência Total",
        "badge": "MAX-POWER",
        "badge_bg": "#581c87",
        "icon": "thermal_max_power.svg",
        "color": "#9e3dff",
    },
    "custom": {
        "id": "custom",
        "title": "Modo Customizado",
        "short_title": "Custom",
        "osd_title": "Modo Customizado",
        "osd_subtitle": "Fn + Q • Ajuste Personalizado de Potência",
        "badge": "CUSTOM",
        "badge_bg": "#581c87",
        "icon": "mode_custom.svg",
        "color": "#9e3dff",
    },
}


class HardwareBackend(
    GamingAutoSwitchMixin,
    CpuThermalUndervoltMixin,
    TelemetryBatteryNetworkMixin,
    DisplayMuxBiosMixin,
    PresetsDiagnosticsRgbMixin,
    SmartFeaturesMixin,
):
    """Núcleo universal de comunicação direta com o Linux (/sys/, ACPI, DRM, HWMon, RAPL, evdev)."""

    PROFILE_MAP = ACPI_PROFILE_MAP
    PROFILE_DETAILS = ACPI_PROFILE_DETAILS

    def __init__(self):
        self.paths = HardwarePaths()
        self.features = HardwareFeatures()
        self.system_info = SystemInfo()
        self.settings = SettingsManager()
        self.nvidia_available = False
        self._nvml_initialized = False
        self._cached_gpu_name = ""
        self._cached_gpu_short = "GPU"

        # Cache de estado para detecção rápida de Fn+Q e atalhos (200ms polling)
        self._last_profile = "balanced"
        self._last_raw_profile = "balanced"
        self._max_power_active = False
        self._promoted_max_power_from_low: bool = False
        self._is_wmi_gamezone: bool = False
        self._last_ac_online = 1
        self._last_conservation = False
        self._last_fn_lock = False
        self._last_camera = True
        self._last_kbd_bright = 0

        # Estado do Auto-Switching de Jogos e Regras por Aplicativo (App Rules)
        self._active_game_name: Optional[str] = None
        self._active_rule_exec: Optional[str] = None
        self._pre_game_profile: str = "balanced"
        self._pre_game_governor: str = "powersave"
        self._pre_game_refresh_hz: Optional[int] = None
        self._pre_game_turbo: Optional[bool] = None
        self._pre_game_tdp: Optional[Tuple[int, int]] = None
        self._pre_game_fan_curve: Optional[Dict[str, Any]] = None
        self._pre_game_vrr_policy: Optional[str] = None
        self._game_changed_refresh: bool = False
        self._game_changed_turbo: bool = False
        self._game_changed_tdp: bool = False
        self._game_changed_fan_curve: bool = False
        self._game_changed_vrr: bool = False
        self._game_changed_wifi: bool = False
        self._pre_game_wifi_ps: Optional[bool] = None
        self._game_locked_touchpad: bool = False
        self._undervolt_active_in_hw: bool = False
        self._game_session_start_ts: float = 0.0
        self._game_peak_cpu_c: float = 0.0
        self._game_peak_gpu_c: float = 0.0
        self._game_power_sum_w: float = 0.0
        self._game_power_samples: int = 0
        self._rgb_backend_name: str = "none"

        # Estado dos novos recursos inteligentes (Throttling, Dock, USB, NVMe, NVIDIA Wakelock)
        self._prev_cpu_throttle_sum: Optional[int] = None
        self._cached_gpu_throttle_reasons: List[str] = []
        self._prev_rapl_uj: Optional[int] = None
        self._prev_rapl_ts: float = 0.0
        self._dock_active: Optional[bool] = None
        self._dock_pre_profile: str = "balanced"
        self._dock_pre_hz: Optional[int] = None
        self._dock_lid_proc: Optional[Any] = None
        self._cached_nvidia_wakelocks: Optional[Dict[str, Any]] = None
        self._last_nvidia_wakelock_scan: float = 0.0
        self._cached_nvme_health: Optional[List[Dict[str, Any]]] = None
        self._last_nvme_health_scan: float = 0.0
        self._last_nvme_temp_alert_ts: float = 0.0

        # Estado da Curva de Ventoinhas e Undervolt Seguro
        self._last_applied_pwm: int = -1
        self._last_emergency_reset: str = ""
        self._hwmon_pwm_nodes: List[Tuple[str, Optional[str]]] = []
        self._hwmon_fan_targets: List[Tuple[str, Optional[str], int, int]] = []
        self._fan_fullspeed_path: Optional[str] = None

        # Estado de Alertas Inteligentes da Bateria
        self._alerted_80_this_session: bool = False
        self._last_temp_alert_ts: float = 0.0

        # Descritores não-bloqueantes /dev/input para capturar tecla Copilot (F23), F8 e atalhos
        self._input_fds: List[int] = []
        self._input_fd_info: Dict[int, Dict[str, str]] = {}
        self._evdev_held_mods: Dict[int, Set[int]] = {}
        self._evdev_last_trigger_ts: Dict[str, float] = {}
        self._evdev_capture_active: bool = False
        self._evdev_capture_mods: Set[int] = set()
        self._evdev_capture_cooldown_until: float = 0.0

        # Caches de telemetria e processos para evitar micro-travamentos (stutters) na interface
        self._cached_cpu_vendor: Optional[str] = None
        self._cached_nvidia_metrics: Optional[GPUMetrics] = None
        self._last_nvidia_smi_time: float = 0.0
        self._cached_running_game: Optional[str] = None
        self._last_game_scan_time: float = 0.0
        self._cached_running_app_rule: Optional[Dict[str, str]] = None
        self._last_app_rule_scan_time: float = 0.0
        self._cached_net_power_status: Optional[NetworkPowerStatus] = None
        self._last_net_power_status_time: float = 0.0

        # Caches e estados para GPU MUX, Taxa de Atualização e BIOS WMI
        self._cached_gpu_mux_info: Optional[GpuMuxInfo] = None
        self._last_gpu_mux_scan: float = 0.0
        self._cached_refresh_info: Optional[DisplayRefreshInfo] = None
        self._last_refresh_scan: float = 0.0
        self._cached_bios_attrs: Optional[List[BiosAttribute]] = None
        self._last_bios_attrs_scan: float = 0.0
        self._last_applied_refresh_hz: Optional[int] = None
        self._touchpad_event_name: Optional[str] = None
        self._touchpad_device_name: Optional[str] = None
        self._cached_touchpad_status: Optional[bool] = None
        self._last_touchpad_scan: float = 0.0
        self._platform_profile_paths: List[str] = []
        self._last_profile_by_path: Dict[str, str] = {}

        self.scan_hardware()
        self._check_undervolt_crash_recovery()

        # Inicializar valores de referência para o polling de 200ms
        initial_raw = self._read_raw_platform_profile()
        self._last_raw_profile = initial_raw
        self._max_power_active = (initial_raw == "max-power")
        self._last_profile = initial_raw
        self._last_ac_online = self._get_ac_online()
        self._last_conservation = self.get_conservation_mode()
        self._last_fn_lock = self.get_fn_lock()
        self._last_camera = self.get_camera_power()
        self._last_kbd_bright = self.get_kbd_backlight()

        # Registrar snapshot de saúde da bateria no histórico
        self.record_battery_snapshot()
        self._init_evdev_listeners()

    def _read_file_text(self, path: Optional[str]) -> Optional[str]:
        """Lê o conteúdo em texto de um arquivo do /sys/ ou /proc/."""
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().strip()
        except Exception:
            return None

    def _read_file_int(self, path: Optional[str], default: int = 0) -> int:
        """Lê um inteiro de um nó sysfs."""
        val = self._read_file_text(path)
        if val is not None:
            try:
                return int(val)
            except ValueError:
                pass
        return default

    def get_cpu_vendor(self) -> str:
        """Identifica e armazena em cache o fabricante do processador (Intel, AMD ou Generic)."""
        if self._cached_cpu_vendor:
            return self._cached_cpu_vendor
        cpuinfo = self._read_file_text("/proc/cpuinfo") or ""
        vendor = "Generic"
        if "GenuineIntel" in cpuinfo or "Intel" in cpuinfo:
            vendor = "Intel"
        elif "AuthenticAMD" in cpuinfo or "AMD" in cpuinfo:
            vendor = "AMD"
        self._cached_cpu_vendor = vendor
        return vendor

    def close(self):
        """Fecha com segurança descritores de arquivo evdev e processos filhos ativos."""
        for fd in list(self._input_fds):
            try:
                os.close(fd)
            except Exception:
                pass
        self._input_fds.clear()
        self._input_fd_info.clear()
        self._evdev_held_mods.clear()
        self._evdev_capture_active = False
        self._evdev_capture_mods.clear()

        proc = getattr(self, "_dock_lid_proc", None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._dock_lid_proc = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # =========================================================================
    # Varredura Universal e Feature Discovery (Zero Hardcoding)
    # =========================================================================
    def scan_hardware(self) -> None:
        """Executa descoberta dinâmica e rigorosa de recursos em qualquer notebook Lenovo."""
        # 1. ACPI / Kernel Platform Profile e Descoberta Dinâmica de 'max-power'
        # Suporte simultâneo ao subsistema class/platform-profile (Linux 6.14+ / 7.x, ex: lenovo-wmi-gamezone)
        # e à interface clássica /sys/firmware/acpi/platform_profile.
        self._platform_profile_paths = []
        self._is_wmi_gamezone = False
        pp_dirs = sorted(glob.glob("/sys/class/platform-profile/platform-profile-*"))
        chosen_pp = None
        chosen_pp_name = ""
        for pp_dir in pp_dirs:
            prof_p = os.path.join(pp_dir, "profile")
            if not os.path.exists(prof_p):
                continue
            self._platform_profile_paths.append(prof_p)
            pp_name = (self._read_file_text(os.path.join(pp_dir, "name")) or "").lower()
            if any(k in pp_name for k in ("lenovo", "ideapad", "legion", "thinkpad", "gamezone")):
                if chosen_pp is None:
                    chosen_pp = pp_dir
                    chosen_pp_name = pp_name
            elif chosen_pp is None:
                chosen_pp = pp_dir
                chosen_pp_name = pp_name

        if os.path.exists("/sys/firmware/acpi/platform_profile"):
            self._platform_profile_paths.append("/sys/firmware/acpi/platform_profile")

        if chosen_pp:
            self.paths.platform_profile = os.path.join(chosen_pp, "profile")
            self.features.platform_profile = True
            self._is_wmi_gamezone = ("gamezone" in chosen_pp_name or "lenovo-wmi" in chosen_pp_name)
            choices_p = os.path.join(chosen_pp, "choices")
            if os.path.exists(choices_p):
                self.paths.platform_profile_choices = choices_p
            elif os.path.exists("/sys/firmware/acpi/platform_profile_choices"):
                self.paths.platform_profile_choices = "/sys/firmware/acpi/platform_profile_choices"
        elif os.path.exists("/sys/firmware/acpi/platform_profile"):
            self.paths.platform_profile = "/sys/firmware/acpi/platform_profile"
            self.features.platform_profile = True
            if os.path.exists("/sys/firmware/acpi/platform_profile_choices"):
                self.paths.platform_profile_choices = "/sys/firmware/acpi/platform_profile_choices"

        if self.paths.platform_profile and self.paths.platform_profile in self._platform_profile_paths:
            # Garante que o caminho primário seja sempre o primeiro da lista monitorada
            self._platform_profile_paths.remove(self.paths.platform_profile)
            self._platform_profile_paths.insert(0, self.paths.platform_profile)

        if self.features.platform_profile:
            canonical_choices = self.get_supported_canonical_profiles()
            self.features.available_profiles = canonical_choices
            self.features.max_power_profile = ("max-power" in canonical_choices)

        # 2. Descoberta Dinâmica do Driver ideapad_acpi / ideapad_laptop / legion_laptop
        vpc_dirs = sorted(glob.glob("/sys/bus/platform/drivers/ideapad_acpi/VPC*"))
        if not vpc_dirs:
            vpc_dirs = sorted(glob.glob("/sys/devices/platform/VPC*"))
        if not vpc_dirs:
            vpc_dirs = sorted(glob.glob("/sys/bus/platform/drivers/ideapad_laptop/*"))

        for vdir in vpc_dirs:
            if os.path.isdir(vdir):
                self.paths.ideapad_dir = vdir
                break

        extra_acpi_dirs = [d for d in (self.paths.ideapad_dir, "/sys/devices/platform/PNP0C09:00") if d and os.path.isdir(d)]
        extra_acpi_dirs.extend(sorted(glob.glob("/sys/bus/platform/drivers/legion_laptop/*")))

        for idir in extra_acpi_dirs:
            if not self.paths.conservation_mode:
                cons = os.path.join(idir, "conservation_mode")
                if os.path.exists(cons):
                    self.paths.conservation_mode = cons
                    self.features.conservation_mode = True

            if not self.paths.rapid_charge:
                rc = os.path.join(idir, "rapid_charge")
                if os.path.exists(rc):
                    self.paths.rapid_charge = rc

            if not self.paths.fn_lock:
                fn = os.path.join(idir, "fn_lock")
                if os.path.exists(fn):
                    self.paths.fn_lock = fn
                    self.features.fn_lock = True

            if not self.paths.camera_power:
                cam = os.path.join(idir, "camera_power")
                if os.path.exists(cam):
                    self.paths.camera_power = cam
                    self.features.camera_power = True

            if not self.paths.usb_charging:
                usb = os.path.join(idir, "usb_charging")
                if os.path.exists(usb):
                    self.paths.usb_charging = usb
                    self.features.usb_charging = True

            if not self.paths.touchpad:
                tp = os.path.join(idir, "touchpad")
                if os.path.exists(tp):
                    self.paths.touchpad = tp

            if not self.paths.fan_mode:
                fan_m = os.path.join(idir, "fan_mode")
                if os.path.exists(fan_m):
                    self.paths.fan_mode = fan_m

            if not self._fan_fullspeed_path:
                for fs_name in ("fan_fullspeed", "full_fan_speed"):
                    fs_p = os.path.join(idir, fs_name)
                    if os.path.exists(fs_p):
                        self._fan_fullspeed_path = fs_p
                        break

        # 3. Retroiluminação do Teclado (Kbd Backlight)
        kbd_candidates = [
            "/sys/class/leds/platform::kbd_backlight/brightness",
        ] + sorted(glob.glob("/sys/class/leds/*kbd_backlight*/brightness"))

        for kc in kbd_candidates:
            if os.path.exists(kc):
                self.paths.kbd_backlight = kc
                self.features.kbd_backlight = True
                max_p = os.path.join(os.path.dirname(kc), "max_brightness")
                if os.path.exists(max_p):
                    self.paths.kbd_max_backlight = max_p
                    self.features.kbd_max_brightness = max(1, self._read_file_int(max_p, 2))
                break

        # 4. CPU Turbo Boost (Intel P-State e AMD CPUFreq), Scaling Governor e TDP (Intel RAPL)
        if os.path.exists("/sys/devices/system/cpu/intel_pstate/no_turbo"):
            self.paths.cpu_turbo_intel = "/sys/devices/system/cpu/intel_pstate/no_turbo"
            self.features.turbo_boost = True
        elif os.path.exists("/sys/devices/system/cpu/cpufreq/boost"):
            self.paths.cpu_turbo_amd = "/sys/devices/system/cpu/cpufreq/boost"
            self.features.turbo_boost = True

        if os.path.exists("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors"):
            self.paths.cpu_available_governors = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors"
        if os.path.exists("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"):
            self.paths.cpu_governor = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
            avail_govs = self.get_available_cpu_governors()
            self.features.cpu_governor = (len(avail_govs) > 1) if self.paths.cpu_available_governors else True

        # Intel RAPL PL1 (long_term) e PL2 (short_term)
        p_pl1 = "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
        p_pl2 = "/sys/class/powercap/intel-rapl:0/constraint_1_power_limit_uw"
        if os.path.exists(p_pl1) and os.path.exists(p_pl2):
            self.paths.rapl_pl1 = p_pl1
            self.paths.rapl_pl2 = p_pl2
            self.features.custom_tdp = True

        mmio_pl1 = "/sys/class/powercap/intel-rapl-mmio:0/constraint_0_power_limit_uw"
        mmio_pl2 = "/sys/class/powercap/intel-rapl-mmio:0/constraint_1_power_limit_uw"
        if os.path.exists(mmio_pl1) and os.path.exists(mmio_pl2):
            self.paths.rapl_mmio_pl1 = mmio_pl1
            self.paths.rapl_mmio_pl2 = mmio_pl2

        # 4.1 Lenovo WMI Other Firmware Attributes (CPU/GPU Temp Limits, AC Offset, PPT, cTGP)
        self.features.wmi_custom_power = False
        for wmi_cand in sorted(glob.glob("/sys/class/firmware-attributes/lenovo-wmi-other-*/attributes")):
            if os.path.isdir(wmi_cand):
                self.paths.lenovo_wmi_attr_dir = wmi_cand
                self.features.wmi_cpu_temp = os.path.exists(os.path.join(wmi_cand, "cpu_temp", "current_value"))
                self.features.wmi_gpu_temp = os.path.exists(os.path.join(wmi_cand, "gpu_temp", "current_value"))
                self.features.wmi_gpu_ac_offset = os.path.exists(os.path.join(wmi_cand, "gpu_nv_ac_offset", "current_value"))
                self.features.wmi_custom_power = any(
                    os.path.exists(os.path.join(wmi_cand, k, "current_value"))
                    for k in ("gpu_nv_ctgp", "gpu_nv_ppab", "gpu_nv_cpu_boost", "ppt_cpu_cl", "ppt_pl1_spl", "ppt_pl2_sppt")
                )
                break

        # 5. Sensores HWMon (CPU Intel/AMD, NVMe, DDR5 RAM, Ventoinhas e PWM)
        self._scan_hwmon()
        self.features.fan_control = bool(
            self.paths.hwmon_pwm1
            or self._hwmon_pwm_nodes
            or self._hwmon_fan_targets
            or self._fan_fullspeed_path
            or (self.paths.fan_mode and not self._is_wmi_gamezone)
        )

        # 6. Bateria e Fonte AC (/sys/class/power_supply/)
        for bat_cand in sorted(glob.glob("/sys/class/power_supply/BAT*")):
            if os.path.isdir(bat_cand):
                self.paths.battery_dir = bat_cand
                self.features.battery = True
                ct = os.path.join(bat_cand, "charge_types")
                if os.path.exists(ct):
                    self.paths.charge_types = ct
                break

        has_fast_charge_type = False
        if self.paths.charge_types:
            ct_txt = (self._read_file_text(self.paths.charge_types) or "").lower()
            ct_tokens = [tok.strip("[]") for tok in ct_txt.split()]
            has_fast_charge_type = "fast" in ct_tokens
        self.features.rapid_charge = bool(self.paths.rapid_charge or has_fast_charge_type)

        for ac_cand in sorted(glob.glob("/sys/class/power_supply/ADP*") + glob.glob("/sys/class/power_supply/AC*")):
            online_p = os.path.join(ac_cand, "online")
            if os.path.exists(online_p):
                self.paths.adapter_online = online_p
                break

        # 7. Placas Gráficas (DRM + NVIDIA NVML / nvidia-smi + PCI Runtime Power Management)
        self._scan_gpus()
        self.features.gpu_telemetry = bool(self.nvidia_available or self.paths.igpu_drm_card)

        # 8. DMI, BIOS e Identificação Dinâmica da Linha Lenovo
        self._scan_system_info()

        # 9. Touchpad, Undervolt e Interfaces de Rede
        self._scan_touchpad()
        self._scan_undervolt()
        self._scan_network_power()

        # 10. GPU MUX Switch (supergfxctl, envycontrol, prime-select, sysfs, pcie-runtime)
        self._scan_gpu_mux()

        # 11. Taxa de Atualização de Tela (kscreen-doctor, wlr-randr, xrandr)
        self._scan_display_refresh()

        # 12. LCD Overdrive e Firmware Attributes Lenovo BIOS WMI
        self._scan_bios_attributes()

        # 12.5 Teclado RGB 4-Zonas (Auto-Discovery USB ITE hidraw / multicolor sysfs)
        self._scan_rgb_keyboard()

        # 12.8 Controle de Brilho de Tela (/sys/class/backlight/*)
        self.paths.backlight_dir = None
        self.paths.backlight_brightness = None
        self.paths.backlight_max_brightness = None
        self.features.screen_brightness = False
        bl_dirs = sorted(glob.glob("/sys/class/backlight/*"))
        bl_priority = ("intel_backlight", "amdgpu_bl", "nvidia", "acpi_video")
        bl_sorted = sorted(
            bl_dirs,
            key=lambda p: next(
                (i for i, pref in enumerate(bl_priority) if os.path.basename(p).lower().startswith(pref)),
                len(bl_priority),
            ),
        )
        for bl_dir in bl_sorted:
            br_p = os.path.join(bl_dir, "brightness")
            mx_p = os.path.join(bl_dir, "max_brightness")
            if os.path.exists(br_p) and os.path.exists(mx_p):
                self.paths.backlight_dir = bl_dir
                self.paths.backlight_brightness = br_p
                self.paths.backlight_max_brightness = mx_p
                self.features.screen_brightness = True
                break

        # 13. Modo Viagem (Eco-Mode Extremo): só habilita se houver ao menos 1 recurso de economia real
        self.features.eco_travel = bool(
            self.features.platform_profile
            or self.features.conservation_mode
            or self.features.turbo_boost
            or self.features.cpu_governor
            or self.features.custom_tdp
            or self.paths.nvidia_pci_power_control
            or self.features.kbd_backlight
            or self.features.screen_brightness
        )

        # 14. Recursos Inteligentes (Wake-on-USB, Dock HDMI, Throttling, NVMe, NVIDIA Wakelock)
        self.features.usb_wakeup = bool(self.get_usb_wakeup_devices())
        self.features.external_monitor_dock = bool(glob.glob("/sys/class/drm/card*-*/status"))
        self.features.thermal_throttling = bool(
            glob.glob("/sys/devices/system/cpu/cpu*/thermal_throttle/*") or self.nvidia_available
        )
        self.features.nvme_health = bool(glob.glob("/sys/class/nvme/nvme*") or glob.glob("/sys/block/nvme*"))
        self.features.nvidia_wakelock_detect = bool(self.nvidia_available or self.paths.nvidia_drm_card)

        # Aplica bloqueio de Wake-on-USB salvo no boot se já estiver liberado via UDEV (sem elevation)
        if self.features.usb_wakeup and bool(self.settings.get("usb_wakeup_blocked", False)):
            try:
                self.set_usb_wakeup_blocked(True, allow_elevation=False)
            except Exception:
                pass

    def _scan_touchpad(self) -> None:
        """Detecta se o notebook possui touchpad físico e backend real para bloqueá-lo."""
        self._touchpad_event_name = None
        self._touchpad_device_name = None
        self._cached_touchpad_status = None
        self._last_touchpad_scan = 0.0

        if self.paths.touchpad and os.path.exists(self.paths.touchpad):
            self.features.touchpad_control = True
            return

        tp_keywords = ("touchpad", "synaptics", "elan", "alps", "cirq", "trackpad")
        best_priority = 99
        for ev_path in sorted(glob.glob("/sys/class/input/event*/device/name")):
            dev_name = self._read_file_text(ev_path) or ""
            dev_low = dev_name.lower()
            if not any(k in dev_low for k in tp_keywords):
                continue
            parts = ev_path.split(os.sep)
            ev_dir = next((p for p in parts if p.startswith("event")), None)
            if not ev_dir:
                continue

            if "touchpad" in dev_low or "trackpad" in dev_low:
                priority = 1
            elif not dev_low.endswith((" mouse", " keyboard")):
                priority = 2
            else:
                priority = 3

            if priority < best_priority:
                best_priority = priority
                self._touchpad_event_name = ev_dir
                self._touchpad_device_name = dev_name
                if priority == 1:
                    break

        if not self._touchpad_event_name:
            self.features.touchpad_control = False
            return

        desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").lower()
        has_kde = bool(shutil.which("qdbus6") or shutil.which("qdbus")) and ("kde" in desktop or "plasma" in desktop or not desktop)
        has_x11 = bool(shutil.which("xinput") and os.environ.get("DISPLAY"))
        has_gnome = bool(shutil.which("gsettings") and "gnome" in desktop)
        self.features.touchpad_control = bool(has_kde or has_x11 or has_gnome)

    def _scan_undervolt(self) -> None:
        """Verifica se o processador e o sistema realmente suportam ajuste de tensão (Undervolt)."""
        vendor = self.get_cpu_vendor()
        if vendor == "Intel":
            model = self.system_info.cpu_model or ""
            is_locked_gen = False
            m_core = re.search(r"\bi[3579]-1[234]\d{2,3}([A-Za-z0-9]*)\b", model)
            if m_core:
                suffix = m_core.group(1).upper()
                if suffix not in ("HX", "HK", "K", "KF", "KS"):
                    is_locked_gen = True
            else:
                m_u = re.search(r"\bUltra\s+\d\s+\d{3}([A-Za-z]*)\b", model, re.IGNORECASE)
                if m_u and m_u.group(1).upper() not in ("HX", "HK", "K", "KF", "KS"):
                    is_locked_gen = True
            has_msr = bool(glob.glob("/dev/cpu/[0-9]*/msr") or shutil.which("wrmsr") or shutil.which("intel-undervolt"))
            self.features.cpu_undervolt = bool(has_msr and not is_locked_gen)
        elif vendor == "AMD":
            self.features.cpu_undervolt = bool(shutil.which("ryzenadj"))
        else:
            self.features.cpu_undervolt = False

    def _scan_network_power(self) -> None:
        """Detecta interface real de Wi-Fi para controle de economia de energia."""
        wifi_if = self._discover_wifi_interface()
        self.features.wifi_power_save = bool(wifi_if)

    def get_eco_travel_summary(self) -> str:
        """Retorna descrição dinâmica do Modo Viagem listando apenas ações ativas e suportadas neste notebook."""
        cfg = self.get_eco_travel_config()
        parts: List[str] = []
        if cfg["dim_brightness"] and self.features.screen_brightness:
            parts.append(f"Brilho {cfg['brightness_pct']}%")
        if cfg["conservation"] and self.features.conservation_mode:
            parts.append("Conservação 80%")
        if cfg["gpu_d3cold"] and self.paths.nvidia_pci_power_control:
            parts.append("GPU D3cold")
        if cfg["turbo_off"] and self.features.turbo_boost:
            parts.append("Turbo Off")
        if cfg["profile"] and self.features.platform_profile:
            parts.append("Low Power")
        if cfg["kbd_off"] and self.features.kbd_backlight:
            parts.append("Teclado Off")
        if cfg["tdp_limit"] and self.features.custom_tdp:
            parts.append("TDP 15W")
        if cfg["refresh_min"] and self.features.refresh_rate:
            parts.append("Hz Mín")
        if cfg["wifi_save"] and self.features.wifi_power_save:
            parts.append("Wi-Fi Eco")
        if not parts:
            return "Nenhuma ação selecionada (configure em Config. & Sistema)."
        return "1-Clique: " + " + ".join(parts[:4]) + ("..." if len(parts) > 4 else "")

    def get_detected_capabilities(self) -> List[Dict[str, str]]:
        """Retorna a lista de capacidades de hardware efetivamente liberadas por este notebook."""
        f = self.features
        caps: List[Dict[str, str]] = []
        if f.platform_profile:
            profs = ", ".join(p.upper() for p in (f.available_profiles or self.get_supported_canonical_profiles()))
            caps.append({"name": "Perfis Térmicos ACPI", "detail": profs or "Suportado"})
        if f.conservation_mode:
            caps.append({"name": "Conservação da Bateria", "detail": "Limite ~80% via EC"})
        if f.rapid_charge:
            caps.append({"name": "Carregamento Rápido", "detail": "Rapid Charge / Fast"})
        if f.fn_lock:
            caps.append({"name": "Trava de Teclas Fn", "detail": "Fn-Lock ACPI"})
        if f.camera_power:
            caps.append({"name": "Obturador da Câmera", "detail": "Privacy E-Shutter"})
        if f.usb_charging:
            caps.append({"name": "Always-On USB", "detail": "Carga USB em repouso"})
        if f.kbd_backlight:
            caps.append({"name": "Luz do Teclado", "detail": f"0..{f.kbd_max_brightness} níveis"})
        if f.rgb_keyboard:
            caps.append({"name": "Teclado RGB 4-Zonas", "detail": f"Backend {self._rgb_backend_name}"})
        if f.touchpad_control:
            caps.append({"name": "Trava do Touchpad", "detail": "Controle ativo"})
        if f.turbo_boost:
            caps.append({"name": "CPU Turbo Boost", "detail": "Intel/AMD Boost"})
        if f.cpu_governor:
            caps.append({"name": "CPU Scaling Governor", "detail": ", ".join(self.get_available_cpu_governors()[:3])})
        if f.custom_tdp:
            caps.append({"name": "Custom TDP (RAPL)", "detail": "Controle PL1 / PL2"})
        if f.fan_control:
            caps.append({"name": "Curva de Ventoinhas", "detail": "Controle EC / PWM"})
        if f.cpu_undervolt or f.wmi_gpu_ac_offset:
            uv_parts = []
            if f.cpu_undervolt:
                uv_parts.append("CPU Voltage")
            if f.wmi_gpu_ac_offset:
                uv_parts.append("WMI GPU Offset")
            caps.append({"name": "Undervolt / Power Offset", "detail": " + ".join(uv_parts)})
        if f.gpu_mux:
            mux = self.get_gpu_mux_info()
            if mux.available and mux.available_modes:
                caps.append({"name": "GPU MUX / Comutação", "detail": f"{mux.backend_name} ({'/'.join(mux.available_modes)})"})
        if f.refresh_rate:
            ref = self.get_display_refresh_info()
            if ref.available and len(ref.available_rates) > 1:
                rates_s = " / ".join(f"{r}Hz" for r in ref.available_rates)
                caps.append({"name": "Taxa de Atualização", "detail": rates_s})
        if f.lcd_overdrive:
            caps.append({"name": "LCD Overdrive", "detail": "Tempo de resposta GtG"})
        if f.bios_attributes:
            attrs = [
                a for a in self.get_bios_attributes()
                if a.attr_id.lower() not in self.PROMOTED_BIOS_ATTR_IDS
            ]
            if attrs:
                caps.append({"name": "BIOS Lenovo WMI", "detail": f"{len(attrs)} parâmetros"})
        if f.wifi_power_save:
            caps.append({"name": "Economia de Rede", "detail": "Wi-Fi"})
        if f.wmi_custom_power:
            caps.append({"name": "Potência Custom WMI", "detail": "cTGP GPU / Dynamic Boost / PPT"})
        if f.screen_brightness:
            caps.append({"name": "Brilho Automático de Tela", "detail": os.path.basename(self.paths.backlight_dir or "backlight")})
        if f.nvme_health:
            caps.append({"name": "Saúde & SMART NVMe", "detail": "Desgaste, TBW e Alerta Térmico"})
        return caps

    def _scan_hwmon(self) -> None:
        """Mapeia sensores térmicos e de rotação em /sys/class/hwmon/."""
        self._hwmon_pwm_nodes = []
        self._hwmon_fan_targets = []
        hwmon_dirs = sorted(glob.glob("/sys/class/hwmon/hwmon*"))
        cpu_sensor_names = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")
        fan_sensor_names = ("yogafan", "legion", "ideapad", "thinkpad", "asus", "dell_smm")

        for hdir in hwmon_dirs:
            name = (self._read_file_text(os.path.join(hdir, "name")) or "").lower()

            # Temperatura da CPU
            if any(k in name for k in cpu_sensor_names) and not self.paths.cpu_temp_input:
                t1 = os.path.join(hdir, "temp1_input")
                if os.path.exists(t1):
                    self.paths.cpu_temp_input = t1

            # Temperatura do SSD NVMe
            if ("nvme" in name or "drivetemp" in name) and not self.paths.nvme_temp_input:
                t1 = os.path.join(hdir, "temp1_input")
                if os.path.exists(t1):
                    self.paths.nvme_temp_input = t1

            # Temperatura da RAM (DDR5 spd5118)
            if "spd5118" in name and not self.paths.ram_temp_input:
                t1 = os.path.join(hdir, "temp1_input")
                if os.path.exists(t1):
                    self.paths.ram_temp_input = t1

            # Ventoinhas (Fan 1, Fan 2 e todos os nós PWM)
            f1 = os.path.join(hdir, "fan1_input")
            f2 = os.path.join(hdir, "fan2_input")
            if os.path.exists(f1):
                if any(k in name for k in fan_sensor_names) or not self.paths.fan1_input:
                    self.paths.fan1_input = f1
            if os.path.exists(f2):
                if any(k in name for k in fan_sensor_names) or not self.paths.fan2_input:
                    self.paths.fan2_input = f2

            try:
                dir_entries = sorted(os.listdir(hdir))
            except OSError:
                dir_entries = []
            for fn in dir_entries:
                if re.fullmatch(r"pwm\d+", fn):
                    pwm_p = os.path.join(hdir, fn)
                    en_p = os.path.join(hdir, f"{fn}_enable")
                    en_real = en_p if os.path.exists(en_p) else None
                    self._hwmon_pwm_nodes.append((pwm_p, en_real))
                    if not self.paths.hwmon_pwm1:
                        self.paths.hwmon_pwm1 = pwm_p
                    if en_real and not self.paths.hwmon_pwm1_enable:
                        self.paths.hwmon_pwm1_enable = en_real
                else:
                    m_ft = re.fullmatch(r"fan(\d+)_target", fn)
                    if m_ft:
                        fidx = m_ft.group(1)
                        tgt_p = os.path.join(hdir, fn)
                        en_p = os.path.join(hdir, f"pwm{fidx}_enable")
                        en_real = en_p if os.path.exists(en_p) else None
                        min_rpm = max(0, self._read_file_int(os.path.join(hdir, f"fan{fidx}_min"), default=1200))
                        max_rpm = max(min_rpm + 100, self._read_file_int(os.path.join(hdir, f"fan{fidx}_max"), default=5400))
                        self._hwmon_fan_targets.append((tgt_p, en_real, min_rpm, max_rpm))

    def _scan_gpus(self) -> None:
        """Identifica GPUs dedicadas (NVIDIA/AMD) e integradas (Intel/AMD) via DRM e NVML."""
        for card_path in sorted(glob.glob("/sys/class/drm/card[0-9]")):
            uevent = self._read_file_text(os.path.join(card_path, "device", "uevent")) or ""
            if "DRIVER=nvidia" in uevent or "10DE:" in uevent.upper():
                self.paths.nvidia_drm_card = card_path
                pci_ctrl = os.path.join(card_path, "device", "power", "control")
                if os.path.exists(pci_ctrl):
                    self.paths.nvidia_pci_power_control = pci_ctrl
            elif any(drv in uevent for drv in ("DRIVER=amdgpu", "DRIVER=i915", "DRIVER=xe")):
                if not self.paths.igpu_drm_card:
                    self.paths.igpu_drm_card = card_path

        self.nvidia_available = shutil.which("nvidia-smi") is not None or bool(self.paths.nvidia_drm_card)
        if HAS_PYNVML and self.nvidia_available:
            try:
                pynvml.nvmlInit()
                self._nvml_initialized = True
            except Exception:
                self._nvml_initialized = False

    @staticmethod
    def _format_short_gpu_name(full_name: str) -> str:
        """Extrai um nome curto limpo (ex: 'GPU RTX 3050', 'GPU RX 7600S', 'GPU Intel Iris')."""
        if not full_name:
            return "GPU"
        m = re.search(r"((?:RTX|GTX|RX|Arc)\s*[0-9]{3,4}(?:\s*Ti|\s*SUPER|\s*M|\s*S)?)", full_name, re.IGNORECASE)
        if m:
            return f"GPU {m.group(1).upper()}"
        if "radeon" in full_name.lower():
            return "GPU AMD Radeon"
        if "iris" in full_name.lower():
            return "GPU Intel Iris"
        if "uhd" in full_name.lower():
            return "GPU Intel UHD"
        if "intel" in full_name.lower():
            return "GPU Intel"
        cleaned = (
            full_name.replace("NVIDIA", "")
            .replace("GeForce", "")
            .replace("Laptop GPU", "")
            .replace("Advanced Micro Devices, Inc.", "")
            .strip()
        )
        return f"GPU {cleaned[:16].strip()}" if cleaned else "GPU"

    def _scan_system_info(self) -> None:
        """Lê DMI, BIOS, CPU, GPU e SSDs e adapta a identidade da linha Lenovo."""
        dmi_base = "/sys/class/dmi/id"
        self.system_info.product_name = self._read_file_text(f"{dmi_base}/product_name") or "Lenovo Notebook"
        self.system_info.product_version = self._read_file_text(f"{dmi_base}/product_version") or "Lenovo"
        self.system_info.product_family = self._read_file_text(f"{dmi_base}/product_family") or "Lenovo"
        self.system_info.board_name = self._read_file_text(f"{dmi_base}/board_name") or "N/A"
        self.system_info.sys_vendor = self._read_file_text(f"{dmi_base}/sys_vendor") or "LENOVO"
        self.system_info.bios_version = self._read_file_text(f"{dmi_base}/bios_version") or "N/A"
        self.system_info.bios_date = self._read_file_text(f"{dmi_base}/bios_date") or "N/A"
        self.system_info.kernel_version = platform.release()

        ver = self.system_info.product_version
        fam = self.system_info.product_family
        pname = self.system_info.product_name
        if ver and ver.lower() not in ("none", "default string", "invalid"):
            self.system_info.display_model_name = ver
        elif fam and fam.lower() not in ("none", "default string", "invalid"):
            self.system_info.display_model_name = fam
        else:
            self.system_info.display_model_name = pname

        combined = f"{ver} {fam} {pname}".upper()
        if "LEGION" in combined:
            self.system_info.laptop_line = "LEGION"
            self.system_info.edge_panel_title = "LEGION EDGE"
        elif "LOQ" in combined:
            self.system_info.laptop_line = "LOQ"
            self.system_info.edge_panel_title = "LOQ EDGE"
        else:
            if "YOGA" in combined:
                self.system_info.laptop_line = "YOGA"
            elif "IDEAPAD" in combined:
                self.system_info.laptop_line = "IDEAPAD"
            else:
                self.system_info.laptop_line = "LENOVO"
            self.system_info.edge_panel_title = "LENOVO EDGE • CONTROLES RÁPIDOS"

        os_release = self._read_file_text("/etc/os-release")
        if os_release:
            for line in os_release.splitlines():
                if line.startswith("PRETTY_NAME="):
                    self.system_info.os_name = line.split("=", 1)[1].strip('"')
                    break

        cpu_m = self.get_cpu_metrics()
        self.system_info.cpu_model = cpu_m.model_name

        gpu_m = self.get_gpu_metrics()
        self.system_info.gpu_model = gpu_m.name

        disks = self.get_storage_devices()
        if disks:
            self.system_info.ssd_summary = " | ".join(
                f"{d.model} ({d.total_gb:.0f} GB)" for d in disks
            )
        else:
            self.system_info.ssd_summary = "Armazenamento NVMe/SATA"

        self.system_info.has_write_permission = self.has_full_write_permissions()

    # =========================================================================
    # Detecção Infalível de Eventos (Polling de 200ms para Fn+Q, AC e Teclas)
    # =========================================================================
    @staticmethod
    def _discover_evdev_keyboard_candidates() -> List[Tuple[str, str]]:
        """
        Descobre nós /dev/input/event* de teclados e botões especiais Lenovo (ex: Ideapad extra buttons),
        descartando botões de energia/tampa/áudio e deduplicando symlinks (usb- vs usbv2-).
        """
        discovered: List[Tuple[str, str]] = []
        seen_paths: Set[str] = set()
        ignore_names = ("power button", "lid switch", "sleep button", "pc speaker", "video bus")
        hotkey_tokens = ("keyboard", "ideapad", "lenovo", "wmi", "hotkey", "extra buttons")

        proc_devices = "/proc/bus/input/devices"
        if os.path.exists(proc_devices):
            try:
                with open(proc_devices, "r", encoding="utf-8", errors="ignore") as f:
                    blocks = f.read().strip().split("\n\n")
                for block in blocks:
                    lines = block.splitlines()
                    name = next((l[8:].strip('"') for l in lines if l.startswith("N: Name=")), "")
                    handlers = next((l[12:] for l in lines if l.startswith("H: Handlers=")), "")
                    name_low = name.lower()
                    if any(tok in name_low for tok in ignore_names):
                        continue
                    has_kbd = "kbd" in handlers.split()
                    has_hotkey_name = any(tok in name_low for tok in hotkey_tokens)
                    if not (has_kbd or has_hotkey_name):
                        continue
                    ev_token = next((h for h in handlers.split() if h.startswith("event")), None)
                    if not ev_token:
                        continue
                    dev_path = f"/dev/input/{ev_token}"
                    real = os.path.realpath(dev_path)
                    if real not in seen_paths:
                        seen_paths.add(real)
                        discovered.append((dev_path, name or ev_token))
            except Exception:
                pass

        for sym in sorted(glob.glob("/dev/input/by-path/*kbd*") + glob.glob("/dev/input/by-path/*VPC*")):
            real = os.path.realpath(sym)
            if real not in seen_paths:
                seen_paths.add(real)
                discovered.append((sym, os.path.basename(sym)))

        return discovered

    def _init_evdev_listeners(self) -> None:
        """Abre dispositivos de teclado/hotkeys em /dev/input deduplicados e não-bloqueantes."""
        for fd in list(self._input_fds):
            try:
                os.close(fd)
            except Exception:
                pass
        self._input_fds.clear()
        self._input_fd_info.clear()
        self._evdev_held_mods.clear()

        seen_rdevs: Set[Tuple[int, int]] = set()
        seen_reals: Set[str] = set()
        for dev, dev_name in self._discover_evdev_keyboard_candidates():
            if not (os.path.exists(dev) and os.access(dev, os.R_OK)):
                continue
            real = os.path.realpath(dev)
            if real in seen_reals:
                continue
            try:
                st = os.stat(real)
                rdev = int(getattr(st, "st_rdev", 0) or 0)
                rdev_key = (int(getattr(st, "st_mode", 0) or 0) & 0o170000, rdev)
                if rdev and rdev_key in seen_rdevs:
                    continue
                fd = os.open(real, os.O_RDONLY | os.O_NONBLOCK)
                seen_reals.add(real)
                if rdev:
                    seen_rdevs.add(rdev_key)
                self._input_fds.append(fd)
                self._input_fd_info[fd] = {"path": real, "name": dev_name}
                self._evdev_held_mods[fd] = set()
            except Exception:
                pass

    def get_evdev_monitored_devices(self) -> List[str]:
        """Lista legível dos dispositivos monitorados pelo leitor evdev (sem duplicatas)."""
        if not self._input_fds:
            self._init_evdev_listeners()
        items: List[str] = []
        for fd in list(self._input_fds):
            info = self._input_fd_info.get(fd)
            if info:
                items.append(f"{info['name']} ({os.path.basename(info['path'])})")
            else:
                items.append(f"fd:{fd}")
        return items

    def _drain_evdev_events(self) -> None:
        """Esvazia eventos pendentes nos descritores evdev sem bloquear."""
        event_size = struct.calcsize("llHHi")
        for fd in list(self._input_fds):
            try:
                while True:
                    data = os.read(fd, event_size * 32)
                    if not data:
                        break
            except (BlockingIOError, OSError):
                continue

    def start_evdev_capture(self) -> bool:
        """Inicia captura em tempo real de uma tecla/atalho diretamente pelo kernel (evdev)."""
        if not self._input_fds:
            self._init_evdev_listeners()
        if not self._input_fds:
            return False
        self._drain_evdev_events()
        self._evdev_capture_mods.clear()
        self._evdev_capture_active = True
        return True

    def stop_evdev_capture(self) -> None:
        """Encerra a captura live via evdev e aplica breve cooldown contra disparo acidental."""
        self._drain_evdev_events()
        self._evdev_capture_active = False
        self._evdev_capture_mods.clear()
        for fd in list(self._input_fds):
            self._evdev_held_mods[fd] = set()
        self._evdev_capture_cooldown_until = time.time() + 0.45

    def get_evdev_capture_preview(self) -> str:
        """Retorna prévia dos modificadores segurados durante a captura (ex: 'Meta+Shift+...')."""
        mods = normalize_modifiers(MODIFIER_EVDEV_MAP[c] for c in self._evdev_capture_mods if c in MODIFIER_EVDEV_MAP)
        if mods:
            return "+".join(mods) + "+..."
        return ""

    def poll_evdev_capture(self) -> Optional[Dict[str, Any]]:
        """Lê o próximo evento de tecla real no evdev durante o modo de captura do botão."""
        if not self._evdev_capture_active:
            return None

        event_size = struct.calcsize("llHHi")
        dead_fds: List[int] = []
        captured: Optional[Dict[str, Any]] = None

        for fd in list(self._input_fds):
            try:
                while True:
                    data = os.read(fd, event_size * 32)
                    if not data:
                        dead_fds.append(fd)
                        break
                    for offset in range(0, len(data) - event_size + 1, event_size):
                        _sec, _usec, ev_type, ev_code, ev_val = struct.unpack(
                            "llHHi", data[offset:offset + event_size]
                        )
                        if ev_type != 1:
                            continue
                        if ev_code in MODIFIER_EVDEV_MAP:
                            if ev_val in (1, 2):
                                self._evdev_capture_mods.add(ev_code)
                            elif ev_val == 0:
                                self._evdev_capture_mods.discard(ev_code)
                            continue
                        if ev_val == 1:
                            if ev_code == 1:  # KEY_ESC
                                captured = {"cancelled": True}
                            else:
                                mods = normalize_modifiers(
                                    MODIFIER_EVDEV_MAP[c]
                                    for c in self._evdev_capture_mods
                                    if c in MODIFIER_EVDEV_MAP
                                )
                                captured = {
                                    "cancelled": False,
                                    "evdev_code": int(ev_code),
                                    "evdev_modifiers": mods,
                                    "qt_shortcut": format_shortcut(int(ev_code), mods),
                                }
                            break
                    if captured is not None:
                        break
            except BlockingIOError:
                pass
            except (OSError, Exception):
                dead_fds.append(fd)
            if captured is not None:
                break

        if dead_fds:
            for fd in dead_fds:
                try:
                    os.close(fd)
                except Exception:
                    pass
                if fd in self._input_fds:
                    self._input_fds.remove(fd)
                self._input_fd_info.pop(fd, None)
                self._evdev_held_mods.pop(fd, None)

        if captured is not None:
            self.stop_evdev_capture()
        return captured

    def _poll_evdev_keys(self) -> List[Dict[str, Any]]:
        """Lê pacotes struct input_event (24 bytes em 64-bit) para capturar Copilot (F8/F23), F24 e atalhos globais."""
        triggered: List[Dict[str, Any]] = []
        if self._evdev_capture_active:
            return triggered

        now = time.time()
        if not self._input_fds:
            if now - getattr(self, "_last_evdev_scan_time", 0.0) > 5.0:
                self._last_evdev_scan_time = now
                self._init_evdev_listeners()
            if not self._input_fds:
                return triggered

        mappings = self.get_key_mappings()
        active_slots = [(sid, cfg) for sid, cfg in mappings.items() if cfg.get("enabled", True)]

        event_size = struct.calcsize("llHHi")
        dead_fds: List[int] = []
        for fd in list(self._input_fds):
            held_set = self._evdev_held_mods.setdefault(fd, set())
            try:
                while True:
                    data = os.read(fd, event_size * 32)
                    if not data:
                        dead_fds.append(fd)
                        break
                    for offset in range(0, len(data) - event_size + 1, event_size):
                        _sec, _usec, ev_type, ev_code, ev_val = struct.unpack(
                            "llHHi", data[offset:offset + event_size]
                        )
                        if ev_type != 1:
                            continue
                        if ev_code in MODIFIER_EVDEV_MAP:
                            if ev_val in (1, 2):
                                held_set.add(ev_code)
                            elif ev_val == 0:
                                held_set.discard(ev_code)
                            continue

                        # ev_val == 1 (Key Down; ignora auto-repeat ev_val == 2 e Key Up 0)
                        if ev_val != 1:
                            continue
                        if now < self._evdev_capture_cooldown_until:
                            continue

                        all_held_codes: Set[int] = set()
                        for mset in self._evdev_held_mods.values():
                            all_held_codes.update(mset)
                        held_mods = {
                            MODIFIER_EVDEV_MAP[c] for c in all_held_codes if c in MODIFIER_EVDEV_MAP
                        }

                        for slot_id, cfg in active_slots:
                            if not matches_evdev_trigger(cfg, ev_code, held_mods):
                                continue
                            last_ts = self._evdev_last_trigger_ts.get(slot_id, 0.0)
                            if (now - last_ts) < 0.35:
                                break
                            self._evdev_last_trigger_ts[slot_id] = now
                            triggered.append({
                                "type": "custom_key_pressed",
                                "slot": slot_id,
                                "action": cfg.get("action", "cycle_profile"),
                                "custom_command": cfg.get("custom_command", ""),
                            })
                            break
            except BlockingIOError:
                continue
            except (OSError, Exception):
                dead_fds.append(fd)
                continue

        if dead_fds:
            for fd in dead_fds:
                try:
                    os.close(fd)
                except Exception:
                    pass
                if fd in self._input_fds:
                    self._input_fds.remove(fd)
                self._input_fd_info.pop(fd, None)
                self._evdev_held_mods.pop(fd, None)

        return triggered

    def _get_ac_online(self) -> int:
        if self.paths.adapter_online:
            return self._read_file_int(self.paths.adapter_online, default=1)
        return 1

    @classmethod
    def normalize_profile(cls, raw_profile: Optional[str]) -> str:
        """
        Traduz qualquer string de perfil (do kernel sysfs, CLI ou UI) para o identificador
        canônico universal: 'low-power', 'balanced', 'performance', 'max-power' ou 'custom'.
        """
        if not raw_profile:
            return "balanced"
        cleaned = raw_profile.lower().strip()
        if cleaned in cls.PROFILE_MAP:
            return cls.PROFILE_MAP[cleaned]
        if "max" in cleaned or "extrem" in cleaned:
            return "max-power"
        if "perf" in cleaned:
            return "performance"
        if "low" in cleaned or "quiet" in cleaned or "silenc" in cleaned:
            return "low-power"
        if "bal" in cleaned or "equil" in cleaned:
            return "balanced"
        return cleaned

    @classmethod
    def get_profile_info(cls, profile: Optional[str] = None) -> Dict[str, str]:
        """Retorna os metadados visuais (título, OSD, ícone, cor e badge) do perfil informado."""
        norm = cls.normalize_profile(profile)
        return dict(cls.PROFILE_DETAILS.get(norm, cls.PROFILE_DETAILS["balanced"]))

    def _sync_platform_profile_cache(self, raw_norm: str) -> None:
        """Mantém a cache de todos os nós monitorados de platform_profile sincronizada após escrita programática."""
        for p in self._platform_profile_paths:
            self._last_profile_by_path[p] = raw_norm

    def _ensure_custom_profile_for_wmi(self, path: Optional[str], allow_elevation: bool = True) -> bool:
        """
        No driver kernel `lenovo_wmi_other`, atributos de firmware (limites térmicos, PPT, cTGP, AC Offset)
        exigem que `platform_profile` esteja em 'custom' (retornando EBUSY caso contrário).
        Alterna automaticamente para 'custom' quando necessário antes da escrita.
        """
        if not path or "lenovo-wmi-other" not in path or not self.paths.platform_profile:
            return False
        choices = [c.lower().strip() for c in self.get_platform_profile_choices()]
        if "custom" not in choices:
            return False
        if self._read_raw_platform_profile() == "custom":
            return False

        ok, _ = PermissionsManager.write_sysfs_value(self.paths.platform_profile, "custom", allow_elevation=allow_elevation)
        if ok:
            self._max_power_active = False
            self._promoted_max_power_from_low = False
            self._last_raw_profile = "custom"
            self._last_profile = "custom"
            self._sync_platform_profile_cache("custom")
            time.sleep(0.05)
            return True
        return False

    def _apply_max_power_fan_boost(self, enable: bool, allow_elevation: bool = False) -> None:
        """
        Quando o perfil 'max-power' é ativado (e não há curva customizada ativa), aciona o modo de
        rotação máxima nos nós reais de hardware suportados (fan_fullspeed, hwmon pwm* ou fan_mode legado).
        """
        if bool(self.settings.get("custom_fan_curve_enabled", False)):
            return

        if self._fan_fullspeed_path and os.path.exists(self._fan_fullspeed_path):
            target = "1" if enable else "0"
            if allow_elevation or os.access(self._fan_fullspeed_path, os.W_OK):
                PermissionsManager.write_sysfs_value(self._fan_fullspeed_path, target, allow_elevation=allow_elevation)
            return

        pwm_nodes = list(self._hwmon_pwm_nodes)
        if not pwm_nodes and self.paths.hwmon_pwm1:
            pwm_nodes = [(self.paths.hwmon_pwm1, self.paths.hwmon_pwm1_enable)]

        if pwm_nodes:
            for pwm_p, en_p in pwm_nodes:
                if enable:
                    if en_p and os.path.exists(en_p) and (allow_elevation or os.access(en_p, os.W_OK)):
                        PermissionsManager.write_sysfs_value(en_p, "1", allow_elevation=allow_elevation)
                    if os.path.exists(pwm_p) and (allow_elevation or os.access(pwm_p, os.W_OK)):
                        PermissionsManager.write_sysfs_value(pwm_p, "255", allow_elevation=allow_elevation)
                else:
                    if en_p and os.path.exists(en_p) and (allow_elevation or os.access(en_p, os.W_OK)):
                        PermissionsManager.write_sysfs_value(en_p, "2", allow_elevation=allow_elevation)
            return

        fan_targets = list(getattr(self, "_hwmon_fan_targets", []) or [])
        if fan_targets:
            for tgt_p, en_p, _min_r, max_r in fan_targets:
                if enable:
                    if en_p and os.path.exists(en_p) and (allow_elevation or os.access(en_p, os.W_OK)):
                        PermissionsManager.write_sysfs_value(en_p, "1", allow_elevation=allow_elevation)
                    if os.path.exists(tgt_p) and (allow_elevation or os.access(tgt_p, os.W_OK)):
                        PermissionsManager.write_sysfs_value(tgt_p, str(max_r), allow_elevation=allow_elevation)
                else:
                    if en_p and os.path.exists(en_p) and (allow_elevation or os.access(en_p, os.W_OK)):
                        PermissionsManager.write_sysfs_value(en_p, "2", allow_elevation=allow_elevation)
            return

        if self.paths.fan_mode and os.path.exists(self.paths.fan_mode) and not self._is_wmi_gamezone:
            target = "2" if enable else "1"
            if allow_elevation or os.access(self.paths.fan_mode, os.W_OK):
                PermissionsManager.write_sysfs_value(self.paths.fan_mode, target, allow_elevation=allow_elevation)

    def _sync_cpu_epp_for_profile(self, profile: str) -> bool:
        """
        Sincroniza `energy_performance_preference` (EPP) da CPU de acordo com o perfil térmico.
        Corrige o fallback do power-profiles-daemon que derruba 'max-power' para 'balance_performance'.
        """
        norm = self.normalize_profile(profile)
        target_map = {
            "max-power": "performance",
            "performance": "performance",
            "balanced": "balance_performance",
            "low-power": "power",
            "quiet": "power",
        }
        target_epp = target_map.get(norm)
        if not target_epp:
            return False

        epp_files = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/energy_performance_preference"))
        if not epp_files or not os.access(epp_files[0], os.W_OK):
            return False

        avail_path = os.path.join(os.path.dirname(epp_files[0]), "energy_performance_available_preferences")
        avail_txt = (self._read_file_text(avail_path) or "").split()
        if avail_txt:
            if target_epp not in avail_txt:
                if target_epp == "power" and "balance_power" in avail_txt:
                    target_epp = "balance_power"
                else:
                    return False

        cur_epp = (self._read_file_text(epp_files[0]) or "").strip()
        if cur_epp == target_epp:
            return False

        wrote_any = False
        for ef in epp_files:
            try:
                if os.access(ef, os.W_OK):
                    with open(ef, "w", encoding="utf-8") as f:
                        f.write(target_epp)
                    wrote_any = True
            except OSError:
                continue
        return wrote_any

    def _read_raw_platform_profile(self) -> str:
        """
        Lê diretamente o nó ativo de platform_profile (class/platform-profile e/ou acpi/platform_profile)
        e normaliza o identificador. Quando múltiplos nós de perfil existem no kernel, detecta mudanças
        em qualquer um deles para garantir captura imediata do atalho físico Fn+Q.
        """
        primary_path = self.paths.platform_profile
        # Se um teste ou override manual apontou para um arquivo customizado fora da lista descoberta
        if primary_path and primary_path not in self._platform_profile_paths:
            val = self._read_file_text(primary_path)
            return self.normalize_profile(val) if val else "balanced"

        monitored = list(self._platform_profile_paths)
        if primary_path and primary_path not in monitored:
            monitored.insert(0, primary_path)

        changed_norm: Optional[str] = None
        first_norm: Optional[str] = None
        for p in monitored:
            val = self._read_file_text(p)
            if not val:
                continue
            norm = self.normalize_profile(val)
            if first_norm is None:
                first_norm = norm
            prev = self._last_profile_by_path.get(p)
            if prev is not None and prev != norm and changed_norm is None:
                changed_norm = norm
            self._last_profile_by_path[p] = norm

        if changed_norm is not None:
            # Sincroniza a memória dos demais nós para evitar falso-positivo no próximo ciclo
            for p in monitored:
                self._last_profile_by_path[p] = changed_norm
            return changed_norm

        if first_norm is not None:
            return first_norm

        val = self._read_file_text(primary_path)
        return self.normalize_profile(val) if val else "balanced"

    def fast_poll_changes(self) -> List[Dict[str, Any]]:
        """
        Executado a cada 200ms pelo QTimer.
        Compara o estado em memória com os arquivos virtuais do sysfs para capturar
        instantaneamente o atalho físico Fn+Q do teclado, eventos de energia e teclas especiais,
        com suporte nativo e completo ao modo 'max-power' (Desempenho Máximo).
        """
        events = []

        # 1. Verificar Perfil de Plataforma (Fn + Q) com reconhecimento nativo do 'max-power'
        raw_prof = self._read_raw_platform_profile()
        if raw_prof and raw_prof != self._last_raw_profile:
            old_p = self._last_profile
            prev_raw = self._last_raw_profile
            current_prof = raw_prof

            # Caso A: O próprio kernel retornou 'max-power' diretamente em platform_profile
            if raw_prof == "max-power":
                current_prof = "max-power"
                self._max_power_active = True
                self._promoted_max_power_from_low = False
                self._last_raw_profile = "max-power"
                self._last_profile = "max-power"
                self._apply_max_power_fan_boost(True, allow_elevation=False)

            # Caso B: Hardware suporta 'max-power' e o EC cicla apenas 3 modos (low-power <-> balanced <-> performance)
            elif self.features.max_power_profile and self.paths.platform_profile:
                if old_p == "performance" and raw_prof in ("low-power", "quiet"):
                    ok, _ = PermissionsManager.write_sysfs_value(self.paths.platform_profile, "max-power", allow_elevation=False)
                    if ok:
                        raw_after = self._read_raw_platform_profile()
                        current_prof = "max-power"
                        self._max_power_active = True
                        self._promoted_max_power_from_low = True
                        self._last_raw_profile = raw_after
                        self._last_profile = "max-power"
                        self._sync_platform_profile_cache(raw_after)
                        self._apply_max_power_fan_boost(True, allow_elevation=False)
                    else:
                        self._max_power_active = False
                        self._promoted_max_power_from_low = False
                        self._last_raw_profile = raw_prof
                        self._last_profile = current_prof
                elif old_p == "max-power":
                    # Saindo de 'max-power' pelo próximo Fn+Q físico: garante retorno ao Modo Silencioso
                    self._max_power_active = False
                    self._apply_max_power_fan_boost(False, allow_elevation=False)
                    was_promoted = self._promoted_max_power_from_low
                    self._promoted_max_power_from_low = False
                    if raw_prof in ("low-power", "quiet"):
                        current_prof = "low-power"
                        self._last_raw_profile = raw_prof
                        self._last_profile = "low-power"
                    elif (was_promoted or prev_raw in ("max-power", "low-power", "quiet")) and raw_prof == "balanced":
                        choices = self.get_platform_profile_choices()
                        low_target = "low-power" if "low-power" in choices else ("quiet" if "quiet" in choices else raw_prof)
                        ok, _ = PermissionsManager.write_sysfs_value(self.paths.platform_profile, low_target, allow_elevation=False)
                        if ok:
                            raw_after = self._read_raw_platform_profile()
                            current_prof = "low-power"
                            self._last_raw_profile = raw_after
                            self._last_profile = "low-power"
                            self._sync_platform_profile_cache(raw_after)
                        else:
                            self._last_raw_profile = raw_prof
                            self._last_profile = current_prof
                    else:
                        self._last_raw_profile = raw_prof
                        self._last_profile = current_prof
                else:
                    self._max_power_active = False
                    self._promoted_max_power_from_low = False
                    self._last_raw_profile = raw_prof
                    self._last_profile = current_prof
                    self._apply_max_power_fan_boost(False, allow_elevation=False)
            else:
                self._max_power_active = (current_prof == "max-power")
                self._promoted_max_power_from_low = False
                self._last_raw_profile = raw_prof
                self._last_profile = current_prof
                self._apply_max_power_fan_boost(current_prof == "max-power", allow_elevation=False)

            self._sync_cpu_epp_for_profile(current_prof)
            events.append({
                "type": "profile_changed",
                "old": old_p,
                "new": current_prof,
                "info": self.get_profile_info(current_prof)
            })
        elif self._last_profile == "max-power":
            # Vence a corrida caso power-profiles-daemon derrube EPP para balance_performance
            self._sync_cpu_epp_for_profile("max-power")

        # 2. Verificar Conexão/Desconexão do Carregador AC
        current_ac = self._get_ac_online()
        if current_ac != self._last_ac_online:
            self._last_ac_online = current_ac
            events.append({
                "type": "ac_changed",
                "ac_online": (current_ac == 1)
            })

            # Transição Automática de Energia (AC vs Bateria)
            if self.get_auto_power_transition() and self.features.platform_profile:
                if current_ac == 0:
                    target = self.get_battery_profile()
                    self.set_platform_profile(target, allow_elevation=False)
                else:
                    target = self.get_ac_profile()
                    self.set_platform_profile(target, allow_elevation=False)

            # Transição Automática de Taxa de Atualização de Tela (AC vs Bateria)
            if self.get_auto_refresh_rate_transition() and self.features.refresh_rate:
                try:
                    info = self.get_display_refresh_info()
                    if info.available and len(info.available_rates) > 1:
                        target_hz = min(info.available_rates) if current_ac == 0 else max(info.available_rates)
                        if target_hz != info.current_hz:
                            ok_hz, _ = self.set_refresh_rate(target_hz)
                            if ok_hz:
                                events.append({
                                    "type": "refresh_rate_changed",
                                    "hz": target_hz,
                                    "reason": "battery" if current_ac == 0 else "ac"
                                })
                except Exception:
                    pass

        # 3. Verificar Fn-Lock
        if self.paths.fn_lock:
            cur_fn = self.get_fn_lock()
            if cur_fn != self._last_fn_lock:
                self._last_fn_lock = cur_fn
                events.append({"type": "fn_lock_changed", "value": cur_fn})

        # 4. Verificar Camera Power
        if self.paths.camera_power:
            cur_cam = self.get_camera_power()
            if cur_cam != self._last_camera:
                self._last_camera = cur_cam
                events.append({"type": "camera_changed", "value": cur_cam})

        # 5. Verificar Modo de Conservação
        if self.paths.conservation_mode:
            cur_cons = self.get_conservation_mode()
            if cur_cons != self._last_conservation:
                self._last_conservation = cur_cons
                events.append({"type": "conservation_changed", "value": cur_cons})

        # 6. Verificar Brilho do Teclado (Fn + Espaço)
        if self.paths.kbd_backlight:
            cur_kbd = self.get_kbd_backlight()
            if cur_kbd != self._last_kbd_bright:
                self._last_kbd_bright = cur_kbd
                events.append({"type": "kbd_backlight_changed", "value": cur_kbd})

        # 7. Verificar Teclas Órfãs / Copilot via evdev não-bloqueante
        ev_keys = self._poll_evdev_keys()
        if ev_keys:
            events.extend(ev_keys)

        return events

    # =========================================================================
    # ELITE 1: Perfis Dinâmicos do Kernel (Suporte nativo a 'max-power')
    # =========================================================================
    def get_platform_profile(self) -> str:
        """
        Lê dinamicamente /sys/firmware/acpi/platform_profile e retorna o perfil canônico ativo
        ('low-power', 'balanced', 'performance', 'max-power' ou 'custom').
        """
        raw_prof = self._read_raw_platform_profile()
        if raw_prof == "max-power":
            self._max_power_active = True
            self._last_raw_profile = "max-power"
            self._last_profile = "max-power"
            return "max-power"
        if self._max_power_active and raw_prof == self._last_raw_profile:
            return "max-power"
        return raw_prof

    def get_platform_profile_choices(self) -> List[str]:
        val = self._read_file_text(self.paths.platform_profile_choices)
        if val:
            return val.split()
        if self.features.platform_profile:
            return ["low-power", "balanced", "performance"]
        return []

    def get_supported_canonical_profiles(self) -> List[str]:
        """Retorna os perfis canônicos ('low-power', 'balanced', 'performance', 'max-power') realmente suportados pelo kernel."""
        if not self.features.platform_profile:
            return []
        raw_choices = [c.lower().strip() for c in self.get_platform_profile_choices()]
        ordered: List[str] = []
        if any(c in raw_choices for c in ("low-power", "quiet", "low_power", "power-saver")):
            ordered.append("low-power")
        if any(c in raw_choices for c in ("balanced", "balanced_performance")):
            ordered.append("balanced")
        if "performance" in raw_choices:
            ordered.append("performance")
        if any(c in raw_choices for c in ("max-power", "max_power", "maxpower", "extreme")):
            ordered.append("max-power")
        return ordered

    def set_platform_profile(self, profile: str, allow_elevation: bool = True) -> Tuple[bool, str]:
        """
        Escreve o perfil térmico desejado ('low-power', 'balanced', 'performance' ou 'max-power')
        em /sys/firmware/acpi/platform_profile e sincroniza o estado ativo da interface e do Fn+Q.
        """
        if not self.paths.platform_profile:
            return False, "Controle de perfil ACPI não suportado neste dispositivo."

        norm_profile = self.normalize_profile(profile)
        choices = self.get_platform_profile_choices()
        kernel_target = norm_profile

        if kernel_target not in choices:
            if kernel_target == "low-power" and "quiet" in choices:
                kernel_target = "quiet"
            elif kernel_target == "quiet" and "low-power" in choices:
                kernel_target = "low-power"
                norm_profile = "low-power"
            elif kernel_target == "max-power" and "max-power" in choices:
                kernel_target = "max-power"
            elif kernel_target == "max-power" and "performance" in choices:
                kernel_target = "performance"
            else:
                return False, f"Perfil '{profile}' não suportado. Opções: {choices}"

        ok, msg = PermissionsManager.write_sysfs_value(self.paths.platform_profile, kernel_target, allow_elevation=allow_elevation)
        if ok:
            raw_after = self._read_raw_platform_profile()
            self._max_power_active = (norm_profile == "max-power")
            self._promoted_max_power_from_low = False
            self._last_raw_profile = raw_after
            self._last_profile = norm_profile
            self._sync_platform_profile_cache(raw_after)
            self._apply_max_power_fan_boost(norm_profile == "max-power", allow_elevation=False)
            self._sync_cpu_epp_for_profile(norm_profile)
            # Se o usuário trocou manualmente para performance/max-power, sai do Eco-Mode restaurando brilho/estado
            if norm_profile in ("performance", "max-power") and self.get_eco_travel_mode() and not getattr(self, "_restoring_eco_mode", False):
                self._restore_eco_side_effects(restore_profile=False)
        return ok, msg

    def cycle_next_profile(self) -> Tuple[bool, str]:
        """
        Alterna ciclicamente entre os perfis térmicos suportados pelo kernel (Fn + Q):
        low-power (Silencioso) -> balanced (Equilibrado) -> performance (Desempenho) -> max-power (Max-Power) -> low-power.
        """
        raw_choices = self.get_platform_profile_choices()
        choices: List[str] = []
        if "low-power" in raw_choices or "quiet" in raw_choices:
            choices.append("low-power")
        if "balanced" in raw_choices:
            choices.append("balanced")
        if "performance" in raw_choices:
            choices.append("performance")
        if "max-power" in raw_choices or self.features.max_power_profile:
            choices.append("max-power")

        if not choices:
            choices = ["low-power", "balanced", "performance"]

        cur = self.get_platform_profile()
        try:
            idx = choices.index(cur)
            next_prof = choices[(idx + 1) % len(choices)]
        except ValueError:
            next_prof = "balanced"
        ok, _ = self.set_platform_profile(next_prof)
        return ok, next_prof

