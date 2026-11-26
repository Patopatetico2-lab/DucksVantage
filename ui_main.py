"""
Ducksvantage - Módulo Principal de Interface Gráfica (ui_main.py)
Substituto universal e leve do Lenovo Vantage para qualquer notebook Lenovo compatível
(Legion, LOQ, IdeaPad Gaming, IdeaPad e Yoga, Intel e AMD).
Organizado em 4 abas essenciais sem duplicações, zero emojis de texto e 6 Recursos de Elite:
  1. Descoberta Dinâmica de Perfis do Kernel (incluindo max-power)
  2. Auto-Switching por Jogo (Steam / Heroic / Proton)
  3. Battery Health Historian (Gráfico de Saúde e Degradação em Wh)
  4. Custom TDP (PL1/PL2) e Curva de Rotação das Ventoinhas
  5. Mapeador de Teclas Personalizadas (Tecla Copilot F23 e Atalhos)
  6. Modo Viagem / Eco-Mode Extremo (1-Clique)
"""

import os
import time
from typing import Dict, List, Tuple
from core.qt_compat import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget, QTimer, Qt, QFont,
    QIcon, QSize, QApplication, QMessageBox, QShortcut, QKeySequence,
    QSystemTrayIcon
)
from core.backend import HardwareBackend
from core.key_mapper import is_valid_shortcut
from core.dbus_service import DucksvantageDBusService
from ui.theme_tokens import ThemeTokens
from ui.components import StatusBadge
from ui.tray_icon import SystemTrayManager
from ui.osd_overlay import VantageOSDOverlay
from ui.dashboard import VantageDashboardView
from ui.tabs.performance_tab import PerformanceTab
from ui.tabs.gpu_display_tab import GpuDisplayTab
from ui.tabs.automation_tab import AutomationTab
from ui.tabs.battery_tab import BatteryTab
from ui.tabs.about_tab import AboutTab
from ui.tabs.lighting_tab import LightingTab

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")


def get_asset_icon(name: str) -> QIcon:
    """Busca o ícone SVG em assets/icons/."""
    p = os.path.join(ICON_DIR, name)
    if os.path.exists(p):
        return QIcon(p)
    return QIcon()


