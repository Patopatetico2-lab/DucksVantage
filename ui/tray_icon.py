"""
Gerenciador do Ícone da Bandeja do Sistema (System Tray) para o Ducksvantage.
Permite alternar perfis (incluindo Max-Power dinâmico), o Modo Viagem (Eco-Mode) e o
Modo de Conservação diretamente pela barra de tarefas do KDE Plasma,
mantendo o monitoramento do Fn+Q, Auto-Switch de Jogos e o OSD ativos em segundo plano.
"""

import os
import shutil
import subprocess
from core.qt_compat import (
    QSystemTrayIcon, QMenu, QAction, QIcon, QPixmap, QPainter,
    QColor, QBrush, QPen, QFont, Qt, Signal, QObject
)
from ui.theme_tokens import ThemeTokens


class SystemTrayManager(QObject):
    """Gerencia o ícone da bandeja e o menu de acesso rápido no painel do KDE."""
    profile_requested = Signal(str)
    conservation_toggled = Signal(bool)
    eco_travel_toggled = Signal(bool)
    show_window_requested = Signal()
    quit_requested = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.tray_icon = QSystemTrayIcon(parent)

        self._create_menu()
        self._setup_events()
        self.update_tray_state()

        self.tray_icon.show()

    def _get_icon(self, filename: str) -> QIcon:
        path = os.path.join("assets", "icons", filename)
        if os.path.exists(path):
            return QIcon(path)
        return QIcon()

    def _create_menu(self):
        self.menu = QMenu()
        self.menu.setStyleSheet(f"""
            QMenu {{
                background-color: {ThemeTokens.BG_SIDEBAR};
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 6px;
                font-family: {ThemeTokens.FONT_FAMILY};
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 8px 24px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                color: {ThemeTokens.BORDER_CYAN};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {ThemeTokens.BORDER_DEFAULT};
                margin: 4px 8px;
            }}
        """)

        # Cabeçalho Informativo
        model_label = self.backend.system_info.display_model_name
        self.title_action = QAction(f"Ducksvantage • {model_label}", self.menu)
        self.title_action.setIcon(self._get_icon("ducksvantage_logo.svg"))
        self.title_action.setEnabled(False)
        self.menu.addAction(self.title_action)
        self.menu.addSeparator()

        # Submenu de Perfis Térmicos
        self.profile_menu = self.menu.addMenu("Modos Térmicos (ACPI)")
        self.profile_menu.setIcon(self._get_icon("power.svg"))
        self.profile_menu.setStyleSheet(self.menu.styleSheet())

        self.action_quiet = QAction("Modo Silencioso (Quiet)", self.profile_menu)
        self.action_quiet.setIcon(self._get_icon("thermal_quiet.svg"))
        self.action_quiet.setCheckable(True)
        self.action_quiet.triggered.connect(lambda: self.profile_requested.emit("low-power"))
        self.profile_menu.addAction(self.action_quiet)

        self.action_balanced = QAction("Modo Equilibrado (Balanced)", self.profile_menu)
        self.action_balanced.setIcon(self._get_icon("thermal_balanced.svg"))
        self.action_balanced.setCheckable(True)
        self.action_balanced.triggered.connect(lambda: self.profile_requested.emit("balanced"))
        self.profile_menu.addAction(self.action_balanced)

        self.action_performance = QAction("Modo Desempenho (Performance)", self.profile_menu)
        self.action_performance.setIcon(self._get_icon("thermal_performance.svg"))
        self.action_performance.setCheckable(True)
        self.action_performance.triggered.connect(lambda: self.profile_requested.emit("performance"))
        self.profile_menu.addAction(self.action_performance)

        if self.backend.features.max_power_profile:
            self.action_max_power = QAction("Desempenho Máximo (Max-Power)", self.profile_menu)
            self.action_max_power.setIcon(self._get_icon("thermal_max_power.svg"))
            self.action_max_power.setCheckable(True)
            self.action_max_power.triggered.connect(lambda: self.profile_requested.emit("max-power"))
            self.profile_menu.addAction(self.action_max_power)
        else:
            self.action_max_power = None

        # Modo Viagem (Eco-Mode Extremo)
        self.action_eco_travel = QAction("Modo Viagem (Eco-Mode Extremo)", self.menu)
        self.action_eco_travel.setIcon(self._get_icon("eco_travel.svg"))
        self.action_eco_travel.setCheckable(True)
        self.action_eco_travel.triggered.connect(self.eco_travel_toggled.emit)
        self.menu.addAction(self.action_eco_travel)

        # Modo de Conservação de Bateria
        self.action_conservation = QAction("Modo de Conservação (~80%)", self.menu)
        self.action_conservation.setIcon(self._get_icon("edge_conservation.svg"))
        self.action_conservation.setCheckable(True)
        self.action_conservation.setEnabled(self.backend.features.conservation_mode)
        self.action_conservation.triggered.connect(self._on_conservation_click)
        self.menu.addAction(self.action_conservation)

        self.menu.addSeparator()

        # Abrir / Ocultar Janela
        self.action_toggle_window = QAction("Abrir Ducksvantage", self.menu)
        self.action_toggle_window.setIcon(self._get_icon("nav_dashboard.svg"))
        self.action_toggle_window.triggered.connect(self.show_window_requested.emit)
        self.menu.addAction(self.action_toggle_window)

        # Sair
        self.action_quit = QAction("Encerrar Aplicativo", self.menu)
        self.action_quit.setIcon(self._get_icon("quit.svg"))
        self.action_quit.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(self.action_quit)

        self.tray_icon.setContextMenu(self.menu)

    def _setup_events(self):
        self.tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window_requested.emit()

    def _on_conservation_click(self, checked: bool):
        self.conservation_toggled.emit(checked)

    def _generate_tray_pixmap(self, profile: str) -> QPixmap:
        """Gera um ícone procedural vetorial para a bandeja refletindo o perfil atual."""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        prof_lower = profile.lower()
        if "max" in prof_lower:
            accent_color = QColor(ThemeTokens.THERMAL_CUSTOM)
        elif "perf" in prof_lower:
            accent_color = QColor(ThemeTokens.THERMAL_PERFORMANCE)
        elif "low" in prof_lower or "quiet" in prof_lower:
            accent_color = QColor(ThemeTokens.THERMAL_QUIET)
        else:
            accent_color = QColor(ThemeTokens.THERMAL_BALANCED)

        painter.setBrush(QBrush(QColor(ThemeTokens.BG_APP)))
        painter.setPen(QPen(accent_color, 5))
        painter.drawEllipse(6, 6, 52, 52)

        painter.setPen(QColor(ThemeTokens.TEXT_WHITE_100))
        font = QFont("Segoe UI", 20, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "D")

        painter.end()
        return pixmap

    def update_tray_state(self):
        """Atualiza o ícone, o menu e a tooltip do system tray com telemetria recente."""
        prof = self.backend.normalize_profile(self.backend.get_platform_profile())

        self.tray_icon.setIcon(QIcon(self._generate_tray_pixmap(prof)))

        self.action_quiet.setChecked(prof in ("low-power", "quiet"))
        self.action_balanced.setChecked(prof == "balanced")
        if self.action_max_power:
            self.action_performance.setChecked(prof == "performance")
            self.action_max_power.setChecked(prof == "max-power")
        else:
            self.action_performance.setChecked(prof in ("performance", "max-power"))

        self.action_eco_travel.setChecked(self.backend.get_eco_travel_mode())
        if self.backend.features.conservation_mode:
            self.action_conservation.setChecked(self.backend.get_conservation_mode())

        bat = self.backend.get_battery_info()
        cpu = self.backend.get_cpu_metrics()
        gpu = self.backend.get_gpu_metrics()

        bat_str = f"{bat.capacity_percent}% ({'AC' if bat.ac_connected else 'Bateria'}) • {bat.temperature_c:.0f}°C"
        gpu_str = f"{gpu.temperature_c:.0f}°C" if gpu.available else "D3cold"

        tooltip = (
            f"Ducksvantage ({self.backend.system_info.display_model_name})\n"
            f"• Perfil: {prof.upper()}\n"
            f"• Bateria: {bat_str}\n"
            f"• CPU: {cpu.temperature_c:.0f}°C | {gpu.short_name}: {gpu_str}"
        )
        self.tray_icon.setToolTip(tooltip)

    def send_native_notification(self, title: str, message: str, urgency: str = "normal"):
        """Envia notificação nativa para a bandeja do KDE Plasma (QSystemTrayIcon + notify-send)."""
        try:
            icon_type = (
                QSystemTrayIcon.MessageIcon.Warning
                if urgency == "critical"
                else QSystemTrayIcon.MessageIcon.Information
            )
            if self.tray_icon.isSystemTrayAvailable():
                self.tray_icon.showMessage(title, message, icon_type, 6500)
        except Exception:
            pass

        if shutil.which("notify-send"):
            try:
                app_ic = os.path.abspath(os.path.join("assets", "app_icon.svg"))
                cmd = ["notify-send", "-a", "Ducksvantage", "-u", urgency]
                if os.path.exists(app_ic):
                    cmd.extend(["-i", app_ic])
                cmd.extend([title, message])
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
