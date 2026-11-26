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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(BASE_DIR, "assets", "icons")
APP_ICON_PATH = os.path.join(BASE_DIR, "assets", "app_icon.svg")


class SystemTrayManager(QObject):
    """Gerencia o ícone da bandeja e o menu de acesso rápido no painel do KDE."""
    profile_requested = Signal(str)
    preset_requested = Signal(str, str)
    refresh_rate_requested = Signal(int)
    game_auto_toggled = Signal(bool)
    touchpad_toggled = Signal(bool)
    conservation_toggled = Signal(bool)
    eco_travel_toggled = Signal(bool)
    cinema_mode_toggled = Signal(bool)
    autostart_toggled = Signal(bool)
    show_window_requested = Signal()
    quit_requested = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.tray_icon = QSystemTrayIcon(parent)

        self._create_menu()
        self._setup_events()
        self.update_tray_state()

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def is_available(self) -> bool:
        """Indica se a bandeja do sistema está acessível e visível."""
        return QSystemTrayIcon.isSystemTrayAvailable() and self.tray_icon.isVisible()

    def _get_icon(self, filename: str) -> QIcon:
        path = os.path.join(ICON_DIR, filename)
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

        # Submenu de Perfis Térmicos (exibe apenas os perfis liberados pelo kernel)
        feat = self.backend.features
        supported_profiles = self.backend.get_supported_canonical_profiles()
        self.profile_menu = self.menu.addMenu("Modos Térmicos (ACPI)")
        self.profile_menu.setIcon(self._get_icon("power.svg"))
        self.profile_menu.setStyleSheet(self.menu.styleSheet())

        self.action_quiet = QAction("Modo Silencioso (Quiet)", self.profile_menu)
        self.action_quiet.setIcon(self._get_icon("thermal_quiet.svg"))
        self.action_quiet.setCheckable(True)
        self.action_quiet.triggered.connect(lambda: self.profile_requested.emit("low-power"))
        self.action_quiet.setVisible("low-power" in supported_profiles)
        self.profile_menu.addAction(self.action_quiet)

        self.action_balanced = QAction("Modo Equilibrado (Balanced)", self.profile_menu)
        self.action_balanced.setIcon(self._get_icon("thermal_balanced.svg"))
        self.action_balanced.setCheckable(True)
        self.action_balanced.triggered.connect(lambda: self.profile_requested.emit("balanced"))
        self.action_balanced.setVisible("balanced" in supported_profiles)
        self.profile_menu.addAction(self.action_balanced)

        self.action_performance = QAction("Modo Desempenho (Performance)", self.profile_menu)
        self.action_performance.setIcon(self._get_icon("thermal_performance.svg"))
        self.action_performance.setCheckable(True)
        self.action_performance.triggered.connect(lambda: self.profile_requested.emit("performance"))
        self.action_performance.setVisible("performance" in supported_profiles)
        self.profile_menu.addAction(self.action_performance)

        self.action_max_power = QAction("Desempenho Máximo (Max-Power)", self.profile_menu)
        self.action_max_power.setIcon(self._get_icon("thermal_max_power.svg"))
        self.action_max_power.setCheckable(True)
        self.action_max_power.triggered.connect(lambda: self.profile_requested.emit("max-power"))
        self.action_max_power.setVisible(bool(feat.max_power_profile or "max-power" in supported_profiles))
        self.profile_menu.addAction(self.action_max_power)

        self.profile_menu.menuAction().setVisible(bool(feat.platform_profile and supported_profiles))

        # Submenu de Presets Personalizados (1 Clique)
        self.presets_menu = self.menu.addMenu("Presets Personalizados")
        self.presets_menu.setIcon(self._get_icon("mode_custom.svg"))
        self.presets_menu.setStyleSheet(self.menu.styleSheet())
        self.rebuild_presets_menu()

        # Submenu de Taxa de Atualização (Hz)
        self.refresh_menu = self.menu.addMenu("Taxa de Atualização (Hz)")
        self.refresh_menu.setIcon(self._get_icon("refresh.svg"))
        self.refresh_menu.setStyleSheet(self.menu.styleSheet())
        self.rebuild_refresh_menu()

        # Auto-Switch em Jogos
        self.action_game_auto = QAction("Auto-Switch em Jogos", self.menu)
        self.action_game_auto.setIcon(self._get_icon("game_controller.svg"))
        self.action_game_auto.setCheckable(True)
        self.action_game_auto.triggered.connect(self.game_auto_toggled.emit)
        self.action_game_auto.setVisible(feat.platform_profile)
        self.menu.addAction(self.action_game_auto)

        # Trava do Touchpad
        self.action_touchpad = QAction("Bloquear Touchpad", self.menu)
        self.action_touchpad.setIcon(self._get_icon("edge_touchpad.svg"))
        self.action_touchpad.setCheckable(True)
        self.action_touchpad.triggered.connect(self.touchpad_toggled.emit)
        self.action_touchpad.setVisible(feat.touchpad_control)
        self.menu.addAction(self.action_touchpad)

        # Modo Viagem (Eco-Mode Extremo)
        self.action_eco_travel = QAction("Modo Viagem (Eco-Mode Extremo)", self.menu)
        self.action_eco_travel.setIcon(self._get_icon("eco_travel.svg"))
        self.action_eco_travel.setCheckable(True)
        self.action_eco_travel.triggered.connect(self.eco_travel_toggled.emit)
        self.action_eco_travel.setVisible(feat.eco_travel)
        self.menu.addAction(self.action_eco_travel)

        # Modo Cinema / Apresentação
        self.action_cinema_mode = QAction("Modo Cinema / Apresentação", self.menu)
        self.action_cinema_mode.setIcon(self._get_icon("power.svg"))
        self.action_cinema_mode.setCheckable(True)
        self.action_cinema_mode.triggered.connect(self.cinema_mode_toggled.emit)
        self.action_cinema_mode.setVisible(feat.cinema_mode)
        self.menu.addAction(self.action_cinema_mode)

        # Modo de Conservação de Bateria
        self.action_conservation = QAction("Modo de Conservação (~80%)", self.menu)
        self.action_conservation.setIcon(self._get_icon("edge_conservation.svg"))
        self.action_conservation.setCheckable(True)
        self.action_conservation.setEnabled(feat.conservation_mode)
        self.action_conservation.setVisible(feat.conservation_mode)
        self.action_conservation.triggered.connect(self._on_conservation_click)
        self.menu.addAction(self.action_conservation)

        # Inicialização Automática com o Sistema (XDG Autostart)
        self.action_autostart = QAction("Iniciar com o sistema", self.menu)
        self.action_autostart.setIcon(self._get_icon("power.svg"))
        self.action_autostart.setCheckable(True)
        self.action_autostart.triggered.connect(self.autostart_toggled.emit)
        self.menu.addAction(self.action_autostart)

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
        if "max" in prof_lower or "custom" in prof_lower:
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
        font = QFont(ThemeTokens.FONT_NAME, 20, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "D")

        painter.end()
        return pixmap

    def rebuild_presets_menu(self):
        """Reconstrói o submenu de presets salvos respeitando as capacidades do hardware."""
        self.presets_menu.clear()
        feat = self.backend.features
        supported_profiles = self.backend.get_supported_canonical_profiles()
        has_perf_ctrl = any((
            bool(feat.platform_profile and supported_profiles),
            feat.cpu_governor,
            feat.turbo_boost,
            feat.custom_tdp,
            feat.refresh_rate,
        ))
        presets = self.backend.get_user_presets()
        self.presets_menu.menuAction().setVisible(bool(has_perf_ctrl and presets))
        for p in presets:
            pid = str(p.get("id", ""))
            pname = str(p.get("name", pid))
            act = QAction(pname, self.presets_menu)
            act.setIcon(self._get_icon("mode_custom.svg"))
            act.triggered.connect(lambda _c=False, i=pid, n=pname: self.preset_requested.emit(i, n))
            self.presets_menu.addAction(act)

    def rebuild_refresh_menu(self):
        """Reconstrói o submenu de taxas de atualização suportadas pelo painel."""
        self.refresh_menu.clear()
        self._refresh_actions = {}
        if not self.backend.features.refresh_rate:
            self.refresh_menu.menuAction().setVisible(False)
            return
        info = self.backend.get_display_refresh_info()
        can_switch = bool(info.available and len(info.available_rates) > 1)
        self.refresh_menu.menuAction().setVisible(can_switch)
        if not can_switch:
            return
        for hz in info.available_rates:
            act = QAction(f"{hz} Hz", self.refresh_menu)
            act.setCheckable(True)
            act.setChecked(hz == info.current_hz)
            act.triggered.connect(lambda _c=False, h=hz: self.refresh_rate_requested.emit(h))
            self.refresh_menu.addAction(act)
            self._refresh_actions[hz] = act

    def update_tray_state(self):
        """Atualiza o ícone, o menu e a tooltip do system tray com telemetria recente."""
        prof = self.backend.normalize_profile(self.backend.get_platform_profile())

        self.tray_icon.setIcon(QIcon(self._generate_tray_pixmap(prof)))

        self.action_quiet.setChecked(prof in ("low-power", "quiet"))
        self.action_balanced.setChecked(prof == "balanced")
        if self.action_max_power and self.action_max_power.isVisible():
            self.action_performance.setChecked(prof == "performance")
            self.action_max_power.setChecked(prof == "max-power")
        else:
            self.action_performance.setChecked(prof in ("performance", "max-power"))

        if self.backend.features.platform_profile:
            self.action_game_auto.setChecked(self.backend.get_game_auto_switch())
        if self.backend.features.touchpad_control:
            self.action_touchpad.setChecked(self.backend.get_touchpad_status())
        if self.backend.features.eco_travel:
            self.action_eco_travel.setChecked(self.backend.get_eco_travel_mode())
        if self.backend.features.cinema_mode and hasattr(self, "action_cinema_mode"):
            self.action_cinema_mode.setChecked(self.backend.get_cinema_mode())
        if self.backend.features.conservation_mode:
            self.action_conservation.setChecked(self.backend.get_conservation_mode())
        self.action_autostart.setChecked(self.backend.get_autostart_enabled())

        if self.backend.features.refresh_rate and getattr(self, "_refresh_actions", None):
            cur_hz = self.backend.get_display_refresh_info().current_hz
            for hz, act in self._refresh_actions.items():
                act.setChecked(hz == cur_hz)

        bat = self.backend.get_battery_info()
        cpu = self.backend.get_cpu_metrics()
        gpu = self.backend.get_gpu_metrics()

        lines = [f"Ducksvantage ({self.backend.system_info.display_model_name})"]
        if self.backend.features.platform_profile:
            lines.append(f"• Perfil: {prof.upper()}")
            active_game = self.backend.get_active_game()
            if active_game:
                lines.append(f"• Jogo/App: {active_game}")
        if self.backend.features.refresh_rate:
            ref = self.backend.get_display_refresh_info()
            if ref.available:
                lines.append(f"• Tela: {ref.current_hz} Hz")
        if bat.available:
            bat_str = f"{bat.capacity_percent}% ({'AC' if bat.ac_connected else 'Bateria'}) • {bat.temperature_c:.0f}°C"
            lines.append(f"• Bateria: {bat_str}")
        if gpu.available:
            gpu_str = f"{gpu.temperature_c:.0f}°C"
            lines.append(f"• CPU: {cpu.temperature_c:.0f}°C | {gpu.short_name}: {gpu_str}")
        elif self.backend.paths.nvidia_drm_card:
            lines.append(f"• CPU: {cpu.temperature_c:.0f}°C | {gpu.short_name}: D3cold")
        else:
            lines.append(f"• CPU: {cpu.temperature_c:.0f}°C")
        self.tray_icon.setToolTip("\n".join(lines))

    def send_native_notification(self, title: str, message: str, urgency: str = "normal"):
        """Envia notificação nativa sem duplicar alertas no KDE Plasma."""
        notify_bin = shutil.which("notify-send")
        if notify_bin:
            try:
                cmd = [notify_bin, "-a", "Ducksvantage", "-u", urgency]
                if os.path.exists(APP_ICON_PATH):
                    cmd.extend(["-i", APP_ICON_PATH])
                cmd.extend([title, message])
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass

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
