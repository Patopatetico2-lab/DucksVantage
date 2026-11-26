"""
Modelos de dados tipados para o Ducksvantage (core/models.py).
Arquitetura universal e agnóstica para toda a linha Lenovo (Legion, LOQ, IdeaPad, Yoga).
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CPUMetrics:
    usage_percent: float = 0.0
    temperature_c: float = 0.0
    frequency_mhz: float = 0.0
    cores_count: int = 0
    model_name: str = "Processador"
    vendor: str = "Generic"
    turbo_supported: bool = False
    turbo_enabled: bool = True
    governor: str = "powersave"
    available_governors: List[str] = field(default_factory=list)
    pl_supported: bool = False
    pl1_w: int = 45
    pl2_w: int = 70
    pl_max_w: int = 115


@dataclass
class GPUMetrics:
    available: bool = False
    vendor: str = "Generic"
    name: str = "Placa Gráfica"
    short_name: str = "GPU"
    runtime_state: str = "Ativa"
    temperature_c: float = 0.0
    utilization_percent: int = 0
    clock_mhz: int = 0
    memory_used_mb: int = 0
    memory_total_mb: int = 0
    power_draw_w: float = 0.0
    pstate: str = "P0"
    throttle_reasons: List[str] = field(default_factory=list)

    @property
    def memory_percent(self) -> float:
        if self.memory_total_mb > 0:
            return (self.memory_used_mb / self.memory_total_mb) * 100.0
        return 0.0


@dataclass
class RAMMetrics:
    usage_percent: float = 0.0
    used_gb: float = 0.0
    total_gb: float = 0.0
    free_gb: float = 0.0
    temperature_c: float = 0.0


@dataclass
class StorageDevice:
    device_name: str = "nvme0n1"
    model: str = "Unidade SSD"
    mountpoint: str = "/"
    used_gb: float = 0.0
    total_gb: float = 0.0
    usage_percent: float = 0.0
    temperature_c: float = 0.0


@dataclass
class FanMetrics:
    available: bool = False
    rpm: int = 0
    second_rpm: int = 0
    ec_fan_mode: int = 0
    name: str = "Sistema de Refrigeração"
    status_label: str = "Automático"


@dataclass
class BatteryInfo:
    available: bool = False
    capacity_percent: int = 0
    status: str = "Desconhecido"
    power_draw_w: float = 0.0
    voltage_v: float = 0.0
    temperature_c: float = 0.0
    energy_now_wh: float = 0.0
    energy_full_wh: float = 0.0
    energy_design_wh: float = 0.0
    health_percent: float = 100.0
    cycle_count: int = 0
    manufacturer: str = "N/A"
    model_name: str = "N/A"
    technology: str = "Li-poly"
    ac_connected: bool = True
    conservation_mode_supported: bool = False
    conservation_mode_active: bool = False
    rapid_charge_supported: bool = False
    rapid_charge_active: bool = False
    estimated_minutes: Optional[int] = None
    estimated_label: str = ""


@dataclass
class BatteryHistoryEntry:
    timestamp: str = ""
    energy_full_wh: float = 0.0
    energy_design_wh: float = 0.0
    health_percent: float = 100.0
    cycle_count: int = 0
    conservation_active: bool = True
    is_estimated: bool = False

    @property
    def date(self) -> str:
        return self.timestamp


@dataclass
class SystemInfo:
    product_name: str = "Lenovo Notebook"
    product_version: str = "Lenovo"
    product_family: str = "Lenovo"
    board_name: str = "N/A"
    sys_vendor: str = "LENOVO"
    bios_version: str = "N/A"
    bios_date: str = "N/A"
    kernel_version: str = "Linux"
    os_name: str = "Linux"
    cpu_model: str = "Processador"
    gpu_model: str = "Placa Gráfica"
    ssd_summary: str = "SSD NVMe"
    laptop_line: str = "LENOVO"
    edge_panel_title: str = "LENOVO EDGE • CONTROLES RÁPIDOS"
    display_model_name: str = "Lenovo"
    has_write_permission: bool = False


@dataclass
class HardwareFeatures:
    platform_profile: bool = False
    available_profiles: List[str] = field(default_factory=list)
    max_power_profile: bool = False
    conservation_mode: bool = False
    rapid_charge: bool = False
    fn_lock: bool = False
    camera_power: bool = False
    usb_charging: bool = False
    kbd_backlight: bool = False
    kbd_max_brightness: int = 2
    turbo_boost: bool = False
    cpu_governor: bool = False
    custom_tdp: bool = False
    fan_control: bool = False
    wmi_cpu_temp: bool = False
    wmi_gpu_temp: bool = False
    cpu_undervolt: bool = False
    wmi_gpu_ac_offset: bool = False
    touchpad_control: bool = False
    gpu_telemetry: bool = False
    gpu_mux: bool = False
    refresh_rate: bool = False
    lcd_overdrive: bool = False
    bios_attributes: bool = False
    battery: bool = False
    wifi_power_save: bool = False
    eth_power_save: bool = False
    eco_travel: bool = False
    rgb_keyboard: bool = False
    cinema_mode: bool = False
    audio_control: bool = False
    usb_wakeup: bool = False
    external_monitor_dock: bool = False
    thermal_throttling: bool = False


@dataclass
class HardwarePaths:
    ideapad_dir: Optional[str] = None
    platform_profile: Optional[str] = None
    platform_profile_choices: Optional[str] = None
    conservation_mode: Optional[str] = None
    rapid_charge: Optional[str] = None
    charge_types: Optional[str] = None
    fn_lock: Optional[str] = None
    camera_power: Optional[str] = None
    usb_charging: Optional[str] = None
    touchpad: Optional[str] = None
    fan_mode: Optional[str] = None
    kbd_backlight: Optional[str] = None
    kbd_max_backlight: Optional[str] = None
    cpu_turbo_intel: Optional[str] = None
    cpu_turbo_amd: Optional[str] = None
    cpu_governor: Optional[str] = None
    cpu_available_governors: Optional[str] = None
    rapl_pl1: Optional[str] = None
    rapl_pl2: Optional[str] = None
    rapl_mmio_pl1: Optional[str] = None
    rapl_mmio_pl2: Optional[str] = None
    cpu_temp_input: Optional[str] = None
    nvme_temp_input: Optional[str] = None
    ram_temp_input: Optional[str] = None
    fan1_input: Optional[str] = None
    fan2_input: Optional[str] = None
    battery_dir: Optional[str] = None
    adapter_online: Optional[str] = None
    nvidia_drm_card: Optional[str] = None
    nvidia_pci_power_control: Optional[str] = None
    igpu_drm_card: Optional[str] = None
    lenovo_wmi_attr_dir: Optional[str] = None
    hwmon_pwm1: Optional[str] = None
    hwmon_pwm1_enable: Optional[str] = None
    lcd_overdrive: Optional[str] = None
    gpu_mode: Optional[str] = None
    rgb_hidraw: Optional[str] = None
    rgb_sysfs_dir: Optional[str] = None


@dataclass
class UndervoltStatus:
    supported: bool = False
    cpu_vendor: str = "Intel"
    method: str = "MSR 0x150 (Intel OC Mailbox)"
    core_offset_mv: int = 0
    cache_offset_mv: int = 0
    gpu_ac_offset_w: int = 20
    safe_guard_active: bool = False
    last_emergency_reset: str = ""
    min_mv: int = -150
    max_mv: int = 0


@dataclass
class NetworkPowerStatus:
    wifi_available: bool = False
    wifi_iface: str = "wlan0"
    wifi_driver: str = "iwlwifi"
    wifi_power_save_on: bool = True
    eth_available: bool = False
    eth_iface: str = "enp7s0"
    eth_driver: str = "r8169"
    eth_power_save_on: bool = True


@dataclass
class AppProfileRule:
    executable: str = ""
    label: str = ""
    profile: str = "performance"
    enabled: bool = True


@dataclass
class GpuMuxInfo:
    available: bool = False
    current_mode: str = "hybrid"  # "hybrid", "dedicated", "integrated"
    available_modes: List[str] = field(default_factory=lambda: ["hybrid", "dedicated", "integrated"])
    backend_name: str = "none"    # "supergfxctl", "envycontrol", "prime-select", "lenovo-wmi", "sysfs", "none"
    requires_reboot: bool = False
    pending_mode: Optional[str] = None
    message: str = ""


@dataclass
class DisplayRefreshInfo:
    available: bool = False
    current_hz: int = 60
    available_rates: List[int] = field(default_factory=lambda: [60])
    display_name: str = ""
    resolution: str = ""
    backend_name: str = "none"  # "kscreen-doctor", "wlr-randr", "xrandr", "drm"
    auto_switch_ac: bool = True
    vrr_supported: bool = False
    vrr_policy: str = "never"  # "never", "always", "automatic"


@dataclass
class BiosAttribute:
    attr_id: str
    display_name: str
    category: str = "Geral"  # "Tela & Vídeo", "Energia & Boot", "Ajustes Térmicos & Potência", "Geral"
    attr_type: str = "enumeration"  # "boolean", "integer", "enumeration"
    current_value: str = ""
    default_value: str = ""
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    scalar_increment: int = 1
    possible_values: List[str] = field(default_factory=list)
    path: str = ""


