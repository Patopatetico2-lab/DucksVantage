"""
Aba GPU & Tela do Ducksvantage (ui/tabs/gpu_display_tab.py) — Estilo 3.
Agrupa os controles gráficos e de painel:
1. Telemetria Detalhada da GPU (Clock, Temperatura, Potência, VRAM, P-State / D3cold)
2. GPU MUX Switch (Híbrido / dGPU Direta / iGPU Pura)
3. Taxa de Atualização do Painel (Hz + Transição Automática AC/Bateria)
4. LCD Overdrive & Atributos WMI da BIOS descobertos dinamicamente
"""

import os
import shutil
from typing import Dict, Any
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QSlider, QComboBox,
    Qt, Signal, QFont, QMessageBox, QPixmap
)
from ui.theme_tokens import ThemeTokens
from ui.components import ToggleSwitch, StatusBadge, BasicModeHintBar
from ui.widgets import GpuModeBlock

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")


class GpuDisplayTab(QWidget):
    """Aba GPU & Tela: telemetria GPU, MUX Switch, taxa Hz, VRR, Modo Mesa, Overdrive e BIOS WMI."""
    gpu_mux_changed = Signal(str, bool)
    refresh_rate_changed = Signal(int)
    vrr_policy_changed = Signal(str)
    dock_config_changed = Signal()
    lcd_overdrive_changed = Signal(bool)
    custom_power_applied = Signal(str)
    switch_advanced_requested = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._advanced_mode = self.backend.is_advanced_mode()
        self.mux_blocks: Dict[str, GpuModeBlock] = {}
        self.refresh_rate_buttons: Dict[int, QPushButton] = {}
        self.vrr_buttons: Dict[str, QPushButton] = {}
        self.bios_attr_widgets: Dict[str, Any] = {}
        self.custom_power_sliders: Dict[str, Any] = {}

        feat = self.backend.features

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)

        # =====================================================================
        # 1. Telemetria Detalhada da GPU
        # =====================================================================
        self.gpu_card = QFrame()
        self.gpu_card.setProperty("class", "card")
        gpu_layout = QVBoxLayout(self.gpu_card)
        gpu_layout.setContentsMargins(18, 16, 18, 16)
        gpu_layout.setSpacing(12)

        gpu_header = QHBoxLayout()
        ic_gpu = QLabel()
        p_gpu = os.path.join(ICON_DIR, "gpu_stack.svg")
        if os.path.exists(p_gpu):
            ic_gpu.setPixmap(QPixmap(p_gpu).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        gpu_header.addWidget(ic_gpu)

        gpu_titles = QVBoxLayout()
        gpu_titles.setSpacing(2)
        self.gpu_title_lbl = QLabel(f"Placa Gráfica • {self.backend.system_info.gpu_model}")
        self.gpu_title_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        self.gpu_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        gpu_titles.addWidget(self.gpu_title_lbl)

        gpu_sub = QLabel("Consumo em tempo real, memória de vídeo, frequências e economia de energia.")
        gpu_sub.setToolTip("Inclui suspensão automática PCIe D3cold e estado P-State da GPU")
        gpu_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gpu_titles.addWidget(gpu_sub)
        gpu_header.addLayout(gpu_titles)
        gpu_header.addStretch()

        self.gpu_state_badge = StatusBadge("ATIVA", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.STATUS_GREEN)
        gpu_header.addWidget(self.gpu_state_badge)
        gpu_layout.addLayout(gpu_header)

        self.gpu_basic_summary_lbl = QLabel("Lendo estado da GPU...")
        self.gpu_basic_summary_lbl.setWordWrap(True)
        self.gpu_basic_summary_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gpu_layout.addWidget(self.gpu_basic_summary_lbl)

        self.gpu_stats_widget = QWidget()
        gpu_grid = QGridLayout(self.gpu_stats_widget)
        gpu_grid.setContentsMargins(0, 0, 0, 0)
        gpu_grid.setSpacing(10)
        self.lbl_gpu_clock = self._create_stat_box(gpu_grid, 0, 0, "Frequência Core", "-- MHz")
        self.lbl_gpu_temp = self._create_stat_box(gpu_grid, 0, 1, "Temperatura GPU", "-- °C")
        self.lbl_gpu_power = self._create_stat_box(gpu_grid, 0, 2, "Consumo Elétrico", "-- W")
        self.lbl_gpu_vram = self._create_stat_box(gpu_grid, 1, 0, "Memória VRAM", "-- / -- MB")
        self.lbl_gpu_util = self._create_stat_box(gpu_grid, 1, 1, "Carga do Núcleo", "-- %")
        self.lbl_gpu_pstate = self._create_stat_box(gpu_grid, 1, 2, "Runtime / P-State", "--")

        gpu_layout.addWidget(self.gpu_stats_widget)
        self.gpu_card.setVisible(feat.gpu_telemetry)
        layout.addWidget(self.gpu_card)

        # =====================================================================
        # 1.5 Painel Dedicado do Modo Custom Lenovo (cTGP GPU + Dynamic Boost + WMI PPT)
        # =====================================================================
        self.custom_power_card = QFrame()
        self.custom_power_card.setProperty("class", "card")
        cp_layout = QVBoxLayout(self.custom_power_card)
        cp_layout.setContentsMargins(18, 16, 18, 16)
        cp_layout.setSpacing(12)

        cp_header = QHBoxLayout()
        cp_titles = QVBoxLayout()
        cp_titles.setSpacing(2)
        cp_t = QLabel("Potência da GPU & Modo Custom Lenovo")
        cp_t.setWordWrap(True)
        cp_t.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        cp_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        cp_titles.addWidget(cp_t)
        self.cp_sub_lbl = QLabel(
            "Controle direto da potência da GPU NVIDIA (cTGP), Dynamic Boost e limites WMI da placa."
        )
        self.cp_sub_lbl.setWordWrap(True)
        self.cp_sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        cp_titles.addWidget(self.cp_sub_lbl)
        cp_header.addLayout(cp_titles, stretch=1)

        self.custom_power_badge = StatusBadge("LENOVO WMI", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.THERMAL_CUSTOM)
        cp_header.addWidget(self.custom_power_badge)
        cp_layout.addLayout(cp_header)

        cp_quick_box = QFrame()
        cp_quick_box.setProperty("class", "subBox")
        cp_q_row = QHBoxLayout(cp_quick_box)
        cp_q_row.setContentsMargins(14, 10, 14, 10)
        cp_q_row.setSpacing(10)

        cp_q_lbl = QLabel("Modos Rápidos 1-Clique (Ativa Perfil Custom):")
        cp_q_lbl.setWordWrap(True)
        cp_q_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        cp_q_row.addWidget(cp_q_lbl, stretch=1)

        self.btn_cp_cool = QPushButton("Jogos Frios & Silenciosos")
        self.btn_cp_cool.setProperty("class", "secondaryButton")
        self.btn_cp_cool.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cp_cool.setFixedHeight(30)
        self.btn_cp_cool.clicked.connect(lambda _c=False: self._on_custom_power_preset("cool_quiet"))
        cp_q_row.addWidget(self.btn_cp_cool)

        self.btn_cp_max = QPushButton("Potência Máxima GPU")
        self.btn_cp_max.setProperty("class", "primaryButton")
        self.btn_cp_max.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cp_max.setFixedHeight(30)
        self.btn_cp_max.clicked.connect(lambda _c=False: self._on_custom_power_preset("max_gpu"))
        cp_q_row.addWidget(self.btn_cp_max)
        cp_layout.addWidget(cp_quick_box)

        self.custom_power_adv_box = QFrame()
        self.custom_power_adv_box.setProperty("class", "subBox")
        self.cp_adv_layout = QVBoxLayout(self.custom_power_adv_box)
        self.cp_adv_layout.setContentsMargins(14, 12, 14, 12)
        self.cp_adv_layout.setSpacing(10)

        self.cp_sliders_container = QWidget()
        self.cp_sliders_layout = QVBoxLayout(self.cp_sliders_container)
        self.cp_sliders_layout.setContentsMargins(0, 0, 0, 0)
        self.cp_sliders_layout.setSpacing(8)
        self.cp_adv_layout.addWidget(self.cp_sliders_container)

        cp_apply_row = QHBoxLayout()
        cp_apply_row.addStretch()
        self.btn_apply_custom_power = QPushButton("Aplicar Limites Custom")
        self.btn_apply_custom_power.setProperty("class", "primaryButton")
        self.btn_apply_custom_power.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_custom_power.setFixedHeight(30)
        self.btn_apply_custom_power.clicked.connect(self._on_apply_custom_power_sliders)
        cp_apply_row.addWidget(self.btn_apply_custom_power)
        self.cp_adv_layout.addLayout(cp_apply_row)

        cp_layout.addWidget(self.custom_power_adv_box)
        self.custom_power_card.setVisible(bool(feat.wmi_custom_power))
        layout.addWidget(self.custom_power_card)

        # =====================================================================
        # 2. GPU MUX Switch
        # =====================================================================
        self.mux_card = QFrame()
        self.mux_card.setProperty("class", "card")
        mux_layout = QVBoxLayout(self.mux_card)
        mux_layout.setContentsMargins(18, 16, 18, 16)
        mux_layout.setSpacing(12)

        mux_header = QHBoxLayout()
        ic_mux = QLabel()
        if os.path.exists(p_gpu):
            ic_mux.setPixmap(QPixmap(p_gpu).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        mux_header.addWidget(ic_mux)

        mux_titles = QVBoxLayout()
        mux_titles.setSpacing(2)
        self.mux_title_lbl = QLabel("GPU MUX Switch")
        self.mux_title_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        self.mux_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        mux_titles.addWidget(self.mux_title_lbl)

        self.mux_sub_lbl = QLabel("Alterne entre os modos gráficos suportados pelo notebook.")
        self.mux_sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        mux_titles.addWidget(self.mux_sub_lbl)
        mux_header.addLayout(mux_titles)
        mux_header.addStretch()

        self.mux_backend_badge = StatusBadge("BACKEND: N/A", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        mux_header.addWidget(self.mux_backend_badge)
        mux_layout.addLayout(mux_header)

        self.mux_reboot_banner = QLabel("A alteração de modo de GPU exige reinicialização do sistema ou sessão.")
        self.mux_reboot_banner.setStyleSheet(f"""
            background-color: #2c1d1f;
            color: #fca5a5;
            border: 1px solid {ThemeTokens.LEGION_RED};
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 11px;
            font-weight: 600;
        """)
        self.mux_reboot_banner.setVisible(False)
        mux_layout.addWidget(self.mux_reboot_banner)

        mux_blocks_layout = QHBoxLayout()
        mux_blocks_layout.setSpacing(10)

        self.block_mux_hybrid = GpuModeBlock(
            "hybrid",
            "Modo Híbrido (Optimus)",
            "iGPU renderiza a tela com aceleração dGPU sob demanda.",
            ThemeTokens.ACCENT_STEEL,
        )
        self.block_mux_hybrid.clicked.connect(self._on_mux_mode_selected)
        self.mux_blocks["hybrid"] = self.block_mux_hybrid
        mux_blocks_layout.addWidget(self.block_mux_hybrid)

        self.block_mux_dedicated = GpuModeBlock(
            "dedicated",
            "dGPU Direta (Exclusiva)",
            "Conexão direta no monitor com menor latência.",
            ThemeTokens.THERMAL_CUSTOM,
        )
        self.block_mux_dedicated.clicked.connect(self._on_mux_mode_selected)
        self.mux_blocks["dedicated"] = self.block_mux_dedicated
        mux_blocks_layout.addWidget(self.block_mux_dedicated)

        self.block_mux_integrated = GpuModeBlock(
            "integrated",
            "iGPU Pura (Eco)",
            "GPU dedicada desligada em nível PCIe para máxima bateria.",
            ThemeTokens.STATUS_GREEN,
        )
        self.block_mux_integrated.clicked.connect(self._on_mux_mode_selected)
        self.mux_blocks["integrated"] = self.block_mux_integrated
        mux_blocks_layout.addWidget(self.block_mux_integrated)

        mux_layout.addLayout(mux_blocks_layout)
        layout.addWidget(self.mux_card)

        # =====================================================================
        # 3. Taxa de Atualização do Painel (Hz)
        # =====================================================================
        self.ref_card = QFrame()
        self.ref_card.setProperty("class", "card")
        ref_layout = QVBoxLayout(self.ref_card)
        ref_layout.setContentsMargins(18, 16, 18, 16)
        ref_layout.setSpacing(12)

        ref_header = QHBoxLayout()
        ic_ref = QLabel()
        p_ref = os.path.join(ICON_DIR, "refresh.svg")
        if os.path.exists(p_ref):
            ic_ref.setPixmap(QPixmap(p_ref).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        ref_header.addWidget(ic_ref)

        ref_titles = QVBoxLayout()
        ref_titles.setSpacing(2)
        self.ref_title_lbl = QLabel("Taxa de Atualização do Painel")
        self.ref_title_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        self.ref_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        ref_titles.addWidget(self.ref_title_lbl)

        ref_sub = QLabel("Troca de frequência (Hz) compatível com Wayland (KDE / wlroots) e X11.")
        ref_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        ref_titles.addWidget(ref_sub)
        ref_header.addLayout(ref_titles)
        ref_header.addStretch()

        self.ref_rate_badge = StatusBadge("-- Hz", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        ref_header.addWidget(self.ref_rate_badge)
        ref_layout.addLayout(ref_header)

        ref_ctrl_box = QFrame()
        ref_ctrl_box.setProperty("class", "subBox")
        ref_ctrl_row = QHBoxLayout(ref_ctrl_box)
        ref_ctrl_row.setContentsMargins(14, 10, 14, 10)

        ref_info = QVBoxLayout()
        self.ref_display_name_lbl = QLabel("Painel Interno (eDP-1)")
        self.ref_display_name_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.ref_display_name_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        ref_info.addWidget(self.ref_display_name_lbl)

        ref_desc = QLabel("Selecione a taxa de atualização ou use Fn + R (Alt + R).")
        ref_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        ref_info.addWidget(ref_desc)
        ref_ctrl_row.addLayout(ref_info)
        ref_ctrl_row.addStretch()

        self.ref_buttons_layout = QHBoxLayout()
        self.ref_buttons_layout.setSpacing(8)
        ref_ctrl_row.addLayout(self.ref_buttons_layout)

        self.btn_cycle_ref = QPushButton("Ciclar Fn + R")
        self.btn_cycle_ref.setProperty("class", "secondaryButton")
        self.btn_cycle_ref.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cycle_ref.clicked.connect(self._on_cycle_refresh_rate_clicked)
        ref_ctrl_row.addWidget(self.btn_cycle_ref)
        ref_layout.addWidget(ref_ctrl_box)

        self.ref_auto_box = QFrame()
        self.ref_auto_box.setProperty("class", "subBox")
        ref_auto_row = QHBoxLayout(self.ref_auto_box)
        ref_auto_row.setContentsMargins(14, 10, 14, 10)

        ra_info = QVBoxLayout()
        ra_lbl = QLabel("Alternância Automática (Tomada AC vs Bateria)")
        ra_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        ra_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        ra_info.addWidget(ra_lbl)

        self.ra_desc = QLabel("Reduz para a menor taxa na bateria e restaura taxa máxima no AC.")
        self.ra_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        ra_info.addWidget(self.ra_desc)
        ref_auto_row.addLayout(ra_info)
        ref_auto_row.addStretch()

        self.ref_auto_switch = ToggleSwitch()
        self.ref_auto_switch.setChecked(self.backend.get_auto_refresh_rate_transition())
        self.ref_auto_switch.toggled.connect(self._on_ref_auto_toggled)
        ref_auto_row.addWidget(self.ref_auto_switch)
        self.ref_auto_box.setVisible(feat.battery)
        ref_layout.addWidget(self.ref_auto_box)

        # VRR / Adaptive Sync (Wayland KDE Plasma 6)
        self.vrr_box = QFrame()
        self.vrr_box.setProperty("class", "subBox")
        vrr_row = QHBoxLayout(self.vrr_box)
        vrr_row.setContentsMargins(14, 10, 14, 10)
        vrr_row.setSpacing(10)

        vrr_info = QVBoxLayout()
        vrr_lbl = QLabel("VRR / Adaptive Sync (Taxa Variável)")
        vrr_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        vrr_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        vrr_info.addWidget(vrr_lbl)
        vrr_desc = QLabel("Sincroniza a taxa da tela com os quadros por segundo para eliminar cortes de imagem.")
        vrr_desc.setToolTip("Controle de VRR / Adaptive Sync via kscreen-doctor (Wayland)")
        vrr_desc.setWordWrap(True)
        vrr_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        vrr_info.addWidget(vrr_desc)
        vrr_row.addLayout(vrr_info, stretch=1)

        for v_lbl, v_pol in [("Desligado", "never"), ("Automático", "automatic"), ("Sempre", "always")]:
            v_btn = QPushButton(v_lbl)
            v_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            v_btn.setFixedHeight(28)
            v_btn.clicked.connect(lambda _c=False, pol=v_pol: self._on_vrr_button_clicked(pol))
            vrr_row.addWidget(v_btn)
            self.vrr_buttons[v_pol] = v_btn

        self.vrr_box.setVisible(False)
        ref_layout.addWidget(self.vrr_box)

        layout.addWidget(self.ref_card)

        # =====================================================================
        # 3.5 Modo Mesa / Monitor Externo Automático (HDMI / DisplayPort)
        # =====================================================================
        supported_profiles = self.backend.get_supported_canonical_profiles()
        dock_cfg = self.backend.get_dock_mode_config()
        self.dock_card = QFrame()
        self.dock_card.setProperty("class", "card")
        dock_layout = QVBoxLayout(self.dock_card)
        dock_layout.setContentsMargins(18, 16, 18, 16)
        dock_layout.setSpacing(12)

        dock_header = QHBoxLayout()
        dock_titles = QVBoxLayout()
        dock_titles.setSpacing(2)
        dt_lbl = QLabel("Modo Mesa / Monitor Externo Automático (HDMI / DP)")
        dt_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        dt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        dock_titles.addWidget(dt_lbl)
        ds_lbl = QLabel("Detecta monitor externo plugado e ajusta perfil térmico, Hz máximo e comportamento da tampa.")
        ds_lbl.setWordWrap(True)
        ds_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        dock_titles.addWidget(ds_lbl)
        dock_header.addLayout(dock_titles, stretch=1)

        self.dock_status_badge = StatusBadge("SEM MONITOR EXTERNO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.TEXT_WHITE_80)
        dock_header.addWidget(self.dock_status_badge)
        self.sw_dock_enabled = ToggleSwitch(checked=dock_cfg["enabled"])
        self.sw_dock_enabled.toggled.connect(self._on_dock_config_changed)
        dock_header.addWidget(self.sw_dock_enabled)
        dock_layout.addLayout(dock_header)

        self.dock_adv_box = QFrame()
        dock_box = self.dock_adv_box
        dock_box.setProperty("class", "subBox")
        dock_box_l = QVBoxLayout(dock_box)
        dock_box_l.setContentsMargins(14, 10, 14, 10)
        dock_box_l.setSpacing(8)

        dock_row1 = QHBoxLayout()
        dock_row1.setSpacing(10)
        dp_lbl = QLabel("Perfil ao conectar monitor externo:")
        dp_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        dock_row1.addWidget(dp_lbl)
        self.combo_dock_profile = QComboBox()
        self.combo_dock_profile.setMinimumWidth(190)
        self.combo_dock_profile.setFixedHeight(28)
        for pid, pname in [("balanced", "Equilibrado"), ("performance", "Desempenho"), ("max-power", "Max-Power")]:
            if pid in supported_profiles or not supported_profiles:
                self.combo_dock_profile.addItem(pname, pid)
        d_idx = self.combo_dock_profile.findData(dock_cfg["target_profile"])
        if d_idx >= 0:
            self.combo_dock_profile.setCurrentIndex(d_idx)
        self.combo_dock_profile.currentIndexChanged.connect(self._on_dock_config_changed)
        dock_row1.addWidget(self.combo_dock_profile)
        dock_row1.addStretch()
        dock_box_l.addLayout(dock_row1)

        self.dock_hz_row = QWidget()
        dhz_l = QHBoxLayout(self.dock_hz_row)
        dhz_l.setContentsMargins(0, 0, 0, 0)
        dhz_lbl = QLabel("Forçar taxa de atualização máxima (Hz) enquanto na mesa")
        dhz_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        dhz_l.addWidget(dhz_lbl, stretch=1)
        self.sw_dock_max_hz = ToggleSwitch(checked=dock_cfg["keep_max_hz"])
        self.sw_dock_max_hz.toggled.connect(self._on_dock_config_changed)
        dhz_l.addWidget(self.sw_dock_max_hz)
        self.dock_hz_row.setVisible(bool(feat.refresh_rate))
        dock_box_l.addWidget(self.dock_hz_row)

        self.dock_lid_row = QWidget()
        dlid_l = QHBoxLayout(self.dock_lid_row)
        dlid_l.setContentsMargins(0, 0, 0, 0)
        dlid_lbl = QLabel("Impedir suspensão ao fechar a tampa do notebook (Clamshell)")
        dlid_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
        dlid_l.addWidget(dlid_lbl, stretch=1)
        self.sw_dock_lid_inhibit = ToggleSwitch(checked=dock_cfg["inhibit_lid_sleep"])
        self.sw_dock_lid_inhibit.toggled.connect(self._on_dock_config_changed)
        dlid_l.addWidget(self.sw_dock_lid_inhibit)
        self.dock_lid_row.setVisible(bool(shutil.which("systemd-inhibit")))
        dock_box_l.addWidget(self.dock_lid_row)

        dock_layout.addWidget(dock_box)
        show_dock = bool(feat.external_monitor_dock and (feat.platform_profile or feat.refresh_rate))
        self.dock_card.setVisible(show_dock)
        layout.addWidget(self.dock_card)

        # =====================================================================
        # 4. LCD Overdrive & Ajustes de Firmware Lenovo (BIOS / WMI)
        # =====================================================================
        self.bios_card = QFrame()
        self.bios_card.setProperty("class", "card")
        bios_layout = QVBoxLayout(self.bios_card)
        bios_layout.setContentsMargins(18, 16, 18, 16)
        bios_layout.setSpacing(12)

        bios_header = QHBoxLayout()
        ic_bios = QLabel()
        p_bios = os.path.join(ICON_DIR, "tools.svg")
        if os.path.exists(p_bios):
            ic_bios.setPixmap(QPixmap(p_bios).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        bios_header.addWidget(ic_bios)

        bios_titles = QVBoxLayout()
        bios_titles.setSpacing(2)
        self.bios_title_lbl = QLabel("Firmware Lenovo (BIOS / WMI)")
        self.bios_title_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        self.bios_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        bios_titles.addWidget(self.bios_title_lbl)

        self.bios_sub_lbl = QLabel("Nós de BIOS descobertos dinamicamente no hardware.")
        self.bios_sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        bios_titles.addWidget(self.bios_sub_lbl)
        bios_header.addLayout(bios_titles)
        bios_header.addStretch()

        self.bios_count_badge = StatusBadge("-- ITENS", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        bios_header.addWidget(self.bios_count_badge)
        bios_layout.addLayout(bios_header)

        self.od_box = QFrame()
        self.od_box.setProperty("class", "subBox")
        od_row = QHBoxLayout(self.od_box)
        od_row.setContentsMargins(14, 10, 14, 10)

        od_info = QVBoxLayout()
        od_lbl = QLabel("LCD Overdrive (Resposta Acelerada)")
        od_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        od_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        od_info.addWidget(od_lbl)

        od_desc = QLabel("Reduz ghosting acelerando a transição cinza-para-cinza do painel.")
        od_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        od_info.addWidget(od_desc)
        od_row.addLayout(od_info)
        od_row.addStretch()

        self.lcd_overdrive_switch = ToggleSwitch()
        is_od_supp = self.backend.is_lcd_overdrive_supported()
        self.lcd_overdrive_switch.setEnabled(is_od_supp)
        self.lcd_overdrive_switch.setChecked(self.backend.get_lcd_overdrive() if is_od_supp else False)
        self.lcd_overdrive_switch.toggled.connect(self._on_lcd_overdrive_toggled)
        od_row.addWidget(self.lcd_overdrive_switch)
        self.od_box.setVisible(is_od_supp)
        bios_layout.addWidget(self.od_box)

        self.bios_dyn_widget = QWidget()
        self.bios_dyn_container = QVBoxLayout(self.bios_dyn_widget)
        self.bios_dyn_container.setContentsMargins(0, 0, 0, 0)
        self.bios_dyn_container.setSpacing(10)
        bios_layout.addWidget(self.bios_dyn_widget)

        self._build_dynamic_bios_attributes()
        layout.addWidget(self.bios_card)

        self.basic_hint_card = BasicModeHintBar(
            "Modo Básico ativo • Telemetria detalhada da GPU (P-State/VRAM/clocks), GPU MUX Switch, sliders Custom Lenovo, Clamshell/HDMI e ajustes BIOS/WMI disponíveis no Modo Avançado."
        )
        self.basic_hint_card.switch_advanced_requested.connect(self.switch_advanced_requested.emit)
        layout.addWidget(self.basic_hint_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.refresh_all()
        self.set_advanced_mode(self._advanced_mode)

    def _create_stat_box(self, grid: QGridLayout, r: int, c: int, label: str, default: str) -> QLabel:
        box = QFrame()
        box.setProperty("class", "subBox")
        b_layout = QVBoxLayout(box)
        b_layout.setSpacing(3)
        b_layout.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel(label)
        lbl.setFont(QFont(ThemeTokens.FONT_NAME, 9))
        lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; border: none;")
        b_layout.addWidget(lbl)

        val = QLabel(default)
        val.setFont(QFont(ThemeTokens.FONT_NAME, 11, QFont.Weight.DemiBold))
        val.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        b_layout.addWidget(val)

        grid.addWidget(box, r, c)
        return val

    def _has_base_supported_feature(self) -> bool:
        feat = self.backend.features
        return bool(
            not self.gpu_card.isHidden()
            or not self.custom_power_card.isHidden()
            or not self.mux_card.isHidden()
            or not self.ref_card.isHidden()
            or not self.dock_card.isHidden()
            or not self.bios_card.isHidden()
            or feat.gpu_mux
            or feat.bios_attributes
        )

    def has_any_supported_feature(self) -> bool:
        """Retorna True se ao menos um bloco de GPU, Custom Power, MUX, Hz, Dock ou BIOS/Overdrive estiver ativo."""
        return self._has_base_supported_feature()

    def refresh_all(self):
        self.refresh_gpu_state()
        self.refresh_custom_power_state()
        self.refresh_mux_state()
        self.refresh_display_state()
        self.refresh_dock_state()
        self.refresh_bios_state()

    def refresh_gpu_state(self):
        gpu = self.backend.get_gpu_metrics()
        self.gpu_title_lbl.setText(f"Placa Gráfica • {gpu.name}")
        if gpu.available:
            self.gpu_state_badge.setText(f"{gpu.runtime_state.upper()} ({gpu.pstate})")
            self.gpu_state_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)
            pwr_txt = f"{gpu.power_draw_w:.1f} W" if gpu.power_draw_w > 0 else "Integrada"
            self.gpu_basic_summary_lbl.setText(
                f"GPU ativa ({gpu.temperature_c:.0f}°C • {pwr_txt} • uso {gpu.utilization_percent}%). "
                "No Modo Avançado você vê clocks, P-State e memória VRAM."
            )
            self.lbl_gpu_clock.setText(f"{gpu.clock_mhz} MHz" if gpu.clock_mhz > 0 else "Dinâmico")
            self.lbl_gpu_temp.setText(f"{gpu.temperature_c:.1f} °C")
            self.lbl_gpu_power.setText(pwr_txt)
            if gpu.memory_total_mb > 0:
                self.lbl_gpu_vram.setText(f"{gpu.memory_used_mb} / {gpu.memory_total_mb} MB")
            else:
                self.lbl_gpu_vram.setText("Memória Compartilhada")
            self.lbl_gpu_util.setText(f"{gpu.utilization_percent}%")
            self.lbl_gpu_pstate.setText(f"Ativa • {gpu.pstate}")
        else:
            self.gpu_state_badge.setText("D3COLD (SUSPENSA)")
            self.gpu_state_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)
            self.gpu_basic_summary_lbl.setText(
                "Placa dedicada em repouso econômico (D3cold) • 0 W consumidos da bateria."
            )
            self.lbl_gpu_clock.setText("0 MHz (D3cold)")
            self.lbl_gpu_temp.setText("Repouso")
            self.lbl_gpu_power.setText("0.0 W")
            self.lbl_gpu_vram.setText("Desligada")
            self.lbl_gpu_util.setText("0%")
            self.lbl_gpu_pstate.setText("Runtime Suspended (D3cold)")

    def _on_mux_mode_selected(self, mode: str):
        ok, msg, req_reboot = self.backend.set_gpu_mux_mode(mode)
        if ok:
            self.refresh_mux_state()
            self.gpu_mux_changed.emit(mode, req_reboot)
        else:
            QMessageBox.warning(self, "GPU MUX Switch", f"Não foi possível alterar o modo de GPU:\n{msg}")

    def refresh_mux_state(self):
        mux = self.backend.get_gpu_mux_info()
        show_mux = bool(self._advanced_mode and mux.available and mux.available_modes and mux.backend_name not in ("none", "software"))
        self.mux_card.setVisible(show_mux)
        if not show_mux:
            return

        self.mux_backend_badge.setText(f"BACKEND: {mux.backend_name.upper()}")
        mode_labels = {
            "hybrid": "Modo Híbrido (Optimus)",
            "dedicated": "dGPU Exclusiva (Direct)",
            "integrated": "iGPU Pura (Eco Extremo)",
        }
        active_labels = [mode_labels[m] for m in ("hybrid", "dedicated", "integrated") if m in mux.available_modes]
        if active_labels:
            self.mux_sub_lbl.setText("Alterne entre " + " e ".join(active_labels) + ".")

        for mid, blk in self.mux_blocks.items():
            is_supported = (mid in mux.available_modes)
            blk.setVisible(is_supported)
            blk.setEnabled(is_supported)
            blk.set_active(mid == mux.current_mode)
        self.mux_reboot_banner.setVisible(mux.requires_reboot)

    def _on_refresh_rate_button_clicked(self, hz: int):
        ok, msg = self.backend.set_refresh_rate(hz)
        if ok:
            self.refresh_display_state()
            self.refresh_rate_changed.emit(hz)
        else:
            QMessageBox.warning(self, "Taxa de Atualização", f"Não foi possível alterar para {hz} Hz:\n{msg}")

    def _on_cycle_refresh_rate_clicked(self):
        ok, new_hz, msg = self.backend.cycle_refresh_rate()
        if ok:
            self.refresh_display_state()
            self.refresh_rate_changed.emit(new_hz)
        else:
            QMessageBox.warning(self, "Taxa de Atualização", f"Não foi possível alternar a taxa:\n{msg}")

    def _on_ref_auto_toggled(self, checked: bool):
        self.backend.set_auto_refresh_rate_transition(checked)

    def refresh_display_state(self):
        info = self.backend.get_display_refresh_info()
        can_switch = bool(
            info.available
            and info.backend_name in ("kscreen-doctor", "wlr-randr", "xrandr")
            and len(info.available_rates) > 1
        )
        self.ref_card.setVisible(can_switch)
        if not can_switch:
            return

        self.ref_rate_badge.setText(f"{info.current_hz} Hz")
        self.ref_display_name_lbl.setText(f"{info.display_name} • {info.resolution}")
        self.ref_auto_box.setVisible(self.backend.features.battery)
        min_hz, max_hz = min(info.available_rates), max(info.available_rates)
        self.ra_desc.setText(
            f"Reduz para {min_hz} Hz na bateria para economizar energia e restaura {max_hz} Hz no AC."
        )

        existing_rates = set(self.refresh_rate_buttons.keys())
        current_rates = set(info.available_rates)
        if existing_rates != current_rates:
            while self.ref_buttons_layout.count():
                item = self.ref_buttons_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.refresh_rate_buttons.clear()

            for hz in info.available_rates:
                btn = QPushButton(f"{hz} Hz")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _c=False, h=hz: self._on_refresh_rate_button_clicked(h))
                self.refresh_rate_buttons[hz] = btn
                self.ref_buttons_layout.addWidget(btn)

        for hz, btn in self.refresh_rate_buttons.items():
            is_active = (hz == info.current_hz)
            if is_active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BG_CARD_ACTIVE};
                        color: {ThemeTokens.TEXT_WHITE_100};
                        border: 1.5px solid {ThemeTokens.ACCENT_STEEL};
                        border-radius: 6px;
                        padding: 5px 14px;
                        font-weight: 600;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BG_CARD_HOVER};
                        color: {ThemeTokens.TEXT_LIGHT_GRAY};
                        border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                        border-radius: 6px;
                        padding: 5px 14px;
                    }}
                    QPushButton:hover {{
                        border-color: {ThemeTokens.ACCENT_STEEL};
                        color: {ThemeTokens.TEXT_WHITE_100};
                    }}
                """)

        self.ref_auto_switch.blockSignals(True)
        self.ref_auto_switch.setChecked(info.auto_switch_ac)
        self.ref_auto_switch.blockSignals(False)

        self.vrr_box.setVisible(bool(info.vrr_supported))
        if info.vrr_supported:
            for pol, btn in self.vrr_buttons.items():
                is_sel = (pol == info.vrr_policy)
                if is_sel:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {ThemeTokens.BG_CARD_ACTIVE};
                            color: {ThemeTokens.TEXT_WHITE_100};
                            border: 1.5px solid {ThemeTokens.ACCENT_STEEL};
                            border-radius: 6px;
                            padding: 4px 12px;
                            font-weight: 600;
                        }}
                    """)
                else:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {ThemeTokens.BG_CARD_HOVER};
                            color: {ThemeTokens.TEXT_LIGHT_GRAY};
                            border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                            border-radius: 6px;
                            padding: 4px 12px;
                        }}
                        QPushButton:hover {{
                            border-color: {ThemeTokens.ACCENT_STEEL};
                            color: {ThemeTokens.TEXT_WHITE_100};
                        }}
                    """)

    def set_advanced_mode(self, advanced: bool):
        """Exibe ou oculta telemetria detalhada GPU, GPU MUX, opções Clamshell, sliders Custom Lenovo e BIOS WMI."""
        self._advanced_mode = bool(advanced)
        if hasattr(self, "gpu_stats_widget"):
            self.gpu_stats_widget.setVisible(bool(self._advanced_mode))
        if hasattr(self, "gpu_basic_summary_lbl"):
            self.gpu_basic_summary_lbl.setVisible(not self._advanced_mode)
        self.refresh_custom_power_state()
        self.refresh_mux_state()
        self.refresh_display_state()
        self.refresh_dock_state()
        self.refresh_bios_state()
        if hasattr(self, "basic_hint_card"):
            self.basic_hint_card.setVisible(bool((not self._advanced_mode) and self._has_base_supported_feature()))

    def refresh_custom_power_state(self):
        """Atualiza o painel dedicado do Modo Custom Lenovo (cTGP GPU + Dynamic Boost + PPT)."""
        if not hasattr(self, "custom_power_card"):
            return
        ctrls = self.backend.get_lenovo_custom_power_controls() if self.backend.features.wmi_custom_power else []
        show_card = bool(self.backend.features.wmi_custom_power and ctrls)
        self.custom_power_card.setVisible(show_card)
        if not show_card:
            return

        ctgp = next((c for c in ctrls if c["attr_id"] == "gpu_nv_ctgp"), None)
        ppab = next((c for c in ctrls if c["attr_id"] == "gpu_nv_ppab"), None)
        if ctgp and ppab:
            self.custom_power_badge.setText(f"cTGP {ctgp['current']}W + {ppab['current']}W")
        elif ctgp:
            self.custom_power_badge.setText(f"cTGP {ctgp['current']}W")
        else:
            self.custom_power_badge.setText(f"{len(ctrls)} CONTROLES")

        self.custom_power_adv_box.setVisible(bool(self._advanced_mode))
        if not self._advanced_mode:
            return

        if set(self.custom_power_sliders.keys()) != {c["attr_id"] for c in ctrls}:
            while self.cp_sliders_layout.count():
                item = self.cp_sliders_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.custom_power_sliders.clear()

            for c in ctrls:
                row_w = QWidget()
                rl = QHBoxLayout(row_w)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(10)
                lbl = QLabel(f"{c['label']}:")
                lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px; min-width: 195px;")
                rl.addWidget(lbl)
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(int(c["min"]), int(c["max"]))
                sl.setValue(max(int(c["min"]), min(int(c["max"]), int(c["current"]))))
                val_lbl = QLabel(f"{c['current']} {c['unit']}")
                val_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
                val_lbl.setStyleSheet(f"color: {ThemeTokens.ACCENT_STEEL}; min-width: 48px;")
                sl.valueChanged.connect(lambda v, l=val_lbl, u=c["unit"]: l.setText(f"{v} {u}"))
                rl.addWidget(sl, stretch=1)
                rl.addWidget(val_lbl)
                self.cp_sliders_layout.addWidget(row_w)
                self.custom_power_sliders[c["attr_id"]] = (sl, val_lbl, c["unit"])
        else:
            for c in ctrls:
                pair = self.custom_power_sliders.get(c["attr_id"])
                if pair:
                    sl, val_lbl, unit = pair
                    sl.blockSignals(True)
                    sl.setValue(max(sl.minimum(), min(sl.maximum(), int(c["current"]))))
                    sl.blockSignals(False)
                    val_lbl.setText(f"{c['current']} {unit}")

    def _on_custom_power_preset(self, preset_key: str):
        ok, msg = self.backend.apply_lenovo_custom_power_preset(preset_key)
        self.refresh_custom_power_state()
        if ok:
            self.custom_power_applied.emit(msg)
        else:
            QMessageBox.warning(self, "Modo Custom Lenovo", msg)

    def _on_apply_custom_power_sliders(self):
        values = {aid: pair[0].value() for aid, pair in self.custom_power_sliders.items()}
        ok, msg = self.backend.set_lenovo_custom_power_values(values)
        self.refresh_custom_power_state()
        if ok:
            self.custom_power_applied.emit(msg)
        else:
            QMessageBox.warning(self, "Modo Custom Lenovo", msg)

    def _on_vrr_button_clicked(self, policy: str):
        ok, msg = self.backend.set_vrr_policy(policy)
        if ok:
            self.refresh_display_state()
            self.vrr_policy_changed.emit(policy)
        else:
            QMessageBox.warning(self, "VRR / Adaptive Sync", msg)

    def _on_dock_config_changed(self, _val=None):
        prof = str(self.combo_dock_profile.currentData() or "performance")
        self.backend.set_dock_mode_config(
            enabled=self.sw_dock_enabled.isChecked(),
            target_profile=prof,
            keep_max_hz=self.sw_dock_max_hz.isChecked(),
            inhibit_lid_sleep=self.sw_dock_lid_inhibit.isChecked(),
        )
        self.refresh_dock_state()
        self.dock_config_changed.emit()

    def refresh_dock_state(self):
        feat = self.backend.features
        show_dock = bool(feat.external_monitor_dock and (feat.platform_profile or feat.refresh_rate))
        self.dock_card.setVisible(show_dock)
        if not show_dock:
            return
        if hasattr(self, "dock_adv_box"):
            self.dock_adv_box.setVisible(bool(self._advanced_mode))
        mons = self.backend.get_external_monitors()
        if mons:
            self.dock_status_badge.setText(f"{', '.join(mons[:2])} CONECTADO")
            self.dock_status_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)
        else:
            self.dock_status_badge.setText("SEM MONITOR EXTERNO")
            self.dock_status_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.TEXT_WHITE_80)

    def _on_lcd_overdrive_toggled(self, checked: bool):
        ok, msg = self.backend.set_lcd_overdrive(checked)
        if ok:
            self.lcd_overdrive_changed.emit(checked)
        else:
            self.lcd_overdrive_switch.blockSignals(True)
            self.lcd_overdrive_switch.setChecked(not checked)
            self.lcd_overdrive_switch.blockSignals(False)
            QMessageBox.warning(self, "LCD Overdrive", f"Não foi possível alterar o LCD Overdrive:\n{msg}")

    def _build_dynamic_bios_attributes(self):
        while self.bios_dyn_container.count():
            item = self.bios_dyn_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.bios_attr_widgets.clear()
        is_od_supp = self.backend.is_lcd_overdrive_supported()
        self.od_box.setVisible(is_od_supp)

        attrs = self.backend.get_bios_attributes()
        promoted = getattr(self.backend, "PROMOTED_BIOS_ATTR_IDS", frozenset({"lcd_overdrive"}))
        visible_attrs = [a for a in attrs if a.attr_id.lower() not in promoted]
        show_dyn = bool(self._advanced_mode and visible_attrs)
        total_items = (len(visible_attrs) if show_dyn else 0) + (1 if is_od_supp else 0)
        self.bios_count_badge.setText(f"{total_items} {'ITEM' if total_items == 1 else 'ITENS'}")

        if is_od_supp and show_dyn:
            self.bios_title_lbl.setText("LCD Overdrive & Firmware Lenovo (BIOS / WMI)")
            self.bios_sub_lbl.setText("Aceleração do monitor e nós de BIOS descobertos no hardware.")
        elif is_od_supp:
            self.bios_title_lbl.setText("LCD Overdrive • Resposta de Painel")
            self.bios_sub_lbl.setText("Aceleração de tempo de resposta do monitor liberada pela BIOS.")
        else:
            self.bios_title_lbl.setText("Firmware Lenovo (BIOS / WMI)")
            self.bios_sub_lbl.setText("Parâmetros de firmware descobertos dinamicamente na BIOS.")

        self.bios_dyn_widget.setVisible(show_dyn)
        self.bios_card.setVisible(bool(is_od_supp or show_dyn))
        if not visible_attrs:
            return

        apply_btn_style = f"""
            QPushButton {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                color: {ThemeTokens.ACCENT_STEEL};
                border: 1px solid {ThemeTokens.ACCENT_STEEL};
                border-radius: 6px;
                padding: 4px 10px;
                font-weight: 600;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.ACCENT_STEEL};
                color: {ThemeTokens.BG_APP};
            }}
        """

        for a in visible_attrs:
            row_box = QFrame()
            row_box.setProperty("class", "subBox")
            r_layout = QHBoxLayout(row_box)
            r_layout.setContentsMargins(14, 10, 14, 10)

            info_layout = QVBoxLayout()
            h_top = QHBoxLayout()
            title_lbl = QLabel(a.display_name)
            title_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
            title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
            h_top.addWidget(title_lbl)

            cat_badge = StatusBadge(a.category.upper(), bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
            h_top.addWidget(cat_badge)
            h_top.addStretch()
            info_layout.addLayout(h_top)

            desc_lbl = QLabel(f"Atributo sysfs: {a.attr_id} • Tipo: {a.attr_type.capitalize()}")
            desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
            info_layout.addWidget(desc_lbl)
            r_layout.addLayout(info_layout, stretch=2)

            ctrl_layout = QHBoxLayout()
            ctrl_layout.setSpacing(10)

            if a.attr_type == "boolean":
                sw = ToggleSwitch()
                is_on = a.current_value.lower() in ("1", "enabled", "on", "true")
                sw.setChecked(is_on)
                sw.toggled.connect(lambda chk, aid=a.attr_id: self._on_toggle_bios_bool_attribute(aid, chk))
                self.bios_attr_widgets[a.attr_id] = sw
                ctrl_layout.addWidget(sw)

            elif a.attr_type == "integer":
                min_v = a.min_value if a.min_value is not None else 0
                max_v = a.max_value if a.max_value is not None else 100
                cur_v = int(a.current_value) if a.current_value.isdigit() else min_v
                if max_v <= min_v:
                    min_v = 0
                    max_v = max(100, cur_v + 25) if cur_v > 0 else 100

                val_lbl = QLabel(f"{cur_v}")
                val_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
                val_lbl.setStyleSheet(f"color: {ThemeTokens.ACCENT_STEEL}; min-width: 38px; border: none;")

                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(min_v, max_v)
                sl.setValue(cur_v)
                sl.setFixedWidth(130)
                sl.valueChanged.connect(lambda v, lbl=val_lbl: lbl.setText(str(v)))

                btn_apply = QPushButton("Aplicar")
                btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_apply.setStyleSheet(apply_btn_style)
                btn_apply.clicked.connect(lambda _c=False, aid=a.attr_id, s=sl, l=val_lbl: self._on_apply_bios_int_attribute(aid, s, l))

                self.bios_attr_widgets[a.attr_id] = (sl, val_lbl)
                ctrl_layout.addWidget(sl)
                ctrl_layout.addWidget(val_lbl)
                ctrl_layout.addWidget(btn_apply)

            else:
                combo = QComboBox()
                combo.setMinimumWidth(110)
                poss = a.possible_values if a.possible_values else [a.current_value]
                for p in poss:
                    combo.addItem(p)
                idx = combo.findText(a.current_value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

                btn_apply = QPushButton("Aplicar")
                btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_apply.setStyleSheet(apply_btn_style)
                btn_apply.clicked.connect(lambda _c=False, aid=a.attr_id, cmb=combo: self._on_apply_bios_enum_attribute(aid, cmb))

                self.bios_attr_widgets[a.attr_id] = combo
                ctrl_layout.addWidget(combo)
                ctrl_layout.addWidget(btn_apply)

            r_layout.addLayout(ctrl_layout)
            self.bios_dyn_container.addWidget(row_box)

    def _on_apply_bios_int_attribute(self, attr_id: str, slider: QSlider, val_lbl: QLabel):
        val = slider.value()
        ok, msg = self.backend.set_bios_attribute(attr_id, str(val))
        if ok:
            self.refresh_bios_state()
            QMessageBox.information(self, "Ajuste de BIOS Aplicado", f"{attr_id}: {val}\n{msg}")
        else:
            QMessageBox.warning(self, "Falha ao Gravar BIOS", f"{attr_id}:\n{msg}")

    def _on_apply_bios_enum_attribute(self, attr_id: str, combo: QComboBox):
        val = combo.currentText()
        ok, msg = self.backend.set_bios_attribute(attr_id, val)
        if ok:
            self.refresh_bios_state()
            QMessageBox.information(self, "Ajuste de BIOS Aplicado", f"{attr_id}: {val}\n{msg}")
        else:
            QMessageBox.warning(self, "Falha ao Gravar BIOS", f"{attr_id}:\n{msg}")

    def _on_toggle_bios_bool_attribute(self, attr_id: str, checked: bool):
        val = "1" if checked else "0"
        ok, msg = self.backend.set_bios_attribute(attr_id, val)
        if ok:
            self.refresh_bios_state()
        else:
            sw = self.bios_attr_widgets.get(attr_id)
            if sw and isinstance(sw, ToggleSwitch):
                sw.blockSignals(True)
                sw.setChecked(not checked)
                sw.blockSignals(False)
            QMessageBox.warning(self, "Falha ao Gravar BIOS", f"{attr_id}:\n{msg}")

    def refresh_bios_state(self):
        is_od_supp = self.backend.is_lcd_overdrive_supported()
        self.od_box.setVisible(is_od_supp)
        if is_od_supp:
            self.lcd_overdrive_switch.setEnabled(True)
            self.lcd_overdrive_switch.blockSignals(True)
            self.lcd_overdrive_switch.setChecked(self.backend.get_lcd_overdrive())
            self.lcd_overdrive_switch.blockSignals(False)
        show_dyn = bool(self._advanced_mode and self.bios_attr_widgets)
        if hasattr(self, "bios_dyn_widget"):
            self.bios_dyn_widget.setVisible(show_dyn)
        total_items = (len(self.bios_attr_widgets) if show_dyn else 0) + (1 if is_od_supp else 0)
        self.bios_count_badge.setText(f"{total_items} {'ITEM' if total_items == 1 else 'ITENS'}")
        if is_od_supp and show_dyn:
            self.bios_title_lbl.setText("LCD Overdrive & Firmware Lenovo (BIOS / WMI)")
            self.bios_sub_lbl.setText("Aceleração do monitor e nós de BIOS descobertos no hardware.")
        elif is_od_supp:
            self.bios_title_lbl.setText("LCD Overdrive • Resposta de Painel")
            self.bios_sub_lbl.setText("Aceleração de tempo de resposta do monitor liberada pela BIOS.")
        else:
            self.bios_title_lbl.setText("Firmware Lenovo (BIOS / WMI)")
            self.bios_sub_lbl.setText("Parâmetros de firmware descobertos dinamicamente na BIOS.")
        self.bios_card.setVisible(bool(is_od_supp or show_dyn))
