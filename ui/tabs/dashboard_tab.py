"""
Aba Dashboard do LenovoLOQ-Control.
Re-exporta VantageDashboardView para manter compatibilidade e modularidade.
"""

from ui.dashboard import VantageDashboardView

class DashboardTab(VantageDashboardView):
    """Alias para VantageDashboardView com o layout oficial Vantage 65%/35%."""
    pass
