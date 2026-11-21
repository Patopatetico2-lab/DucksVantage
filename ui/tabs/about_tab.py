"""
Aba Sobre o Dispositivo do Ducksvantage (ui/tabs/about_tab.py).
Apresenta informações completas e dinâmicas de DMI/BIOS, Processador, GPU, Kernel e SSDs,
além de um card compacto de status UDEV com botão de reparo (sem blocos de código que gerem scroll horizontal).
Zero emojis: utiliza exclusivamente ícones vetoriais SVG.
"""

import os
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QPushButton, QScrollArea, QComboBox, QFileDialog,
    Qt, Signal, QFont, QThread, QMessageBox, QApplication, QIcon, QPixmap
)
from core.backend import APP_VERSION
from ui.theme_tokens import ThemeTokens
from ui.components import StatusBadge, ToggleSwitch
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
    """Informações completas de DMI/BIOS do sistema, Preferências, Autostart XDG e reparo compacto de permissões UDEV."""
    permissions_updated = Signal()
    autostart_toggled = Signal(bool)
    preferences_changed = Signal()
    test_osd_requested = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._update_worker = None

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(18)

        # =====================================================================
        # 1. Card de Identificação DMI / BIOS / Hardware do Dispositivo
        # =====================================================================
        info_card = QFrame()
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
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {ThemeTokens.BORDER_CYAN};")
        title_box.addWidget(title)

        subtitle = QLabel("Substituto universal e leve do Lenovo Vantage para notebooks Legion, LOQ, IdeaPad e Yoga no Linux.")
        subtitle.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        title_box.addWidget(subtitle)
        info_header.addLayout(title_box)

        info_header.addStretch()

        ver_badge = StatusBadge(f"DUCKSVANTAGE v{APP_VERSION}", bg_color="#1e293b", text_color="#00d2ff")
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

        layout.addWidget(info_card)

        # =====================================================================
        # 1.5 Card de Recursos Liberados por Este Hardware (Auto-Discovery)
        # =====================================================================
        caps = self.backend.get_detected_capabilities()
        self.caps_card = QFrame()
        self.caps_card.setProperty("class", "card")
        caps_layout = QVBoxLayout(self.caps_card)
        caps_layout.setContentsMargins(20, 18, 20, 18)
        caps_layout.setSpacing(12)

        caps_header = QHBoxLayout()
        c_icon = QLabel()
        tools_path = os.path.join(ICON_DIR, "tools.svg")
        if os.path.exists(tools_path):
            c_icon.setPixmap(QPixmap(tools_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        caps_header.addWidget(c_icon)

        caps_titles = QVBoxLayout()
        caps_titles.setSpacing(2)
        caps_title = QLabel("Recursos Liberados por Este Notebook (Auto-Discovery)")
        caps_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        caps_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        caps_titles.addWidget(caps_title)

        caps_sub = QLabel(
            f"A interface foi adaptada automaticamente para o {sys.display_model_name}, exibindo apenas as funções suportadas pelo hardware e kernel."
        )
        caps_sub.setWordWrap(True)
        caps_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        caps_titles.addWidget(caps_sub)
        caps_header.addLayout(caps_titles, stretch=1)

        self.caps_badge = StatusBadge(
            f"{len(caps)} {'RECURSO ATIVO' if len(caps) == 1 else 'RECURSOS ATIVOS'}",
            bg_color="#064e3b",
            text_color="#34d399"
        )
        caps_header.addWidget(self.caps_badge)
        caps_layout.addLayout(caps_header)

        if caps:
            caps_grid = QGridLayout()
            caps_grid.setSpacing(10)
            for idx, cap in enumerate(caps):
                self._add_spec_item(caps_grid, idx // 3, idx % 3, cap["name"], cap["detail"])
            caps_layout.addLayout(caps_grid)
        else:
            empty_lbl = QLabel("Nenhum controle proprietário ACPI/WMI foi exposto pelo kernel atual.")
            empty_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
            caps_layout.addWidget(empty_lbl)

        layout.addWidget(self.caps_card)

        # =====================================================================
        # 2. Card de Inicialização Automática Universal (XDG Autostart)
        # =====================================================================
        autostart_card = QFrame()
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
        auto_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        auto_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        auto_titles.addWidget(auto_title)

        self.autostart_desc_lbl = QLabel(
            "Inicia o Ducksvantage silenciosamente na bandeja do sistema (--minimized) via padrão XDG (~/.config/autostart/ducksvantage.desktop)."
        )
        self.autostart_desc_lbl.setWordWrap(True)
        self.autostart_desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        auto_titles.addWidget(self.autostart_desc_lbl)
        autostart_layout.addLayout(auto_titles, stretch=1)

        self.autostart_badge = StatusBadge("DESATIVADO", bg_color="#1e293b", text_color="#cbd5e1")
        autostart_layout.addWidget(self.autostart_badge)

        self.autostart_toggle = ToggleSwitch(checked=self.backend.get_autostart_enabled())
        self.autostart_toggle.toggled.connect(self._on_autostart_toggled)
        autostart_layout.addWidget(self.autostart_toggle)

        layout.addWidget(autostart_card)

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
        pt_t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        pt_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        pref_titles.addWidget(pt_t)

        pt_s = QLabel("Personalize o overlay OSD no Wayland/X11, perfis de tomada/bateria e exporte suas configurações.")
        pt_s.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        pref_titles.addWidget(pt_s)
        prefs_header.addLayout(pref_titles, stretch=1)
        prefs_layout.addLayout(prefs_header)

        # Linha 1: OSD Ativo, Posição, Duração e Testar OSD
        osd_box = QFrame()
        osd_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 12px;")
        osd_v = QVBoxLayout(osd_box)
        osd_v.setContentsMargins(6, 4, 6, 4)
        osd_v.setSpacing(8)

        osd_row1 = QHBoxLayout()
        osd_lbl = QLabel("Exibir Pop-up Flutuante (OSD) ao trocar Fn+Q, Jogos ou Brilho")
        osd_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
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
        self.combo_osd_position.setStyleSheet(f"""
            QComboBox {{
                background-color: #192338;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
            }}
        """)
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
        beh_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 12px;")
        beh_v = QVBoxLayout(beh_box)
        beh_v.setContentsMargins(6, 4, 6, 4)
        beh_v.setSpacing(8)

        min_row = QHBoxLayout()
        min_lbl = QLabel("Minimizar para a bandeja do sistema ao clicar em Fechar (X)")
        min_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        min_row.addWidget(min_lbl, stretch=1)
        self.sw_minimize_to_tray = ToggleSwitch(checked=self.backend.get_minimize_to_tray())
        self.sw_minimize_to_tray.toggled.connect(self._on_pref_changed)
        min_row.addWidget(self.sw_minimize_to_tray)
        beh_v.addLayout(min_row)

        self.game_summary_row_widget = QWidget()
        sum_row = QHBoxLayout(self.game_summary_row_widget)
        sum_row.setContentsMargins(0, 0, 0, 0)
        sum_lbl = QLabel("Notificar resumo pós-jogo (duração e pico de temperatura CPU/GPU ao sair do jogo)")
        sum_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        sum_row.addWidget(sum_lbl, stretch=1)
        self.sw_game_summary = ToggleSwitch(checked=self.backend.get_game_session_summary_enabled())
        self.sw_game_summary.toggled.connect(self._on_pref_changed)
        sum_row.addWidget(self.sw_game_summary)
        self.game_summary_row_widget.setVisible(bool(feat.platform_profile and supported_profiles))
        beh_v.addWidget(self.game_summary_row_widget)
        prefs_layout.addWidget(beh_box)

        # Linha 3: Perfis automáticos AC vs Bateria (oculto se não houver ACPI + bateria)
        self.ac_bat_prefs_widget = QFrame()
        self.ac_bat_prefs_widget.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 12px;")
        ab_row = QHBoxLayout(self.ac_bat_prefs_widget)
        ab_row.setContentsMargins(6, 4, 6, 4)
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
        self.ac_bat_prefs_widget.setVisible(bool(feat.platform_profile and feat.battery and supported_profiles))
        prefs_layout.addWidget(self.ac_bat_prefs_widget)

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

        layout.addWidget(self.prefs_card)

        # =====================================================================
        # 3. Card Compacto de Status UDEV e Reparo de Permissões (Sem Bloco Gigante)
        # =====================================================================
        udev_card = QFrame()
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
        u_title = QLabel("Status de Permissões do Kernel (/sys/ & Regras UDEV)")
        u_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        u_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        u_titles.addWidget(u_title)

        self.udev_desc_lbl = QLabel(
            "Concede acesso direto sem senha (chmod 0666) aos controles de ACPI, bateria, teclado e CPU."
        )
        self.udev_desc_lbl.setWordWrap(True)
        self.udev_desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        u_titles.addWidget(self.udev_desc_lbl)
        udev_top.addLayout(u_titles)

        udev_top.addStretch()

        self.perm_badge = StatusBadge("VERIFICANDO", bg_color="#1e293b", text_color="#cbd5e1")
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

        layout.addWidget(udev_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.update_autostart_status()
        self.update_permission_status()

    def update_autostart_status(self):
        """Sincroniza o estado visual do switch e badge com ~/.config/autostart/ducksvantage.desktop."""
        enabled = self.backend.get_autostart_enabled()
        self.autostart_toggle.blockSignals(True)
        self.autostart_toggle.setChecked(enabled)
        self.autostart_toggle.blockSignals(False)

        if enabled:
            self.autostart_badge.setText("ATIVO NO BOOT")
            self.autostart_badge.setColor("#064e3b", "#34d399")
        else:
            self.autostart_badge.setText("DESATIVADO")
            self.autostart_badge.setColor("#1e293b", "#cbd5e1")

    def _on_autostart_toggled(self, checked: bool):
        """Cria ou remove ~/.config/autostart/ducksvantage.desktop conforme o switch."""
        ok, msg = self.backend.set_autostart_enabled(checked)
        if not ok:
            QMessageBox.critical(self, "Erro no Autostart", msg)
        self.update_autostart_status()
        self.autostart_toggled.emit(self.backend.get_autostart_enabled())

    def _add_spec_item(self, grid: QGridLayout, row: int, col: int, label: str, value: str):
        box = QFrame()
        box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px;")
        b_layout = QVBoxLayout(box)
        b_layout.setSpacing(3)
        b_layout.setContentsMargins(10, 8, 10, 8)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; font-weight: bold;")
        b_layout.addWidget(lbl)

        val_lbl = QLabel(value)
        val_lbl.setWordWrap(True)
        val_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        val_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        b_layout.addWidget(val_lbl)

        grid.addWidget(box, row, col)

    def update_permission_status(self):
        """Verifica o status atual de escrita nos diretórios do kernel."""
        has_perms = self.backend.has_full_write_permissions()
        is_installed = PermissionsManager.is_udev_rule_installed()
        is_up_to_date = PermissionsManager.is_udev_rule_up_to_date()

        if has_perms and is_up_to_date:
            self.perm_badge.setText("UDEV ATIVO • SEM SUDO")
            self.perm_badge.setColor("#064e3b", "#34d399")
            self.btn_install_udev.setText("Reaplicar / Reparar Permissões UDEV")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "check_circle.svg")))
        elif has_perms and not is_up_to_date:
            self.perm_badge.setText("UDEV DESATUALIZADO")
            self.perm_badge.setColor("#78350f", "#fbbf24")
            self.btn_install_udev.setText("Atualizar Regras UDEV Agora")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))
        elif is_installed:
            self.perm_badge.setText("REQUER REPARO")
            self.perm_badge.setColor("#78350f", "#fbbf24")
            self.btn_install_udev.setText("Reparar Permissões UDEV Agora")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))
        else:
            self.perm_badge.setText("REQUER CONFIGURAÇÃO")
            self.perm_badge.setColor("#78350f", "#fbbf24")
            self.btn_install_udev.setText("Instalar Regras UDEV (Sem Sudo)")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))

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
        self.backend.set_game_session_summary_enabled(self.sw_game_summary.isChecked())
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
