"""
Aba Sobre o Dispositivo do Ducksvantage (ui/tabs/about_tab.py).
Apresenta informações completas e dinâmicas de DMI/BIOS, Processador, GPU, Kernel e SSDs,
além de um card compacto de status UDEV com botão de reparo (sem blocos de código que gerem scroll horizontal).
Zero emojis: utiliza exclusivamente ícones vetoriais SVG.
"""

import os
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QPushButton, QScrollArea, QStackedWidget, QComboBox, QFileDialog,
    Qt, Signal, QFont, QThread, QMessageBox, QApplication, QIcon, QPixmap
)
from core.backend import APP_VERSION
from ui.theme_tokens import ThemeTokens
from ui.components import StatusBadge, ToggleSwitch, SubTabSelector
from core.permissions import PermissionsManager

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")

PROFILE_LABELS_PREFS = {
    "low-power": "Modo Silencioso (Low-Power)",
    "balanced": "Modo Equilibrado (Balanced)",
    "performance": "Modo Desempenho (Performance)",
    "max-power": "Desempenho Máximo (Max-Power)",
}


class UpdateCheckWorker(QThread):
    """Thread leve para verificar atualizações no GitHub sem travar a interface."""
    finished_check = Signal(dict)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend

    def run(self):
        res = self.backend.check_for_updates()
        self.finished_check.emit(res)


