"""
Aba CPU & Térmico do Ducksvantage (ui/tabs/performance_tab.py) — Estilo 3.
Focada exclusivamente em:
1. Controles Avançados de CPU (Turbo Boost + Scaling Governor)
2. Editor Interativo de Curva de Ventoinhas (EC) & Limites TDP (PL1/PL2)
3. Overclock / Undervolt Dinâmico com Watchdog de Segurança (15s)
4. Perfis Térmicos ACPI (Silencioso, Equilibrado, Desempenho, Max-Power)
"""

import os
from typing import Dict, List
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QSlider, QProgressBar,
    Qt, QTimer, Signal, QFont, QMessageBox, QPixmap
)
from ui.theme_tokens import ThemeTokens
from ui.components import ProfileCard, ToggleSwitch, StatusBadge
from ui.widgets import GpuModeBlock, FanCurveWidget, KeyCaptureButton  # Re-export compatível

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")


class PerformanceTab(QWidget):
    """Aba CPU & Térmico: frequência, TDP, curva de ventoinhas, undervolt e perfis ACPI."""
    profile_changed = Signal(str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.cards: Dict[str, ProfileCard] = {}
        self.gov_buttons: Dict[str, QPushButton] = {}
        self._watchdog_seconds = 0
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(1000)
        self._watchdog_timer.timeout.connect(self._on_undervolt_watchdog_tick)

        self._checkup_timer = QTimer(self)
        self._checkup_timer.setInterval(500)
        self._checkup_timer.timeout.connect(self._on_checkup_tick)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)

        feat = self.backend.features
        chip_btn_style = f"""
            QPushButton {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                color: {ThemeTokens.TEXT_WHITE_80};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {ThemeTokens.ACCENT_STEEL};
                color: {ThemeTokens.TEXT_WHITE_100};
            }}
        """

        # =====================================================================
        # 1. Controles Avançados da CPU (Turbo Boost + Scaling Governor)
        # =====================================================================
        self.cpu_card = QFrame()
        self.cpu_card.setProperty("class", "card")
        cpu_layout = QVBoxLayout(self.cpu_card)
        cpu_layout.setContentsMargins(18, 16, 18, 16)
        cpu_layout.setSpacing(12)

        cpu_header = QHBoxLayout()
        ic_cpu = QLabel()
        p_cpu = os.path.join(ICON_DIR, "turbo.svg")
        if os.path.exists(p_cpu):
            ic_cpu.setPixmap(QPixmap(p_cpu).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        cpu_header.addWidget(ic_cpu)

        cpu_titles = QVBoxLayout()
        cpu_titles.setSpacing(2)
        self.cpu_title_lbl = QLabel(f"Processador • {self.backend.system_info.cpu_model}")
        self.cpu_title_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        self.cpu_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        cpu_titles.addWidget(self.cpu_title_lbl)

        if feat.turbo_boost and feat.cpu_governor:
            cpu_sub_txt = "Controle de boost de frequência do processador."
        elif feat.turbo_boost:
            cpu_sub_txt = "Controle direto do Turbo Boost do processador."
        else:
            cpu_sub_txt = "Seleção de desempenho e economia de frequência da CPU."
        cpu_sub = QLabel(cpu_sub_txt)
        cpu_sub.setToolTip("Escalonamento Linux (intel_pstate / amd_pstate / cpufreq)")
        cpu_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        cpu_titles.addWidget(cpu_sub)
        cpu_header.addLayout(cpu_titles)
        cpu_header.addStretch()

        self.current_badge = StatusBadge("EQUILIBRADO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        self.current_badge.setVisible(feat.platform_profile)
        cpu_header.addWidget(self.current_badge)

        self.cpu_throttle_badge = StatusBadge("SEM THROTTLING", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.STATUS_GREEN)
        self.cpu_throttle_badge.setVisible(feat.thermal_throttling)
        cpu_header.addWidget(self.cpu_throttle_badge)

        self.cpu_freq_badge = StatusBadge("-- MHz", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        cpu_header.addWidget(self.cpu_freq_badge)
        cpu_layout.addLayout(cpu_header)

        # Turbo Boost
        self.turbo_box = QFrame()
        self.turbo_box.setProperty("class", "subBox")
        turbo_row = QHBoxLayout(self.turbo_box)
        turbo_row.setContentsMargins(14, 10, 14, 10)

        t_info = QVBoxLayout()
        t_lbl = QLabel("CPU Turbo Boost")
        t_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        t_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        t_info.addWidget(t_lbl)

        self.turbo_desc_lbl = QLabel("Permite frequências máximas acima do clock base.")
        self.turbo_desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        t_info.addWidget(self.turbo_desc_lbl)
        turbo_row.addLayout(t_info)
        turbo_row.addStretch()

        self.turbo_switch = ToggleSwitch()
        self.turbo_switch.setEnabled(feat.turbo_boost)
        self.turbo_switch.toggled.connect(self._on_turbo_toggled)
        turbo_row.addWidget(self.turbo_switch)
        self.turbo_box.setVisible(feat.turbo_boost)
        cpu_layout.addWidget(self.turbo_box)

        # CPU Scaling Governor
        self.gov_box = QFrame()
        self.gov_box.setProperty("class", "subBox")
        gov_row = QHBoxLayout(self.gov_box)
        gov_row.setContentsMargins(14, 10, 14, 10)

        g_info = QVBoxLayout()
        g_lbl = QLabel("CPU Scaling Governor")
        g_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        g_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        g_info.addWidget(g_lbl)

        g_desc = QLabel("Política de escalonamento de frequência de todos os núcleos.")
        g_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        g_info.addWidget(g_desc)
        gov_row.addLayout(g_info)
        gov_row.addStretch()

        avail_govs = self.backend.get_available_cpu_governors()
        ordered_govs = [g for g in ("powersave", "performance", "schedutil", "ondemand", "conservative") if g in avail_govs]
        for g in avail_govs:
            if g not in ordered_govs:
                ordered_govs.append(g)
        for gov_name in ordered_govs:
            btn = QPushButton(gov_name.upper())
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setMinimumWidth(108)
            btn.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
            btn.clicked.connect(lambda checked, g=gov_name: self._on_governor_selected(g))
            gov_row.addWidget(btn)
            self.gov_buttons[gov_name] = btn

        self.gov_box.setVisible(bool(feat.cpu_governor and self.gov_buttons))
        cpu_layout.addWidget(self.gov_box)
        self.cpu_card.setVisible(bool(feat.platform_profile or feat.turbo_boost or (feat.cpu_governor and self.gov_buttons)))
        layout.addWidget(self.cpu_card)

        # =====================================================================
        # 2. Editor de Curva de Ventoinhas (EC) + Limites TDP (PL1/PL2)
        # =====================================================================
        self.tdp_card = QFrame()
        self.tdp_card.setProperty("class", "card")
        tdp_layout = QVBoxLayout(self.tdp_card)
        tdp_layout.setContentsMargins(18, 16, 18, 16)
        tdp_layout.setSpacing(12)

        tdp_header = QHBoxLayout()
        ic_tdp = QLabel()
        p_tdp = os.path.join(ICON_DIR, "fan_curve.svg")
        if not os.path.exists(p_tdp):
            p_tdp = os.path.join(ICON_DIR, "mode_custom.svg")
        if os.path.exists(p_tdp):
            ic_tdp.setPixmap(QPixmap(p_tdp).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        tdp_header.addWidget(ic_tdp)

        tdp_titles = QVBoxLayout()
        tdp_titles.setSpacing(2)
        if feat.fan_control and feat.custom_tdp:
            tdp_title_txt = "Ventoinhas & Limites de Potência"
            tdp_sub_txt = "Arraste os pontos de controle (°C vs %) e ajuste os limites de energia da CPU."
        elif feat.fan_control:
            tdp_title_txt = "Curva de Ventoinhas"
            tdp_sub_txt = "Arraste os pontos (°C vs %) para ajustar a velocidade das ventoinhas."
        else:
            tdp_title_txt = "Limites de Potência (TDP)"
            tdp_sub_txt = "Ajuste de potência sustentada (PL1) e pico boost (PL2) da CPU."
        tdp_t = QLabel(tdp_title_txt)
        tdp_t.setToolTip("Controle via Embedded Controller (EC) e Intel RAPL")
        tdp_t.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        tdp_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        tdp_titles.addWidget(tdp_t)

        tdp_sub = QLabel(tdp_sub_txt)
        tdp_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        tdp_titles.addWidget(tdp_sub)
        tdp_header.addLayout(tdp_titles)
        tdp_header.addStretch()

        self.tdp_badge = StatusBadge("PL1: --W | PL2: --W", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.TEXT_WHITE_80)
        self.tdp_badge.setVisible(feat.custom_tdp)
        tdp_header.addWidget(self.tdp_badge)
        tdp_layout.addLayout(tdp_header)

        # Curva de Ventoinhas no EC
        fan_cfg = self.backend.get_custom_fan_curve()
        self.fan_ctrl_box = QFrame()
        self.fan_ctrl_box.setProperty("class", "subBox")
        fan_ctrl_layout = QVBoxLayout(self.fan_ctrl_box)
        fan_ctrl_layout.setContentsMargins(14, 12, 14, 12)
        fan_ctrl_layout.setSpacing(10)

        fc_top = QHBoxLayout()
        fc_lbl_v = QVBoxLayout()
        fc_title = QLabel("Curva de Rotação das Ventoinhas")
        fc_title.setToolTip("Controle direto via Embedded Controller (EC)")
        fc_title.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        fc_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        fc_lbl_v.addWidget(fc_title)

        self.lbl_fan_curve_status = QLabel(
            "Arraste os pontos ou selecione um preset térmico abaixo."
        )
        self.lbl_fan_curve_status.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        fc_lbl_v.addWidget(self.lbl_fan_curve_status)
        fc_top.addLayout(fc_lbl_v)
        fc_top.addStretch()

        self.sw_custom_fan = ToggleSwitch()
        self.sw_custom_fan.setChecked(bool(fan_cfg.get("enabled", False)))
        self.sw_custom_fan.toggled.connect(self._on_custom_fan_toggled)
        fc_top.addWidget(self.sw_custom_fan)
        fan_ctrl_layout.addLayout(fc_top)

        self.fan_curve_widget = FanCurveWidget()
        self.fan_curve_widget.set_custom_curve(fan_cfg.get("points", []), bool(fan_cfg.get("enabled", False)))
        self.fan_curve_widget.curve_changed.connect(self._on_fan_curve_points_dragged)
        fan_ctrl_layout.addWidget(self.fan_curve_widget)

        # Alvos térmicos WMI
        self.wmi_temp_widget = QWidget()
        wmi_temp_row = QHBoxLayout(self.wmi_temp_widget)
        wmi_temp_row.setContentsMargins(0, 0, 0, 0)
        wmi_temp_row.setSpacing(16)

        init_cpu_t = int(fan_cfg.get("cpu_temp_limit", 94))
        init_gpu_t = int(fan_cfg.get("gpu_temp_limit", 87))

        self.wmi_cpu_temp_widget = QWidget()
        wmi_cpu_l = QHBoxLayout(self.wmi_cpu_temp_widget)
        wmi_cpu_l.setContentsMargins(0, 0, 0, 0)
        wmi_cpu_l.setSpacing(8)
        self.lbl_wmi_cpu_temp = QLabel(f"Limite Térmico CPU: {init_cpu_t}°C")
        self.lbl_wmi_cpu_temp.setToolTip("Alvo térmico WMI configurado no firmware")
        self.lbl_wmi_cpu_temp.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.lbl_wmi_cpu_temp.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 155px;")
        wmi_cpu_l.addWidget(self.lbl_wmi_cpu_temp)

        self.slider_wmi_cpu_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_wmi_cpu_temp.setRange(85, 100)
        self.slider_wmi_cpu_temp.setValue(init_cpu_t)
        self.slider_wmi_cpu_temp.valueChanged.connect(
            lambda v: self.lbl_wmi_cpu_temp.setText(f"Limite Térmico CPU: {v}°C")
        )
        wmi_cpu_l.addWidget(self.slider_wmi_cpu_temp, stretch=1)
        self.wmi_cpu_temp_widget.setVisible(feat.wmi_cpu_temp)
        wmi_temp_row.addWidget(self.wmi_cpu_temp_widget, stretch=1)

        self.wmi_gpu_temp_widget = QWidget()
        wmi_gpu_l = QHBoxLayout(self.wmi_gpu_temp_widget)
        wmi_gpu_l.setContentsMargins(0, 0, 0, 0)
        wmi_gpu_l.setSpacing(8)
        self.lbl_wmi_gpu_temp = QLabel(f"Limite Térmico GPU: {init_gpu_t}°C")
        self.lbl_wmi_gpu_temp.setToolTip("Alvo térmico WMI configurado no firmware")
        self.lbl_wmi_gpu_temp.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.lbl_wmi_gpu_temp.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 155px;")
        wmi_gpu_l.addWidget(self.lbl_wmi_gpu_temp)

        self.slider_wmi_gpu_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_wmi_gpu_temp.setRange(75, 87)
        self.slider_wmi_gpu_temp.setValue(init_gpu_t)
        self.slider_wmi_gpu_temp.valueChanged.connect(
            lambda v: self.lbl_wmi_gpu_temp.setText(f"Limite Térmico GPU: {v}°C")
        )
        wmi_gpu_l.addWidget(self.slider_wmi_gpu_temp, stretch=1)
        self.wmi_gpu_temp_widget.setVisible(feat.wmi_gpu_temp)
        wmi_temp_row.addWidget(self.wmi_gpu_temp_widget, stretch=1)

        self.wmi_temp_widget.setVisible(bool(feat.wmi_cpu_temp or feat.wmi_gpu_temp))
        fan_ctrl_layout.addWidget(self.wmi_temp_widget)

        fc_preset_row = QHBoxLayout()
        fc_preset_row.setSpacing(8)
        for p_key, p_title in [
            ("passive_gaming", "Passivo 0 RPM"),
            ("silent", "Silencioso"),
            ("balanced", "Equilibrado EC"),
            ("aggressive", "Rampa 100%"),
        ]:
            btn_fp = QPushButton(p_title)
            btn_fp.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_fp.setFixedHeight(28)
            btn_fp.setStyleSheet(chip_btn_style)
            btn_fp.clicked.connect(lambda _c, k=p_key: self._apply_fan_curve_preset(k))
            fc_preset_row.addWidget(btn_fp)

        fc_preset_row.addStretch()

        self.btn_apply_fan_curve = QPushButton("Aplicar Curva no EC")
        self.btn_apply_fan_curve.setProperty("class", "primaryButton")
        self.btn_apply_fan_curve.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_fan_curve.setFixedHeight(30)
        self.btn_apply_fan_curve.clicked.connect(self._on_apply_custom_fan_curve)
        fc_preset_row.addWidget(self.btn_apply_fan_curve)
        fan_ctrl_layout.addLayout(fc_preset_row)

        self.fan_ctrl_box.setVisible(feat.fan_control)
        tdp_layout.addWidget(self.fan_ctrl_box)

        # Sliders PL1 e PL2 (Intel RAPL)
        init_pl1, init_pl2 = self.backend.get_cpu_tdp_limits()
        self.sliders_box = QFrame()
        self.sliders_box.setProperty("class", "subBox")
        s_layout = QVBoxLayout(self.sliders_box)
        s_layout.setContentsMargins(14, 12, 14, 12)
        s_layout.setSpacing(10)

        pl1_row = QHBoxLayout()
        self.lbl_pl1_title = QLabel(f"PL1 • Potência Sustentada: {init_pl1} W")
        self.lbl_pl1_title.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_pl1_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 240px; border: none;")
        pl1_row.addWidget(self.lbl_pl1_title)

        self.slider_pl1 = QSlider(Qt.Orientation.Horizontal)
        self.slider_pl1.setRange(15, 90)
        self.slider_pl1.setValue(init_pl1)
        self.slider_pl1.setEnabled(feat.custom_tdp)
        self.slider_pl1.valueChanged.connect(self._on_pl1_slider_changed)
        pl1_row.addWidget(self.slider_pl1, stretch=1)
        s_layout.addLayout(pl1_row)

        pl2_row = QHBoxLayout()
        self.lbl_pl2_title = QLabel(f"PL2 • Potência de Pico Boost: {init_pl2} W")
        self.lbl_pl2_title.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_pl2_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 240px; border: none;")
        pl2_row.addWidget(self.lbl_pl2_title)

        self.slider_pl2 = QSlider(Qt.Orientation.Horizontal)
        self.slider_pl2.setRange(20, 115)
        self.slider_pl2.setValue(init_pl2)
        self.slider_pl2.setEnabled(feat.custom_tdp)
        self.slider_pl2.valueChanged.connect(self._on_pl2_slider_changed)
        pl2_row.addWidget(self.slider_pl2, stretch=1)
        s_layout.addLayout(pl2_row)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        for label_p, p1, p2 in [
            ("Silencioso (20W / 30W)", 20, 30),
            ("Equilibrado (45W / 65W)", 45, 65),
            ("Gaming (60W / 80W)", 60, 80),
        ]:
            b_pre = QPushButton(label_p)
            b_pre.setCursor(Qt.CursorShape.PointingHandCursor)
            b_pre.setFixedHeight(28)
            b_pre.setStyleSheet(chip_btn_style)
            b_pre.clicked.connect(lambda checked, a=p1, b=p2: self._set_tdp_sliders(a, b))
            preset_row.addWidget(b_pre)

        preset_row.addStretch()

        self.btn_apply_tdp = QPushButton("Aplicar Limites TDP")
        self.btn_apply_tdp.setProperty("class", "primaryButton")
        self.btn_apply_tdp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_tdp.setFixedHeight(30)
        self.btn_apply_tdp.setEnabled(feat.custom_tdp)
        self.btn_apply_tdp.clicked.connect(self._on_apply_tdp)
        preset_row.addWidget(self.btn_apply_tdp)
        s_layout.addLayout(preset_row)

        self.sliders_box.setVisible(feat.custom_tdp)
        tdp_layout.addWidget(self.sliders_box)
        self.tdp_card.setVisible(bool(feat.fan_control or feat.custom_tdp))
        layout.addWidget(self.tdp_card)

        # =====================================================================
        # 3. Undervolt & Boost Dinâmico de Tensão/Potência
        # =====================================================================
        uv_status = self.backend.get_undervolt_status()
        has_cpu_uv = feat.cpu_undervolt
        has_gpu_off = feat.wmi_gpu_ac_offset
        is_amd_uv = (uv_status.cpu_vendor == "AMD")

        self.uv_card = QFrame()
        self.uv_card.setProperty("class", "card")
        uv_layout = QVBoxLayout(self.uv_card)
        uv_layout.setContentsMargins(18, 16, 18, 16)
        uv_layout.setSpacing(12)

        uv_header = QHBoxLayout()
        ic_uv = QLabel()
        p_uv = os.path.join(ICON_DIR, "undervolt.svg")
        if os.path.exists(p_uv):
            ic_uv.setPixmap(QPixmap(p_uv).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        uv_header.addWidget(ic_uv)

        uv_titles = QVBoxLayout()
        uv_titles.setSpacing(2)
        uv_title_txt = (
            f"Undervolt Dinâmico • {uv_status.method}"
            if has_cpu_uv
            else "Boost Dinâmico GPU (Lenovo WMI)"
        )
        uv_t = QLabel(uv_title_txt)
        uv_t.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        uv_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        uv_titles.addWidget(uv_t)

        uv_sub_txt = (
            "Offsets negativos com Watchdog de estabilidade de 15s"
            + (" e Boost AC WMI." if has_gpu_off else ".")
            if has_cpu_uv
            else "Offset dinâmico de potência da GPU NVIDIA via Lenovo WMI."
        )
        uv_sub = QLabel(uv_sub_txt)
        uv_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        uv_titles.addWidget(uv_sub)
        uv_header.addLayout(uv_titles)
        uv_header.addStretch()

        if has_cpu_uv and not is_amd_uv:
            uv_badge_txt = f"CORE: {uv_status.core_offset_mv} mV | CACHE: {uv_status.cache_offset_mv} mV"
        elif has_cpu_uv:
            uv_badge_txt = f"CURVE OPT: {uv_status.core_offset_mv} mV"
        else:
            uv_badge_txt = f"GPU OFFSET: +{uv_status.gpu_ac_offset_w} W"
        self.uv_badge = StatusBadge(
            uv_badge_txt,
            bg_color=ThemeTokens.BG_CARD_HOVER,
            text_color=ThemeTokens.ACCENT_STEEL,
        )
        uv_header.addWidget(self.uv_badge)
        uv_layout.addLayout(uv_header)

        # Watchdog banner
        self.uv_watchdog_frame = QFrame()
        self.uv_watchdog_frame.setStyleSheet(
            f"background-color: #292015; border: 1px solid {ThemeTokens.COLOR_WARNING}; border-radius: 8px; padding: 8px 12px;"
        )
        wd_row = QHBoxLayout(self.uv_watchdog_frame)
        self.lbl_uv_watchdog = QLabel(
            "Teste de Estabilidade (15s): confirme estabilidade ou as tensões voltarão para 0 mV."
        )
        self.lbl_uv_watchdog.setWordWrap(True)
        self.lbl_uv_watchdog.setStyleSheet("color: #fde68a; font-weight: 600; font-size: 11px; border: none;")
        wd_row.addWidget(self.lbl_uv_watchdog, stretch=1)

        self.btn_confirm_uv = QPushButton("Confirmar Estabilidade")
        self.btn_confirm_uv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm_uv.setFixedHeight(28)
        self.btn_confirm_uv.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.STATUS_GREEN};
                color: {ThemeTokens.BG_APP};
                border: none;
                border-radius: 5px;
                padding: 3px 12px;
                font-weight: 600;
                font-size: 10px;
            }}
        """)
        self.btn_confirm_uv.clicked.connect(self._on_confirm_undervolt)
        wd_row.addWidget(self.btn_confirm_uv)
        self.uv_watchdog_frame.setVisible(False)
        uv_layout.addWidget(self.uv_watchdog_frame)

        uv_box = QFrame()
        uv_box.setProperty("class", "subBox")
        uv_box_layout = QVBoxLayout(uv_box)
        uv_box_layout.setContentsMargins(14, 12, 14, 12)
        uv_box_layout.setSpacing(10)

        # Core Offset
        self.uv_core_row_widget = QWidget()
        core_row = QHBoxLayout(self.uv_core_row_widget)
        core_row.setContentsMargins(0, 0, 0, 0)
        core_lbl_prefix = "Offset Curve Optimizer (Núcleos)" if is_amd_uv else "Offset de Tensão dos Núcleos (Core)"
        self.lbl_uv_core = QLabel(f"{core_lbl_prefix}: {uv_status.core_offset_mv} mV")
        self.lbl_uv_core.setToolTip("MSR Voltage Plane 0 / Curve Optimizer" if is_amd_uv else "Intel MSR Voltage Plane 0")
        self.lbl_uv_core.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_uv_core.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 270px;")
        core_row.addWidget(self.lbl_uv_core)

        self.slider_uv_core = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_core.setRange(-150, 0)
        self.slider_uv_core.setValue(uv_status.core_offset_mv)
        self.slider_uv_core.valueChanged.connect(self._on_uv_slider_changed)
        core_row.addWidget(self.slider_uv_core, stretch=1)
        self.uv_core_row_widget.setVisible(has_cpu_uv)
        uv_box_layout.addWidget(self.uv_core_row_widget)

        # Cache Offset (Intel)
        self.uv_cache_row_widget = QWidget()
        cache_row = QHBoxLayout(self.uv_cache_row_widget)
        cache_row.setContentsMargins(0, 0, 0, 0)
        self.lbl_uv_cache = QLabel(f"Offset de Tensão do Cache (Ring): {uv_status.cache_offset_mv} mV")
        self.lbl_uv_cache.setToolTip("Intel MSR Voltage Plane 2 (Ring/Cache)")
        self.lbl_uv_cache.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_uv_cache.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 270px;")
        cache_row.addWidget(self.lbl_uv_cache)

        self.slider_uv_cache = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_cache.setRange(-150, 0)
        self.slider_uv_cache.setValue(uv_status.cache_offset_mv)
        self.slider_uv_cache.valueChanged.connect(self._on_uv_slider_changed)
        cache_row.addWidget(self.slider_uv_cache, stretch=1)
        self.uv_cache_row_widget.setVisible(bool(has_cpu_uv and not is_amd_uv))
        uv_box_layout.addWidget(self.uv_cache_row_widget)

        # GPU AC Offset
        self.uv_gpu_offset_widget = QWidget()
        ac_off_row = QHBoxLayout(self.uv_gpu_offset_widget)
        ac_off_row.setContentsMargins(0, 0, 0, 0)
        self.lbl_uv_gpu_offset = QLabel(f"Boost Dinâmico de Potência GPU: +{uv_status.gpu_ac_offset_w} W")
        self.lbl_uv_gpu_offset.setToolTip("Lenovo WMI GPU / AC Dynamic Offset")
        self.lbl_uv_gpu_offset.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_uv_gpu_offset.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 270px;")
        ac_off_row.addWidget(self.lbl_uv_gpu_offset)

        self.slider_uv_gpu_offset = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_gpu_offset.setRange(10, 30)
        self.slider_uv_gpu_offset.setValue(uv_status.gpu_ac_offset_w)
        self.slider_uv_gpu_offset.valueChanged.connect(self._on_uv_slider_changed)
        ac_off_row.addWidget(self.slider_uv_gpu_offset, stretch=1)
        self.uv_gpu_offset_widget.setVisible(has_gpu_off)
        uv_box_layout.addWidget(self.uv_gpu_offset_widget)

        uv_actions = QHBoxLayout()
        uv_actions.setSpacing(8)
        self._uv_preset_buttons: List[QPushButton] = []
        for uv_lbl, c_mv, ca_mv in [
            ("Padrão (0 mV)", 0, 0),
            ("Leve (-50 / -40 mV)", -50, -40),
            ("Otimizado HX (-80 / -60 mV)", -80, -60),
        ]:
            b_uvp = QPushButton(uv_lbl)
            b_uvp.setCursor(Qt.CursorShape.PointingHandCursor)
            b_uvp.setFixedHeight(28)
            b_uvp.setStyleSheet(chip_btn_style)
            b_uvp.clicked.connect(lambda _c, cm=c_mv, cam=ca_mv: self._set_uv_sliders(cm, cam))
            b_uvp.setVisible(has_cpu_uv)
            self._uv_preset_buttons.append(b_uvp)
            uv_actions.addWidget(b_uvp)

        uv_actions.addStretch()

        self.btn_emergency_reset_uv = QPushButton("Reset 0 mV")
        self.btn_emergency_reset_uv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_emergency_reset_uv.setFixedHeight(30)
        self.btn_emergency_reset_uv.setStyleSheet(f"""
            QPushButton {{
                background-color: #2f1a1c;
                color: #fca5a5;
                border: 1px solid {ThemeTokens.LEGION_RED};
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.LEGION_RED};
                color: {ThemeTokens.TEXT_WHITE_100};
            }}
        """)
        self.btn_emergency_reset_uv.clicked.connect(self._on_emergency_reset_undervolt)
        self.btn_emergency_reset_uv.setVisible(has_cpu_uv)
        uv_actions.addWidget(self.btn_emergency_reset_uv)

        self.btn_apply_uv = QPushButton("Aplicar Offsets" if has_cpu_uv else "Aplicar Offset WMI")
        self.btn_apply_uv.setProperty("class", "primaryButton")
        self.btn_apply_uv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_uv.setFixedHeight(30)
        self.btn_apply_uv.clicked.connect(self._on_apply_undervolt)
        uv_actions.addWidget(self.btn_apply_uv)
        uv_box_layout.addLayout(uv_actions)

        default_uv_note = (
            "Limite seguro [-150 mV, 0 mV]. Em caso de travamento, o Watchdog restaura 0 mV no boot."
            if has_cpu_uv
            else "Ajusta gpu_nv_ac_offset dentro dos limites da BIOS (10W a 30W)."
        )
        self.lbl_uv_status = QLabel(
            uv_status.last_emergency_reset if uv_status.last_emergency_reset else default_uv_note
        )
        self.lbl_uv_status.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        uv_box_layout.addWidget(self.lbl_uv_status)

        uv_layout.addWidget(uv_box)
        self.uv_card.setVisible(bool(has_cpu_uv or has_gpu_off))
        layout.addWidget(self.uv_card)

        # =====================================================================
        # 3.5 Checkup Térmico Rápido (20s Baseline das Ventoinhas & Pasta Térmica)
        # =====================================================================
        self.checkup_card = QFrame()
        self.checkup_card.setProperty("class", "card")
        chk_layout = QVBoxLayout(self.checkup_card)
        chk_layout.setContentsMargins(18, 16, 18, 16)
        chk_layout.setSpacing(10)

        chk_header = QHBoxLayout()
        chk_titles = QVBoxLayout()
        chk_titles.setSpacing(2)
        chk_t = QLabel("Checkup Térmico Rápido (Baseline de Ventoinhas & Pasta)")
        chk_t.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        chk_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        chk_titles.addWidget(chk_t)

        chk_sub = QLabel(
            "Executa carga controlada de 20s para comparar Temperatura × Consumo (W) × RPM contra a baseline do notebook."
        )
        chk_sub.setWordWrap(True)
        chk_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        chk_titles.addWidget(chk_sub)
        chk_header.addLayout(chk_titles, stretch=1)

        self.checkup_badge = StatusBadge("PRONTO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        chk_header.addWidget(self.checkup_badge)

        self.btn_start_checkup = QPushButton("Iniciar Checkup (20s)")
        self.btn_start_checkup.setProperty("class", "primaryButton")
        self.btn_start_checkup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_checkup.setFixedHeight(30)
        self.btn_start_checkup.clicked.connect(self._on_toggle_thermal_checkup)
        chk_header.addWidget(self.btn_start_checkup)
        chk_layout.addLayout(chk_header)

        self.checkup_progress = QProgressBar()
        self.checkup_progress.setRange(0, 100)
        self.checkup_progress.setValue(0)
        self.checkup_progress.setFixedHeight(8)
        self.checkup_progress.setTextVisible(False)
        self.checkup_progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {ThemeTokens.BG_SURFACE_DEEP};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {ThemeTokens.ACCENT_STEEL};
                border-radius: 3px;
            }}
        """)
        self.checkup_progress.setVisible(False)
        chk_layout.addWidget(self.checkup_progress)

        chk_foot = QHBoxLayout()
        self.lbl_checkup_status = QLabel("Nenhuma medição salva ainda.")
        self.lbl_checkup_status.setWordWrap(True)
        self.lbl_checkup_status.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        chk_foot.addWidget(self.lbl_checkup_status, stretch=1)

        self.btn_clear_checkup = QPushButton("Limpar Histórico")
        self.btn_clear_checkup.setProperty("class", "secondaryButton")
        self.btn_clear_checkup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_checkup.setFixedHeight(26)
        self.btn_clear_checkup.clicked.connect(self._on_clear_checkup_history)
        chk_foot.addWidget(self.btn_clear_checkup)
        chk_layout.addLayout(chk_foot)

        has_checkup = any((feat.platform_profile, feat.turbo_boost, feat.cpu_governor, feat.fan_control))
        self.checkup_card.setVisible(bool(has_checkup))
        layout.addWidget(self.checkup_card)
        self._refresh_checkup_summary()

        # =====================================================================
        # 4. Aviso discreto do Modo Básico (oculto no Modo Avançado)
        # =====================================================================
        self.basic_hint_card = QFrame()
        self.basic_hint_card.setProperty("class", "subBox")
        bh_lay = QHBoxLayout(self.basic_hint_card)
        bh_lay.setContentsMargins(16, 12, 16, 12)
        bh_lbl = QLabel(
            "Modo Básico ativo • Alterne para 'Avançado' no final da barra lateral para acessar "
            "Limites de Potência (PL1/PL2), Undervolt, Governor manual e Checkup Térmico."
        )
        bh_lbl.setWordWrap(True)
        bh_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        bh_lay.addWidget(bh_lbl, stretch=1)
        layout.addWidget(self.basic_hint_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.set_advanced_mode(self.backend.is_advanced_mode())
        self.refresh_profile_state()

    def set_advanced_mode(self, advanced: bool):
        """Exibe ou recolhe controles avançados (Governor, PL1/PL2, Alvos WMI, Undervolt e Checkup)."""
        feat = self.backend.features
        adv = bool(advanced)
        self.gov_box.setVisible(bool(adv and feat.cpu_governor and self.gov_buttons))
        self.wmi_temp_widget.setVisible(bool(adv and (feat.wmi_cpu_temp or feat.wmi_gpu_temp)))
        self.sliders_box.setVisible(bool(adv and feat.custom_tdp))
        self.tdp_card.setVisible(bool(feat.fan_control or (adv and feat.custom_tdp)))
        has_cpu_uv = feat.cpu_undervolt
        has_gpu_off = feat.wmi_gpu_ac_offset
        self.uv_card.setVisible(bool(adv and (has_cpu_uv or has_gpu_off)))
        has_checkup = any((feat.platform_profile, feat.turbo_boost, feat.cpu_governor, feat.fan_control))
        self.checkup_card.setVisible(bool(adv and has_checkup))
        self.basic_hint_card.setVisible(not adv)

    # =========================================================================
    # Métodos da Curva de Ventoinhas (EC)
    # =========================================================================
    def _on_custom_fan_toggled(self, checked: bool):
        pts = self.fan_curve_widget.get_custom_points()
        self.fan_curve_widget.set_custom_curve(pts, checked)
        self._on_apply_custom_fan_curve()

    def _on_fan_curve_points_dragged(self, new_points: List[List[int]]):
        if not self.sw_custom_fan.isChecked():
            self.sw_custom_fan.blockSignals(True)
            self.sw_custom_fan.setChecked(True)
            self.sw_custom_fan.blockSignals(False)
        self.lbl_fan_curve_status.setText(
            "Curva editada: "
            + " | ".join(f"{t}°C:{p}%" for t, p in new_points)
            + " (Clique em 'Aplicar Curva no EC')"
        )

    def _apply_fan_curve_preset(self, preset_key: str):
        presets = self.backend.get_fan_curve_presets()
        pts = presets.get(preset_key)
        if not pts:
            return
        self.sw_custom_fan.blockSignals(True)
        self.sw_custom_fan.setChecked(True)
        self.sw_custom_fan.blockSignals(False)
        self.fan_curve_widget.set_custom_curve(pts, True)
        self._on_apply_custom_fan_curve()

    def _on_apply_custom_fan_curve(self):
        pts = self.fan_curve_widget.get_custom_points()
        enabled = self.sw_custom_fan.isChecked()
        cpu_lim = self.slider_wmi_cpu_temp.value()
        gpu_lim = self.slider_wmi_gpu_temp.value()
        _, msg = self.backend.set_custom_fan_curve(pts, enabled, cpu_lim, gpu_lim)
        self.lbl_fan_curve_status.setText(msg)
        self.refresh_profile_state()

    # =========================================================================
    # Métodos de Undervolt & Watchdog
    # =========================================================================
    def _on_uv_slider_changed(self, _val: int = 0):
        core_mv = self.slider_uv_core.value()
        cache_mv = self.slider_uv_cache.value()
        gpu_w = self.slider_uv_gpu_offset.value()
        if self.backend.get_cpu_vendor() == "AMD":
            self.lbl_uv_core.setText(f"Offset Curve Optimizer (Núcleos): {core_mv} mV")
        else:
            hex_core = hex(self.backend._encode_intel_msr_undervolt_offset(0, core_mv))
            self.lbl_uv_core.setText(f"Offset de Tensão dos Núcleos (Core): {core_mv} mV")
            self.lbl_uv_core.setToolTip(f"Intel MSR Voltage Plane 0 ({hex_core})")
        self.lbl_uv_cache.setText(f"Offset de Tensão do Cache (Ring): {cache_mv} mV")
        self.lbl_uv_gpu_offset.setText(f"Boost Dinâmico de Potência GPU: +{gpu_w} W")

    def _set_uv_sliders(self, core_mv: int, cache_mv: int):
        self.slider_uv_core.setValue(core_mv)
        self.slider_uv_cache.setValue(cache_mv)

    def _on_apply_undervolt(self):
        feat = self.backend.features
        core_mv = self.slider_uv_core.value() if feat.cpu_undervolt else 0
        cache_mv = (
            self.slider_uv_cache.value()
            if (feat.cpu_undervolt and self.backend.get_cpu_vendor() != "AMD")
            else 0
        )
        gpu_w = self.slider_uv_gpu_offset.value() if feat.wmi_gpu_ac_offset else None
        ok, msg = self.backend.apply_undervolt_offsets(core_mv, cache_mv, gpu_w)
        self.lbl_uv_status.setText(msg)

        if not ok:
            self._watchdog_timer.stop()
            self.uv_watchdog_frame.setVisible(False)
            if feat.cpu_undervolt:
                self.uv_badge.setText(
                    "CURVE OPT: 0 mV" if self.backend.get_cpu_vendor() == "AMD" else "CORE: 0 mV | CACHE: 0 mV"
                )
            return

        if feat.cpu_undervolt and self.backend.get_cpu_vendor() != "AMD":
            self.uv_badge.setText(f"CORE: {core_mv} mV | CACHE: {cache_mv} mV")
        elif feat.cpu_undervolt:
            self.uv_badge.setText(f"CURVE OPT: {core_mv} mV")
        elif gpu_w is not None:
            self.uv_badge.setText(f"GPU OFFSET: +{gpu_w} W")

        if feat.cpu_undervolt and (core_mv < 0 or cache_mv < 0):
            self._watchdog_seconds = 15
            self.uv_watchdog_frame.setVisible(True)
            self.lbl_uv_watchdog.setText(
                f"Teste de Estabilidade ({self._watchdog_seconds}s): confirme abaixo ou as tensões voltarão para 0 mV."
            )
            self._watchdog_timer.start()
        else:
            self._watchdog_timer.stop()
            self.uv_watchdog_frame.setVisible(False)

    def _on_undervolt_watchdog_tick(self):
        self._watchdog_seconds -= 1
        if self._watchdog_seconds <= 0:
            self._watchdog_timer.stop()
            self._on_emergency_reset_undervolt(reason="Tempo limite do Watchdog (15s) expirado")
            return
        self.lbl_uv_watchdog.setText(
            f"Teste de Estabilidade ({self._watchdog_seconds}s): confirme abaixo ou as tensões voltarão para 0 mV."
        )

    def _on_confirm_undervolt(self):
        self._watchdog_timer.stop()
        self.uv_watchdog_frame.setVisible(False)
        _, msg = self.backend.confirm_undervolt_stability()
        self.lbl_uv_status.setText(msg)

    def _on_emergency_reset_undervolt(self, _checked: bool = False, reason: str = "Reset manual"):
        self._watchdog_timer.stop()
        self.uv_watchdog_frame.setVisible(False)
        _, msg = self.backend.emergency_reset_undervolt(reason=reason)
        self.slider_uv_core.setValue(0)
        self.slider_uv_cache.setValue(0)
        self.slider_uv_gpu_offset.setValue(20)
        self.uv_badge.setText("CORE: 0 mV | CACHE: 0 mV")
        self.lbl_uv_status.setText(msg)

    # =========================================================================
    # Métodos de TDP, Governor, Turbo e Perfis ACPI
    # =========================================================================
    def _on_pl1_slider_changed(self, val: int):
        self.lbl_pl1_title.setText(f"PL1 • Potência Sustentada: {val} W")
        if self.slider_pl2.value() < val:
            self.slider_pl2.setValue(val)

    def _on_pl2_slider_changed(self, val: int):
        if val < self.slider_pl1.value():
            val = self.slider_pl1.value()
            self.slider_pl2.setValue(val)
        self.lbl_pl2_title.setText(f"PL2 • Potência de Pico Boost: {val} W")

    def _set_tdp_sliders(self, pl1: int, pl2: int):
        self.slider_pl1.setValue(pl1)
        self.slider_pl2.setValue(pl2)
        self._on_apply_tdp()

    def _on_apply_tdp(self):
        pl1 = self.slider_pl1.value()
        pl2 = self.slider_pl2.value()
        ok, msg = self.backend.set_cpu_tdp_limits(pl1, pl2)
        if not ok:
            QMessageBox.warning(
                self, "Permissão Necessária",
                f"Não foi possível aplicar os limites TDP (PL1={pl1}W / PL2={pl2}W):\n{msg}",
            )
        else:
            self.refresh_profile_state()

    def _on_turbo_toggled(self, enabled: bool):
        ok, msg = self.backend.set_cpu_turbo(enabled)
        if not ok:
            self.turbo_switch.blockSignals(True)
            self.turbo_switch.setChecked(not enabled)
            self.turbo_switch.blockSignals(False)
            QMessageBox.warning(self, "Permissão Necessária", msg)
        else:
            self.refresh_profile_state()

    def _on_governor_selected(self, gov: str):
        ok, msg = self.backend.set_cpu_governor(gov)
        if not ok:
            QMessageBox.warning(self, "Permissão Necessária", msg)
        else:
            self.refresh_profile_state()

    def refresh_profile_state(self):
        """Atualiza os estados de CPU, TDP, Curva de Ventoinhas e Perfis Térmicos ACPI."""
        cpu = self.backend.get_cpu_metrics()
        fan = self.backend.get_fan_metrics()
        active_prof = self.backend.normalize_profile(self.backend.get_platform_profile())

        self.cpu_freq_badge.setText(f"{cpu.frequency_mhz:.0f} MHz • {cpu.temperature_c:.0f}°C")
        if self.backend.features.thermal_throttling and hasattr(self, "cpu_throttle_badge"):
            thr = self.backend.get_throttling_status()
            self.cpu_throttle_badge.setText(thr["badge"])
            sev = thr.get("severity", "ok")
            t_col = ThemeTokens.STATUS_DANGER if sev == "thermal" else (
                ThemeTokens.STATUS_WARNING if sev == "power" else ThemeTokens.STATUS_GREEN
            )
            self.cpu_throttle_badge.setColor(ThemeTokens.BG_CARD_HOVER, t_col)
            self.cpu_throttle_badge.setToolTip("\n".join(thr["reasons"]) if thr["reasons"] else "Sem throttling ativo")
        self.turbo_switch.blockSignals(True)
        self.turbo_switch.setChecked(cpu.turbo_enabled)
        self.turbo_switch.blockSignals(False)

        self.tdp_badge.setText(f"PL1: {cpu.pl1_w}W | PL2: {cpu.pl2_w}W")
        self.fan_curve_widget.update_state(active_prof, cpu.temperature_c, fan.rpm, fan.second_rpm)

        for gname, btn in self.gov_buttons.items():
            is_active = (gname == cpu.governor)
            if is_active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BG_CARD_ACTIVE};
                        color: {ThemeTokens.TEXT_WHITE_100};
                        border: 1.5px solid {ThemeTokens.ACCENT_STEEL};
                        border-radius: 6px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BG_CARD_HOVER};
                        color: {ThemeTokens.TEXT_LIGHT_GRAY};
                        border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        border-color: {ThemeTokens.ACCENT_STEEL};
                        color: {ThemeTokens.TEXT_WHITE_100};
                    }}
                """)

        badge_bg = ThemeTokens.BG_CARD_HOVER
        if active_prof == "max-power":
            self.current_badge.setText("MAX-POWER")
            self.current_badge.setColor(badge_bg, ThemeTokens.ACCENT_STEEL)
        elif active_prof == "custom":
            self.current_badge.setText("CUSTOM")
            self.current_badge.setColor(badge_bg, ThemeTokens.THERMAL_CUSTOM)
        elif active_prof == "performance":
            self.current_badge.setText("DESEMPENHO")
            self.current_badge.setColor(badge_bg, ThemeTokens.THERMAL_PERFORMANCE)
        elif active_prof in ("low-power", "quiet"):
            self.current_badge.setText("SILENCIOSO")
            self.current_badge.setColor(badge_bg, ThemeTokens.THERMAL_QUIET)
        else:
            self.current_badge.setText("EQUILIBRADO")
            self.current_badge.setColor(badge_bg, ThemeTokens.THERMAL_BALANCED)

    # =========================================================================
    # Métodos do Checkup Térmico Rápido (Baseline 20s)
    # =========================================================================
    def _refresh_checkup_summary(self):
        if not hasattr(self, "lbl_checkup_status"):
            return
        hist = self.backend.get_thermal_checkup_history()
        self.btn_clear_checkup.setVisible(bool(hist))
        if not hist:
            self.checkup_badge.setText("PRONTO")
            self.checkup_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)
            self.lbl_checkup_status.setText("Nenhuma baseline registrada. Clique em 'Iniciar Checkup (20s)' com o notebook na tomada.")
            return
        base = hist[0]
        last = hist[-1]
        verdict = str(last.get("verdict", "OK"))
        v_col = ThemeTokens.STATUS_GREEN if ("SAUDÁVEL" in verdict or "BASELINE" in verdict) else (
            ThemeTokens.STATUS_WARNING if "ATENÇÃO" in verdict else ThemeTokens.STATUS_DANGER
        )
        self.checkup_badge.setText(verdict)
        self.checkup_badge.setColor(ThemeTokens.BG_CARD_HOVER, v_col)
        delta_s = f" ({last.get('delta_vs_baseline_c', 0):+.1f}°C vs baseline)" if len(hist) > 1 else " (Baseline inicial)"
        rpm_s = f" • {last['max_fan_rpm']} RPM" if last.get("max_fan_rpm", 0) > 0 else ""
        self.lbl_checkup_status.setText(
            f"Último ({last['timestamp']}): Pico {last['peak_temp_c']:.1f}°C | Média {last['avg_temp_c']:.1f}°C | "
            f"{last['avg_power_w']:.1f}W{rpm_s}{delta_s}  •  Baseline ({base['timestamp']}): {base['peak_temp_c']:.1f}°C."
        )

    def _on_toggle_thermal_checkup(self):
        if self._checkup_timer.isActive():
            self._checkup_timer.stop()
            self.backend.cancel_thermal_checkup()
            self.btn_start_checkup.setText("Iniciar Checkup (20s)")
            self.checkup_progress.setVisible(False)
            self._refresh_checkup_summary()
            return

        ok, msg = self.backend.start_thermal_checkup(duration_sec=20, spawn_load=True)
        if not ok:
            QMessageBox.warning(self, "Checkup Térmico", msg)
            return
        self.btn_start_checkup.setText("Cancelar Checkup")
        self.checkup_progress.setValue(2)
        self.checkup_progress.setVisible(True)
        self.checkup_badge.setText("EM ANDAMENTO")
        self.checkup_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_WARNING)
        self.lbl_checkup_status.setText(msg)
        self._checkup_timer.start()

    def _on_checkup_tick(self):
        st = self.backend.poll_thermal_checkup()
        if not st.get("running") and not st.get("completed"):
            self._checkup_timer.stop()
            self.btn_start_checkup.setText("Iniciar Checkup (20s)")
            self.checkup_progress.setVisible(False)
            return

        self.checkup_progress.setValue(int(st.get("progress_pct", 0)))
        if st.get("completed"):
            self._checkup_timer.stop()
            self.btn_start_checkup.setText("Iniciar Checkup (20s)")
            self.checkup_progress.setVisible(False)
            self._refresh_checkup_summary()
            QMessageBox.information(self, "Checkup Térmico Concluído", st.get("summary", "Checkup finalizado."))
            return

        rpm_txt = f" | {st['max_fan_rpm']} RPM" if st.get("max_fan_rpm", 0) > 0 else ""
        self.lbl_checkup_status.setText(
            f"Medindo ({st['elapsed_sec']:.0f}/{st['duration_sec']}s): Atual {st['current_temp_c']:.1f}°C | "
            f"Pico {st['peak_temp_c']:.1f}°C | {st['avg_power_w']:.1f}W{rpm_txt}"
        )

    def _on_clear_checkup_history(self):
        self.backend.clear_thermal_checkup_history()
        self._refresh_checkup_summary()
