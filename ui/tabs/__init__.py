"""
Pacote de Abas do Ducksvantage (Apenas as 4 Abas Essenciais sem duplicação).
"""

from ui.tabs.dashboard_tab import DashboardTab
from ui.tabs.performance_tab import PerformanceTab
from ui.tabs.battery_tab import BatteryTab
from ui.tabs.about_tab import AboutTab

__all__ = ["DashboardTab", "PerformanceTab", "BatteryTab", "AboutTab"]