class AboutTab(QWidget):
    """Preferências, Integração KDE, Hardware e Permissões UDEV do Ducksvantage."""
    permissions_updated = Signal()
    autostart_toggled = Signal(bool)
    preferences_changed = Signal()
    test_osd_requested = Signal()
    fn_lock_toggled = Signal(bool)
    usb_charging_toggled = Signal(bool)
    auto_power_toggled = Signal(bool)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._advanced_mode = self.backend.is_advanced_mode()
        self._update_worker = None

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(22, 18, 22, 20)
        root_layout.setSpacing(14)

        self.sub_tabs = SubTabSelector([
            ("prefs", "Preferências & Integração"),
            ("system", "Hardware & Permissões"),
        ])
        root_layout.addWidget(self.sub_tabs)

        self.sub_stack = QStackedWidget()
        self.sub_tabs.tab_selected.connect(self.sub_stack.setCurrentIndex)
        root_layout.addWidget(self.sub_stack, stretch=1)

        page_prefs = QWidget()
        prefs_page_layout = QVBoxLayout(page_prefs)
        prefs_page_layout.setContentsMargins(0, 0, 0, 0)
        prefs_page_layout.setSpacing(16)

        page_sys = QWidget()
        sys_page_layout = QVBoxLayout(page_sys)
        sys_page_layout.setContentsMargins(0, 0, 0, 0)
        sys_page_layout.setSpacing(16)

        # =====================================================================
        # 1. Card de Identificação DMI / BIOS / Hardware do Dispositivo
        # =====================================================================
        self.info_card = QFrame()
        info_card = self.info_card
        info_card.setProperty("class", "card")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(20, 18, 20, 18)
        info_layout.setSpacing(16)

        info_header = QHBoxLayout()
        icon = QLabel()
        dv_path = os.path.join(ICON_DIR, "ducksvantage_logo.svg")
        if os.path.exists(dv_path):
            icon.setPixmap(QPixmap(dv_path).scaled(34, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        info_header.addWidget(icon)

        sys = self.backend.system_info
        title_box = QVBoxLayout()
        title = QLabel(f"Ducksvantage • {sys.display_model_name} ({sys.product_name})")
        title.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        title_box.addWidget(title)

        subtitle = QLabel("Substituto universal e leve do Lenovo Vantage para notebooks Legion, LOQ, IdeaPad e Yoga no Linux.")
        subtitle.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        title_box.addWidget(subtitle)
        info_header.addLayout(title_box)

        info_header.addStretch()

        ver_badge = StatusBadge(f"DUCKSVANTAGE v{APP_VERSION}", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        info_header.addWidget(ver_badge)

        info_layout.addLayout(info_header)

        # Grid completo com especificações dinâmicas (Zero Hardcoding)
        grid = QGridLayout()
        grid.setSpacing(10)

        self._add_spec_item(grid, 0, 0, "Fabricante & Linha", f"{sys.sys_vendor} ({sys.laptop_line})")
        self._add_spec_item(grid, 0, 1, "Modelo / Produto DMI", f"{sys.display_model_name} ({sys.product_name})")
        self._add_spec_item(grid, 0, 2, "Versão & Data da BIOS", f"{sys.bios_version} ({sys.bios_date})")
        self._add_spec_item(grid, 1, 0, "Processador (CPU)", sys.cpu_model)
        self._add_spec_item(grid, 1, 1, "Placa Gráfica (GPU)", sys.gpu_model)
        self._add_spec_item(grid, 1, 2, "Armazenamento (SSDs)", sys.ssd_summary)
        self._add_spec_item(grid, 2, 0, "Sistema Operacional", sys.os_name)
        self._add_spec_item(grid, 2, 1, "Versão do Kernel", sys.kernel_version)
        self._add_spec_item(grid, 2, 2, "Placa-Mãe (Board)", sys.board_name)

        info_layout.addLayout(grid)

        diag_row = QHBoxLayout()
        diag_row.setSpacing(10)
        self.btn_copy_diag = QPushButton("Copiar Diagnóstico de Hardware")
        self.btn_copy_diag.setIcon(QIcon(os.path.join(ICON_DIR, "copy.svg")))
        self.btn_copy_diag.setProperty("class", "secondaryButton")
        self.btn_copy_diag.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_diag.clicked.connect(self._copy_diagnostic_action)
        diag_row.addWidget(self.btn_copy_diag)

        self.btn_check_updates = QPushButton("Verificar Atualizações")
        self.btn_check_updates.setIcon(QIcon(os.path.join(ICON_DIR, "update.svg")))
        self.btn_check_updates.setProperty("class", "secondaryButton")
        self.btn_check_updates.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_updates.clicked.connect(self._check_updates_action)
        diag_row.addWidget(self.btn_check_updates)

        self.update_status_lbl = QLabel(
            "Diagnóstico Markdown sem dados pessoais • Checagem manual no GitHub (zero telemetria)."
        )
        self.update_status_lbl.setWordWrap(True)
        self.update_status_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        diag_row.addWidget(self.update_status_lbl, stretch=1)
        info_layout.addLayout(diag_row)

        sys_page_layout.addWidget(info_card)

        # =====================================================================
        # 2. Card de Inicialização Automática Universal (XDG Autostart)
        # =====================================================================
        self.autostart_card = QFrame()
        autostart_card = self.autostart_card
        autostart_card.setProperty("class", "card")
        autostart_layout = QHBoxLayout(autostart_card)
        autostart_layout.setContentsMargins(20, 16, 20, 16)
        autostart_layout.setSpacing(14)

        auto_icon = QLabel()
        power_icon_path = os.path.join(ICON_DIR, "power.svg")
        if os.path.exists(power_icon_path):
            auto_icon.setPixmap(QPixmap(power_icon_path).scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        autostart_layout.addWidget(auto_icon)

        auto_titles = QVBoxLayout()
        auto_titles.setSpacing(3)
        auto_title = QLabel("Iniciar com o sistema")
        auto_title.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.Bold))
        auto_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        auto_titles.addWidget(auto_title)

        self.autostart_desc_lbl = QLabel(
            "Inicia o Ducksvantage silenciosamente na bandeja ao ligar o computador."
        )
        self.autostart_desc_lbl.setToolTip("Atalho XDG (~/.config/autostart/ducksvantage.desktop com --minimized)")
        self.autostart_desc_lbl.setWordWrap(True)
        self.autostart_desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        auto_titles.addWidget(self.autostart_desc_lbl)
        autostart_layout.addLayout(auto_titles, stretch=1)

        self.autostart_badge = StatusBadge("DESATIVADO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.TEXT_WHITE_80)
        autostart_layout.addWidget(self.autostart_badge)

        self.autostart_toggle = ToggleSwitch(checked=self.backend.get_autostart_enabled())
        self.autostart_toggle.toggled.connect(self._on_autostart_toggled)
        autostart_layout.addWidget(self.autostart_toggle)

        prefs_page_layout.addWidget(autostart_card)

        # =====================================================================
        # 2.5 Card de Preferências do App, OSD, Transição AC/Bateria & Backup JSON
        # =====================================================================
        feat = self.backend.features
        supported_profiles = self.backend.get_supported_canonical_profiles()
        self.prefs_card = QFrame()
        self.prefs_card.setProperty("class", "card")
        prefs_layout = QVBoxLayout(self.prefs_card)
        prefs_layout.setContentsMargins(20, 18, 20, 18)
        prefs_layout.setSpacing(12)

        prefs_header = QHBoxLayout()
        ic_pref = QLabel()
        g_path = os.path.join(ICON_DIR, "gear.svg")
        if os.path.exists(g_path):
            ic_pref.setPixmap(QPixmap(g_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        prefs_header.addWidget(ic_pref)

        pref_titles = QVBoxLayout()
        pt_t = QLabel("Preferências do Aplicativo, Pop-up OSD & Backup")
        pt_t.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.Bold))
        pt_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        pref_titles.addWidget(pt_t)

        pt_s = QLabel("Personalize o overlay OSD no Wayland/X11, perfis de tomada/bateria e exporte suas configurações.")
        pt_s.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        pref_titles.addWidget(pt_s)
        prefs_header.addLayout(pref_titles, stretch=1)
        prefs_layout.addLayout(prefs_header)

        # Linha 1: OSD Ativo, Posição, Duração e Testar OSD
        osd_box = QFrame()
        osd_box.setProperty("class", "subBox")
        osd_v = QVBoxLayout(osd_box)
        osd_v.setContentsMargins(14, 10, 14, 10)
        osd_v.setSpacing(8)

        osd_row1 = QHBoxLayout()
        osd_lbl = QLabel("Exibir Pop-up Flutuante (OSD) ao trocar Fn+Q, Jogos ou Brilho")
        osd_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.Bold))
        osd_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        osd_row1.addWidget(osd_lbl, stretch=1)
        self.sw_osd_enabled = ToggleSwitch(checked=self.backend.get_osd_enabled())
        self.sw_osd_enabled.toggled.connect(self._on_pref_changed)
        osd_row1.addWidget(self.sw_osd_enabled)
        osd_v.addLayout(osd_row1)

        osd_row2 = QHBoxLayout()
        osd_row2.setSpacing(10)
        pos_lbl = QLabel("Posição:")
        pos_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        osd_row2.addWidget(pos_lbl)

        self.combo_osd_position = QComboBox()
        self.combo_osd_position.setFixedHeight(28)
        for pid, plbl in [
            ("bottom-center", "Inferior Central"),
            ("top-center", "Topo Central"),
            ("top-right", "Canto Superior Direito"),
        ]:
            self.combo_osd_position.addItem(plbl, pid)
        p_idx = self.combo_osd_position.findData(self.backend.get_osd_position())
        if p_idx >= 0:
            self.combo_osd_position.setCurrentIndex(p_idx)
        self.combo_osd_position.currentIndexChanged.connect(self._on_pref_changed)
        osd_row2.addWidget(self.combo_osd_position)

        dur_lbl = QLabel("Duração:")
        dur_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        osd_row2.addWidget(dur_lbl)

        self.combo_osd_duration = QComboBox()
        self.combo_osd_duration.setFixedHeight(28)
        self.combo_osd_duration.setStyleSheet(self.combo_osd_position.styleSheet())
        for ms_val, ms_lbl in [(1200, "1,2s (Rápido)"), (1800, "1,8s (Padrão)"), (2800, "2,8s"), (4000, "4,0s (Longo)")]:
            self.combo_osd_duration.addItem(ms_lbl, ms_val)
        d_idx = self.combo_osd_duration.findData(self.backend.get_osd_duration_ms())
        if d_idx >= 0:
            self.combo_osd_duration.setCurrentIndex(d_idx)
        self.combo_osd_duration.currentIndexChanged.connect(self._on_pref_changed)
        osd_row2.addWidget(self.combo_osd_duration)

        osd_row2.addStretch()

        self.btn_test_osd = QPushButton("Testar OSD")
        self.btn_test_osd.setProperty("class", "secondaryButton")
        self.btn_test_osd.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_osd.clicked.connect(self.test_osd_requested.emit)
        osd_row2.addWidget(self.btn_test_osd)
        osd_v.addLayout(osd_row2)
        prefs_layout.addWidget(osd_box)

        # Linha 2: Minimizar ao fechar + Resumo Pós-Jogo
        beh_box = QFrame()
        beh_box.setProperty("class", "subBox")
        beh_v = QVBoxLayout(beh_box)
        beh_v.setContentsMargins(14, 10, 14, 10)
        beh_v.setSpacing(8)

        min_row = QHBoxLayout()
        min_lbl = QLabel("Minimizar para a bandeja do sistema ao clicar em Fechar (X)")
        min_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        min_row.addWidget(min_lbl, stretch=1)
        self.sw_minimize_to_tray = ToggleSwitch(checked=self.backend.get_minimize_to_tray())
        self.sw_minimize_to_tray.toggled.connect(self._on_pref_changed)
        min_row.addWidget(self.sw_minimize_to_tray)
        beh_v.addLayout(min_row)
        prefs_layout.addWidget(beh_box)

        # Linha 3: Perfis automáticos AC vs Bateria (oculto se não houver ACPI + bateria)
        self.ac_bat_prefs_widget = QFrame()
        self.ac_bat_prefs_widget.setProperty("class", "subBox")
        ab_v = QVBoxLayout(self.ac_bat_prefs_widget)
        ab_v.setContentsMargins(14, 10, 14, 10)
        ab_v.setSpacing(8)

        ab_top = QHBoxLayout()
        ab_toggle_lbl = QLabel("Alternar perfil térmico automaticamente entre Tomada (AC) e Bateria")
        ab_toggle_lbl.setWordWrap(True)
        ab_toggle_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        ab_top.addWidget(ab_toggle_lbl, stretch=1)
        self.sw_auto_power = ToggleSwitch(checked=self.backend.get_auto_power_transition())
        self.sw_auto_power.toggled.connect(self.auto_power_toggled.emit)
        ab_top.addWidget(self.sw_auto_power)
        ab_v.addLayout(ab_top)

        ab_row = QHBoxLayout()
        ab_row.setContentsMargins(0, 0, 0, 0)
        ab_row.setSpacing(10)

        ac_l = QLabel("Perfil na Tomada (AC):")
        ac_l.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        ab_row.addWidget(ac_l)

        self.combo_ac_profile = QComboBox()
        self.combo_ac_profile.setFixedHeight(28)
        self.combo_ac_profile.setStyleSheet(self.combo_osd_position.styleSheet())
        bat_l = QLabel("Perfil na Bateria:")
        bat_l.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        self.combo_battery_profile = QComboBox()
        self.combo_battery_profile.setFixedHeight(28)
        self.combo_battery_profile.setStyleSheet(self.combo_osd_position.styleSheet())

        for pid in supported_profiles:
            plabel = PROFILE_LABELS_PREFS.get(pid, pid.upper())
            self.combo_ac_profile.addItem(plabel, pid)
            self.combo_battery_profile.addItem(plabel, pid)

        ac_i = self.combo_ac_profile.findData(self.backend.get_ac_profile())
        if ac_i >= 0:
            self.combo_ac_profile.setCurrentIndex(ac_i)
        bat_i = self.combo_battery_profile.findData(self.backend.get_battery_profile())
        if bat_i >= 0:
            self.combo_battery_profile.setCurrentIndex(bat_i)

        self.combo_ac_profile.currentIndexChanged.connect(self._on_pref_changed)
        self.combo_battery_profile.currentIndexChanged.connect(self._on_pref_changed)
        ab_row.addWidget(self.combo_ac_profile, stretch=1)
        ab_row.addWidget(bat_l)
        ab_row.addWidget(self.combo_battery_profile, stretch=1)
        ab_v.addLayout(ab_row)
        self.ac_bat_prefs_widget.setVisible(bool(feat.platform_profile and feat.battery and supported_profiles))
        prefs_layout.addWidget(self.ac_bat_prefs_widget)

        # Linha 3.5: Controles de Hardware de Configuração Eventual (Trava Fn & Energia USB)
        self.hw_toggles_box = QFrame()
        self.hw_toggles_box.setProperty("class", "subBox")
        hw_v = QVBoxLayout(self.hw_toggles_box)
        hw_v.setContentsMargins(14, 10, 14, 10)
        hw_v.setSpacing(8)

        self.fn_lock_row_widget = QWidget()
        fn_r = QHBoxLayout(self.fn_lock_row_widget)
        fn_r.setContentsMargins(0, 0, 0, 0)
        fn_lbl = QLabel("Trava Fn (Fn-Lock) • Alterna F1–F12 diretos vs multimídia")
        fn_lbl.setWordWrap(True)
        fn_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        fn_r.addWidget(fn_lbl, stretch=1)
        self.sw_fn_lock = ToggleSwitch(checked=self.backend.get_fn_lock() if feat.fn_lock else False)
        self.sw_fn_lock.toggled.connect(self.fn_lock_toggled.emit)
        fn_r.addWidget(self.sw_fn_lock)
        self.fn_lock_row_widget.setVisible(bool(feat.fn_lock))
        hw_v.addWidget(self.fn_lock_row_widget)

        self.usb_row_widget = QWidget()
        usb_r = QHBoxLayout(self.usb_row_widget)
        usb_r.setContentsMargins(0, 0, 0, 0)
        usb_lbl = QLabel("Energia USB Sempre Ativa (Carregar celular com notebook suspenso)")
        usb_lbl.setWordWrap(True)
        usb_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        usb_r.addWidget(usb_lbl, stretch=1)
        self.sw_usb_charging = ToggleSwitch(checked=self.backend.get_usb_charging() if feat.usb_charging else False)
        self.sw_usb_charging.toggled.connect(self.usb_charging_toggled.emit)
        usb_r.addWidget(self.sw_usb_charging)
        self.usb_row_widget.setVisible(bool(feat.usb_charging))
        hw_v.addWidget(self.usb_row_widget)

        self.hw_toggles_box.setVisible(bool(feat.fn_lock or feat.usb_charging))
        prefs_layout.addWidget(self.hw_toggles_box)

        # Linha 4: Backup & Restauração JSON
        backup_row = QHBoxLayout()
        backup_row.setSpacing(10)
        self.btn_export_cfg = QPushButton("Exportar Backup (JSON)")
        self.btn_export_cfg.setIcon(QIcon(os.path.join(ICON_DIR, "copy.svg")))
        self.btn_export_cfg.setProperty("class", "secondaryButton")
        self.btn_export_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_cfg.clicked.connect(self._export_settings_action)
        backup_row.addWidget(self.btn_export_cfg)

        self.btn_import_cfg = QPushButton("Importar Backup (JSON)")
        self.btn_import_cfg.setIcon(QIcon(os.path.join(ICON_DIR, "tools.svg")))
        self.btn_import_cfg.setProperty("class", "secondaryButton")
        self.btn_import_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import_cfg.clicked.connect(self._import_settings_action)
        backup_row.addWidget(self.btn_import_cfg)
        backup_row.addStretch()
        prefs_layout.addLayout(backup_row)

        prefs_page_layout.addWidget(self.prefs_card)

        # =====================================================================
        # 3. Card Compacto de Status UDEV e Reparo de Permissões (Sem Bloco Gigante)
        # =====================================================================
        self.udev_card = QFrame()
        udev_card = self.udev_card
        udev_card.setProperty("class", "card")
        udev_layout = QVBoxLayout(udev_card)
        udev_layout.setContentsMargins(20, 18, 20, 18)
        udev_layout.setSpacing(12)

        udev_top = QHBoxLayout()
        u_icon = QLabel()
        gear_path = os.path.join(ICON_DIR, "shield.svg")
        if os.path.exists(gear_path):
            u_icon.setPixmap(QPixmap(gear_path).scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        udev_top.addWidget(u_icon)

        u_titles = QVBoxLayout()
        u_title = QLabel("Permissões do Sistema (Acesso Direto sem Senha)")
        u_title.setToolTip("Regras UDEV em /etc/udev/rules.d/99-ducksvantage.rules para escrita direta em /sys/")
        u_title.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.Bold))
        u_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        u_titles.addWidget(u_title)

        self.udev_desc_lbl = QLabel(
            "Permite alterar modos térmicos, conservação da bateria e brilho sem digitar senha a cada clique."
        )
        self.udev_desc_lbl.setWordWrap(True)
        self.udev_desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        u_titles.addWidget(self.udev_desc_lbl)
        udev_top.addLayout(u_titles)

        udev_top.addStretch()

        self.perm_badge = StatusBadge("VERIFICANDO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.TEXT_WHITE_80)
        udev_top.addWidget(self.perm_badge)
        udev_layout.addLayout(udev_top)

        # Barra compacta de ações
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_install_udev = QPushButton("Instalar / Reparar Permissões UDEV")
        self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))
        self.btn_install_udev.setProperty("class", "primaryButton")
        self.btn_install_udev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install_udev.clicked.connect(self._install_udev_action)
        btn_layout.addWidget(self.btn_install_udev)

        btn_copy = QPushButton("Copiar Regra UDEV")
        btn_copy.setIcon(QIcon(os.path.join(ICON_DIR, "copy.svg")))
        btn_copy.setProperty("class", "secondaryButton")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(self._copy_rules_action)
        btn_layout.addWidget(btn_copy)

        btn_layout.addStretch()
        udev_layout.addLayout(btn_layout)

        sys_page_layout.addWidget(udev_card)
        sys_page_layout.addStretch()

        # =====================================================================
        # 4. Integração Nativa KDE Plasma 6 (Widget Plasmoid & KRunner D-Bus)
        # =====================================================================
        self.kde_card = QFrame()
        self.kde_card.setProperty("class", "card")
        kde_layout = QVBoxLayout(self.kde_card)
        kde_layout.setContentsMargins(20, 18, 20, 18)
        kde_layout.setSpacing(12)

        kde_top = QHBoxLayout()
        kde_titles = QVBoxLayout()
        kt_lbl = QLabel("Integração Nativa KDE Plasma 6 (Widget na Barra & KRunner)")
        kt_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        kt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        kde_titles.addWidget(kt_lbl)

        self.kde_desc_lbl = QLabel(
            "Exibe temperaturas CPU/GPU e perfil ativo no painel do KDE e libera comandos rápidos via Alt+Espaço."
        )
        self.kde_desc_lbl.setWordWrap(True)
        self.kde_desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        kde_titles.addWidget(self.kde_desc_lbl)
        kde_top.addLayout(kde_titles, stretch=1)

        self.kde_badge = StatusBadge("OPCIONAL", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        kde_top.addWidget(self.kde_badge)
        kde_layout.addLayout(kde_top)

        kde_btns = QHBoxLayout()
        kde_btns.setSpacing(10)
        self.btn_install_plasmoid = QPushButton("Instalar Widget Plasma 6 (Plasmoid)")
        self.btn_install_plasmoid.setProperty("class", "primaryButton")
        self.btn_install_plasmoid.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install_plasmoid.clicked.connect(self._install_plasmoid_action)
        kde_btns.addWidget(self.btn_install_plasmoid)

        self.btn_install_krunner = QPushButton("Ativar Plugin KRunner (Alt+Espaço)")
        self.btn_install_krunner.setProperty("class", "secondaryButton")
        self.btn_install_krunner.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install_krunner.clicked.connect(self._install_krunner_action)
        kde_btns.addWidget(self.btn_install_krunner)
        kde_btns.addStretch()
        kde_layout.addLayout(kde_btns)

        prefs_page_layout.addWidget(self.kde_card)
        prefs_page_layout.addStretch()

        self.sub_stack.addWidget(page_prefs)
        self.sub_stack.addWidget(page_sys)

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.update_autostart_status()
        self.update_permission_status()
        self.update_kde_integration_status()
        self.refresh_hardware_toggles()
        self.set_advanced_mode(self._advanced_mode)

    def refresh_hardware_toggles(self):
        """Sincroniza os switches de Fn-Lock, USB Always-On e Transição AC."""
        feat = self.backend.features
        if hasattr(self, "sw_auto_power"):
            self.sw_auto_power.blockSignals(True)
            self.sw_auto_power.setChecked(self.backend.get_auto_power_transition())
            self.sw_auto_power.blockSignals(False)
        if feat.fn_lock and hasattr(self, "sw_fn_lock"):
            self.sw_fn_lock.blockSignals(True)
            self.sw_fn_lock.setChecked(self.backend.get_fn_lock())
            self.sw_fn_lock.blockSignals(False)
        if feat.usb_charging and hasattr(self, "sw_usb_charging"):
            self.sw_usb_charging.blockSignals(True)
            self.sw_usb_charging.setChecked(self.backend.get_usb_charging())
            self.sw_usb_charging.blockSignals(False)

    def set_advanced_mode(self, advanced: bool):
        """Armazena estado do modo de interface para ajustes futuros."""
        self._advanced_mode = bool(advanced)

    def update_autostart_status(self):
        """Sincroniza o estado visual do switch e badge com ~/.config/autostart/ducksvantage.desktop."""
        enabled = self.backend.get_autostart_enabled()
        self.autostart_toggle.blockSignals(True)
        self.autostart_toggle.setChecked(enabled)
        self.autostart_toggle.blockSignals(False)

        if enabled:
            self.autostart_badge.setText("ATIVO NO BOOT")
            self.autostart_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)
        else:
            self.autostart_badge.setText("DESATIVADO")
            self.autostart_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.TEXT_WHITE_80)

    def _on_autostart_toggled(self, checked: bool):
        """Cria ou remove ~/.config/autostart/ducksvantage.desktop conforme o switch."""
        ok, msg = self.backend.set_autostart_enabled(checked)
        if not ok:
            QMessageBox.critical(self, "Erro no Autostart", msg)
        self.update_autostart_status()
        self.autostart_toggled.emit(self.backend.get_autostart_enabled())

    def _add_spec_item(self, grid: QGridLayout, row: int, col: int, label: str, value: str):
        box = QFrame()
        box.setProperty("class", "subBox")
        b_layout = QVBoxLayout(box)
        b_layout.setSpacing(3)
        b_layout.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; font-weight: bold;")
        b_layout.addWidget(lbl)

        val_lbl = QLabel(value)
        val_lbl.setWordWrap(True)
        val_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 11, QFont.Weight.Bold))
        val_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        b_layout.addWidget(val_lbl)

        grid.addWidget(box, row, col)

    def update_permission_status(self):
        """Verifica o status atual de escrita nos diretórios do kernel."""
        has_perms = self.backend.has_full_write_permissions()
        is_installed = PermissionsManager.is_udev_rule_installed()
        is_up_to_date = PermissionsManager.is_udev_rule_up_to_date()

        if has_perms and is_up_to_date:
            self.perm_badge.setText("PERMISSÕES OK")
            self.perm_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)
            self.btn_install_udev.setText("Reaplicar / Reparar Permissões")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "check_circle.svg")))
        elif has_perms and not is_up_to_date:
            self.perm_badge.setText("ATUALIZAÇÃO DISPONÍVEL")
            self.perm_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.COLOR_WARNING)
            self.btn_install_udev.setText("Atualizar Permissões Agora")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))
        elif is_installed:
            self.perm_badge.setText("REQUER REPARO")
            self.perm_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.COLOR_WARNING)
            self.btn_install_udev.setText("Reparar Permissões Agora")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))
        else:
            self.perm_badge.setText("REQUER CONFIGURAÇÃO")
            self.perm_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.COLOR_WARNING)
            self.btn_install_udev.setText("Configurar Acesso Sem Senha")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))

    def update_kde_integration_status(self):
        """Atualiza status visual da instalação do Plasmoid KDE 6 e KRunner D-Bus."""
        if not hasattr(self, "kde_badge"):
            return
        pl_ok = self.backend.is_kde_plasmoid_installed()
        kr_ok = self.backend.is_krunner_plugin_installed()
        if pl_ok and kr_ok:
            self.kde_badge.setText("PLASMOID + KRUNNER ATIVOS")
            self.kde_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)
        elif pl_ok or kr_ok:
            self.kde_badge.setText("PARCIALMENTE INSTALADO")
            self.kde_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)
        else:
            self.kde_badge.setText("DISPONÍVEL")
            self.kde_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.TEXT_WHITE_80)
        self.btn_install_plasmoid.setText(
            "Atualizar Widget Plasma 6" if pl_ok else "Instalar Widget Plasma 6 (Plasmoid)"
        )
        self.btn_install_krunner.setText(
            "Reinstalar Plugin KRunner (Alt+Espaço)" if kr_ok else "Ativar Plugin KRunner (Alt+Espaço)"
        )

    def _install_plasmoid_action(self):
        ok, msg = self.backend.install_kde_plasmoid()
        self.update_kde_integration_status()
        if ok:
            QMessageBox.information(self, "Widget KDE Plasma 6", msg)
        else:
            QMessageBox.warning(self, "Widget KDE Plasma 6", msg)

    def _install_krunner_action(self):
        ok, msg = self.backend.install_krunner_plugin()
        self.update_kde_integration_status()
        if ok:
            QMessageBox.information(self, "Plugin KRunner (Alt+Espaço)", msg)
        else:
            QMessageBox.warning(self, "Plugin KRunner", msg)

    def _install_udev_action(self):
        active_paths = self.backend.get_active_writable_paths()
        success, message = PermissionsManager.install_udev_rules(active_paths)
        if success:
            QMessageBox.information(self, "Ducksvantage UDEV", message)
            self.update_permission_status()
            self.permissions_updated.emit()
        else:
            QMessageBox.critical(self, "Erro na Instalação UDEV", message)

    def cleanup_workers(self):
        """Aguarda threads de checagem assíncrona antes de encerrar a janela."""
        if self._update_worker and self._update_worker.isRunning():
            self._update_worker.wait(1500)

    def _on_pref_changed(self, _val=None):
        self.backend.set_osd_enabled(self.sw_osd_enabled.isChecked())
        pos = self.combo_osd_position.currentData()
        if pos:
            self.backend.set_osd_position(str(pos))
        dur = self.combo_osd_duration.currentData()
        if dur is not None:
            self.backend.set_osd_duration_ms(int(dur))
        self.backend.set_minimize_to_tray(self.sw_minimize_to_tray.isChecked())
        if self.combo_ac_profile.count() > 0 and self.combo_ac_profile.currentData():
            self.backend.set_ac_profile(str(self.combo_ac_profile.currentData()))
        if self.combo_battery_profile.count() > 0 and self.combo_battery_profile.currentData():
            self.backend.set_battery_profile(str(self.combo_battery_profile.currentData()))
        self.preferences_changed.emit()

    def _export_settings_action(self):
        dst, _ = QFileDialog.getSaveFileName(
            self, "Exportar Backup de Configurações",
            os.path.expanduser("~/ducksvantage-backup.json"),
            "Arquivos JSON (*.json)"
        )
        if not dst:
            return
        ok, msg = self.backend.export_settings(dst)
        if ok:
            QMessageBox.information(self, "Backup Exportado", msg)
        else:
            QMessageBox.critical(self, "Erro no Backup", msg)

    def _import_settings_action(self):
        src, _ = QFileDialog.getOpenFileName(
            self, "Importar Backup de Configurações",
            os.path.expanduser("~"),
            "Arquivos JSON (*.json)"
        )
        if not src:
            return
        ok, msg = self.backend.import_settings(src)
        if ok:
            self.preferences_changed.emit()
            QMessageBox.information(
                self, "Backup Importado",
                f"{msg}\nAlgumas listas (como Presets ou App Rules) podem exigir reabrir a janela ou trocar de aba."
            )
        else:
            QMessageBox.critical(self, "Erro ao Importar", msg)

    def _check_updates_action(self):
        if self._update_worker and self._update_worker.isRunning():
            return
        self.btn_check_updates.setEnabled(False)
        self.update_status_lbl.setText("Consultando último commit no GitHub...")
        self._update_worker = UpdateCheckWorker(self.backend, self)
        self._update_worker.finished_check.connect(self._on_check_updates_done)
        self._update_worker.start()

    def _on_check_updates_done(self, res: dict):
        self.btn_check_updates.setEnabled(True)
        msg = res.get("message", "")
        self.update_status_lbl.setText(msg)
        if not res.get("ok"):
            QMessageBox.warning(self, "Verificar Atualizações", msg)
        elif res.get("up_to_date"):
            QMessageBox.information(self, "Ducksvantage Atualizado", msg)
        else:
            extra = f"\n\nÚltimo commit ({res.get('remote_sha')} em {res.get('remote_date')}):\n{res.get('remote_message')}\n\nRepositório: {res.get('url')}"
            QMessageBox.information(self, "Atualização Disponível", msg + extra)

    def _copy_diagnostic_action(self):
        report = self.backend.generate_hardware_diagnostic_report()
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(report)
            QMessageBox.information(
                self, "Diagnóstico Copiado",
                "O relatório técnico de hardware e kernel (sem dados pessoais) foi copiado para a área de transferência."
            )

    def _copy_rules_action(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(PermissionsManager.get_udev_rule_content())
            QMessageBox.information(
                self, "Regra UDEV Copiada",
                "As regras UDEV foram copiadas para a área de transferência.\n"
                "Clique no botão 'Atualizar / Instalar Regras UDEV' ou execute no terminal:\n"
                "sudo ./install.sh  (ou sudo ./setup_udev.sh)"
            )
