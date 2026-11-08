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
from typing import List
from core.qt_compat import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget, QTimer, Qt, QFont,
    QIcon, QSize, QApplication, QMessageBox, QShortcut, QKeySequence
)
from core.backend import HardwareBackend
from ui.theme_tokens import ThemeTokens
from ui.components import StatusBadge
from ui.tray_icon import SystemTrayManager
from ui.osd_overlay import VantageOSDOverlay
from ui.dashboard import VantageDashboardView
from ui.tabs.performance_tab import PerformanceTab
from ui.tabs.battery_tab import BatteryTab
from ui.tabs.about_tab import AboutTab

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")
RESOURCE_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons")


def get_asset_icon(name: str) -> QIcon:
    """Busca o ícone SVG em assets/icons/ com fallback em resources/icons/."""
    for d in (ICON_DIR, RESOURCE_ICON_DIR):
        p = os.path.join(d, name)
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

        # Pilha de 4 Abas Essenciais (Fim das Duplicações)
        self.stack = QStackedWidget()
        self.dashboard_tab = VantageDashboardView(self.backend)
        self.performance_tab = PerformanceTab(self.backend)
        self.battery_tab = BatteryTab(self.backend)
        self.about_tab = AboutTab(self.backend)

        self.stack.addWidget(self.dashboard_tab)    # Índice 0: Dashboard
        self.stack.addWidget(self.performance_tab)  # Índice 1: Desempenho
        self.stack.addWidget(self.battery_tab)      # Índice 2: Alimentação & Bateria
        self.stack.addWidget(self.about_tab)        # Índice 3: Sobre o Dispositivo

        workspace.addWidget(self.stack, stretch=1)
        main_layout.addLayout(workspace, stretch=1)

        # 3. Pop-up OSD Não-Intrusivo (para Fn+Q, Auto-Switch Jogo, Modo Viagem e Tecla Copilot)
        self.osd = VantageOSDOverlay()

        # 4. Bandeja do Sistema (System Tray Manager)
        self.tray_manager = SystemTrayManager(self.backend, self)

        # 5. Conectar Sinais Intermódulos e Registrar Atalhos do Remapper
        self._connect_signals()
        self._register_qt_shortcuts()

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

        # Inicialização visual na Aba 0 (Dashboard)
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
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(14)

        # Logo Oficial Lenovo + Emblema Ducksvantage
        logo_icon = get_asset_icon("lenovo_logo.svg")
        if not logo_icon.isNull():
            lbl_logo = QLabel()
            lbl_logo.setPixmap(logo_icon.pixmap(68, 20))
            layout.addWidget(lbl_logo)

        title = QLabel("DUCKSVANTAGE")
        title.setObjectName("headerTitle")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # Badge Dinâmica do Modelo Detectado via DMI (Zero Hardcoding)
        model_name = self.backend.system_info.display_model_name or "LENOVO"
        self.model_pill = StatusBadge(f"{model_name.upper()}", bg_color="#253048", text_color="#fbfdff")
        layout.addWidget(self.model_pill)

        layout.addStretch()

        # Badge de Eco-Mode / Auto-Gaming
        self.header_eco_pill = StatusBadge("ECO VIAGEM ATIVO", bg_color="#064e3b", text_color="#2fe08c")
        self.header_eco_pill.setVisible(False)
        layout.addWidget(self.header_eco_pill)

        # Badge do Perfil Ativo
        self.header_profile_pill = StatusBadge("EQUILIBRADO", bg_color="#293c4f", text_color="#2ec5eb")
        layout.addWidget(self.header_profile_pill)

        # Badge de Bateria e Fonte AC
        self.header_bat_pill = StatusBadge("BATERIA: --%", bg_color="#064e3b", text_color="#34d399")
        layout.addWidget(self.header_bat_pill)

        return header

    def _create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 16, 0, 16)
        layout.setSpacing(4)

        # 4 Abas Essenciais (Sem aba duplicada de Iluminação)
        nav_items = [
            ("Dashboard", "nav_dashboard.svg", "nav_dashboard_active.svg", 0),
            ("Desempenho", "nav_performance.svg", "nav_performance_active.svg", 1),
            ("Alimentação & Bateria", "nav_battery.svg", "nav_battery_active.svg", 2),
            ("Sobre o Dispositivo", "nav_about.svg", "nav_about_active.svg", 3),
        ]

        buttons = []
        icon_pairs = []
        for text, inactive_icon, active_icon, index in nav_items:
            btn = QPushButton(f"  {text}")
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

            ic_off = get_asset_icon(inactive_icon)
            ic_on = get_asset_icon(active_icon)
            if not ic_off.isNull():
                btn.setIcon(ic_off)
                btn.setIconSize(QSize(20, 20))

            btn.clicked.connect(lambda checked, idx=index: self._switch_tab(idx))
            layout.addWidget(btn)
            buttons.append(btn)
            icon_pairs.append((ic_off, ic_on))

        layout.addStretch()

        # Emblema Ducksvantage no rodapé
        v_logo = get_asset_icon("ducksvantage_logo.svg")
        if not v_logo.isNull():
            footer_logo = QLabel()
            footer_logo.setPixmap(v_logo.pixmap(28, 28))
            footer_logo.setStyleSheet("padding: 0px 22px;")
            layout.addWidget(footer_logo)

        sys = self.backend.system_info
        k_info = QLabel(f"{sys.os_name} • {sys.laptop_line}\nKernel {sys.kernel_version}")
        k_info.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_40}; font-size: 10px; padding: 6px 22px;")
        layout.addWidget(k_info)

        return sidebar, buttons, icon_pairs

    def _switch_tab(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            is_sel = (i == index)
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

        # 3. ELITE 5: Mapeador de Teclas Personalizadas (Tecla Copilot F23 & Atalhos)
        self.performance_tab.shortcuts_updated.connect(self._register_qt_shortcuts)
        self.performance_tab.custom_action_requested.connect(self._execute_custom_key_action)

        # 4. Exclusão Mútua de Bateria (Modo de Conservação vs Rapid Charge) e Alertas Inteligentes
        self.dashboard_tab.conservation_toggled.connect(self._apply_conservation)
        self.dashboard_tab.rapid_charge_toggled.connect(self._apply_rapid_charge)
        self.battery_tab.conservation_changed.connect(self._on_conservation_changed)
        self.battery_tab.rapid_charge_changed.connect(self._on_rapid_charge_changed)
        self.battery_tab.test_alert_requested.connect(self._on_test_battery_alert)
        self.tray_manager.conservation_toggled.connect(self._apply_conservation)

        # 5. Controles do Painel EDGE
        self.dashboard_tab.fn_lock_toggled.connect(self._apply_fn_lock)
        self.dashboard_tab.camera_toggled.connect(self._apply_camera)
        self.dashboard_tab.usb_charging_toggled.connect(self._apply_usb_charging)
        self.dashboard_tab.touchpad_toggled.connect(self._apply_touchpad)
        self.dashboard_tab.auto_power_toggled.connect(self._apply_auto_power)
        self.dashboard_tab.kbd_backlight_requested.connect(self._apply_kbd_backlight)

        # 6. Aba Sobre / UDEV / Autostart XDG
        self.about_tab.permissions_updated.connect(self.about_tab.update_permission_status)
        self.about_tab.autostart_toggled.connect(self._on_autostart_changed)
        self.tray_manager.autostart_toggled.connect(self._apply_autostart)

        # 7. Bandeja do Sistema
        self.tray_manager.show_window_requested.connect(self._toggle_visibility)
        self.tray_manager.quit_requested.connect(self._quit_app)

    def _register_qt_shortcuts(self):
        """Registra os atalhos de teclado (incluindo F23 / Meta+Shift+F23 da tecla Copilot)."""
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

            sequences = [seq_str] if seq_str else []
            # No Windows/Linux, a tecla Copilot física envia F23 ou Meta+Shift+F23
            if slot_id == "copilot_key" and "Meta+Shift+F23" not in sequences:
                sequences.append("Meta+Shift+F23")

            for s_txt in sequences:
                sc = QShortcut(QKeySequence(s_txt), self)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                sc.activated.connect(lambda a=act_id, c=custom_cmd: self._execute_custom_key_action(a, c))
                self._active_shortcuts.append(sc)

    def _execute_custom_key_action(self, action_id: str, custom_cmd: str = ""):
        """Executa a ação associada a uma tecla remapeada e exibe o OSD correspondente."""
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
        elif osd_type == "window":
            self._toggle_visibility()

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
        self.tray_manager.update_tray_state()

    def _apply_eco_travel(self, enable: bool):
        ok, msg = self.backend.set_eco_travel_mode(enable)
        if ok:
            self.osd.notify_feature_osd(
                title="Modo Viagem (Eco-Mode Extremo)" if enable else "Modo Viagem Desativado",
                subtitle="Conservação 80% • GPU D3cold • Turbo Off • Low Power" if enable else "Desempenho Padrão Restaurado",
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

    def _apply_conservation(self, active: bool):
        success, msg = self.backend.set_conservation_mode(active)
        if success:
            if active:
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
            if active:
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
            self.dashboard_tab.item_fn_lock.set_checked(not active)
            QMessageBox.warning(self, "Permissão Necessária", f"Não foi possível alterar o Fn-Lock:\n{msg}")

    def _apply_camera(self, active: bool):
        success, msg = self.backend.set_camera_power(active)
        if not success:
            self.dashboard_tab.item_camera.set_checked(not active)
            QMessageBox.warning(self, "Permissão Necessária", f"Não foi possível alterar o obturador da câmera:\n{msg}")

    def _apply_usb_charging(self, active: bool):
        success, msg = self.backend.set_usb_charging(active)
        if not success and self.dashboard_tab.item_usb:
            self.dashboard_tab.item_usb.set_checked(not active)
            QMessageBox.warning(self, "Permissão Necessária", msg)

    def _apply_touchpad(self, locked: bool):
        self.backend.set_touchpad_status(locked)

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
                self.dashboard_tab.item_fn_lock.set_checked(val)

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

            # 7. Tecla Copilot (F23) ou Especial capturada via evdev
            elif ev_type == "custom_key_pressed":
                act = ev.get("action", "cycle_profile")
                cmd = ev.get("custom_command", "")
                self._execute_custom_key_action(act, cmd)

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
            if g_type == "game_started":
                self.osd.notify_feature_osd(
                    title=f"Jogo Detectado: {g_name[:22]}",
                    subtitle=f"Auto-Switch Ativado • Modo {g_prof}",
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
                self.osd.notify_feature_osd(
                    title="Sessão Encerrada",
                    subtitle=f"Perfil Restaurado • Modo {g_prof}",
                    icon_name="game_controller.svg",
                    accent_color=ThemeTokens.THERMAL_BALANCED
                )

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

        bat = self.backend.get_battery_info()
        if bat.available:
            status_txt = "AC" if bat.ac_connected else "BAT"
            self.header_bat_pill.setText(f"{status_txt}: {bat.capacity_percent}%")
            if bat.capacity_percent > 25:
                self.header_bat_pill.setColor("#064e3b", "#34d399")
            else:
                self.header_bat_pill.setColor("#78350f", "#fbbf24")

        self._update_header_profile_pill()
        self.tray_manager.update_tray_state()

    def _update_header_profile_pill(self):
        self.header_eco_pill.setVisible(self.backend.get_eco_travel_mode())
        prof = self.backend.normalize_profile(self.backend.get_platform_profile())
        if prof == "max-power":
            self.header_profile_pill.setText("MAX-POWER")
            self.header_profile_pill.setColor("#581c87", ThemeTokens.THERMAL_CUSTOM)
        elif prof == "performance":
            self.header_profile_pill.setText("DESEMPENHO")
            self.header_profile_pill.setColor("#7f1d1d", ThemeTokens.THERMAL_PERFORMANCE)
        elif prof in ("low-power", "quiet"):
            self.header_profile_pill.setText("SILENCIOSO")
            self.header_profile_pill.setColor("#0369a1", ThemeTokens.THERMAL_QUIET)
        else:
            self.header_profile_pill.setText("EQUILIBRADO")
            self.header_profile_pill.setColor("#155e75", ThemeTokens.THERMAL_BALANCED)

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
        QApplication.quit()

    def closeEvent(self, event):
        """Ao fechar a janela, minimiza para a bandeja para manter o OSD e Fn+Q ativos."""
        if not self._is_quitting and self.tray_manager and self.tray_manager.tray_icon.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()
