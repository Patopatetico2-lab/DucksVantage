"""
Aba Automação & Atalhos do Ducksvantage (ui/tabs/automation_tab.py) — Estilo 3.
Agrupa automação de perfil, jogos e atalhos:
1. Perfis Personalizados (Presets em 1 Clique)
2. Auto-Switch em Jogos + Lista de Exclusões + Regras por Aplicativo (App Rules)
3. Mapeador de Teclas Personalizadas (Tecla Copilot F23 e Atalhos Globais)
"""

import os
import shutil
from typing import Dict, Any, List, Tuple
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QStackedWidget, QComboBox, QLineEdit, QFileDialog,
    Qt, Signal, QFont, QMessageBox, QPixmap
)
from ui.theme_tokens import ThemeTokens
from ui.components import ToggleSwitch, StatusBadge, SubTabSelector
from ui.widgets import KeyCaptureButton
from core.key_mapper import default_extra_codes_for_slot, normalize_modifiers

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")

AVAILABLE_KEY_ACTIONS: List[Tuple[str, str]] = [
    ("cycle_profile", "Alternar Modo Térmico (Ciclo com OSD)"),
    ("cycle_refresh_rate", "Alternar Taxa de Atualização de Tela (Fn+R)"),
    ("toggle_max_power", "Ativar / Desativar Desempenho Máximo (Max-Power)"),
    ("toggle_eco_mode", "Ativar / Desativar Modo Viagem (Eco-Mode)"),
    ("toggle_window", "Abrir / Minimizar Janela do Ducksvantage"),
    ("toggle_conservation", "Ativar / Desativar Conservação da Bateria (80%)"),
    ("toggle_mic_mute", "Silenciar / Ativar Microfone"),
    ("cycle_audio_preset", "Alternar Preset de Áudio (Padrão / Voz / Mudo)"),
    ("toggle_cinema_mode", "Ativar / Desativar Modo Cinema & Não Perturbe"),
    ("toggle_touchpad", "Bloquear / Desbloquear Touchpad"),
    ("custom_command", "Executar Comando ou Script Personalizado"),
]

PROFILE_COMBO_ITEMS: List[Tuple[str, str]] = [
    ("max-power", "Desempenho Máximo (Max-Power)"),
    ("performance", "Modo Desempenho (Performance)"),
    ("balanced", "Modo Equilibrado (Balanced)"),
    ("low-power", "Modo Silencioso (Economia)"),
]


