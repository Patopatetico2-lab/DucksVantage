"""Mixins modulares do HardwareBackend do Ducksvantage."""

from core.mixins.gaming import GamingAutoSwitchMixin
from core.mixins.cpu_thermal import CpuThermalUndervoltMixin
from core.mixins.telemetry_battery import TelemetryBatteryNetworkMixin
from core.mixins.display_mux_bios import DisplayMuxBiosMixin
from core.mixins.extras import PresetsDiagnosticsRgbMixin

__all__ = [
    "GamingAutoSwitchMixin",
    "CpuThermalUndervoltMixin",
    "TelemetryBatteryNetworkMixin",
    "DisplayMuxBiosMixin",
    "PresetsDiagnosticsRgbMixin",
]
