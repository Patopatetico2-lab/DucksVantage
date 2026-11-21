"""Widgets customizados reutilizáveis da interface Ducksvantage."""

from ui.widgets.live_thermal_chart import LiveThermalChart
from ui.widgets.gpu_mode_block import GpuModeBlock
from ui.widgets.fan_curve_widget import FanCurveWidget
from ui.widgets.key_capture_button import KeyCaptureButton

__all__ = [
    "LiveThermalChart",
    "GpuModeBlock",
    "FanCurveWidget",
    "KeyCaptureButton",
]