class MainWindow(QMainWindow):
    """Janela Principal do Ducksvantage (4 Abas Essenciais + OSD + System Tray + 6 Elite Features)."""

    def __init__(self, backend: HardwareBackend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._is_quitting = False
        self._active_shortcuts: List[QShortcut] = []
        self._last_key_action_ts: Dict[Tuple[str, str], float] = {}

        model_title = self.backend.system_info.display_model_name
        self.setWindowTitle(f"Ducksvantage • {model_title}")
        self.resize(1160, 770)
        self.setMinimumSize(960, 640)

        app_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "app_icon.svg")
        app_icon = QIcon(app_icon_path) if os.path.exists(app_icon_path) else get_asset_icon("ducksvantage_logo.svg")
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        # Carregar folha de estilos extraída (styles.qss)
        self._apply_styles()

        # Widget Central
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Cabeçalho Superior Dinâmico (Header Bar)
        self.header_bar = self._create_header_bar()
        main_layout.addWidget(self.header_bar)

        # 2. Área de Trabalho (Sidebar de 4 Abas + QStackedWidget)
        workspace = QHBoxLayout()
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(0)

        self.sidebar, self.nav_buttons, self.nav_icon_pairs = self._create_sidebar()
        workspace.addWidget(self.sidebar)

        # Pilha de Abas (Dashboard, CPU & Térmico, GPU & Tela, Automação, Bateria, Sobre e RGB)
        self.stack = QStackedWidget()
        self.dashboard_tab = VantageDashboardView(self.backend)
        self.performance_tab = PerformanceTab(self.backend)
        self.battery_tab = BatteryTab(self.backend)
        self.about_tab = AboutTab(self.backend)
        self.lighting_tab = LightingTab(self.backend)
        self.gpu_display_tab = GpuDisplayTab(self.backend)
        self.automation_tab = AutomationTab(self.backend)

        self.stack.addWidget(self.dashboard_tab)    # Índice 0: Dashboard
        self.stack.addWidget(self.performance_tab)  # Índice 1: CPU & Térmico
        self.stack.addWidget(self.battery_tab)      # Índice 2: Bateria & Rede
        self.stack.addWidget(self.about_tab)        # Índice 3: Sobre
        self.stack.addWidget(self.lighting_tab)     # Índice 4: Iluminação RGB 4-Zonas
        self.stack.addWidget(self.gpu_display_tab)  # Índice 5: GPU & Tela
        self.stack.addWidget(self.automation_tab)   # Índice 6: Automação & Atalhos

        if self.gpu_display_nav_btn is not None:
            self.gpu_display_nav_btn.setVisible(self.gpu_display_tab.has_any_supported_feature())

        workspace.addWidget(self.stack, stretch=1)
        main_layout.addLayout(workspace, stretch=1)

        # 3. Pop-up OSD Não-Intrusivo (para Fn+Q, Auto-Switch Jogo, Modo Viagem e Tecla Copilot)
        self.osd = VantageOSDOverlay()
        self._apply_osd_preferences()

        # 4. Bandeja do Sistema (System Tray Manager)
        self.tray_manager = SystemTrayManager(self.backend, self)

        # 5. Conectar Sinais Intermódulos e Registrar Atalhos do Remapper
        self._connect_signals()
        self._register_qt_shortcuts()

        # 5.5 Serviço D-Bus de Sessão & Integração KRunner (org.ducksvantage.Control)
        self.dbus_service = DucksvantageDBusService(
            self.backend,
            ui_callback=self._on_dbus_command_executed,
        )
        self.dbus_service.start()

        # 6. Polling Rápido de 200ms para Hardware / Fn+Q / AC / evdev (Infalível no sysfs)
        self.fast_poll_timer = QTimer(self)
        self.fast_poll_timer.setInterval(200)
        self.fast_poll_timer.timeout.connect(self._on_fast_poll)
        self.fast_poll_timer.start()

        # 7. Timer Periódico de Telemetria e Auto-Switching por Jogo (1500ms)
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.setInterval(1500)
        self.telemetry_timer.timeout.connect(self._on_telemetry_tick)
        self.telemetry_timer.start()

        # Aplicar Modo da Interface (Básico / Avançado) e inicializar na Aba 0 (Dashboard)
        self.apply_ui_mode(self.backend.get_ui_mode())
        self._switch_tab(0)
        self._on_telemetry_tick()

    def _apply_styles(self):
        """Aplica o arquivo styles.qss com os tokens do Ducksvantage."""
        qss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles.qss")
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def _create_header_bar(self) -> QFrame:
        header = QFrame()
        header.setObjectName("headerBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(10)

        logo_icon = get_asset_icon("lenovo_logo.svg")
        if not logo_icon.isNull():
            lbl_logo = QLabel()
            lbl_logo.setPixmap(logo_icon.pixmap(60, 18))
            layout.addWidget(lbl_logo)

        sep = QFrame()
        sep.setFixedSize(1, 14)
        sep.setStyleSheet(f"background-color: {ThemeTokens.BORDER_DEFAULT};")
        layout.addWidget(sep)

        duck_icon = get_asset_icon("ducksvantage_logo.svg")
        if not duck_icon.isNull():
            lbl_duck = QLabel()
            lbl_duck.setPixmap(duck_icon.pixmap(18, 18))
            layout.addWidget(lbl_duck)

        title = QLabel("Ducksvantage")
        title.setObjectName("headerTitle")
        title.setFont(QFont(ThemeTokens.FONT_NAME, 11, QFont.Weight.DemiBold))
        layout.addWidget(title)

        layout.addStretch()

        model_name = self.backend.system_info.display_model_name or "LENOVO"
        self.model_pill = StatusBadge(
            f"{model_name.upper()}",
            bg_color="transparent",
            text_color=ThemeTokens.TEXT_LIGHT_GRAY,
        )
        layout.addWidget(self.model_pill)

        self.header_eco_pill = StatusBadge("ECO VIAGEM", bg_color="transparent", text_color=ThemeTokens.STATUS_GREEN)
        self.header_eco_pill.setVisible(False)
        layout.addWidget(self.header_eco_pill)

        self.header_profile_pill = StatusBadge("EQUILIBRADO", bg_color="transparent", text_color=ThemeTokens.ACCENT_STEEL)
        self.header_profile_pill.setVisible(self.backend.features.platform_profile)
        layout.addWidget(self.header_profile_pill)

        self.header_bat_pill = StatusBadge("BATERIA --%", bg_color="transparent", text_color=ThemeTokens.TEXT_WHITE_80)
        self.header_bat_pill.setVisible(self.backend.features.battery)
        layout.addWidget(self.header_bat_pill)

        return header

    def _create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(2)

        nav_items = [
            ("Dashboard", "nav_dashboard.svg", "nav_dashboard_active.svg", 0),
            ("CPU && Térmico", "nav_performance.svg", "nav_performance_active.svg", 1),
            ("GPU && Tela", "nav_gpu.svg", "nav_gpu_active.svg", 5),
            ("Automação && Atalhos", "nav_automation.svg", "nav_automation_active.svg", 6),
            ("Bateria && Rede", "nav_battery.svg", "nav_battery_active.svg", 2),
            ("Iluminação RGB", "nav_lighting.svg", "nav_lighting_active.svg", 4),
            ("Config. && Sistema", "nav_about.svg", "nav_about_active.svg", 3),
        ]

        buttons = []
        icon_pairs = []
        self.lighting_nav_btn = None
        self.gpu_display_nav_btn = None
        for text, inactive_icon, active_icon, index in nav_items:
            btn = QPushButton(f"  {text}")
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("tab_index", index)

            ic_off = get_asset_icon(inactive_icon)
            ic_on = get_asset_icon(active_icon)
            if not ic_off.isNull():
                btn.setIcon(ic_off)
                btn.setIconSize(QSize(18, 18))

            if index == 4:
                btn.setVisible(bool(self.backend.features.rgb_keyboard))
                self.lighting_nav_btn = btn
            elif index == 5:
                self.gpu_display_nav_btn = btn

            btn.clicked.connect(lambda checked, idx=index: self._switch_tab(idx))
            layout.addWidget(btn)
            buttons.append(btn)
            icon_pairs.append((ic_off, ic_on))

        layout.addStretch()

        mode_container = QWidget()
        mode_v = QVBoxLayout(mode_container)
        mode_v.setContentsMargins(12, 6, 12, 6)
        mode_v.setSpacing(5)

        mode_lbl = QLabel("MODO DA INTERFACE")
        mode_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 8, QFont.Weight.DemiBold))
        mode_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_40}; letter-spacing: 0.4px;")
        mode_v.addWidget(mode_lbl)

        mode_pill = QFrame()
        mode_pill.setObjectName("uiModePill")
        mode_pill.setStyleSheet("""
            QFrame#uiModePill {
                background-color: #121316;
                border: 1px solid #2c3037;
                border-radius: 6px;
            }
        """)
        mp_row = QHBoxLayout(mode_pill)
        mp_row.setContentsMargins(2, 2, 2, 2)
        mp_row.setSpacing(2)

        self.btn_mode_basic = QPushButton("Básico")
        self.btn_mode_basic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_basic.setFixedHeight(24)
        self.btn_mode_basic.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.btn_mode_basic.clicked.connect(lambda _c=False: self.apply_ui_mode("basic"))
        mp_row.addWidget(self.btn_mode_basic)

        self.btn_mode_advanced = QPushButton("Avançado")
        self.btn_mode_advanced.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mode_advanced.setFixedHeight(24)
        self.btn_mode_advanced.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.btn_mode_advanced.clicked.connect(lambda _c=False: self.apply_ui_mode("advanced"))
        mp_row.addWidget(self.btn_mode_advanced)

        mode_v.addWidget(mode_pill)
        layout.addWidget(mode_container)

        sys = self.backend.system_info
        k_info = QLabel(f"{sys.os_name} • {sys.laptop_line}")
        k_info.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_40}; font-size: 10px; padding: 6px 18px;")
        layout.addWidget(k_info)

        return sidebar, buttons, icon_pairs

    def apply_ui_mode(self, mode: str):
        """Alterna globalmente entre Modo Básico e Modo Avançado em todas as abas."""
        self.backend.set_ui_mode(mode)
        is_adv = self.backend.is_advanced_mode()

        active_css = """
            QPushButton {
                background-color: #22252b;
                color: #f4f5f7;
                border: 1px solid #60a5fa;
                border-radius: 4px;
                padding: 0px 8px;
            }
        """
        idle_css = """
            QPushButton {
                background-color: transparent;
                color: #8f96a3;
                border: none;
                border-radius: 4px;
                padding: 0px 8px;
            }
            QPushButton:hover {
                color: #f4f5f7;
            }
        """
        self.btn_mode_basic.setStyleSheet(idle_css if is_adv else active_css)
        self.btn_mode_advanced.setStyleSheet(active_css if is_adv else idle_css)

        self.performance_tab.set_advanced_mode(is_adv)
        self.gpu_display_tab.set_advanced_mode(is_adv)
        self.automation_tab.set_advanced_mode(is_adv)
        self.battery_tab.set_advanced_mode(is_adv)
        self.about_tab.set_advanced_mode(is_adv)

        if self.gpu_display_nav_btn is not None:
            has_gpu_disp = self.gpu_display_tab.has_any_supported_feature()
            self.gpu_display_nav_btn.setVisible(has_gpu_disp)
            if not has_gpu_disp and self.stack.currentIndex() == 5:
                self._switch_tab(0)

    def _switch_tab(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            tab_idx = btn.property("tab_index")
            if tab_idx is None:
                tab_idx = i
            is_sel = (int(tab_idx) == index)
            btn.setChecked(is_sel)
            btn.setProperty("active", "true" if is_sel else "false")
            ic_off, ic_on = self.nav_icon_pairs[i]
            if is_sel and not ic_on.isNull():
                btn.setIcon(ic_on)
            elif not ic_off.isNull():
                btn.setIcon(ic_off)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # Atualizar dados da aba selecionada imediatamente
        if index == 0:
            self.dashboard_tab.update_telemetry()
        elif index == 1:
            self.performance_tab.refresh_profile_state()
        elif index == 2:
            self.battery_tab.refresh_display()
        elif index == 3:
            self.about_tab.update_autostart_status()
            self.about_tab.update_permission_status()
            self.about_tab.update_kde_integration_status()
            self.about_tab.refresh_hardware_toggles()
        elif index == 5:
            self.gpu_display_tab.refresh_all()
        elif index == 6:
            self.automation_tab.refresh_automation_state()

    def _connect_signals(self):
        # 1. Troca de Perfis Térmicos e Ciclo Fn + Q (incluindo Max-Power)
        self.dashboard_tab.profile_requested.connect(self._apply_profile)
        self.dashboard_tab.fn_q_cycle_requested.connect(self._on_fn_q_cycle)
        self.performance_tab.profile_changed.connect(self._on_profile_changed)
        self.tray_manager.profile_requested.connect(self._apply_profile)

        # 2. ELITE 6 & ELITE 2: Modo Viagem (Eco-Mode Extremo) & Auto-Switch em Jogos
        self.dashboard_tab.eco_travel_toggled.connect(self._apply_eco_travel)
        self.tray_manager.eco_travel_toggled.connect(self._apply_eco_travel)
        self.dashboard_tab.game_auto_toggled.connect(self._apply_game_auto)

        # 3. ELITE 5: Mapeador de Teclas Personalizadas (Tecla Copilot F8/F23 & Atalhos)
        self.automation_tab.shortcuts_updated.connect(self._register_qt_shortcuts)
        self.automation_tab.custom_action_requested.connect(
            lambda act, cmd="": self._execute_custom_key_action(act, cmd, source="test")
        )
        self.automation_tab.cinema_mode_toggled.connect(self._apply_cinema_mode)

        # 4. Exclusão Mútua de Bateria (Modo de Conservação vs Rapid Charge) e Alertas Inteligentes
        self.dashboard_tab.conservation_toggled.connect(self._apply_conservation)
        self.dashboard_tab.rapid_charge_toggled.connect(self._apply_rapid_charge)
        self.battery_tab.conservation_changed.connect(self._on_conservation_changed)
        self.battery_tab.rapid_charge_changed.connect(self._on_rapid_charge_changed)
        self.battery_tab.test_alert_requested.connect(self._on_test_battery_alert)
        self.tray_manager.conservation_toggled.connect(self._apply_conservation)

        # 5. Controles do Painel EDGE & Controles Eventuais na Aba Config. & Sistema
        self.dashboard_tab.camera_toggled.connect(self._apply_camera)
        self.dashboard_tab.touchpad_toggled.connect(self._apply_touchpad)
        self.dashboard_tab.kbd_backlight_requested.connect(self._apply_kbd_backlight)
        self.about_tab.fn_lock_toggled.connect(self._apply_fn_lock)
        self.about_tab.usb_charging_toggled.connect(self._apply_usb_charging)
        self.about_tab.auto_power_toggled.connect(self._apply_auto_power)
        self.tray_manager.cinema_mode_toggled.connect(self._apply_cinema_mode)

        # 6. Aba Sobre / UDEV / Autostart XDG / Preferências
        self.about_tab.permissions_updated.connect(self.about_tab.update_permission_status)
        self.about_tab.autostart_toggled.connect(self._on_autostart_changed)
        self.about_tab.preferences_changed.connect(self._on_preferences_changed)
        self.about_tab.test_osd_requested.connect(self._on_test_osd_requested)
        self.tray_manager.autostart_toggled.connect(self._apply_autostart)

        # 7. Bandeja do Sistema (Ações rápidas e Sync)
        self.tray_manager.preset_requested.connect(self._apply_preset_from_tray)
        self.tray_manager.refresh_rate_requested.connect(self._apply_refresh_rate_from_tray)
        self.tray_manager.game_auto_toggled.connect(self._apply_game_auto)
        self.tray_manager.touchpad_toggled.connect(self._apply_touchpad)
        self.tray_manager.show_window_requested.connect(self._toggle_visibility)
        self.tray_manager.quit_requested.connect(self._quit_app)

        # 8. GPU MUX Switch, Taxa de Atualização, VRR/Dock, LCD Overdrive, Presets e RGB
        self.gpu_display_tab.gpu_mux_changed.connect(self._on_gpu_mux_changed)
        self.gpu_display_tab.refresh_rate_changed.connect(self._on_refresh_rate_changed)
        self.gpu_display_tab.vrr_policy_changed.connect(self._on_vrr_policy_changed)
        self.gpu_display_tab.dock_config_changed.connect(self._on_dock_config_changed)
        self.gpu_display_tab.lcd_overdrive_changed.connect(self._on_lcd_overdrive_changed)
        self.automation_tab.preset_applied.connect(self._on_user_preset_applied)
        self.automation_tab.presets_updated.connect(self._on_presets_updated)
        self.lighting_tab.rgb_changed.connect(self._on_rgb_changed)

    def _register_qt_shortcuts(self):
        """Registra os atalhos de teclado Qt dentro da janela (ignorando valores inválidos)."""
        for sc in self._active_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._active_shortcuts.clear()

        mappings = self.backend.get_key_mappings()
        for slot_id, cfg in mappings.items():
            if not cfg.get("enabled", True):
                continue
            seq_str = str(cfg.get("qt_shortcut", "")).strip()
            act_id = str(cfg.get("action", "cycle_profile"))
            custom_cmd = str(cfg.get("custom_command", ""))

            sequences = [seq_str] if is_valid_shortcut(seq_str) else []
            # Mantém F23 e Meta+Shift+F23 registrados quando slotcopilot usa F23
            if slot_id == "copilot_key" and int(cfg.get("evdev_code", 0) or 0) == 193:
                for alias in ("F23", "Meta+Shift+F23"):
                    if alias not in sequences:
                        sequences.append(alias)

            for s_txt in sequences:
                sc = QShortcut(QKeySequence(s_txt), self)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                sc.activated.connect(
                    lambda a=act_id, c=custom_cmd: self._execute_custom_key_action(a, c, source="qt_shortcut")
                )
                self._active_shortcuts.append(sc)

    def _execute_custom_key_action(self, action_id: str, custom_cmd: str = "", source: str = "shortcut"):
        """Executa a ação associada a uma tecla remapeada (com debounce contra duplo disparo Qt+evdev)."""
        if source != "test":
            now = time.time()
            key = (str(action_id), str(custom_cmd or "").strip())
            last = self._last_key_action_ts.get(key, 0.0)
            if (now - last) < 0.35:
                return
            self._last_key_action_ts[key] = now

        res = self.backend.execute_mapped_action(action_id, custom_cmd)
        osd_type = res.get("osd_type", "")

        if osd_type == "profile":
            new_prof = res.get("value", "balanced")
            self._on_profile_changed(new_prof)
        elif osd_type == "feature":
            self.osd.notify_feature_osd(
                title=res.get("title", "Atalho Ducksvantage"),
                subtitle=res.get("subtitle", ""),
                icon_name=res.get("icon", "copilot_key.svg"),
                accent_color=res.get("accent", ThemeTokens.BORDER_CYAN)
            )
            self._update_header_profile_pill()
            self.dashboard_tab.update_telemetry()
            self.performance_tab.refresh_profile_state()
            self.battery_tab.refresh_display()
            self.tray_manager.update_tray_state()
        elif osd_type == "refresh_rate":
            hz = res.get("hz", 60)
            self.osd.notify_refresh_rate(hz)
            self.gpu_display_tab.refresh_display_state()
        elif osd_type == "window":
            self._toggle_visibility()

    def _on_gpu_mux_changed(self, mode: str, req_reboot: bool):
        self.osd.notify_gpu_mux(mode, req_reboot)
        self.dashboard_tab.update_telemetry()
        if req_reboot:
            QMessageBox.information(
                self,
                "GPU MUX Switch - Reinicialização Necessária",
                f"O modo de GPU foi configurado para '{mode.upper()}'.\n\n"
                "Para concluir a ativação no Linux, reinicie o computador ou a sessão gráfica."
            )

    def _on_refresh_rate_changed(self, hz: int):
        self.osd.notify_refresh_rate(hz)
        self.tray_manager.rebuild_refresh_menu()
        self.tray_manager.update_tray_state()

    def _on_vrr_policy_changed(self, policy: str):
        labels = {"never": "Desligado", "automatic": "Automático", "always": "Sempre Ativo"}
        self.osd.notify_feature_osd(
            title="VRR / Adaptive Sync",
            subtitle=f"Modo: {labels.get(policy, policy)}",
            icon_name="refresh.svg",
            accent_color=ThemeTokens.ACCENT_STEEL,
        )

    def _on_dock_config_changed(self):
        dock_ev = self.backend.check_external_monitor_dock_mode()
        if dock_ev:
            self.osd.notify_feature_osd(
                title="Modo Mesa (Monitor Externo)" if dock_ev["type"] == "dock_mode_entered" else "Monitor Externo Desconectado",
                subtitle=dock_ev["summary"][:58],
                icon_name="gpu_stack.svg",
                accent_color=ThemeTokens.ACCENT_STEEL,
            )
            self._update_header_profile_pill()
            self.dashboard_tab.update_telemetry()
            self.performance_tab.refresh_profile_state()
            self.gpu_display_tab.refresh_all()
            self.tray_manager.update_tray_state()

    def _apply_cinema_mode(self, enable: bool):
        ok, msg = self.backend.set_cinema_mode(enable)
        self.osd.notify_feature_osd(
            title="Modo Cinema / Apresentação: Ativo" if enable else "Modo Cinema Desativado",
            subtitle="Tela acesa • Não Perturbe KDE • Teclado Off" if enable else msg[:58],
            icon_name="power.svg",
            accent_color=ThemeTokens.ACCENT_STEEL if enable else ThemeTokens.TEXT_LIGHT_GRAY,
        )
        self.dashboard_tab.update_telemetry()
        self.automation_tab.refresh_automation_state()
        self.tray_manager.update_tray_state()

    def _apply_audio_preset(self, preset_id: str):
        ok, msg = self.backend.set_audio_preset(preset_id)
        if not ok:
            QMessageBox.warning(self, "Presets de Áudio", msg)
            self.dashboard_tab.update_telemetry()
            return
        titles = {
            "normal": "Áudio: Modo Padrão",
            "voice_call": "Áudio: Call / Voz (Filtro Ruído)",
            "privacy_mute": "Áudio: Silêncio & Privacidade",
        }
        accent = ThemeTokens.STATUS_GREEN if preset_id == "voice_call" else (
            ThemeTokens.STATUS_DANGER if preset_id == "privacy_mute" else ThemeTokens.ACCENT_STEEL
        )
        self.osd.notify_feature_osd(
            title=titles.get(preset_id, "Áudio"),
            subtitle=msg[:58],
            icon_name="copilot_key.svg",
            accent_color=accent,
        )
        self.dashboard_tab.update_telemetry()

    def _on_dbus_command_executed(self, event_name: str, payload: dict):
        QTimer.singleShot(0, lambda: self._handle_dbus_ui_sync(event_name, dict(payload)))

    def _handle_dbus_ui_sync(self, event_name: str, payload: dict):
        if event_name == "profile":
            self._on_profile_changed(str(payload.get("profile", "balanced")))
        elif event_name == "preset":
            self._on_user_preset_applied(str(payload.get("name", "Preset")), str(payload.get("summary", "")))
        elif event_name == "refresh_rate":
            self._on_refresh_rate_changed(int(payload.get("hz", 60)))
            self.gpu_display_tab.refresh_display_state()
        elif event_name == "eco":
            en = bool(payload.get("enabled", False))
            self.osd.notify_feature_osd(
                title="Modo Viagem (Eco-Mode Extremo)" if en else "Modo Viagem Desativado",
                subtitle=self.backend.get_eco_travel_summary() if en else "Desempenho Padrão Restaurado",
                icon_name="eco_travel.svg",
                accent_color=ThemeTokens.STATUS_GREEN if en else ThemeTokens.BORDER_CYAN,
            )
            self._update_header_profile_pill()
            self.dashboard_tab.update_telemetry()
            self.performance_tab.refresh_profile_state()
            self.tray_manager.update_tray_state()
        elif event_name == "cinema":
            en = bool(payload.get("enabled", False))
            self.osd.notify_feature_osd(
                title="Modo Cinema: Ativo" if en else "Modo Cinema Desativado",
                subtitle="Tela acesa • Não Perturbe KDE" if en else "Estado padrão restaurado",
                icon_name="power.svg",
                accent_color=ThemeTokens.ACCENT_STEEL if en else ThemeTokens.TEXT_LIGHT_GRAY,
            )
            self.dashboard_tab.update_telemetry()
            self.automation_tab.refresh_automation_state()
            self.tray_manager.update_tray_state()
        elif event_name == "audio":
            self.osd.notify_feature_osd(
                title="Preset de Áudio",
                subtitle=str(payload.get("message", ""))[:58],
                icon_name="copilot_key.svg",
                accent_color=ThemeTokens.ACCENT_STEEL,
            )
            self.dashboard_tab.update_telemetry()
        elif event_name == "show_window":
            if not self.isVisible():
                self._toggle_visibility()
            else:
                self.raise_()
                self.activateWindow()

    def _apply_osd_preferences(self):
        self.osd.configure(
            enabled=self.backend.get_osd_enabled(),
            position=self.backend.get_osd_position(),
            duration_ms=self.backend.get_osd_duration_ms(),
        )

    def _on_preferences_changed(self):
        self._apply_osd_preferences()
        self._register_qt_shortcuts()
        self.automation_tab._rebuild_user_presets_list()
        self.automation_tab._populate_game_preset_combo()
        self.automation_tab._populate_app_rule_profile_combo()
        self.automation_tab._rebuild_app_rules_list()
        self.automation_tab._rebuild_game_ignore_list()
        self.automation_tab.refresh_automation_state()
        self.performance_tab.refresh_profile_state()
        self.gpu_display_tab.refresh_all()
        self.battery_tab.refresh_display()
        self.tray_manager.rebuild_presets_menu()
        self.tray_manager.rebuild_refresh_menu()
        self.tray_manager.update_tray_state()

    def _on_test_osd_requested(self):
        self.osd.notify_feature_osd(
            title="Teste de Pop-up OSD",
            subtitle=f"Posição: {self.backend.get_osd_position()} • {self.backend.get_osd_duration_ms()} ms",
            icon_name="ducksvantage_logo.svg",
            accent_color=ThemeTokens.BORDER_CYAN
        )

    def _on_presets_updated(self):
        self.tray_manager.rebuild_presets_menu()

    def _apply_preset_from_tray(self, preset_id: str, preset_name: str):
        ok, msg = self.backend.apply_user_preset(preset_id)
        if ok:
            self._on_user_preset_applied(preset_name, msg)
        else:
            QMessageBox.warning(self, "Preset Personalizado", f"Não foi possível aplicar o preset '{preset_name}':\n{msg}")

    def _apply_refresh_rate_from_tray(self, hz: int):
        ok, msg = self.backend.set_refresh_rate(hz)
        if ok:
            self._on_refresh_rate_changed(hz)
            self.gpu_display_tab.refresh_display_state()
        else:
            QMessageBox.warning(self, "Taxa de Atualização", msg)

    def _on_rgb_changed(self, msg: str):
        self.osd.notify_feature_osd(
            title="Iluminação RGB 4-Zonas",
            subtitle=msg[:58],
            icon_name="nav_lighting_active.svg",
            accent_color=ThemeTokens.BORDER_CYAN
        )

    def _apply_lcd_overdrive(self, enabled: bool):
        ok, msg = self.backend.set_lcd_overdrive(enabled)
        if ok:
            self.osd.notify_lcd_overdrive(enabled)
            self.gpu_display_tab.refresh_bios_state()
            if getattr(self.dashboard_tab, "item_lcd_overdrive", None):
                self.dashboard_tab.item_lcd_overdrive.set_checked(enabled)
        else:
            if getattr(self.dashboard_tab, "item_lcd_overdrive", None):
                self.dashboard_tab.item_lcd_overdrive.set_checked(not enabled)
            self.gpu_display_tab.refresh_bios_state()
            QMessageBox.warning(self, "LCD Overdrive", f"Não foi possível alterar o LCD Overdrive:\n{msg}")

    def _on_lcd_overdrive_changed(self, enabled: bool):
        self.osd.notify_lcd_overdrive(enabled)
        if getattr(self.dashboard_tab, "item_lcd_overdrive", None):
            self.dashboard_tab.item_lcd_overdrive.set_checked(enabled)

    def _on_user_preset_applied(self, preset_name: str, summary: str):
        self.osd.notify_feature_osd(
            title=f"Preset: {preset_name[:26]}",
            subtitle=summary[:58],
            icon_name="mode_custom.svg",
            accent_color=ThemeTokens.THERMAL_CUSTOM
        )
        self._update_header_profile_pill()
        self.dashboard_tab.update_telemetry()
        self.performance_tab.refresh_profile_state()
        self.gpu_display_tab.refresh_all()
        self.automation_tab.refresh_automation_state()
        self.tray_manager.update_tray_state()

    # =========================================================================
    # Ações e Sincronização de Hardware
    # =========================================================================
    def _on_fn_q_cycle(self):
        """Executa o ciclo completo do Fn + Q (Silencioso -> Equilibrado -> Desempenho -> Max-Power) com OSD."""
        ok, next_prof = self.backend.cycle_next_profile()
        if ok:
            self._on_profile_changed(next_prof)
        else:
            QMessageBox.warning(
                self, "Permissão Necessária",
                f"Não foi possível alternar para o modo '{next_prof}' via Fn + Q.\n"
                "Instale/repare as Regras UDEV na aba 'Sobre o Dispositivo'."
            )

    def _apply_profile(self, profile_id: str):
        success, msg = self.backend.set_platform_profile(profile_id)
        if success:
            self._on_profile_changed(profile_id)
        else:
            QMessageBox.warning(self, "Permissão Necessária", f"Não foi possível alterar o perfil:\n{msg}")

    def _on_profile_changed(self, profile_id: str):
        norm_prof = self.backend.normalize_profile(profile_id)
        self.osd.notify_thermal_mode(norm_prof)
        self._update_header_profile_pill()
        self.dashboard_tab.update_telemetry()
        self.performance_tab.refresh_profile_state()
        self.automation_tab.refresh_automation_state()
        self.tray_manager.update_tray_state()

    def _apply_eco_travel(self, enable: bool):
        ok, msg = self.backend.set_eco_travel_mode(enable)
        if ok:
            self.osd.notify_feature_osd(
                title="Modo Viagem (Eco-Mode Extremo)" if enable else "Modo Viagem Desativado",
                subtitle=self.backend.get_eco_travel_summary() if enable else "Desempenho Padrão Restaurado",
                icon_name="eco_travel.svg",
                accent_color=ThemeTokens.STATUS_GREEN if enable else ThemeTokens.BORDER_CYAN
            )
            self._update_header_profile_pill()
            self.dashboard_tab.update_telemetry()
            self.performance_tab.refresh_profile_state()
            self.battery_tab.refresh_display()
            self.tray_manager.update_tray_state()
        else:
            self.dashboard_tab.item_eco_travel.set_checked(not enable)
            QMessageBox.warning(self, "Permissão Necessária", msg)

    def _apply_game_auto(self, enable: bool):
        self.backend.set_game_auto_switch(enable)
        self.osd.notify_feature_osd(
            title=f"Auto-Switch em Jogos: {'Ativado' if enable else 'Desativado'}",
            subtitle="Monitoramento inteligente Steam / Heroic / Proton",
            icon_name="game_controller.svg",
            accent_color=ThemeTokens.STATUS_GREEN if enable else ThemeTokens.TEXT_LIGHT_GRAY
        )
        self.dashboard_tab.update_telemetry()
        self.tray_manager.update_tray_state()

    def _apply_conservation(self, active: bool):
        success, msg = self.backend.set_conservation_mode(active)
        if success:
            if active and self.backend.features.rapid_charge:
                self.backend.set_rapid_charge(False)
                self.dashboard_tab.item_rapid_charge.set_checked(False)
            self.dashboard_tab.item_conservation.set_checked(active)
            self.battery_tab.refresh_display()
            self.tray_manager.update_tray_state()
        else:
            self.dashboard_tab.item_conservation.set_checked(not active)
            QMessageBox.warning(self, "Permissão Necessária", f"Não foi possível alterar o Modo de Conservação:\n{msg}")

    def _apply_rapid_charge(self, active: bool):
        success, msg = self.backend.set_rapid_charge(active)
        if success:
            if active and self.backend.features.conservation_mode:
                self.backend.set_conservation_mode(False)
                self.dashboard_tab.item_conservation.set_checked(False)
            self.dashboard_tab.item_rapid_charge.set_checked(active)
            self.battery_tab.refresh_display()
            self.tray_manager.update_tray_state()
        else:
            self.dashboard_tab.item_rapid_charge.set_checked(not active)
            QMessageBox.warning(self, "Permissão Necessária", f"Não foi possível alterar o Carregamento Rápido:\n{msg}")

    def _on_conservation_changed(self, active: bool):
        if active:
            self.dashboard_tab.item_rapid_charge.set_checked(False)
        self.dashboard_tab.item_conservation.set_checked(active)
        self.tray_manager.update_tray_state()

    def _on_rapid_charge_changed(self, active: bool):
        if active:
            self.dashboard_tab.item_conservation.set_checked(False)
        self.dashboard_tab.item_rapid_charge.set_checked(active)
        self.tray_manager.update_tray_state()

    def _apply_fn_lock(self, active: bool):
        success, msg = self.backend.set_fn_lock(active)
        if not success:
            self.about_tab.refresh_hardware_toggles()
            QMessageBox.warning(self, "Permissão Necessária", f"Não foi possível alterar o Fn-Lock:\n{msg}")

    def _apply_camera(self, active: bool):
        success, msg = self.backend.set_camera_power(active)
        if not success:
            self.dashboard_tab.item_camera.set_checked(not active)
            QMessageBox.warning(self, "Permissão Necessária", f"Não foi possível alterar o obturador da câmera:\n{msg}")

    def _apply_usb_charging(self, active: bool):
        success, msg = self.backend.set_usb_charging(active)
        if not success:
            self.about_tab.refresh_hardware_toggles()
            QMessageBox.warning(self, "Permissão Necessária", msg)

    def _apply_touchpad(self, locked: bool):
        ok, msg = self.backend.set_touchpad_status(locked)
        if not ok and getattr(self.dashboard_tab, "item_touchpad", None):
            self.dashboard_tab.item_touchpad.set_checked(not locked)
            QMessageBox.warning(self, "Touchpad", f"Não foi possível alterar o estado do Touchpad:\n{msg}")
        else:
            if getattr(self.dashboard_tab, "item_touchpad", None):
                self.dashboard_tab.item_touchpad.set_checked(locked)
            self.tray_manager.update_tray_state()

    def _apply_auto_power(self, enabled: bool):
        self.backend.set_auto_power_transition(enabled)

    def _apply_kbd_backlight(self, level: int):
        success, msg = self.backend.set_kbd_backlight(level)
        if success:
            self.dashboard_tab.item_kbd_backlight.set_level(level)
        else:
            QMessageBox.information(self, "Luz do Teclado", msg)

    # =========================================================================
    # Ciclo de Polling (200ms) e Telemetria (1500ms)
    # =========================================================================
    def _on_fast_poll(self):
        """Executado a cada 200ms para capturar eventos de Fn+Q, AC e Tecla Copilot instantaneamente."""
        events = self.backend.fast_poll_changes()
        for ev in events:
            ev_type = ev.get("type")

            # 1. Troca de Perfil via Fn+Q no teclado físico
            if ev_type == "profile_changed":
                new_p = ev.get("new", "balanced")
                self._on_profile_changed(new_p)

            # 2. Conexão / Desconexão da Fonte AC
            elif ev_type == "ac_changed":
                online = ev.get("ac_online", True)
                p_icon = os.path.join(ICON_DIR, "power.svg")
                if online:
                    self.osd.show_osd(
                        title="Alimentação AC Conectada",
                        subtitle="Carregador Plugado • Perfil Restaurado",
                        icon_path=p_icon,
                        accent_color=ThemeTokens.COLOR_SUCCESS
                    )
                else:
                    self.osd.show_osd(
                        title="Modo Bateria Ativado",
                        subtitle="Carregador Removido • Economia de Energia",
                        icon_path=p_icon,
                        accent_color=ThemeTokens.COLOR_WARNING
                    )
                self._update_header_profile_pill()
                self.dashboard_tab.update_telemetry()
                self.battery_tab.refresh_display()
                self.tray_manager.update_tray_state()

            # 3. Tecla Fn-Lock (Fn + Esc)
            elif ev_type == "fn_lock_changed":
                val = ev.get("value", False)
                self.osd.show_osd(
                    title="Trava Fn (Fn-Lock)",
                    subtitle="Fn-Lock Ativado" if val else "Fn-Lock Desativado",
                    icon_path=os.path.join(ICON_DIR, "edge_fn_lock.svg"),
                    accent_color=ThemeTokens.BORDER_CYAN
                )
                self.about_tab.refresh_hardware_toggles()

            # 4. Obturador de Câmera (E-Shutter)
            elif ev_type == "camera_changed":
                val = ev.get("value", True)
                self.osd.show_osd(
                    title="Obturador da Câmera",
                    subtitle="Câmera Ativada" if val else "Câmera Bloqueada (Privacidade)",
                    icon_path=os.path.join(ICON_DIR, "edge_camera.svg"),
                    accent_color=ThemeTokens.BORDER_CYAN if val else ThemeTokens.COLOR_DANGER
                )
                self.dashboard_tab.item_camera.set_checked(val)

            # 5. Modo de Conservação
            elif ev_type == "conservation_changed":
                val = ev.get("value", False)
                self.dashboard_tab.item_conservation.set_checked(val)
                self.battery_tab.refresh_display()
                self.tray_manager.update_tray_state()

            # 6. Brilho do Teclado (Fn + Espaço)
            elif ev_type == "kbd_backlight_changed":
                lvl = ev.get("value", 0)
                self.dashboard_tab.item_kbd_backlight.set_level(lvl)

            # 7. Tecla Copilot (F8/F23) ou Especial capturada via evdev
            elif ev_type == "custom_key_pressed":
                act = ev.get("action", "cycle_profile")
                cmd = ev.get("custom_command", "")
                self._execute_custom_key_action(act, cmd, source="evdev")

            # 8. Transição Automática de Taxa de Atualização (AC vs Bateria)
            elif ev_type == "refresh_rate_changed":
                hz = ev.get("hz", 60)
                reason = ev.get("reason", "ac")
                self.osd.notify_refresh_rate(hz, reason=reason)
                self.gpu_display_tab.refresh_display_state()

    def _on_test_battery_alert(self):
        """Dispara imediatamente um alerta de teste no KDE Plasma e no OSD."""
        alerts = self.backend.check_battery_smart_alerts(force_test=True)
        for al in alerts:
            self.tray_manager.send_native_notification(
                al.get("title", "Monitor da Bateria"),
                al.get("message", ""),
                al.get("urgency", "normal")
            )
            self.osd.notify_feature_osd(
                title=al.get("title", "Monitor Inteligente da Bateria"),
                subtitle=al.get("message", "")[:58],
                icon_name="battery_alert.svg",
                accent_color=ThemeTokens.STATUS_GREEN
            )

    def _on_telemetry_tick(self):
        """Atualização periódica de telemetria visual, Curva de Ventoinhas, App Rules e Alertas (1500ms)."""
        # 1. Aplicar tick dinâmico da Curva de Ventoinhas Personalizada no EC
        self.backend.apply_dynamic_fan_curve_tick()

        # 2. Verificar Auto-Switching por Jogo (Steam/Heroic/Proton) e App Rules
        game_ev = self.backend.check_game_auto_switch()
        if game_ev:
            g_type = game_ev.get("type")
            g_name = game_ev.get("game", "Aplicativo")
            g_prof = game_ev.get("profile", "max-power").upper()
            extras = game_ev.get("extras") or []
            extras_txt = (" • " + " • ".join(str(x) for x in extras)) if extras else ""
            if g_type == "game_started":
                self.osd.notify_feature_osd(
                    title=f"Jogo Detectado: {g_name[:22]}",
                    subtitle=f"Auto-Switch Ativado • {g_prof}{extras_txt}"[:58],
                    icon_name="game_controller.svg",
                    accent_color=ThemeTokens.THERMAL_CUSTOM
                )
            elif g_type == "app_rule_started":
                self.osd.notify_feature_osd(
                    title=f"App Rule: {g_name[:24]}",
                    subtitle=f"Perfil Aplicado Automaticamente • {g_prof}",
                    icon_name="app_rules.svg",
                    accent_color=ThemeTokens.BORDER_CYAN
                )
            elif g_type == "game_stopped":
                self.automation_tab._rebuild_game_session_history()
            if self.backend.features.touchpad_control and getattr(self.dashboard_tab, "item_touchpad", None):
                self.dashboard_tab.item_touchpad.set_checked(self.backend.get_touchpad_status())
            self._update_header_profile_pill()
            self.dashboard_tab.update_telemetry()
            self.performance_tab.refresh_profile_state()
            self.gpu_display_tab.refresh_display_state()
            self.automation_tab.refresh_automation_state()
            self.tray_manager.update_tray_state()

        if self.backend.get_active_game():
            cpu_m = self.backend.get_cpu_metrics()
            gpu_m = self.backend.get_gpu_metrics()
            rapl_w = self.backend._read_rapl_package_watts()
            tot_w = (gpu_m.power_draw_w if gpu_m.available else 0.0) + (rapl_w if rapl_w > 0 else 0.0)
            self.backend.update_game_session_peaks(
                cpu_m.temperature_c,
                gpu_m.temperature_c if gpu_m.available else 0.0,
                tot_w,
            )

        # 2.5 Verificar Modo Mesa (Monitor Externo), Regras Wi-Fi SSID e Perfil Noturno
        for bg_ev in (
            self.backend.check_external_monitor_dock_mode(),
            self.backend.check_wifi_ssid_rules(),
            self.backend.check_night_schedule(),
        ):
            if not bg_ev:
                continue
            ev_t = bg_ev.get("type", "")
            if ev_t in ("dock_mode_entered", "dock_mode_exited"):
                self.osd.notify_feature_osd(
                    title="Modo Mesa (Monitor Externo)" if ev_t == "dock_mode_entered" else "Monitor Externo Desconectado",
                    subtitle=str(bg_ev.get("summary", ""))[:58],
                    icon_name="gpu_stack.svg",
                    accent_color=ThemeTokens.ACCENT_STEEL,
                )
            elif ev_t == "wifi_rule_applied":
                self.osd.notify_feature_osd(
                    title=f"Regra Wi-Fi: {str(bg_ev.get('ssid', ''))[:24]}",
                    subtitle=str(bg_ev.get("summary", ""))[:58],
                    icon_name="network_power.svg",
                    accent_color=ThemeTokens.STATUS_GREEN,
                )
            elif ev_t in ("night_mode_entered", "night_mode_exited"):
                self.osd.notify_feature_osd(
                    title="Perfil Noturno Ativado" if ev_t == "night_mode_entered" else "Perfil Noturno Encerrado",
                    subtitle=str(bg_ev.get("summary", ""))[:58],
                    icon_name="thermal_quiet.svg",
                    accent_color=ThemeTokens.THERMAL_QUIET,
                )
            self._update_header_profile_pill()
            self.dashboard_tab.update_telemetry()
            self.performance_tab.refresh_profile_state()
            self.gpu_display_tab.refresh_all()
            self.tray_manager.update_tray_state()

        # 3. Verificar Alertas Inteligentes de Ciclo de Vida e Temperatura da Bateria
        bat_alerts = self.backend.check_battery_smart_alerts(force_test=False)
        for al in bat_alerts:
            urg = al.get("urgency", "normal")
            self.tray_manager.send_native_notification(
                al.get("title", "Alerta da Bateria"),
                al.get("message", ""),
                urg
            )
            self.osd.notify_feature_osd(
                title=al.get("title", "Alerta da Bateria"),
                subtitle=al.get("message", "")[:56],
                icon_name="battery_alert.svg",
                accent_color=ThemeTokens.LEGION_RED if urg == "critical" else ThemeTokens.STATUS_GREEN
            )

        if self.isVisible():
            idx = self.stack.currentIndex()
            if idx == 0:
                self.dashboard_tab.update_telemetry()
            elif idx == 1:
                self.performance_tab.refresh_profile_state()
            elif idx == 2:
                self.battery_tab.refresh_display()
            elif idx == 5:
                self.gpu_display_tab.refresh_all()
            elif idx == 6:
                self.automation_tab.refresh_automation_state()

        bat = self.backend.get_battery_info()
        self.header_bat_pill.setVisible(bat.available)
        if bat.available:
            status_txt = "AC" if bat.ac_connected else "BAT"
            self.header_bat_pill.setText(f"{bat.capacity_percent}% {status_txt}")
            if bat.capacity_percent > 25:
                self.header_bat_pill.setColor("transparent", ThemeTokens.TEXT_WHITE_80)
            else:
                self.header_bat_pill.setColor("transparent", ThemeTokens.COLOR_WARNING)

        self._update_header_profile_pill()
        self.tray_manager.update_tray_state()

    def _update_header_profile_pill(self):
        self.header_eco_pill.setVisible(bool(self.backend.features.eco_travel and self.backend.get_eco_travel_mode()))
        if not self.backend.features.platform_profile:
            self.header_profile_pill.setVisible(False)
            return
        self.header_profile_pill.setVisible(True)
        prof = self.backend.normalize_profile(self.backend.get_platform_profile())
        if prof == "max-power":
            self.header_profile_pill.setText("MAX-POWER")
            self.header_profile_pill.setColor("transparent", ThemeTokens.ACCENT_STEEL)
        elif prof == "custom":
            self.header_profile_pill.setText("CUSTOM")
            self.header_profile_pill.setColor("transparent", ThemeTokens.THERMAL_CUSTOM)
        elif prof == "performance":
            self.header_profile_pill.setText("DESEMPENHO")
            self.header_profile_pill.setColor("transparent", ThemeTokens.THERMAL_PERFORMANCE)
        elif prof in ("low-power", "quiet"):
            self.header_profile_pill.setText("SILENCIOSO")
            self.header_profile_pill.setColor("transparent", ThemeTokens.THERMAL_QUIET)
        else:
            self.header_profile_pill.setText("EQUILIBRADO")
            self.header_profile_pill.setColor("transparent", ThemeTokens.TEXT_WHITE_80)

    def _apply_autostart(self, enabled: bool):
        ok, msg = self.backend.set_autostart_enabled(enabled)
        if not ok:
            QMessageBox.critical(self, "Erro no Autostart", msg)
        self._on_autostart_changed(self.backend.get_autostart_enabled())

    def _on_autostart_changed(self, enabled: bool):
        self.about_tab.update_autostart_status()
        self.tray_manager.update_tray_state()
        self.osd.notify_feature_osd(
            title="Iniciar com o Sistema",
            subtitle="Ativado em ~/.config/autostart" if enabled else "Inicialização automática desativada",
            icon_name="power.svg",
            accent_color=ThemeTokens.STATUS_GREEN if enabled else ThemeTokens.BORDER_CYAN
        )

    def _toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()
            self._on_telemetry_tick()

    def _quit_app(self):
        self._is_quitting = True
        if hasattr(self, "fast_poll_timer"):
            self.fast_poll_timer.stop()
        if hasattr(self, "telemetry_timer"):
            self.telemetry_timer.stop()
        if hasattr(self, "about_tab") and hasattr(self.about_tab, "cleanup_workers"):
            self.about_tab.cleanup_workers()
        if hasattr(self, "performance_tab") and hasattr(self.performance_tab, "_checkup_timer"):
            self.performance_tab._checkup_timer.stop()
        if hasattr(self, "dbus_service") and self.dbus_service:
            self.dbus_service.stop()
        if hasattr(self, "backend") and self.backend:
            self.backend.close()
        QApplication.quit()

    def closeEvent(self, event):
        """Ao fechar a janela, minimiza para a bandeja se configurado e disponível, ou encerra o app."""
        tray_available = (
            QSystemTrayIcon.isSystemTrayAvailable()
            and self.tray_manager is not None
            and self.tray_manager.is_available()
        )
        if not self._is_quitting and tray_available and self.backend.get_minimize_to_tray():
            event.ignore()
            self.hide()
        else:
            self._quit_app()
            event.accept()