class AutomationTab(QWidget):
    """Aba Automação & Atalhos: jogos/app rules, teclas/presets e horários/ambiente."""
    shortcuts_updated = Signal()
    custom_action_requested = Signal(str, str)
    preset_applied = Signal(str, str)
    presets_updated = Signal()
    cinema_mode_toggled = Signal(bool)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._advanced_mode = self.backend.is_advanced_mode()
        feat = self.backend.features
        supported_profiles = self.backend.get_supported_canonical_profiles()
        self._supported_profiles = supported_profiles

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(20, 18, 20, 18)
        root_layout.setSpacing(14)

        self.sub_tabs = SubTabSelector([
            ("games", "Jogos & Regras"),
            ("keys", "Teclas & Presets"),
            ("schedule", "Horários & Ambiente"),
        ])
        root_layout.addWidget(self.sub_tabs)

        self.sub_stack = QStackedWidget()
        self.sub_tabs.tab_selected.connect(self.sub_stack.setCurrentIndex)
        root_layout.addWidget(self.sub_stack, stretch=1)

        page_games = QWidget()
        games_layout = QVBoxLayout(page_games)
        games_layout.setContentsMargins(0, 0, 0, 0)
        games_layout.setSpacing(16)

        page_keys = QWidget()
        keys_layout = QVBoxLayout(page_keys)
        keys_layout.setContentsMargins(0, 0, 0, 0)
        keys_layout.setSpacing(16)

        page_sched = QWidget()
        sched_layout = QVBoxLayout(page_sched)
        sched_layout.setContentsMargins(0, 0, 0, 0)
        sched_layout.setSpacing(16)

        # =====================================================================
        # 1. Perfis Personalizados (Presets em 1 Clique -> Sub-aba Teclas & Presets)
        # =====================================================================
        self.presets_card = QFrame()
        self.presets_card.setProperty("class", "card")
        presets_layout = QVBoxLayout(self.presets_card)
        presets_layout.setContentsMargins(18, 16, 18, 16)
        presets_layout.setSpacing(12)

        presets_header = QHBoxLayout()
        ic_pre = QLabel()
        p_pre = os.path.join(ICON_DIR, "mode_custom.svg")
        if os.path.exists(p_pre):
            ic_pre.setPixmap(QPixmap(p_pre).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        presets_header.addWidget(ic_pre)

        presets_titles = QVBoxLayout()
        presets_titles.setSpacing(2)
        pt_title = QLabel("Presets Personalizados (1 Clique)")
        pt_title.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        pt_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        presets_titles.addWidget(pt_title)

        pt_sub = QLabel("Salve o estado atual (Perfil, Governor, Turbo, TDP e Hz) e aplique com 1 clique.")
        pt_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        presets_titles.addWidget(pt_sub)
        presets_header.addLayout(presets_titles)
        presets_header.addStretch()

        self.presets_count_badge = StatusBadge("0 PRESETS", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        presets_header.addWidget(self.presets_count_badge)
        presets_layout.addLayout(presets_header)

        add_preset_box = QFrame()
        add_preset_box.setProperty("class", "subBox")
        add_p_row = QHBoxLayout(add_preset_box)
        add_p_row.setContentsMargins(14, 10, 14, 10)
        add_p_row.setSpacing(10)

        self.edit_preset_name = QLineEdit()
        self.edit_preset_name.setPlaceholderText("Nome do preset (ex: Render Silencioso, Competitivo 144Hz)")
        self.edit_preset_name.setFixedHeight(30)
        add_p_row.addWidget(self.edit_preset_name, stretch=1)

        self.btn_save_preset = QPushButton("Salvar Estado Atual")
        self.btn_save_preset.setProperty("class", "primaryButton")
        self.btn_save_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_preset.setFixedHeight(30)
        self.btn_save_preset.clicked.connect(self._on_save_user_preset)
        add_p_row.addWidget(self.btn_save_preset)

        self.btn_import_preset = QPushButton("Importar")
        self.btn_import_preset.setProperty("class", "secondaryButton")
        self.btn_import_preset.setToolTip("Importar Preset (.json) com curva de fan + TDP")
        self.btn_import_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import_preset.setFixedHeight(30)
        self.btn_import_preset.clicked.connect(self._on_import_user_preset)
        add_p_row.addWidget(self.btn_import_preset)
        presets_layout.addWidget(add_preset_box)

        self.presets_list_container = QWidget()
        self.presets_list_layout = QVBoxLayout(self.presets_list_container)
        self.presets_list_layout.setContentsMargins(0, 0, 0, 0)
        self.presets_list_layout.setSpacing(8)
        presets_layout.addWidget(self.presets_list_container)
        self._rebuild_user_presets_list()

        avail_govs = self.backend.get_available_cpu_governors()
        has_preset_ctrl = any((
            bool(feat.platform_profile and supported_profiles),
            bool(feat.cpu_governor and avail_govs),
            feat.turbo_boost,
            feat.custom_tdp,
            feat.refresh_rate,
        ))
        self._has_preset_ctrl = bool(has_preset_ctrl)
        self.presets_card.setVisible(bool(self._advanced_mode and has_preset_ctrl))
        keys_layout.addWidget(self.presets_card)

        # =====================================================================
        # 2. Auto-Switch em Jogos + Regras por Aplicativo (App Rules)
        # =====================================================================
        self.rules_card = QFrame()
        self.rules_card.setProperty("class", "card")
        rules_layout = QVBoxLayout(self.rules_card)
        rules_layout.setContentsMargins(18, 16, 18, 16)
        rules_layout.setSpacing(12)

        rules_header = QHBoxLayout()
        ic_rules = QLabel()
        p_rules = os.path.join(ICON_DIR, "app_rules.svg")
        if os.path.exists(p_rules):
            ic_rules.setPixmap(QPixmap(p_rules).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        rules_header.addWidget(ic_rules)

        rules_titles = QVBoxLayout()
        rules_titles.setSpacing(2)
        rt_title = QLabel("Auto-Switch em Jogos & Regras por Aplicativo")
        rt_title.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        rt_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        rules_titles.addWidget(rt_title)

        rt_sub = QLabel("Configure comportamento automático em jogos (Steam/Heroic/Proton) e apps.")
        rt_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        rules_titles.addWidget(rt_sub)
        rules_header.addLayout(rules_titles)
        rules_header.addStretch()

        self.app_rules_badge = StatusBadge("AUTO-SWITCH ATIVO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.STATUS_GREEN)
        rules_header.addWidget(self.app_rules_badge)
        rules_layout.addLayout(rules_header)

        self.game_switch_opts_box = QFrame()
        self.game_switch_opts_box.setProperty("class", "subBox")
        gopts_layout = QVBoxLayout(self.game_switch_opts_box)
        gopts_layout.setContentsMargins(14, 12, 14, 12)
        gopts_layout.setSpacing(10)

        gopts_title_row = QHBoxLayout()
        ic_game = QLabel()
        p_game = os.path.join(ICON_DIR, "game_controller.svg")
        if os.path.exists(p_game):
            ic_game.setPixmap(QPixmap(p_game).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        gopts_title_row.addWidget(ic_game)

        gopts_title = QLabel("Opções do Auto-Switch em Jogos")
        gopts_title.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        gopts_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        gopts_title_row.addWidget(gopts_title)
        gopts_title_row.addStretch()
        gopts_layout.addLayout(gopts_title_row)

        self.game_target_row_widget = QWidget()
        gt_row = QHBoxLayout(self.game_target_row_widget)
        gt_row.setContentsMargins(0, 0, 0, 0)
        gt_row.setSpacing(10)
        gt_lbl = QLabel("Perfil térmico ao detectar jogos (Steam, Heroic, Sober, Wine):")
        gt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gt_row.addWidget(gt_lbl)
        gt_row.addStretch()

        self.combo_game_target_profile = QComboBox()
        self.combo_game_target_profile.setMinimumWidth(220)
        self.combo_game_target_profile.setFixedHeight(28)
        if "performance" in supported_profiles or not supported_profiles:
            self.combo_game_target_profile.addItem("Modo Desempenho (Performance)", "performance")
        if "max-power" in supported_profiles or feat.max_power_profile:
            self.combo_game_target_profile.addItem("Desempenho Máximo (Max-Power)", "max-power")
        cur_game_target = self.backend.get_game_target_profile()
        t_idx = self.combo_game_target_profile.findData(cur_game_target)
        if t_idx >= 0:
            self.combo_game_target_profile.setCurrentIndex(t_idx)
        self.combo_game_target_profile.currentIndexChanged.connect(self._on_game_target_profile_changed)
        gt_row.addWidget(self.combo_game_target_profile)
        gopts_layout.addWidget(self.game_target_row_widget)

        self.game_refresh_row_widget = QWidget()
        gr_row = QHBoxLayout(self.game_refresh_row_widget)
        gr_row.setContentsMargins(0, 0, 0, 0)
        gr_lbl = QLabel("Elevar taxa do painel (Hz) para o máximo durante o jogo")
        gr_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gr_row.addWidget(gr_lbl, stretch=1)
        self.sw_game_refresh_max = ToggleSwitch(checked=self.backend.get_game_auto_refresh_max())
        self.sw_game_refresh_max.toggled.connect(self._on_game_refresh_max_toggled)
        gr_row.addWidget(self.sw_game_refresh_max)
        self.game_refresh_row_widget.setVisible(bool(feat.refresh_rate))
        gopts_layout.addWidget(self.game_refresh_row_widget)

        self.game_touchpad_row_widget = QWidget()
        gtp_row = QHBoxLayout(self.game_touchpad_row_widget)
        gtp_row.setContentsMargins(0, 0, 0, 0)
        gtp_lbl = QLabel("Bloquear Touchpad automaticamente enquanto um jogo estiver aberto")
        gtp_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gtp_row.addWidget(gtp_lbl, stretch=1)
        self.sw_game_lock_touchpad = ToggleSwitch(checked=self.backend.get_game_auto_lock_touchpad())
        self.sw_game_lock_touchpad.toggled.connect(self._on_game_lock_touchpad_toggled)
        gtp_row.addWidget(self.sw_game_lock_touchpad)
        self.game_touchpad_row_widget.setVisible(bool(feat.touchpad_control))
        gopts_layout.addWidget(self.game_touchpad_row_widget)

        self.game_preset_row_widget = QWidget()
        gp_row = QHBoxLayout(self.game_preset_row_widget)
        gp_row.setContentsMargins(0, 0, 0, 0)
        gp_row.setSpacing(10)
        gp_lbl = QLabel("Ou aplicar um Preset personalizado ao abrir jogos:")
        gp_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gp_row.addWidget(gp_lbl)
        gp_row.addStretch()

        self.combo_game_target_preset = QComboBox()
        self.combo_game_target_preset.setMinimumWidth(220)
        self.combo_game_target_preset.setFixedHeight(28)
        self._populate_game_preset_combo()
        self.combo_game_target_preset.currentIndexChanged.connect(self._on_game_target_preset_changed)
        gp_row.addWidget(self.combo_game_target_preset)
        gopts_layout.addWidget(self.game_preset_row_widget)

        # Política VRR (Adaptive Sync) durante jogos
        self.game_vrr_row_widget = QWidget()
        gvrr_l = QHBoxLayout(self.game_vrr_row_widget)
        gvrr_l.setContentsMargins(0, 0, 0, 0)
        gvrr_l.setSpacing(10)

        vrr_g_lbl = QLabel("Política VRR (Adaptive Sync) ao abrir jogos:")
        vrr_g_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gvrr_l.addWidget(vrr_g_lbl)
        gvrr_l.addStretch()

        self.combo_game_vrr = QComboBox()
        self.combo_game_vrr.setMinimumWidth(220)
        self.combo_game_vrr.setFixedHeight(28)
        for v_txt, v_id in [("Manter atual", "keep"), ("Automático", "automatic"), ("Sempre ativo", "always"), ("Desligado", "never")]:
            self.combo_game_vrr.addItem(v_txt, v_id)
        v_i = self.combo_game_vrr.findData(self.backend.get_game_vrr_policy())
        if v_i >= 0:
            self.combo_game_vrr.setCurrentIndex(v_i)
        self.combo_game_vrr.currentIndexChanged.connect(self._on_game_vrr_changed)
        gvrr_l.addWidget(self.combo_game_vrr)
        self.game_vrr_row_widget.setVisible(bool(feat.refresh_rate))
        gopts_layout.addWidget(self.game_vrr_row_widget)

        self.game_ignore_box = QWidget()
        gi_v = QVBoxLayout(self.game_ignore_box)
        gi_v.setContentsMargins(0, 2, 0, 0)
        gi_v.setSpacing(6)
        gi_row = QHBoxLayout()
        gi_row.setSpacing(8)
        gi_lbl = QLabel("Ignorar processos no Auto-Switch:")
        gi_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gi_row.addWidget(gi_lbl)

        self.edit_game_ignore = QLineEdit()
        self.edit_game_ignore.setPlaceholderText("Ex: launcher.exe, java, wineboot")
        self.edit_game_ignore.setFixedHeight(28)
        gi_row.addWidget(self.edit_game_ignore, stretch=1)

        self.btn_add_game_ignore = QPushButton("Ignorar")
        self.btn_add_game_ignore.setProperty("class", "secondaryButton")
        self.btn_add_game_ignore.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_game_ignore.setFixedHeight(28)
        self.btn_add_game_ignore.clicked.connect(self._on_add_game_ignore)
        gi_row.addWidget(self.btn_add_game_ignore)
        gi_v.addLayout(gi_row)

        self.ignore_list_container = QWidget()
        self.ignore_list_layout = QHBoxLayout(self.ignore_list_container)
        self.ignore_list_layout.setContentsMargins(0, 0, 0, 0)
        self.ignore_list_layout.setSpacing(6)
        gi_v.addWidget(self.ignore_list_container)
        self._rebuild_game_ignore_list()
        gopts_layout.addWidget(self.game_ignore_box)

        rules_layout.addWidget(self.game_switch_opts_box)

        self.add_rule_box = QFrame()
        add_rule_box = self.add_rule_box
        add_rule_box.setProperty("class", "subBox")
        add_row = QHBoxLayout(add_rule_box)
        add_row.setContentsMargins(14, 10, 14, 10)
        add_row.setSpacing(10)

        self.combo_app_exec = QComboBox()
        self.combo_app_exec.setEditable(True)
        self.combo_app_exec.setMinimumWidth(200)
        self.combo_app_exec.setFixedHeight(30)
        self._populate_running_apps_combo()
        add_row.addWidget(self.combo_app_exec, stretch=1)

        self.btn_refresh_procs = QPushButton("Atualizar")
        self.btn_refresh_procs.setProperty("class", "secondaryButton")
        self.btn_refresh_procs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_procs.setFixedHeight(30)
        self.btn_refresh_procs.clicked.connect(self._populate_running_apps_combo)
        add_row.addWidget(self.btn_refresh_procs)

        self.edit_app_label = QLineEdit()
        self.edit_app_label.setPlaceholderText("Descrição opcional (ex: Blender 3D)")
        self.edit_app_label.setFixedHeight(30)
        add_row.addWidget(self.edit_app_label, stretch=1)

        self.combo_app_profile = QComboBox()
        self.combo_app_profile.setMinimumWidth(200)
        self.combo_app_profile.setFixedHeight(30)
        self._populate_app_rule_profile_combo()
        add_row.addWidget(self.combo_app_profile)

        btn_add_rule = QPushButton("Adicionar Regra")
        btn_add_rule.setProperty("class", "primaryButton")
        btn_add_rule.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_rule.setFixedHeight(30)
        btn_add_rule.clicked.connect(self._on_add_app_rule)
        add_row.addWidget(btn_add_rule)

        rules_layout.addWidget(add_rule_box)

        self.rules_list_container = QWidget()
        self.rules_list_layout = QVBoxLayout(self.rules_list_container)
        self.rules_list_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_list_layout.setSpacing(8)
        rules_layout.addWidget(self.rules_list_container)
        self._rebuild_app_rules_list()

        self.rules_card.setVisible(bool(feat.platform_profile and supported_profiles))
        games_layout.addWidget(self.rules_card)
        games_layout.addStretch()

        # =====================================================================
        # 3. Mapeador de Teclas Personalizadas (Tecla Copilot F23 -> Sub-aba Teclas & Presets)
        # =====================================================================
        self.remap_card = QFrame()
        self.remap_card.setProperty("class", "card")
        remap_layout = QVBoxLayout(self.remap_card)
        remap_layout.setContentsMargins(18, 16, 18, 16)
        remap_layout.setSpacing(12)

        remap_header = QHBoxLayout()
        ic_key = QLabel()
        p_key = os.path.join(ICON_DIR, "copilot_key.svg")
        if os.path.exists(p_key):
            ic_key.setPixmap(QPixmap(p_key).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        remap_header.addWidget(ic_key)

        remap_titles = QVBoxLayout()
        remap_titles.setSpacing(2)
        rt_lbl = QLabel("Mapeador de Teclas & Atalhos Globais")
        rt_lbl.setToolTip("Tecla Copilot (F8 / F23), teclas especiais (F24) e atalhos globais do sistema")
        rt_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        rt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        remap_titles.addWidget(rt_lbl)

        rs_lbl = QLabel(
            "Clique no botão azul, pressione a tecla física (Copilot/F8, F24) e ative o interruptor."
        )
        rs_lbl.setWordWrap(True)
        rs_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        remap_titles.addWidget(rs_lbl)
        remap_header.addLayout(remap_titles, stretch=1)

        self.evdev_status_badge = StatusBadge(
            "ATALHOS GLOBAIS ATIVOS",
            bg_color=ThemeTokens.BG_CARD_HOVER,
            text_color=ThemeTokens.STATUS_GREEN,
        )
        remap_header.addWidget(self.evdev_status_badge)

        self.btn_reset_keys = QPushButton("Restaurar")
        self.btn_reset_keys.setProperty("class", "secondaryButton")
        self.btn_reset_keys.setToolTip("Restaurar atalhos de fábrica")
        self.btn_reset_keys.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_keys.setFixedHeight(28)
        self.btn_reset_keys.clicked.connect(self._on_reset_key_mappings)
        remap_header.addWidget(self.btn_reset_keys)
        remap_layout.addLayout(remap_header)

        self._slot_widgets: Dict[str, Dict[str, Any]] = {}
        mappings = self.backend.get_key_mappings()
        for slot_id, slot_cfg in mappings.items():
            row_frame = self._create_key_slot_row(slot_id, slot_cfg)
            if slot_id == "refresh_rate_hotkey" and not feat.refresh_rate:
                row_frame.setVisible(False)
            elif slot_id == "eco_hotkey" and not feat.eco_travel:
                row_frame.setVisible(False)
            remap_layout.addWidget(row_frame)

        keys_layout.addWidget(self.remap_card)
        keys_layout.addStretch()

        # =====================================================================
        # 4. Modo Cinema / Apresentação (Sub-aba Horários & Ambiente)
        # =====================================================================
        self.cinema_card = QFrame()
        self.cinema_card.setProperty("class", "card")
        cin_lay = QHBoxLayout(self.cinema_card)
        cin_lay.setContentsMargins(18, 16, 18, 16)
        cin_lay.setSpacing(14)

        cin_titles = QVBoxLayout()
        cin_titles.setSpacing(2)
        cin_t = QLabel("Modo Cinema / Apresentação")
        cin_t.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        cin_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        cin_titles.addWidget(cin_t)
        cin_sub = QLabel(
            "Impede a tela de apagar, silencia notificações do KDE (Não Perturbe) e apaga a luz do teclado."
        )
        cin_sub.setWordWrap(True)
        cin_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        cin_titles.addWidget(cin_sub)
        cin_lay.addLayout(cin_titles, stretch=1)

        self.sw_cinema_mode = ToggleSwitch(checked=self.backend.get_cinema_mode() if feat.cinema_mode else False)
        self.sw_cinema_mode.toggled.connect(self.cinema_mode_toggled.emit)
        cin_lay.addWidget(self.sw_cinema_mode)
        self.cinema_card.setVisible(bool(feat.cinema_mode))
        sched_layout.addWidget(self.cinema_card)

        # =====================================================================
        # 5. Histórico Persistente de Sessões de Jogo
        # =====================================================================
        self.session_hist_card = QFrame()
        self.session_hist_card.setProperty("class", "card")
        sh_layout = QVBoxLayout(self.session_hist_card)
        sh_layout.setContentsMargins(18, 16, 18, 16)
        sh_layout.setSpacing(10)

        sh_header = QHBoxLayout()
        sh_titles = QVBoxLayout()
        sh_titles.setSpacing(2)
        sht_lbl = QLabel("Histórico de Sessões de Jogo")
        sht_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        sht_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        sh_titles.addWidget(sht_lbl)
        shs_lbl = QLabel("Registro persistente de duração, temperaturas de pico e consumo médio por partida.")
        shs_lbl.setWordWrap(True)
        shs_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        sh_titles.addWidget(shs_lbl)
        sh_header.addLayout(sh_titles, stretch=1)

        self.session_hist_badge = StatusBadge("0 SESSÕES", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        sh_header.addWidget(self.session_hist_badge)
        self.btn_clear_sessions = QPushButton("Limpar")
        self.btn_clear_sessions.setProperty("class", "secondaryButton")
        self.btn_clear_sessions.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_sessions.setFixedHeight(28)
        self.btn_clear_sessions.clicked.connect(self._on_clear_session_history)
        sh_header.addWidget(self.btn_clear_sessions)
        sh_layout.addLayout(sh_header)

        self.session_hist_container = QWidget()
        self.session_hist_list_layout = QVBoxLayout(self.session_hist_container)
        self.session_hist_list_layout.setContentsMargins(0, 0, 0, 0)
        self.session_hist_list_layout.setSpacing(6)
        sh_layout.addWidget(self.session_hist_container)
        self._rebuild_game_session_history()

        self.session_hist_card.setVisible(bool(self._advanced_mode and feat.platform_profile and supported_profiles))

        # =====================================================================
        # 6. Perfil Noturno / Agendamento por Horário
        # =====================================================================
        night_cfg = self.backend.get_night_schedule_config()
        self.night_card = QFrame()
        self.night_card.setProperty("class", "card")
        night_layout = QVBoxLayout(self.night_card)
        night_layout.setContentsMargins(18, 16, 18, 16)
        night_layout.setSpacing(10)

        night_header = QHBoxLayout()
        night_titles = QVBoxLayout()
        night_titles.setSpacing(2)
        nt_lbl = QLabel("Perfil Noturno (Agendamento por Horário)")
        nt_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        nt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        night_titles.addWidget(nt_lbl)
        ns_lbl = QLabel("Reduz ruído, brilho do teclado e ativa conservação automaticamente no período configurado.")
        ns_lbl.setWordWrap(True)
        ns_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        night_titles.addWidget(ns_lbl)
        night_header.addLayout(night_titles, stretch=1)

        self.night_badge = StatusBadge(
            "ATIVO" if night_cfg["enabled"] else "DESATIVADO",
            bg_color=ThemeTokens.BG_CARD_HOVER,
            text_color=ThemeTokens.STATUS_GREEN if night_cfg["enabled"] else ThemeTokens.TEXT_WHITE_80,
        )
        night_header.addWidget(self.night_badge)
        self.sw_night_enabled = ToggleSwitch(checked=night_cfg["enabled"])
        self.sw_night_enabled.toggled.connect(self._on_night_schedule_changed)
        night_header.addWidget(self.sw_night_enabled)
        night_layout.addLayout(night_header)

        night_box = QFrame()
        night_box.setProperty("class", "subBox")
        nb_l = QVBoxLayout(night_box)
        nb_l.setContentsMargins(14, 10, 14, 10)
        nb_l.setSpacing(8)

        nb_row1 = QHBoxLayout()
        nb_row1.setSpacing(10)
        nb_row1.addWidget(QLabel("Início:"))
        self.combo_night_start = QComboBox()
        self.combo_night_start.setFixedHeight(28)
        for h in range(24):
            val = f"{h:02d}:00"
            self.combo_night_start.addItem(val, val)
        s_i = self.combo_night_start.findData(night_cfg["start_time"])
        if s_i >= 0:
            self.combo_night_start.setCurrentIndex(s_i)
        self.combo_night_start.currentIndexChanged.connect(self._on_night_schedule_changed)
        nb_row1.addWidget(self.combo_night_start)

        nb_row1.addWidget(QLabel("Fim:"))
        self.combo_night_end = QComboBox()
        self.combo_night_end.setFixedHeight(28)
        for h in range(24):
            val = f"{h:02d}:00"
            self.combo_night_end.addItem(val, val)
        e_i = self.combo_night_end.findData(night_cfg["end_time"])
        if e_i >= 0:
            self.combo_night_end.setCurrentIndex(e_i)
        self.combo_night_end.currentIndexChanged.connect(self._on_night_schedule_changed)
        nb_row1.addWidget(self.combo_night_end)

        nb_row1.addWidget(QLabel("Perfil:"))
        self.combo_night_profile = QComboBox()
        self.combo_night_profile.setFixedHeight(28)
        for pid, pname in [("low-power", "Silencioso"), ("balanced", "Equilibrado")]:
            if pid in supported_profiles or not supported_profiles:
                self.combo_night_profile.addItem(pname, pid)
        np_i = self.combo_night_profile.findData(night_cfg["profile"])
        if np_i >= 0:
            self.combo_night_profile.setCurrentIndex(np_i)
        self.combo_night_profile.currentIndexChanged.connect(self._on_night_schedule_changed)
        nb_row1.addWidget(self.combo_night_profile)
        nb_row1.addStretch()
        nb_l.addLayout(nb_row1)

        nb_opts = QHBoxLayout()
        nb_opts.setSpacing(14)
        self.night_kbd_widget = QWidget()
        nk_l = QHBoxLayout(self.night_kbd_widget)
        nk_l.setContentsMargins(0, 0, 0, 0)
        nk_l.addWidget(QLabel("Apagar luz do teclado"))
        self.sw_night_kbd_off = ToggleSwitch(checked=night_cfg["kbd_off"])
        self.sw_night_kbd_off.toggled.connect(self._on_night_schedule_changed)
        nk_l.addWidget(self.sw_night_kbd_off)
        self.night_kbd_widget.setVisible(bool(feat.kbd_backlight))
        nb_opts.addWidget(self.night_kbd_widget)

        self.night_cons_widget = QWidget()
        nc_l = QHBoxLayout(self.night_cons_widget)
        nc_l.setContentsMargins(0, 0, 0, 0)
        nc_l.addWidget(QLabel("Ativar Conservação 80%"))
        self.sw_night_conservation = ToggleSwitch(checked=night_cfg["conservation"])
        self.sw_night_conservation.toggled.connect(self._on_night_schedule_changed)
        nc_l.addWidget(self.sw_night_conservation)
        self.night_cons_widget.setVisible(bool(feat.conservation_mode))
        nb_opts.addWidget(self.night_cons_widget)
        nb_opts.addStretch()
        nb_l.addLayout(nb_opts)

        night_layout.addWidget(night_box)
        self.night_card.setVisible(bool(feat.platform_profile and supported_profiles))
        sched_layout.addWidget(self.night_card)
        sched_layout.addWidget(self.session_hist_card)
        sched_layout.addStretch()

        self.sub_stack.addWidget(page_games)
        self.sub_stack.addWidget(page_keys)
        self.sub_stack.addWidget(page_sched)

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.set_advanced_mode(self._advanced_mode)
        self.refresh_automation_state()

    def set_advanced_mode(self, advanced: bool):
        """Alterna visibilidade das opções avançadas (Presets, VRR, Exclusões, App Rules e Histórico)."""
        self._advanced_mode = bool(advanced)
        feat = self.backend.features
        self.presets_card.setVisible(bool(self._advanced_mode and self._has_preset_ctrl))
        self.game_preset_row_widget.setVisible(bool(self._advanced_mode))
        self.game_vrr_row_widget.setVisible(bool(self._advanced_mode and feat.refresh_rate))
        self.game_ignore_box.setVisible(bool(self._advanced_mode))
        self.add_rule_box.setVisible(bool(self._advanced_mode))
        self.rules_list_container.setVisible(bool(self._advanced_mode))
        self.session_hist_card.setVisible(bool(self._advanced_mode and feat.platform_profile and self._supported_profiles))

    def refresh_automation_state(self):
        active_game = self.backend.get_active_game()
        if active_game:
            self.app_rules_badge.setText(f"ATIVO: {active_game[:22].upper()}")
            self.app_rules_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)
        else:
            self.app_rules_badge.setText("AUTO-SWITCH ATIVO")
            self.app_rules_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)

        self.combo_game_target_profile.blockSignals(True)
        cur_gt = self.backend.get_game_target_profile()
        gt_idx = self.combo_game_target_profile.findData(cur_gt)
        if gt_idx >= 0:
            self.combo_game_target_profile.setCurrentIndex(gt_idx)
        self.combo_game_target_profile.blockSignals(False)

        self.sw_game_refresh_max.blockSignals(True)
        self.sw_game_refresh_max.setChecked(self.backend.get_game_auto_refresh_max())
        self.sw_game_refresh_max.blockSignals(False)

        self.sw_game_lock_touchpad.blockSignals(True)
        self.sw_game_lock_touchpad.setChecked(self.backend.get_game_auto_lock_touchpad())
        self.sw_game_lock_touchpad.blockSignals(False)

        self.combo_game_target_preset.blockSignals(True)
        cur_gp = self.backend.get_game_target_preset_id()
        gp_idx = self.combo_game_target_preset.findData(cur_gp)
        self.combo_game_target_preset.setCurrentIndex(gp_idx if gp_idx >= 0 else 0)
        self.combo_game_target_preset.blockSignals(False)

        self.combo_game_vrr.blockSignals(True)
        cur_gvrr = self.backend.get_game_vrr_policy()
        gv_idx = self.combo_game_vrr.findData(cur_gvrr)
        self.combo_game_vrr.setCurrentIndex(gv_idx if gv_idx >= 0 else 0)
        self.combo_game_vrr.blockSignals(False)

        if hasattr(self, "sw_cinema_mode"):
            self.sw_cinema_mode.blockSignals(True)
            self.sw_cinema_mode.setChecked(self.backend.get_cinema_mode())
            self.sw_cinema_mode.blockSignals(False)

        self._refresh_evdev_status_badge()
        self._sync_key_mapping_widgets()
        self._rebuild_game_session_history()

    def _populate_app_rule_profile_combo(self):
        if not hasattr(self, "combo_app_profile"):
            return
        cur_data = self.combo_app_profile.currentData()
        self.combo_app_profile.blockSignals(True)
        self.combo_app_profile.clear()
        supported_profiles = self.backend.get_supported_canonical_profiles()
        for prof_id, prof_label in PROFILE_COMBO_ITEMS:
            if prof_id in supported_profiles:
                self.combo_app_profile.addItem(prof_label, prof_id)
        for p in self.backend.get_user_presets():
            self.combo_app_profile.addItem(f"Preset: {p['name']}", f"preset:{p['id']}")
        idx = self.combo_app_profile.findData(cur_data)
        if idx >= 0:
            self.combo_app_profile.setCurrentIndex(idx)
        self.combo_app_profile.blockSignals(False)

    def _on_game_vrr_changed(self, _val=None):
        self.backend.set_game_vrr_policy(str(self.combo_game_vrr.currentData() or "keep"))

    def _rebuild_game_session_history(self):
        if not hasattr(self, "session_hist_list_layout"):
            return
        while self.session_hist_list_layout.count():
            item = self.session_hist_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        hist = list(reversed(self.backend.get_game_session_history()))[:8]
        cnt = len(hist)
        self.session_hist_badge.setText(f"{cnt} {'SESSÃO' if cnt == 1 else 'SESSÕES'}")
        if not hist:
            lbl = QLabel("Nenhuma sessão registrada ainda. Jogue com o Auto-Switch ativo para gravar métricas.")
            lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
            self.session_hist_list_layout.addWidget(lbl)
            return
        for s in hist:
            row_f = QFrame()
            row_f.setProperty("class", "subBox")
            rl = QHBoxLayout(row_f)
            rl.setContentsMargins(14, 7, 14, 7)
            rl.setSpacing(10)
            dur_m, dur_s = divmod(int(s.get("duration_sec", 0)), 60)
            dur_str = f"{dur_m}m {dur_s:02d}s"
            g_lbl = QLabel(f"{s.get('game', 'Jogo')[:26]}")
            g_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
            g_lbl.setStyleSheet(f"color: {ThemeTokens.ACCENT_STEEL}; min-width: 145px;")
            rl.addWidget(g_lbl)
            dt_lbl = QLabel(f"{s.get('timestamp', '--')} • {dur_str}")
            dt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
            rl.addWidget(dt_lbl, stretch=1)
            gpu_s = f" | GPU {s['peak_gpu_c']:.0f}°C" if s.get("peak_gpu_c", 0) > 0 else ""
            pwr_s = f" • {s['avg_power_w']:.1f}W" if s.get("avg_power_w", 0) > 0 else ""
            pk_lbl = QLabel(f"Pico CPU {s.get('peak_cpu_c', 0):.0f}°C{gpu_s}{pwr_s}")
            pk_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
            rl.addWidget(pk_lbl)
            self.session_hist_list_layout.addWidget(row_f)

    def _on_clear_session_history(self):
        self.backend.clear_game_session_history()
        self._rebuild_game_session_history()

    def _on_night_schedule_changed(self, _val=None):
        en = self.sw_night_enabled.isChecked()
        self.backend.set_night_schedule_config(
            enabled=en,
            start_time=str(self.combo_night_start.currentData() or "23:00"),
            end_time=str(self.combo_night_end.currentData() or "07:00"),
            profile=str(self.combo_night_profile.currentData() or "low-power"),
            kbd_off=self.sw_night_kbd_off.isChecked(),
            conservation=self.sw_night_conservation.isChecked(),
        )
        self.night_badge.setText("ATIVO" if en else "DESATIVADO")
        self.night_badge.setColor(
            ThemeTokens.BG_CARD_HOVER,
            ThemeTokens.STATUS_GREEN if en else ThemeTokens.TEXT_WHITE_80,
        )

    # =========================================================================
    # App Rules & Auto-Switch
    # =========================================================================
    def _populate_running_apps_combo(self):
        self.combo_app_exec.clear()
        self.combo_app_exec.addItem("blender")
        self.combo_app_exec.addItem("resolve")
        self.combo_app_exec.addItem("kdenlive")
        self.combo_app_exec.addItem("obs")
        self.combo_app_exec.addItem("firefox")
        for proc_name in self.backend.get_running_user_processes():
            if self.combo_app_exec.findText(proc_name) < 0:
                self.combo_app_exec.addItem(proc_name)
        self.combo_app_exec.setEditText("")
        if self.combo_app_exec.lineEdit():
            self.combo_app_exec.lineEdit().setPlaceholderText("Executável (ex: blender, cs2, firefox)")

    def _rebuild_app_rules_list(self):
        while self.rules_list_layout.count():
            item = self.rules_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rules = self.backend.get_app_power_rules()
        for rule in rules:
            exec_name = str(rule.get("executable", ""))
            label_txt = str(rule.get("label") or exec_name)
            prof_id = self.backend.normalize_profile(str(rule.get("profile", "performance")))
            enabled = bool(rule.get("enabled", True))
            preset_id = str(rule.get("preset_id", "") or "").strip()
            pinfo = self.backend.get_profile_info(prof_id)
            badge_txt = f"PRESET: {preset_id[:12].upper()}" if preset_id else pinfo["badge"]

            row_f = QFrame()
            row_f.setProperty("class", "subBox")
            r_lay = QHBoxLayout(row_f)
            r_lay.setContentsMargins(14, 8, 14, 8)
            r_lay.setSpacing(10)

            lbl_exec = QLabel(f"{exec_name}")
            lbl_exec.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
            lbl_exec.setStyleSheet(f"color: {ThemeTokens.ACCENT_STEEL}; min-width: 110px; border: none;")
            r_lay.addWidget(lbl_exec)

            lbl_desc = QLabel(label_txt)
            lbl_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px; border: none;")
            r_lay.addWidget(lbl_desc, stretch=1)

            badge = StatusBadge(badge_txt, bg_color=ThemeTokens.BG_CARD_HOVER, text_color=pinfo.get("color", ThemeTokens.TEXT_WHITE_80))
            r_lay.addWidget(badge)

            sw_rule = ToggleSwitch()
            sw_rule.setChecked(enabled)
            sw_rule.toggled.connect(lambda chk, ex=exec_name: self._on_toggle_app_rule(ex, chk))
            r_lay.addWidget(sw_rule)

            btn_del = QPushButton("Remover")
            btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_del.setFixedHeight(26)
            btn_del.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                    color: {ThemeTokens.TEXT_LIGHT_GRAY};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    border-color: {ThemeTokens.LEGION_RED};
                    color: {ThemeTokens.LEGION_RED};
                }}
            """)
            btn_del.clicked.connect(lambda _c, ex=exec_name: self._on_remove_app_rule(ex))
            r_lay.addWidget(btn_del)

            self.rules_list_layout.addWidget(row_f)

    def _on_add_app_rule(self):
        exec_name = self.combo_app_exec.currentText().strip()
        label_txt = self.edit_app_label.text().strip()
        raw_choice = str(self.combo_app_profile.currentData() or "performance")
        if raw_choice.startswith("preset:"):
            pid = raw_choice.split(":", 1)[1]
            ok, msg = self.backend.add_app_power_rule(exec_name, "performance", label_txt, preset_id=pid)
        else:
            ok, msg = self.backend.add_app_power_rule(exec_name, raw_choice, label_txt)
        if not ok:
            QMessageBox.warning(self, "Regra de Aplicativo", msg)
            return
        self.combo_app_exec.setEditText("")
        self.edit_app_label.clear()
        self._rebuild_app_rules_list()

    def _on_toggle_app_rule(self, exec_name: str, enabled: bool):
        self.backend.toggle_app_power_rule(exec_name, enabled)

    def _on_remove_app_rule(self, exec_name: str):
        self.backend.remove_app_power_rule(exec_name)
        self._rebuild_app_rules_list()

    def _on_game_target_profile_changed(self):
        prof = self.combo_game_target_profile.currentData()
        if prof:
            self.backend.set_game_target_profile(str(prof))

    def _on_game_refresh_max_toggled(self, checked: bool):
        self.backend.set_game_auto_refresh_max(checked)

    def _on_game_lock_touchpad_toggled(self, checked: bool):
        self.backend.set_game_auto_lock_touchpad(checked)

    def _populate_game_preset_combo(self):
        self.combo_game_target_preset.blockSignals(True)
        self.combo_game_target_preset.clear()
        self.combo_game_target_preset.addItem("Usar apenas perfil térmico padrão", "")
        for p in self.backend.get_user_presets():
            self.combo_game_target_preset.addItem(f"Preset: {p['name']}", str(p["id"]))
        cur_id = self.backend.get_game_target_preset_id()
        idx = self.combo_game_target_preset.findData(cur_id)
        self.combo_game_target_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_game_target_preset.blockSignals(False)

    def _on_game_target_preset_changed(self):
        pid = str(self.combo_game_target_preset.currentData() or "")
        self.backend.set_game_target_preset_id(pid)

    def _rebuild_game_ignore_list(self):
        while self.ignore_list_layout.count():
            item = self.ignore_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        items = self.backend.get_game_ignore_list()
        if not items:
            lbl = QLabel("Nenhum processo ignorado.")
            lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_40}; font-size: 10px;")
            self.ignore_list_layout.addWidget(lbl)
            self.ignore_list_layout.addStretch()
            return
        for ig in items:
            tag = QPushButton(f"{ig}  ×")
            tag.setCursor(Qt.CursorShape.PointingHandCursor)
            tag.setFixedHeight(22)
            tag.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                    color: {ThemeTokens.TEXT_LIGHT_GRAY};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 11px;
                    padding: 1px 10px;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    border-color: {ThemeTokens.LEGION_RED};
                    color: {ThemeTokens.LEGION_RED};
                }}
            """)
            tag.clicked.connect(lambda _c=False, term=ig: self._on_remove_game_ignore(term))
            self.ignore_list_layout.addWidget(tag)
        self.ignore_list_layout.addStretch()

    def _on_add_game_ignore(self):
        term = self.edit_game_ignore.text().strip()
        ok, msg = self.backend.add_game_ignore_item(term)
        if not ok:
            QMessageBox.warning(self, "Lista de Exclusões", msg)
            return
        self.edit_game_ignore.clear()
        self._rebuild_game_ignore_list()

    def _on_remove_game_ignore(self, term: str):
        self.backend.remove_game_ignore_item(term)
        self._rebuild_game_ignore_list()

    # =========================================================================
    # User Presets (1 Clique)
    # =========================================================================
    def _rebuild_user_presets_list(self):
        while self.presets_list_layout.count():
            item = self.presets_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        presets = self.backend.get_user_presets()
        cnt = len(presets)
        self.presets_count_badge.setText(f"{cnt} {'PRESET' if cnt == 1 else 'PRESETS'}")
        if not presets:
            empty_lbl = QLabel("Nenhum preset salvo ainda. Ajuste os controles desejados e salve acima.")
            empty_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px; padding: 4px 2px;")
            self.presets_list_layout.addWidget(empty_lbl)
            return

        for p in presets:
            pid = str(p.get("id", ""))
            pname = str(p.get("name", pid))
            summary = self.backend.format_user_preset_summary(p)

            row_f = QFrame()
            row_f.setProperty("class", "subBox")
            r_lay = QHBoxLayout(row_f)
            r_lay.setContentsMargins(14, 8, 14, 8)
            r_lay.setSpacing(10)

            lbl_name = QLabel(pname)
            lbl_name.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
            lbl_name.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 140px; border: none;")
            r_lay.addWidget(lbl_name)

            lbl_sum = QLabel(summary)
            lbl_sum.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px; border: none;")
            r_lay.addWidget(lbl_sum, stretch=1)

            btn_apply = QPushButton("Aplicar")
            btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_apply.setFixedHeight(26)
            btn_apply.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                    color: {ThemeTokens.ACCENT_STEEL};
                    border: 1px solid {ThemeTokens.ACCENT_STEEL};
                    border-radius: 5px;
                    padding: 2px 12px;
                    font-weight: 600;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    background-color: {ThemeTokens.ACCENT_STEEL};
                    color: {ThemeTokens.BG_APP};
                }}
            """)
            btn_apply.clicked.connect(lambda _c=False, p_id=pid, p_name=pname: self._on_apply_user_preset(p_id, p_name))
            r_lay.addWidget(btn_apply)

            btn_exp = QPushButton("Exportar")
            btn_exp.setProperty("class", "secondaryButton")
            btn_exp.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_exp.setFixedHeight(26)
            btn_exp.clicked.connect(lambda _c=False, p_id=pid, p_name=pname: self._on_export_user_preset(p_id, p_name))
            r_lay.addWidget(btn_exp)

            btn_del = QPushButton("Remover")
            btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_del.setFixedHeight(26)
            btn_del.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                    color: {ThemeTokens.TEXT_LIGHT_GRAY};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    border-color: {ThemeTokens.LEGION_RED};
                    color: {ThemeTokens.LEGION_RED};
                }}
            """)
            btn_del.clicked.connect(lambda _c=False, p_id=pid: self._on_delete_user_preset(p_id))
            r_lay.addWidget(btn_del)

            self.presets_list_layout.addWidget(row_f)

    def _on_save_user_preset(self):
        name = self.edit_preset_name.text().strip()
        ok, msg, _ = self.backend.save_current_as_preset(name)
        if not ok:
            QMessageBox.warning(self, "Preset Personalizado", msg)
            return
        self.edit_preset_name.clear()
        self._rebuild_user_presets_list()
        self._populate_game_preset_combo()
        self._populate_app_rule_profile_combo()
        self.presets_updated.emit()

    def _on_export_user_preset(self, preset_id: str, preset_name: str):
        dst, _ = QFileDialog.getSaveFileName(
            self, f"Exportar Preset '{preset_name}'",
            os.path.expanduser(f"~/ducksvantage-preset-{preset_id}.json"),
            "Arquivos JSON (*.json)"
        )
        if not dst:
            return
        ok, msg = self.backend.export_user_preset_to_file(preset_id, dst)
        if ok:
            QMessageBox.information(self, "Preset Exportado", msg)
        else:
            QMessageBox.warning(self, "Exportar Preset", msg)

    def _on_import_user_preset(self):
        src, _ = QFileDialog.getOpenFileName(
            self, "Importar Preset (.json)", os.path.expanduser("~"), "Arquivos JSON (*.json)"
        )
        if not src:
            return
        ok, msg, _ = self.backend.import_user_preset_from_file(src)
        if ok:
            self._rebuild_user_presets_list()
            self._populate_game_preset_combo()
            self._populate_app_rule_profile_combo()
            self.presets_updated.emit()
            QMessageBox.information(self, "Preset Importado", msg)
        else:
            QMessageBox.warning(self, "Importar Preset", msg)

    def _on_apply_user_preset(self, preset_id: str, preset_name: str):
        ok, msg = self.backend.apply_user_preset(preset_id)
        if not ok:
            QMessageBox.warning(self, "Preset Personalizado", f"Não foi possível aplicar o preset '{preset_name}':\n{msg}")
            return
        self.refresh_automation_state()
        self.preset_applied.emit(preset_name, msg)

    def _on_delete_user_preset(self, preset_id: str):
        self.backend.delete_user_preset(preset_id)
        self._rebuild_user_presets_list()
        self._populate_game_preset_combo()
        self._populate_app_rule_profile_combo()
        self.presets_updated.emit()

    # =========================================================================
    # Key Remapper (Tecla Copilot F23)
    # =========================================================================
    def _get_supported_key_actions(self) -> List[Tuple[str, str]]:
        feat = self.backend.features
        has_mic_tool = bool(shutil.which("wpctl") or shutil.which("pactl"))
        filtered: List[Tuple[str, str]] = []
        for act_id, act_label in AVAILABLE_KEY_ACTIONS:
            if act_id == "cycle_profile" and not feat.platform_profile:
                continue
            if act_id == "cycle_refresh_rate" and not feat.refresh_rate:
                continue
            if act_id == "toggle_max_power":
                if not feat.platform_profile:
                    continue
                if not feat.max_power_profile:
                    act_label = "Ativar / Desativar Modo Desempenho (Performance)"
            if act_id == "toggle_eco_mode" and not feat.eco_travel:
                continue
            if act_id == "toggle_conservation" and not feat.conservation_mode:
                continue
            if act_id == "toggle_cinema_mode" and not feat.cinema_mode:
                continue
            if act_id == "cycle_audio_preset" and not feat.audio_control:
                continue
            if act_id == "toggle_touchpad" and not feat.touchpad_control:
                continue
            if act_id == "toggle_mic_mute" and not has_mic_tool:
                continue
            filtered.append((act_id, act_label))
        return filtered

    def _create_key_slot_row(self, slot_id: str, slot_cfg: Dict[str, Any]) -> QFrame:
        box = QFrame()
        box.setProperty("class", "subBox")
        v_layout = QVBoxLayout(box)
        v_layout.setContentsMargins(14, 10, 14, 10)
        v_layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)

        lbl_name = QLabel(str(slot_cfg.get("label", slot_id)))
        lbl_name.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        lbl_name.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 185px; border: none;")
        top.addWidget(lbl_name)

        cap_btn = KeyCaptureButton(
            str(slot_cfg.get("qt_shortcut", "Meta+Shift+F23")),
            backend=self.backend,
            evdev_code=int(slot_cfg.get("evdev_code", 0) or 0),
            evdev_modifiers=list(slot_cfg.get("evdev_modifiers") or []),
        )
        cap_btn.shortcut_captured.connect(lambda _seq, s=slot_id: self._on_slot_modified(s))
        top.addWidget(cap_btn)

        combo = QComboBox()
        combo.setMinimumWidth(210)
        combo.setFixedHeight(30)
        current_act = str(slot_cfg.get("action", "cycle_profile"))
        supported_actions = self._get_supported_key_actions()
        sel_idx = 0
        for idx, (act_id, act_label) in enumerate(supported_actions):
            combo.addItem(act_label, act_id)
            if act_id == current_act:
                sel_idx = idx
        combo.setCurrentIndex(sel_idx)
        combo.currentIndexChanged.connect(lambda _idx, s=slot_id: self._on_slot_modified(s))
        top.addWidget(combo, stretch=1)

        btn_test = QPushButton("Testar")
        btn_test.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test.setFixedHeight(30)
        btn_test.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                color: {ThemeTokens.STATUS_GREEN};
                border: 1px solid {ThemeTokens.STATUS_GREEN};
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.STATUS_GREEN};
                color: {ThemeTokens.BG_APP};
            }}
        """)
        btn_test.clicked.connect(lambda _checked, s=slot_id: self._on_test_slot(s))
        top.addWidget(btn_test)

        sw = ToggleSwitch()
        sw.setChecked(bool(slot_cfg.get("enabled", True)))
        sw.toggled.connect(lambda _checked, s=slot_id: self._on_slot_modified(s))
        top.addWidget(sw)

        v_layout.addLayout(top)

        cmd_edit = QLineEdit(str(slot_cfg.get("custom_command", "")))
        cmd_edit.setPlaceholderText("Comando ou script (ex: /usr/bin/konsole ou ~/.local/bin/script.sh)")
        cmd_edit.setVisible(current_act == "custom_command")
        cmd_edit.editingFinished.connect(lambda s=slot_id: self._on_slot_modified(s))
        v_layout.addWidget(cmd_edit)

        self._slot_widgets[slot_id] = {
            "cfg": dict(slot_cfg),
            "cap_btn": cap_btn,
            "combo": combo,
            "cmd_edit": cmd_edit,
            "switch": sw,
        }
        return box

    def _on_slot_modified(self, slot_id: str):
        w = self._slot_widgets.get(slot_id)
        if not w:
            return
        act_id = w["combo"].currentData()
        w["cmd_edit"].setVisible(act_id == "custom_command")

        cap_btn: KeyCaptureButton = w["cap_btn"]
        qt_shortcut = cap_btn.text().strip()
        evdev_code = int(getattr(cap_btn, "evdev_code", 0) or 0)
        evdev_modifiers = normalize_modifiers(getattr(cap_btn, "evdev_modifiers", []) or [])

        cfg = dict(w["cfg"])
        cfg["qt_shortcut"] = qt_shortcut
        cfg["evdev_code"] = evdev_code
        cfg["evdev_modifiers"] = evdev_modifiers
        cfg["extra_evdev_codes"] = default_extra_codes_for_slot(slot_id, qt_shortcut, evdev_code)
        cfg["action"] = act_id
        cfg["custom_command"] = w["cmd_edit"].text().strip()
        cfg["enabled"] = w["switch"].isChecked()
        w["cfg"] = cfg

        self.backend.update_key_mapping(slot_id, cfg)
        self.shortcuts_updated.emit()

    def _refresh_evdev_status_badge(self):
        if not hasattr(self, "evdev_status_badge"):
            return
        devices = self.backend.get_evdev_monitored_devices() if hasattr(self.backend, "get_evdev_monitored_devices") else []
        if devices:
            self.evdev_status_badge.setText("ATALHOS GLOBAIS ATIVOS")
            self.evdev_status_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)
            self.evdev_status_badge.setToolTip("Dispositivos monitorados em background:\n• " + "\n• ".join(devices))
        else:
            self.evdev_status_badge.setText("SOMENTE JANELA")
            self.evdev_status_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_WARNING)
            self.evdev_status_badge.setToolTip(
                "Sem acesso de leitura a /dev/input/event*. Repare as Regras UDEV na aba Config. & Sistema para ativar atalhos globais."
            )

    def _sync_key_mapping_widgets(self):
        mappings = self.backend.get_key_mappings()
        for slot_id, w in self._slot_widgets.items():
            cfg = mappings.get(slot_id)
            if not cfg:
                continue
            w["cfg"] = dict(cfg)
            cap_btn: KeyCaptureButton = w["cap_btn"]
            cap_btn.set_shortcut_state(
                str(cfg.get("qt_shortcut", "")),
                evdev_code=int(cfg.get("evdev_code", 0) or 0),
                evdev_modifiers=list(cfg.get("evdev_modifiers") or []),
            )
            combo: QComboBox = w["combo"]
            combo.blockSignals(True)
            idx = combo.findData(str(cfg.get("action", "cycle_profile")))
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

            w["cmd_edit"].blockSignals(True)
            w["cmd_edit"].setText(str(cfg.get("custom_command", "")))
            w["cmd_edit"].setVisible(str(cfg.get("action", "")) == "custom_command")
            w["cmd_edit"].blockSignals(False)

            sw: ToggleSwitch = w["switch"]
            sw.blockSignals(True)
            sw.setChecked(bool(cfg.get("enabled", True)))
            sw.blockSignals(False)

    def _on_reset_key_mappings(self):
        self.backend.reset_key_mappings_to_default()
        self._sync_key_mapping_widgets()
        self.shortcuts_updated.emit()

    def _on_test_slot(self, slot_id: str):
        w = self._slot_widgets.get(slot_id)
        if not w:
            return
        act_id = w["combo"].currentData()
        cmd = w["cmd_edit"].text().strip()
        self.custom_action_requested.emit(act_id, cmd)
