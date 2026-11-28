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
    QPushButton, QScrollArea, QSlider,
    Qt, Signal, QTimer, QFont, QMessageBox, QPixmap
)
from ui.theme_tokens import ThemeTokens
from ui.components import ToggleSwitch, StatusBadge, BasicModeHintBar
from ui.widgets import FanCurveWidget

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")


class PerformanceTab(QWidget):
    """Aba CPU & Térmico: frequência, TDP, curva de ventoinhas, undervolt e perfis ACPI."""
    switch_advanced_requested = Signal()
    cooling_changed = Signal(str, str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._advanced_mode = self.backend.is_advanced_mode()
        self.gov_buttons: Dict[str, QPushButton] = {}
        self.cooling_mode_buttons: Dict[str, QPushButton] = {}
        self._watchdog_seconds = 0
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(1000)
        self._watchdog_timer.timeout.connect(self._on_undervolt_watchdog_tick)

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
        self.cpu_title_lbl.setWordWrap(True)
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
        cpu_sub.setWordWrap(True)
        cpu_sub.setToolTip("Escalonamento Linux (intel_pstate / amd_pstate / cpufreq)")
        cpu_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        cpu_titles.addWidget(cpu_sub)
        cpu_header.addLayout(cpu_titles, stretch=1)

        self.current_badge = StatusBadge("EQUILIBRADO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        self.current_badge.setVisible(feat.platform_profile)
        cpu_header.addWidget(self.current_badge)

        self.cpu_throttle_badge = StatusBadge("SEM THROTTLING", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.STATUS_GREEN)
        self.cpu_throttle_badge.setVisible(feat.thermal_throttling)
        cpu_header.addWidget(self.cpu_throttle_badge)

        self.cpu_freq_badge = StatusBadge("-- MHz", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        cpu_header.addWidget(self.cpu_freq_badge)
        cpu_layout.addLayout(cpu_header)

        self.cpu_basic_summary_lbl = QLabel(
            "Frequência e envelope térmico gerenciados pelo perfil ativo no Dashboard. "
            "No Modo Avançado você pode forçar CPU Turbo Boost e Scaling Governor manualmente."
        )
        self.cpu_basic_summary_lbl.setWordWrap(True)
        self.cpu_basic_summary_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        cpu_layout.addWidget(self.cpu_basic_summary_lbl)

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
        gov_v = QVBoxLayout(self.gov_box)
        gov_v.setContentsMargins(14, 10, 14, 10)
        gov_v.setSpacing(8)

        g_info = QVBoxLayout()
        g_info.setSpacing(2)
        g_lbl = QLabel("CPU Scaling Governor")
        g_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        g_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        g_info.addWidget(g_lbl)

        g_desc = QLabel("Política de escalonamento de frequência de todos os núcleos.")
        g_desc.setWordWrap(True)
        g_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        g_info.addWidget(g_desc)
        gov_v.addLayout(g_info)

        gov_row = QHBoxLayout()
        gov_row.setContentsMargins(0, 0, 0, 0)
        gov_row.setSpacing(8)

        avail_govs = self.backend.get_available_cpu_governors()
        ordered_govs = [g for g in ("powersave", "performance", "schedutil", "ondemand", "conservative") if g in avail_govs]
        for g in avail_govs:
            if g not in ordered_govs:
                ordered_govs.append(g)
        for gov_name in ordered_govs:
            btn = QPushButton(gov_name.upper())
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setMinimumWidth(78)
            btn.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
            btn.clicked.connect(lambda checked, g=gov_name: self._on_governor_selected(g))
            gov_row.addWidget(btn, stretch=1)
            self.gov_buttons[gov_name] = btn
        gov_v.addLayout(gov_row)

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

        has_cooling = self.backend.has_cooling_controls()
        tdp_titles = QVBoxLayout()
        tdp_titles.setSpacing(2)
        if has_cooling and feat.custom_tdp:
            tdp_title_txt = "Ventoinhas & Limites de Potência"
            tdp_sub_txt = (
                "Controle fácil de ventilação em 1 clique + limites de energia e alvos térmicos."
            )
        elif has_cooling:
            tdp_title_txt = "Ventoinhas & Controle Térmico"
            tdp_sub_txt = (
                "Controle fácil em 1 clique da resposta das ventoinhas e alvos térmicos do notebook."
            )
        else:
            tdp_title_txt = "Limites de Potência (TDP)"
            tdp_sub_txt = "Ajuste de potência sustentada (PL1) e pico boost (PL2) da CPU."
        tdp_t = QLabel(tdp_title_txt)
        tdp_t.setToolTip("Controle via Embedded Controller (EC), Lenovo WMI e Intel RAPL")
        tdp_t.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        tdp_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        tdp_titles.addWidget(tdp_t)

        tdp_sub = QLabel(tdp_sub_txt)
        tdp_sub.setWordWrap(True)
        tdp_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        tdp_titles.addWidget(tdp_sub)
        tdp_header.addLayout(tdp_titles, stretch=1)

        self.fan_status_badge = StatusBadge("EC AUTOMÁTICO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        self.fan_status_badge.setVisible(has_cooling)
        tdp_header.addWidget(self.fan_status_badge)

        self.tdp_badge = StatusBadge("PL1: --W | PL2: --W", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.TEXT_WHITE_80)
        self.tdp_badge.setVisible(feat.custom_tdp)
        tdp_header.addWidget(self.tdp_badge)
        tdp_layout.addLayout(tdp_header)

        # Controle Fácil + Curva / Alvos Térmicos das Ventoinhas
        fan_cfg = self.backend.get_custom_fan_curve()
        wmi_bounds = self.backend.get_wmi_thermal_bounds()
        c_lo, c_hi, init_cpu_t = wmi_bounds["cpu_temp"]
        g_lo, g_hi, init_gpu_t = wmi_bounds["gpu_temp"]

        self.fan_ctrl_box = QFrame()
        self.fan_ctrl_box.setProperty("class", "subBox")
        fan_ctrl_layout = QVBoxLayout(self.fan_ctrl_box)
        fan_ctrl_layout.setContentsMargins(14, 12, 14, 12)
        fan_ctrl_layout.setSpacing(10)

        fc_top = QHBoxLayout()
        fc_lbl_v = QVBoxLayout()
        fc_title = QLabel("Modo de Ventilação")
        fc_title.setToolTip("Controle direto via Embedded Controller (EC) / Lenovo WMI")
        fc_title.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        fc_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; border: none;")
        fc_lbl_v.addWidget(fc_title)

        self.lbl_fan_curve_status = QLabel(
            "Escolha em 1 clique como a ventoinha deve se comportar:"
        )
        self.lbl_fan_curve_status.setWordWrap(True)
        self.lbl_fan_curve_status.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        fc_lbl_v.addWidget(self.lbl_fan_curve_status)
        fc_top.addLayout(fc_lbl_v, stretch=1)

        self.sw_custom_fan = ToggleSwitch()
        self.sw_custom_fan.setChecked(bool(fan_cfg.get("enabled", False)))
        self.sw_custom_fan.toggled.connect(self._on_custom_fan_toggled)
        fc_top.addWidget(self.sw_custom_fan)
        fan_ctrl_layout.addLayout(fc_top)

        # Botões fáceis de 1 clique (visíveis tanto no Básico quanto no Avançado)
        quick_cool_row = QHBoxLayout()
        quick_cool_row.setSpacing(8)
        cool_modes = [
            ("quiet", "Silencioso", "Prioriza silêncio e 0 RPM em uso leve"),
            ("auto", "Automático", "Curva equilibrada padrão do notebook"),
            ("cool", "Mais Frio", "Adianta a ventoinha para manter CPU e GPU mais frias"),
            ("max", "Turbo Máximo", "Rotação e refrigeração máximas para jogos pesados"),
        ]
        for cm_id, cm_label, cm_tip in cool_modes:
            btn_cm = QPushButton(cm_label)
            btn_cm.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_cm.setFixedHeight(32)
            btn_cm.setToolTip(cm_tip)
            btn_cm.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
            btn_cm.clicked.connect(lambda _c=False, k=cm_id: self._on_quick_cooling_selected(k))
            quick_cool_row.addWidget(btn_cm, stretch=1)
            self.cooling_mode_buttons[cm_id] = btn_cm
        fan_ctrl_layout.addLayout(quick_cool_row)

        # Controle Manual / Direto (contínuo 25%..100% quando hwmon PWM existir;
        # Boost Direto ~5600 RPM <-> Auto EC em modelos com boost binário via VPC2004/fan_mode)
        manual_cfg = self.backend.get_manual_fan_speed()
        is_bin_boost = bool(feat.fan_control and self.backend.has_binary_fan_boost())
        has_cont_fan = bool(feat.fan_control and not is_bin_boost)
        init_man_pct = max(25, min(100, int(manual_cfg.get("speed_pct", 100) or 100)))
        self.manual_fan_box = QWidget()
        man_v = QVBoxLayout(self.manual_fan_box)
        man_v.setContentsMargins(0, 2, 0, 2)
        man_v.setSpacing(6)

        man_row = QHBoxLayout()
        man_row.setContentsMargins(0, 0, 0, 0)
        man_row.setSpacing(8)

        init_man_txt = (
            f"Velocidade Manual: {init_man_pct}% • Atual: -- RPM"
            if has_cont_fan
            else "Ventoinha EC: Automática • Atual: -- RPM"
        )
        self.lbl_manual_fan = QLabel(init_man_txt)
        self.lbl_manual_fan.setWordWrap(True)
        self.lbl_manual_fan.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.lbl_manual_fan.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 175px; border: none;")
        man_row.addWidget(self.lbl_manual_fan, stretch=0 if has_cont_fan else 1)

        self.slider_manual_fan = QSlider(Qt.Orientation.Horizontal)
        self.slider_manual_fan.setRange(25, 100)
        self.slider_manual_fan.setSingleStep(5)
        self.slider_manual_fan.setPageStep(5)
        self.slider_manual_fan.setValue(init_man_pct)
        self.slider_manual_fan.valueChanged.connect(self._on_manual_fan_slider_changed)
        self.slider_manual_fan.sliderReleased.connect(self._on_manual_fan_apply)
        self.slider_manual_fan.setVisible(has_cont_fan)
        man_row.addWidget(self.slider_manual_fan, stretch=1)

        self.btn_apply_manual_fan = QPushButton("Aplicar")
        self.btn_apply_manual_fan.setProperty("class", "primaryButton")
        self.btn_apply_manual_fan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_manual_fan.setFixedHeight(28)
        self.btn_apply_manual_fan.clicked.connect(self._on_manual_fan_apply)
        self.btn_apply_manual_fan.setVisible(has_cont_fan)
        man_row.addWidget(self.btn_apply_manual_fan)

        self.btn_boost_max_fan = QPushButton("Forçar Turbo (~5600 RPM)")
        self.btn_boost_max_fan.setProperty("class", "primaryButton")
        self.btn_boost_max_fan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_boost_max_fan.setFixedHeight(28)
        self.btn_boost_max_fan.clicked.connect(lambda _c=False: self._on_quick_cooling_selected("max"))
        self.btn_boost_max_fan.setVisible(not has_cont_fan)
        man_row.addWidget(self.btn_boost_max_fan)

        self.btn_auto_manual_fan = QPushButton("Auto EC")
        self.btn_auto_manual_fan.setProperty("class", "secondaryButton")
        self.btn_auto_manual_fan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_auto_manual_fan.setFixedHeight(28)
        self.btn_auto_manual_fan.clicked.connect(lambda _c=False: self._on_quick_cooling_selected("auto"))
        man_row.addWidget(self.btn_auto_manual_fan)
        man_v.addLayout(man_row)

        hint_text = (
            "Proteção térmica automática ativa acima de 78°C."
            if has_cont_fan
            else "Este modelo usa curvas térmicas automáticas do EC no dia a dia + Modo Turbo Máximo (~5600 RPM contínuo via VPC2004)."
        )
        self.lbl_manual_fan_hint = QLabel(hint_text)
        self.lbl_manual_fan_hint.setWordWrap(True)
        self.lbl_manual_fan_hint.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        man_v.addWidget(self.lbl_manual_fan_hint)

        self.manual_fan_box.setVisible(bool(feat.fan_control))
        fan_ctrl_layout.addWidget(self.manual_fan_box)

        self.fan_curve_widget = FanCurveWidget()
        self.fan_curve_widget.set_custom_curve(fan_cfg.get("points", []), bool(fan_cfg.get("enabled", False)))
        self.fan_curve_widget.curve_changed.connect(self._on_fan_curve_points_dragged)
        fan_ctrl_layout.addWidget(self.fan_curve_widget)

        # Alvos térmicos WMI (em quantos °C o EC acelera a ventoinha)
        self.wmi_temp_widget = QWidget()
        wmi_temp_v = QVBoxLayout(self.wmi_temp_widget)
        wmi_temp_v.setContentsMargins(0, 2, 0, 0)
        wmi_temp_v.setSpacing(8)

        wmi_temp_row = QHBoxLayout()
        wmi_temp_row.setContentsMargins(0, 0, 0, 0)
        wmi_temp_row.setSpacing(12)

        self.wmi_cpu_temp_widget = QWidget()
        wmi_cpu_l = QHBoxLayout(self.wmi_cpu_temp_widget)
        wmi_cpu_l.setContentsMargins(0, 0, 0, 0)
        wmi_cpu_l.setSpacing(8)
        self.lbl_wmi_cpu_temp = QLabel(f"Alvo CPU: {init_cpu_t}°C")
        self.lbl_wmi_cpu_temp.setToolTip("Temperatura em que o EC acelera a ventoinha da CPU (quanto menor, mais fresca)")
        self.lbl_wmi_cpu_temp.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.lbl_wmi_cpu_temp.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 110px;")
        wmi_cpu_l.addWidget(self.lbl_wmi_cpu_temp)

        self.slider_wmi_cpu_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_wmi_cpu_temp.setRange(c_lo, c_hi)
        self.slider_wmi_cpu_temp.setValue(init_cpu_t)
        self.slider_wmi_cpu_temp.valueChanged.connect(
            lambda v: self.lbl_wmi_cpu_temp.setText(f"Alvo CPU: {v}°C")
        )
        wmi_cpu_l.addWidget(self.slider_wmi_cpu_temp, stretch=1)
        self.wmi_cpu_temp_widget.setVisible(feat.wmi_cpu_temp)
        wmi_temp_row.addWidget(self.wmi_cpu_temp_widget, stretch=1)

        self.wmi_gpu_temp_widget = QWidget()
        wmi_gpu_l = QHBoxLayout(self.wmi_gpu_temp_widget)
        wmi_gpu_l.setContentsMargins(0, 0, 0, 0)
        wmi_gpu_l.setSpacing(8)
        self.lbl_wmi_gpu_temp = QLabel(f"Alvo GPU: {init_gpu_t}°C")
        self.lbl_wmi_gpu_temp.setToolTip("Temperatura em que o EC acelera a ventoinha da GPU")
        self.lbl_wmi_gpu_temp.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.lbl_wmi_gpu_temp.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 110px;")
        wmi_gpu_l.addWidget(self.lbl_wmi_gpu_temp)

        self.slider_wmi_gpu_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_wmi_gpu_temp.setRange(g_lo, g_hi)
        self.slider_wmi_gpu_temp.setValue(init_gpu_t)
        self.slider_wmi_gpu_temp.valueChanged.connect(
            lambda v: self.lbl_wmi_gpu_temp.setText(f"Alvo GPU: {v}°C")
        )
        wmi_gpu_l.addWidget(self.slider_wmi_gpu_temp, stretch=1)
        self.wmi_gpu_temp_widget.setVisible(feat.wmi_gpu_temp)
        wmi_temp_row.addWidget(self.wmi_gpu_temp_widget, stretch=1)

        wmi_temp_v.addLayout(wmi_temp_row)

        wmi_btn_row = QHBoxLayout()
        wmi_hint = QLabel("Valores menores antecipam a ventoinha no perfil Custom.")
        wmi_hint.setWordWrap(True)
        wmi_hint.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        wmi_btn_row.addWidget(wmi_hint, stretch=1)
        self.btn_apply_wmi_temps = QPushButton("Aplicar Alvos Térmicos")
        self.btn_apply_wmi_temps.setProperty("class", "primaryButton")
        self.btn_apply_wmi_temps.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_wmi_temps.setFixedHeight(28)
        self.btn_apply_wmi_temps.clicked.connect(self._on_apply_wmi_thermal_targets)
        wmi_btn_row.addWidget(self.btn_apply_wmi_temps)
        wmi_temp_v.addLayout(wmi_btn_row)

        self.wmi_temp_widget.setVisible(bool(feat.wmi_cpu_temp or feat.wmi_gpu_temp))
        fan_ctrl_layout.addWidget(self.wmi_temp_widget)

        self.fc_curve_presets_widget = QWidget()
        fc_preset_row = QHBoxLayout(self.fc_curve_presets_widget)
        fc_preset_row.setContentsMargins(0, 0, 0, 0)
        fc_preset_row.setSpacing(8)
        self.btn_fan_passive = None
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
            if p_key == "passive_gaming":
                self.btn_fan_passive = btn_fp
            fc_preset_row.addWidget(btn_fp)

        fc_preset_row.addStretch()

        self.btn_apply_fan_curve = QPushButton("Aplicar Curva no EC")
        self.btn_apply_fan_curve.setProperty("class", "primaryButton")
        self.btn_apply_fan_curve.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_fan_curve.setFixedHeight(30)
        self.btn_apply_fan_curve.clicked.connect(self._on_apply_custom_fan_curve)
        fc_preset_row.addWidget(self.btn_apply_fan_curve)
        fan_ctrl_layout.addWidget(self.fc_curve_presets_widget)

        self.fan_ctrl_box.setVisible(has_cooling)
        tdp_layout.addWidget(self.fan_ctrl_box)

        # Sliders PL1 e PL2 (Intel RAPL)
        init_pl1, init_pl2 = self.backend.get_cpu_tdp_limits()
        self.sliders_box = QFrame()
        self.sliders_box.setProperty("class", "subBox")
        s_layout = QVBoxLayout(self.sliders_box)
        s_layout.setContentsMargins(14, 12, 14, 12)
        s_layout.setSpacing(10)

        rapl_note = QLabel("Limites Imediatos do Processador via Intel RAPL / Powercap:")
        rapl_note.setWordWrap(True)
        rapl_note.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        s_layout.addWidget(rapl_note)

        pl1_row = QHBoxLayout()
        self.lbl_pl1_title = QLabel(f"PL1 • Potência Sustentada: {init_pl1} W")
        self.lbl_pl1_title.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_pl1_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 195px; border: none;")
        pl1_row.addWidget(self.lbl_pl1_title)

        self.slider_pl1 = QSlider(Qt.Orientation.Horizontal)
        self.slider_pl1.setRange(15, 90)
        self.slider_pl1.setValue(init_pl1)
        self.slider_pl1.setEnabled(feat.custom_tdp)
        self.slider_pl1.valueChanged.connect(self._on_pl1_slider_changed)
        pl1_row.addWidget(self.slider_pl1, stretch=1)
        s_layout.addLayout(pl1_row)

        pl2_row = QHBoxLayout()
        self.lbl_pl2_title = QLabel(f"PL2 • Potência de Pico: {init_pl2} W")
        self.lbl_pl2_title.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_pl2_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 195px; border: none;")
        pl2_row.addWidget(self.lbl_pl2_title)

        self.slider_pl2 = QSlider(Qt.Orientation.Horizontal)
        self.slider_pl2.setRange(20, 115)
        self.slider_pl2.setValue(init_pl2)
        self.slider_pl2.setEnabled(feat.custom_tdp)
        self.slider_pl2.valueChanged.connect(self._on_pl2_slider_changed)
        pl2_row.addWidget(self.slider_pl2, stretch=1)
        s_layout.addLayout(pl2_row)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        for label_p, p1, p2 in [
            ("Eco (20/30W)", 20, 30),
            ("Normal (45/65W)", 45, 65),
            ("Game (60/80W)", 60, 80),
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
        self.tdp_card.setVisible(bool(self.backend.has_cooling_controls() or feat.custom_tdp))
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
        uv_t.setWordWrap(True)
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
        uv_sub.setWordWrap(True)
        uv_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        uv_titles.addWidget(uv_sub)
        uv_header.addLayout(uv_titles, stretch=1)

        uv_hw_active = bool(getattr(self.backend, "_undervolt_active_in_hw", False))
        uv_saved_unapplied = bool(has_cpu_uv and (uv_status.core_offset_mv < 0 or uv_status.cache_offset_mv < 0) and not uv_hw_active)

        if has_cpu_uv and not is_amd_uv:
            if uv_saved_unapplied:
                uv_badge_txt = f"SALVO: {uv_status.core_offset_mv} / {uv_status.cache_offset_mv} mV"
            else:
                uv_badge_txt = f"CORE: {uv_status.core_offset_mv} mV | CACHE: {uv_status.cache_offset_mv} mV"
        elif has_cpu_uv:
            uv_badge_txt = (
                f"SALVO: {uv_status.core_offset_mv} mV"
                if uv_saved_unapplied
                else f"CURVE OPT: {uv_status.core_offset_mv} mV"
            )
        else:
            uv_badge_txt = f"GPU OFFSET: +{uv_status.gpu_ac_offset_w} W"
        self.uv_badge = StatusBadge(
            uv_badge_txt,
            bg_color=ThemeTokens.BG_CARD_HOVER,
            text_color=ThemeTokens.COLOR_WARNING if uv_saved_unapplied else ThemeTokens.ACCENT_STEEL,
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
        core_lbl_prefix = "Curve Optimizer (Core)" if is_amd_uv else "Offset Núcleos (Core)"
        self.lbl_uv_core = QLabel(f"{core_lbl_prefix}: {uv_status.core_offset_mv} mV")
        self.lbl_uv_core.setToolTip("MSR Voltage Plane 0 / Curve Optimizer" if is_amd_uv else "Intel MSR Voltage Plane 0")
        self.lbl_uv_core.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_uv_core.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 195px;")
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
        self.lbl_uv_cache = QLabel(f"Offset Cache (Ring): {uv_status.cache_offset_mv} mV")
        self.lbl_uv_cache.setToolTip("Intel MSR Voltage Plane 2 (Ring/Cache)")
        self.lbl_uv_cache.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_uv_cache.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 195px;")
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
        self.lbl_uv_gpu_offset = QLabel(f"Boost Dinâmico WMI GPU: +{uv_status.gpu_ac_offset_w} W")
        self.lbl_uv_gpu_offset.setToolTip("Lenovo WMI GPU / AC Dynamic Offset")
        self.lbl_uv_gpu_offset.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        self.lbl_uv_gpu_offset.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 195px;")
        ac_off_row.addWidget(self.lbl_uv_gpu_offset)

        self.slider_uv_gpu_offset = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_gpu_offset.setRange(10, 30)
        self.slider_uv_gpu_offset.setValue(uv_status.gpu_ac_offset_w)
        self.slider_uv_gpu_offset.valueChanged.connect(self._on_uv_slider_changed)
        ac_off_row.addWidget(self.slider_uv_gpu_offset, stretch=1)
        self.uv_gpu_offset_widget.setVisible(has_gpu_off)
        uv_box_layout.addWidget(self.uv_gpu_offset_widget)

        uv_actions = QHBoxLayout()
        uv_actions.setSpacing(6)
        self._uv_preset_buttons: List[QPushButton] = []
        for uv_lbl, c_mv, ca_mv in [
            ("Padrão (0)", 0, 0),
            ("Leve (-50/-40)", -50, -40),
            ("HX (-80/-60)", -80, -60),
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
        if uv_status.last_emergency_reset:
            init_uv_note = uv_status.last_emergency_reset
        elif uv_saved_unapplied:
            init_uv_note = (
                f"Offsets salvos da última sessão ({uv_status.core_offset_mv} / {uv_status.cache_offset_mv} mV) "
                "ainda não aplicados no hardware — clique em 'Aplicar Offsets' para ativar nesta sessão."
            )
        else:
            init_uv_note = default_uv_note
        self.lbl_uv_status = QLabel(init_uv_note)
        self.lbl_uv_status.setWordWrap(True)
        self.lbl_uv_status.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; border: none;")
        uv_box_layout.addWidget(self.lbl_uv_status)

        uv_layout.addWidget(uv_box)
        self.uv_card.setVisible(bool(has_cpu_uv or has_gpu_off))
        layout.addWidget(self.uv_card)

        # =====================================================================
        # 4. Aviso discreto do Modo Básico (oculto no Modo Avançado)
        # =====================================================================
        self.basic_hint_card = BasicModeHintBar(
            "Modo Básico ativo • Ajuste fino (Turbo Boost, Governor, Curva PWM de 5 pontos, Passivo 0 RPM, PL1/PL2 RAPL e Undervolt) disponível no Modo Avançado."
        )
        self.basic_hint_card.switch_advanced_requested.connect(self.switch_advanced_requested.emit)
        layout.addWidget(self.basic_hint_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.set_advanced_mode(self.backend.is_advanced_mode())
        self.refresh_profile_state()

    def set_advanced_mode(self, advanced: bool):
        """Exibe ou recolhe controles técnicos (Turbo, Governor, Curva PWM, Alvos WMI, PL1/PL2 e Undervolt)."""
        feat = self.backend.features
        has_cool = self.backend.has_cooling_controls()
        is_bin_boost = bool(feat.fan_control and self.backend.has_binary_fan_boost())
        has_cont_fan = bool(feat.fan_control and not is_bin_boost)
        adv = bool(advanced)
        self._advanced_mode = adv

        self.cpu_basic_summary_lbl.setVisible(not adv)
        self.turbo_box.setVisible(bool(adv and feat.turbo_boost))
        self.gov_box.setVisible(bool(adv and feat.cpu_governor and self.gov_buttons))

        self.fan_status_badge.setVisible(has_cool)
        self.tdp_badge.setVisible(bool(adv and feat.custom_tdp))
        self.fan_ctrl_box.setVisible(has_cool)
        self.manual_fan_box.setVisible(bool(feat.fan_control))
        if hasattr(self, "slider_manual_fan"):
            self.slider_manual_fan.setVisible(has_cont_fan)
            self.btn_apply_manual_fan.setVisible(has_cont_fan)
            self.btn_boost_max_fan.setVisible(is_bin_boost)
        self.sw_custom_fan.setVisible(bool(adv and has_cont_fan))
        self.fan_curve_widget.setVisible(bool(adv and has_cont_fan))
        self.fc_curve_presets_widget.setVisible(bool(adv and has_cont_fan))
        self.btn_apply_fan_curve.setVisible(bool(adv and has_cont_fan))
        if getattr(self, "btn_fan_passive", None) is not None:
            self.btn_fan_passive.setVisible(bool(adv and has_cont_fan))
        self.wmi_temp_widget.setVisible(bool(adv and (feat.wmi_cpu_temp or feat.wmi_gpu_temp)))
        self.btn_apply_wmi_temps.setVisible(bool(adv and (feat.wmi_cpu_temp or feat.wmi_gpu_temp)))
        self.sliders_box.setVisible(bool(adv and feat.custom_tdp))
        self.tdp_card.setVisible(bool(has_cool or (adv and feat.custom_tdp)))

        if has_cool:
            if adv and has_cont_fan:
                self.lbl_fan_curve_status.setText("Escolha um modo rápido, defina a velocidade manual ou ajuste a curva PWM.")
            elif adv and (feat.wmi_cpu_temp or feat.wmi_gpu_temp):
                self.lbl_fan_curve_status.setText("Escolha um modo rápido 1-clique ou ajuste os alvos térmicos WMI do EC.")
            else:
                self.lbl_fan_curve_status.setText("Escolha em 1 clique como a ventoinha deve se comportar:")

        has_cpu_uv = feat.cpu_undervolt
        has_gpu_off = feat.wmi_gpu_ac_offset
        self.uv_card.setVisible(bool(adv and (has_cpu_uv or has_gpu_off)))
        self.basic_hint_card.setVisible(not adv)

    # =========================================================================
    # Métodos de Ventilação Rápida, Alvos WMI e Curva PWM (EC)
    # =========================================================================
    def _on_quick_cooling_selected(self, preset_id: str):
        ok, msg = self.backend.apply_cooling_preset(preset_id)
        self.lbl_fan_curve_status.setText(msg)
        if ok:
            if self.backend.features.fan_control:
                curve_on = bool(self.backend.get_custom_fan_curve().get("enabled", False))
                self.sw_custom_fan.blockSignals(True)
                self.sw_custom_fan.setChecked(curve_on)
                self.sw_custom_fan.blockSignals(False)
                if preset_id == "max":
                    self.slider_manual_fan.blockSignals(True)
                    self.slider_manual_fan.setValue(100)
                    self.slider_manual_fan.blockSignals(False)
            self.refresh_profile_state()
            self.cooling_changed.emit(preset_id, msg)
        else:
            QMessageBox.warning(self, "Controle de Ventoinhas", msg)

    def _on_manual_fan_slider_changed(self, pct: int):
        rpm_txt = f"{self._last_live_rpm} RPM" if getattr(self, "_last_live_rpm", 0) > 0 else "-- RPM"
        self.lbl_manual_fan.setText(f"Velocidade Manual: {pct}% • Atual: {rpm_txt}")

    def _on_manual_fan_apply(self):
        pct = self.slider_manual_fan.value()
        ok, msg = self.backend.set_manual_fan_speed(True, pct)
        self.lbl_fan_curve_status.setText(msg)
        if ok:
            self.sw_custom_fan.blockSignals(True)
            self.sw_custom_fan.setChecked(False)
            self.sw_custom_fan.blockSignals(False)
            self.refresh_profile_state()
            self.cooling_changed.emit("max" if pct >= 90 else "custom", msg)
        else:
            QMessageBox.warning(self, "Velocidade Manual da Ventoinha", msg)

    def _on_apply_wmi_thermal_targets(self):
        cpu_lim = self.slider_wmi_cpu_temp.value()
        gpu_lim = self.slider_wmi_gpu_temp.value()
        ok, msg = self.backend.apply_wmi_thermal_targets(cpu_lim, gpu_lim)
        self.lbl_fan_curve_status.setText(msg)
        if ok:
            self.refresh_profile_state()
            self.cooling_changed.emit("custom", msg)
        else:
            QMessageBox.warning(self, "Alvos Térmicos WMI", msg)
    def _on_custom_fan_toggled(self, checked: bool):
        pts = self.fan_curve_widget.get_custom_points()
        self.fan_curve_widget.set_custom_curve(pts, checked)
        self._on_apply_custom_fan_curve()

    def _on_fan_curve_points_dragged(self, new_points: List[List[int]]):
        if not self.sw_custom_fan.isChecked():
            self.sw_custom_fan.blockSignals(True)
            self.sw_custom_fan.setChecked(True)
            self.sw_custom_fan.blockSignals(False)
        cpu_lim = self.slider_wmi_cpu_temp.value()
        gpu_lim = self.slider_wmi_gpu_temp.value()
        _, msg = self.backend.set_custom_fan_curve(new_points, True, cpu_lim, gpu_lim)
        self.lbl_fan_curve_status.setText(msg)
        self.refresh_profile_state()

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
            self.lbl_uv_core.setText(f"Curve Optimizer (Core): {core_mv} mV")
        else:
            hex_core = hex(self.backend._encode_intel_msr_undervolt_offset(0, core_mv))
            self.lbl_uv_core.setText(f"Offset Núcleos (Core): {core_mv} mV")
            self.lbl_uv_core.setToolTip(f"Intel MSR Voltage Plane 0 ({hex_core})")
        self.lbl_uv_cache.setText(f"Offset Cache (Ring): {cache_mv} mV")
        self.lbl_uv_gpu_offset.setText(f"Boost Dinâmico WMI GPU: +{gpu_w} W")

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
            self.uv_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)
        elif feat.cpu_undervolt:
            self.uv_badge.setText(f"CURVE OPT: {core_mv} mV")
            self.uv_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)
        elif gpu_w is not None:
            self.uv_badge.setText(f"GPU OFFSET: +{gpu_w} W")
            self.uv_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)

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
        uv_st = self.backend.get_undervolt_status()
        self.slider_uv_core.blockSignals(True)
        self.slider_uv_core.setValue(0)
        self.slider_uv_core.blockSignals(False)
        self.slider_uv_cache.blockSignals(True)
        self.slider_uv_cache.setValue(0)
        self.slider_uv_cache.blockSignals(False)
        self.slider_uv_gpu_offset.blockSignals(True)
        self.slider_uv_gpu_offset.setValue(uv_st.gpu_ac_offset_w)
        self.slider_uv_gpu_offset.blockSignals(False)
        self._on_uv_slider_changed()
        if self.backend.features.cpu_undervolt:
            self.uv_badge.setText(
                "CURVE OPT: 0 mV" if self.backend.get_cpu_vendor() == "AMD" else "CORE: 0 mV | CACHE: 0 mV"
            )
        else:
            self.uv_badge.setText(f"GPU OFFSET: +{uv_st.gpu_ac_offset_w} W")
        self.lbl_uv_status.setText(msg)

    def refresh_from_settings(self):
        """Sincroniza sliders, curva, limites WMI e switches após restauração de fábrica."""
        self._watchdog_timer.stop()
        self.uv_watchdog_frame.setVisible(False)

        fan_cfg = self.backend.get_custom_fan_curve()
        self.sw_custom_fan.blockSignals(True)
        self.sw_custom_fan.setChecked(bool(fan_cfg.get("enabled", False)))
        self.sw_custom_fan.blockSignals(False)
        self.fan_curve_widget.set_custom_curve(fan_cfg.get("points", []), bool(fan_cfg.get("enabled", False)))

        wmi_bounds = self.backend.get_wmi_thermal_bounds()
        self.slider_wmi_cpu_temp.blockSignals(True)
        self.slider_wmi_cpu_temp.setValue(wmi_bounds["cpu_temp"][2])
        self.slider_wmi_cpu_temp.blockSignals(False)
        self.lbl_wmi_cpu_temp.setText(f"Alvo CPU: {wmi_bounds['cpu_temp'][2]}°C")

        self.slider_wmi_gpu_temp.blockSignals(True)
        self.slider_wmi_gpu_temp.setValue(wmi_bounds["gpu_temp"][2])
        self.slider_wmi_gpu_temp.blockSignals(False)
        self.lbl_wmi_gpu_temp.setText(f"Alvo GPU: {wmi_bounds['gpu_temp'][2]}°C")

        man_cfg = self.backend.get_manual_fan_speed()
        self.slider_manual_fan.blockSignals(True)
        self.slider_manual_fan.setValue(max(25, min(100, int(man_cfg.get("speed_pct", 100) or 100))))
        self.slider_manual_fan.blockSignals(False)

        pl1, pl2 = self.backend.get_cpu_tdp_limits()
        self.slider_pl1.blockSignals(True)
        self.slider_pl1.setValue(pl1)
        self.slider_pl1.blockSignals(False)
        self.lbl_pl1_title.setText(f"PL1 • Potência Sustentada: {pl1} W")
        self.slider_pl2.blockSignals(True)
        self.slider_pl2.setValue(pl2)
        self.slider_pl2.blockSignals(False)
        self.lbl_pl2_title.setText(f"PL2 • Potência de Pico: {pl2} W")

        uv_st = self.backend.get_undervolt_status()
        self.slider_uv_core.blockSignals(True)
        self.slider_uv_core.setValue(uv_st.core_offset_mv)
        self.slider_uv_core.blockSignals(False)
        self.slider_uv_cache.blockSignals(True)
        self.slider_uv_cache.setValue(uv_st.cache_offset_mv)
        self.slider_uv_cache.blockSignals(False)
        self.slider_uv_gpu_offset.blockSignals(True)
        self.slider_uv_gpu_offset.setValue(uv_st.gpu_ac_offset_w)
        self.slider_uv_gpu_offset.blockSignals(False)
        self._on_uv_slider_changed()
        if self.backend.features.cpu_undervolt:
            self.uv_badge.setText(
                f"CURVE OPT: {uv_st.core_offset_mv} mV"
                if self.backend.get_cpu_vendor() == "AMD"
                else f"CORE: {uv_st.core_offset_mv} mV | CACHE: {uv_st.cache_offset_mv} mV"
            )
        else:
            self.uv_badge.setText(f"GPU OFFSET: +{uv_st.gpu_ac_offset_w} W")

        self.set_advanced_mode(self.backend.is_advanced_mode())
        self.refresh_profile_state()

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
        self.lbl_pl2_title.setText(f"PL2 • Potência de Pico: {val} W")

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

        self._last_live_rpm = int(fan.rpm or 0)
        is_bin_boost = self.backend.has_binary_fan_boost()
        if hasattr(self, "lbl_manual_fan"):
            rpm_live = f"{fan.rpm} RPM" if fan.rpm > 0 else ("~5600 RPM" if fan.ec_fan_mode == 3 else "-- RPM")
            if not is_bin_boost:
                man_pct = self.slider_manual_fan.value()
                self.lbl_manual_fan.setText(f"Velocidade Manual: {man_pct}% • Atual: {rpm_live}")
            else:
                mode_str = "Turbo Máximo Contínuo" if (bool(self.backend.settings.get("manual_fan_enabled", False)) or fan.ec_fan_mode == 3) else "Automática (EC)"
                self.lbl_manual_fan.setText(f"Ventoinha EC: {mode_str} • {rpm_live}")

        if hasattr(self, "fan_status_badge"):
            if fan.rpm > 0 and fan.second_rpm > 0:
                self.fan_status_badge.setText(f"{fan.rpm} / {fan.second_rpm} RPM • {cpu.temperature_c:.0f}°C")
            elif fan.rpm > 0:
                self.fan_status_badge.setText(f"{fan.rpm} RPM • {cpu.temperature_c:.0f}°C")
            elif fan.ec_fan_mode == 3 and self.backend.features.fan_control:
                self.fan_status_badge.setText(f"TURBO 5600 RPM • {cpu.temperature_c:.0f}°C")
            else:
                self.fan_status_badge.setText(f"EC ATIVO • {cpu.temperature_c:.0f}°C")

        active_cool = self.backend.get_active_cooling_preset()
        cool_accent_map = {
            "quiet": ThemeTokens.THERMAL_QUIET,
            "auto": ThemeTokens.THERMAL_BALANCED,
            "cool": ThemeTokens.BORDER_CYAN,
            "max": ThemeTokens.ACCENT_STEEL,
        }
        for cid, cbtn in self.cooling_mode_buttons.items():
            is_c_active = (cid == active_cool)
            c_acc = cool_accent_map.get(cid, ThemeTokens.ACCENT_STEEL)
            if is_c_active:
                cbtn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BG_CARD_ACTIVE};
                        color: {ThemeTokens.TEXT_WHITE_100};
                        border: 1.5px solid {c_acc};
                        border-radius: 6px;
                        padding: 0px 8px;
                    }}
                """)
            else:
                cbtn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BG_CARD_HOVER};
                        color: {ThemeTokens.TEXT_LIGHT_GRAY};
                        border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                        border-radius: 6px;
                        padding: 0px 8px;
                    }}
                    QPushButton:hover {{
                        border-color: {c_acc};
                        color: {ThemeTokens.TEXT_WHITE_100};
                    }}
                """)

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
