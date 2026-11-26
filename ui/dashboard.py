"""
Dashboard Principal do Ducksvantage (ui/dashboard.py) — Estilo 3 (Vantage Refinado).
Layout assimétrico 65% Esquerda / 35% Direita em paleta grafite/obsidiana fosca:
- Esquerda (65%): 3 Gauges Circulares finos + Seletor compacto de Modo Térmico
  + Card de Histórico Térmico (2 min) com barra de status inline limpa.
- Direita (35%): Painel único EDGE (LEGION / LOQ / LENOVO EDGE) em lista com divisores finos 1px
  (sem caixas aninhadas dentro de caixas).
"""

import os
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QScrollArea, QPushButton, Qt, QFont,
    Signal, QSizePolicy
)
from ui.theme_tokens import ThemeTokens
from ui.gauges import HardwareGaugesCard
from ui.components import ToggleSwitch, StatusBadge
from ui.widgets import LiveThermalChart


class ThermalBlock(QFrame):
    """Cartão compacto de seleção de modo térmico (Estilo 3)."""
    clicked = Signal(str)

    def __init__(self, mode_id: str, title: str, subtitle: str, icon_file: str, accent_color: str, parent=None):
        super().__init__(parent)
        self.mode_id = mode_id
        self.accent_color = accent_color
        self.is_active = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(2)

        # Mantido para compatibilidade sem poluir visualmente
        self.badge = QLabel("ATIVO")
        self.badge.setVisible(False)

        self.title_lbl = QLabel(title)
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        layout.addWidget(self.title_lbl)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_lbl.setWordWrap(True)
        self.sub_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 8))
        layout.addWidget(self.sub_lbl)

        self.update_style()

    def set_active(self, active: bool):
        self.is_active = active
        self.badge.setVisible(False)
        self.update_style()

    def update_style(self):
        if self.is_active:
            self.setStyleSheet(f"""
                ThermalBlock {{
                    background-color: {ThemeTokens.BG_CARD_ACTIVE};
                    border: 1.5px solid {self.accent_color};
                    border-radius: 7px;
                }}
            """)
            self.title_lbl.setStyleSheet(f"color: {self.accent_color}; background: transparent;")
            self.sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_80}; background: transparent;")
        else:
            self.setStyleSheet(f"""
                ThermalBlock {{
                    background-color: {ThemeTokens.BG_HEADER};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 7px;
                }}
                ThermalBlock:hover {{
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                    border-color: {ThemeTokens.BORDER_HOVER};
                }}
            """)
            self.title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; background: transparent;")
            self.sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; background: transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mode_id)
        super().mousePressEvent(event)


class EdgeControlItem(QFrame):
    """Linha limpa de controle do painel EDGE com divisor inferior sutil (sem mini-card aninhado)."""
    toggled = Signal(bool)

    def __init__(self, icon_file: str, title: str, subtitle: str, supported: bool = True, parent=None):
        super().__init__(parent)
        self.supported = supported
        self._default_sub = subtitle
        self.setStyleSheet(f"""
            EdgeControlItem {{
                background-color: transparent;
                border: none;
                border-bottom: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 0px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 9, 2, 9)
        layout.setSpacing(10)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)

        self.t_label = QLabel(title)
        self.t_label.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.Medium))
        self.t_label.setStyleSheet(
            f"color: {ThemeTokens.TEXT_WHITE_100 if supported else ThemeTokens.TEXT_WHITE_40}; background: transparent;"
        )
        text_layout.addWidget(self.t_label)

        self.sub_label = QLabel(subtitle if supported else "Não suportado")
        self.sub_label.setFont(QFont(ThemeTokens.FONT_NAME, 8))
        self.sub_label.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_40}; background: transparent;")
        self.sub_label.setVisible(False)
        text_layout.addWidget(self.sub_label)

        layout.addLayout(text_layout, stretch=1)

        self.switch = ToggleSwitch()
        self.switch.setEnabled(supported)
        self.switch.toggled.connect(self.toggled.emit)
        layout.addWidget(self.switch)

    def set_checked(self, checked: bool):
        if self.switch.isChecked() != checked:
            self.switch.blockSignals(True)
            self.switch.setChecked(checked)
            self.switch.blockSignals(False)

    def set_subtitle(self, text: str, highlight_color: str = ""):
        self.sub_label.setText(text)
        if highlight_color:
            self.sub_label.setStyleSheet(f"color: {highlight_color}; background: transparent;")
            self.sub_label.setVisible(True)
        else:
            self.sub_label.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_40}; background: transparent;")
            self.sub_label.setVisible(False)


class KeyboardBacklightEdgeItem(QFrame):
    """Linha limpa inline para o brilho do teclado (Desl | Baixo | Alto) sem caixa aninhada."""
    level_requested = Signal(int)

    def __init__(self, supported: bool = True, max_level: int = 2, parent=None):
        super().__init__(parent)
        self.supported = supported
        self.max_level = max(1, int(max_level))
        self.current_level = 0

        self.setStyleSheet("""
            KeyboardBacklightEdgeItem {
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 9, 2, 4)
        layout.setSpacing(8)

        title = QLabel("Luz do Teclado")
        title.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.Medium))
        title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; background: transparent;")
        layout.addWidget(title)
        layout.addStretch()

        pill_frame = QFrame()
        pill_frame.setObjectName("kbdPillFrame")
        pill_frame.setStyleSheet(f"""
            QFrame#kbdPillFrame {{
                background-color: {ThemeTokens.BG_SURFACE_DEEP};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
            }}
        """)
        btn_row = QHBoxLayout(pill_frame)
        btn_row.setContentsMargins(2, 2, 2, 2)
        btn_row.setSpacing(2)

        self.buttons = []
        if self.max_level == 1:
            labels = [("Desl", 0), ("Lig", 1)]
        elif self.max_level == 2:
            labels = [("Desl", 0), ("Baixo", 1), ("Alto", 2)]
        else:
            mid = max(1, self.max_level // 2)
            labels = [("Desl", 0), ("Baixo", 1), ("Méd", mid), ("Alto", self.max_level)]

        for text, lvl in labels:
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor if supported else Qt.CursorShape.ArrowCursor)
            btn.setEnabled(supported)
            btn.setFixedHeight(22)
            btn.setFont(QFont(ThemeTokens.FONT_NAME, 8, QFont.Weight.DemiBold))
            btn.clicked.connect(lambda checked, l=lvl: self.level_requested.emit(l))
            btn_row.addWidget(btn)
            self.buttons.append((btn, lvl))

        layout.addWidget(pill_frame)
        self.set_level(0)

    def set_level(self, level: int):
        self.current_level = level
        for btn, lvl in self.buttons:
            is_sel = (lvl == level) and self.supported
            if is_sel:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BG_CARD_ACTIVE};
                        color: {ThemeTokens.TEXT_WHITE_100};
                        border: 1px solid {ThemeTokens.ACCENT_STEEL};
                        border-radius: 4px;
                        padding: 0px 8px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {ThemeTokens.TEXT_LIGHT_GRAY if self.supported else ThemeTokens.TEXT_WHITE_40};
                        border: none;
                        border-radius: 4px;
                        padding: 0px 8px;
                    }}
                    QPushButton:hover {{
                        color: {ThemeTokens.TEXT_WHITE_100};
                    }}
                """)


class VantageDashboardView(QWidget):
    """Visualização principal do Dashboard Ducksvantage — Estilo 3 (65% Esquerda / 35% Direita)."""
    profile_requested = Signal(str)
    fn_q_cycle_requested = Signal()
    eco_travel_toggled = Signal(bool)
    game_auto_toggled = Signal(bool)
    conservation_toggled = Signal(bool)
    rapid_charge_toggled = Signal(bool)
    camera_toggled = Signal(bool)
    touchpad_toggled = Signal(bool)
    kbd_backlight_requested = Signal(int)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        feat = self.backend.features

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        main_layout = QHBoxLayout(container)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(16)

        # =====================================================================
        # COLUNA ESQUERDA (65%)
        # =====================================================================
        left_col = QVBoxLayout()
        left_col.setSpacing(14)

        # 1. Card dos 3 Gauges Circulares Refinados
        self.gauges_card = HardwareGaugesCard()
        left_col.addWidget(self.gauges_card)

        # 2. Seletor Compacto de Modo Térmico
        self.thermal_card = QFrame()
        self.thermal_card.setProperty("class", "vantageCard")
        self.thermal_card.setStyleSheet(f"""
            QFrame.vantageCard {{
                background-color: {ThemeTokens.BG_CARD};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: {ThemeTokens.RADIUS_CARD}px;
            }}
        """)
        th_layout = QVBoxLayout(self.thermal_card)
        th_layout.setContentsMargins(18, 12, 18, 14)
        th_layout.setSpacing(10)

        supported_profiles = self.backend.get_supported_canonical_profiles()
        prof_labels_map = {
            "low-power": "Silencioso",
            "balanced": "Equilibrado",
            "performance": "Desempenho",
            "max-power": "Max-Power",
        }
        supported_names = ", ".join(prof_labels_map[p] for p in supported_profiles if p in prof_labels_map) or "perfis disponíveis"

        th_header = QHBoxLayout()
        th_title = QLabel("Modo Térmico")
        th_title.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        th_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        th_header.addWidget(th_title)
        th_header.addStretch()

        shortcut_btn = QPushButton("Fn+Q")
        shortcut_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        shortcut_btn.setFixedHeight(24)
        shortcut_btn.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        shortcut_btn.setToolTip(
            f"Pressione Fn + Q no teclado ou clique aqui para alternar entre: {supported_names}."
        )
        shortcut_btn.setStyleSheet(f"""
            QPushButton {{
                color: {ThemeTokens.TEXT_WHITE_80};
                background-color: {ThemeTokens.BG_CARD_HOVER};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                padding: 2px 10px;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                border-color: {ThemeTokens.ACCENT_STEEL};
                color: {ThemeTokens.TEXT_WHITE_100};
            }}
        """)
        shortcut_btn.clicked.connect(self.fn_q_cycle_requested.emit)
        th_header.addWidget(shortcut_btn)
        th_layout.addLayout(th_header)

        blocks_row = QHBoxLayout()
        blocks_row.setSpacing(10)

        self.block_quiet = ThermalBlock(
            "low-power", "Silencioso", "Baixo ruído",
            "thermal_quiet.svg", ThemeTokens.THERMAL_QUIET
        )
        self.block_quiet.clicked.connect(self.profile_requested.emit)
        self.block_quiet.setVisible("low-power" in supported_profiles)
        blocks_row.addWidget(self.block_quiet)

        self.block_balanced = ThermalBlock(
            "balanced", "Equilibrado", "Uso diário",
            "thermal_balanced.svg", ThemeTokens.THERMAL_BALANCED
        )
        self.block_balanced.clicked.connect(self.profile_requested.emit)
        self.block_balanced.setVisible("balanced" in supported_profiles)
        blocks_row.addWidget(self.block_balanced)

        self.block_perf = ThermalBlock(
            "performance", "Desempenho", "Jogos",
            "thermal_performance.svg", ThemeTokens.THERMAL_PERFORMANCE
        )
        self.block_perf.clicked.connect(self.profile_requested.emit)
        self.block_perf.setVisible("performance" in supported_profiles)
        blocks_row.addWidget(self.block_perf)

        self.block_max_power = ThermalBlock(
            "max-power", "Max-Power", "Máximo",
            "thermal_max_power.svg", ThemeTokens.ACCENT_STEEL
        )
        self.block_max_power.clicked.connect(self.profile_requested.emit)
        self.block_max_power.setVisible(bool(feat.max_power_profile or "max-power" in supported_profiles))
        blocks_row.addWidget(self.block_max_power)

        th_layout.addLayout(blocks_row)
        self.thermal_card.setVisible(bool(feat.platform_profile and supported_profiles))
        left_col.addWidget(self.thermal_card)

        # 3. Card de Histórico Térmico + Resumo Inline de Sistema (sem 6 subcaixas)
        self.live_chart_card = QFrame()
        self.live_chart_card.setProperty("class", "vantageCard")
        self.live_chart_card.setStyleSheet(f"""
            QFrame.vantageCard {{
                background-color: {ThemeTokens.BG_CARD};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: {ThemeTokens.RADIUS_CARD}px;
            }}
        """)
        lc_layout = QVBoxLayout(self.live_chart_card)
        lc_layout.setContentsMargins(18, 14, 18, 12)
        lc_layout.setSpacing(10)

        lc_header = QHBoxLayout()
        lc_title = QLabel("Histórico Térmico (2 min)")
        lc_title.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        lc_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        lc_header.addWidget(lc_title)
        lc_header.addStretch()

        self.throttling_badge = StatusBadge(
            "SEM THROTTLING",
            bg_color=ThemeTokens.BG_CARD_HOVER,
            text_color=ThemeTokens.STATUS_GREEN,
        )
        self.throttling_badge.setVisible(feat.thermal_throttling)
        lc_header.addWidget(self.throttling_badge)

        self.live_peaks_badge = StatusBadge(
            "PICOS: CPU --°C | GPU --°C",
            bg_color="transparent",
            text_color=ThemeTokens.TEXT_LIGHT_GRAY,
        )
        lc_header.addWidget(self.live_peaks_badge)

        self.btn_reset_peaks = QPushButton("Zerar")
        self.btn_reset_peaks.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_peaks.setFixedHeight(22)
        self.btn_reset_peaks.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                color: {ThemeTokens.TEXT_LIGHT_GRAY};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 5px;
                padding: 1px 9px;
                font-size: 10px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                border-color: {ThemeTokens.ACCENT_STEEL};
                color: {ThemeTokens.TEXT_WHITE_100};
            }}
        """)
        self.btn_reset_peaks.clicked.connect(self._on_reset_thermal_peaks)
        lc_header.addWidget(self.btn_reset_peaks)
        lc_layout.addLayout(lc_header)

        self.live_thermal_chart = LiveThermalChart()
        lc_layout.addWidget(self.live_thermal_chart)

        # Divisor + Barra horizontal limpa de sistema (SSD | Fans | GPU | CPU)
        div_line = QFrame()
        div_line.setFixedHeight(1)
        div_line.setStyleSheet(f"background-color: {ThemeTokens.BORDER_DEFAULT};")
        lc_layout.addWidget(div_line)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(2, 2, 2, 0)
        footer_row.setSpacing(12)

        self.lbl_ssd_model = self._add_inline_stat(footer_row, "SSD", "--")
        footer_row.addWidget(self._make_v_sep())
        self.lbl_ssd_temp = self._add_inline_stat(footer_row, "Temp", "--°C")
        footer_row.addWidget(self._make_v_sep())
        self.lbl_fan_rpm = self._add_inline_stat(footer_row, "Fans", "--")
        footer_row.addWidget(self._make_v_sep())
        self.lbl_gpu_state = self._add_inline_stat(footer_row, "GPU", "--")
        footer_row.addStretch()

        lc_layout.addLayout(footer_row)

        left_col.addWidget(self.live_chart_card)
        left_col.addStretch()

        main_layout.addLayout(left_col, stretch=65)

        # =====================================================================
        # COLUNA DIREITA (35%) - PAINEL ÚNICO EDGE COM DIVISORES FINOS
        # =====================================================================
        self.edge_card = QFrame()
        self.edge_card.setProperty("class", "vantageCard")
        self.edge_card.setStyleSheet(f"""
            QFrame.vantageCard {{
                background-color: {ThemeTokens.BG_CARD};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: {ThemeTokens.RADIUS_CARD}px;
            }}
        """)
        edge_layout = QVBoxLayout(self.edge_card)
        edge_layout.setContentsMargins(18, 14, 18, 14)
        edge_layout.setSpacing(0)

        edge_header = QHBoxLayout()
        edge_header.setContentsMargins(2, 0, 2, 8)
        self.edge_title_lbl = QLabel(self.backend.system_info.edge_panel_title.split("•")[0].strip())
        self.edge_title_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        self.edge_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; letter-spacing: 0.4px;")
        edge_header.addWidget(self.edge_title_lbl)
        edge_header.addStretch()
        edge_layout.addLayout(edge_header)

        # Controles rápidos em lista limpa
        self.item_eco_travel = EdgeControlItem(
            "eco_travel.svg",
            "Modo Viagem",
            self.backend.get_eco_travel_summary(),
            supported=feat.eco_travel,
        )
        self.item_eco_travel.toggled.connect(self.eco_travel_toggled.emit)
        self.item_eco_travel.setVisible(feat.eco_travel)
        edge_layout.addWidget(self.item_eco_travel)

        self._game_auto_default_sub = (
            "Ativa Max-Power / Desempenho em jogos"
            if feat.max_power_profile
            else "Ativa Desempenho em jogos"
        )
        self.item_game_auto = EdgeControlItem(
            "game_controller.svg",
            "Auto-Switch em Jogos",
            self._game_auto_default_sub,
            supported=feat.platform_profile,
        )
        self.item_game_auto.toggled.connect(self.game_auto_toggled.emit)
        self.item_game_auto.setVisible(feat.platform_profile)
        edge_layout.addWidget(self.item_game_auto)

        self.item_conservation = EdgeControlItem(
            "edge_conservation.svg",
            "Conservação 80%",
            "Limita carga em ~80%.",
            supported=feat.conservation_mode,
        )
        self.item_conservation.toggled.connect(self.conservation_toggled.emit)
        self.item_conservation.setVisible(feat.conservation_mode)
        edge_layout.addWidget(self.item_conservation)

        self.item_rapid_charge = EdgeControlItem(
            "edge_rapid_charge.svg",
            "Carregamento Rápido",
            "Carga rápida até 100%.",
            supported=feat.rapid_charge,
        )
        self.item_rapid_charge.toggled.connect(self.rapid_charge_toggled.emit)
        self.item_rapid_charge.setVisible(feat.rapid_charge)
        edge_layout.addWidget(self.item_rapid_charge)

        self.item_camera = EdgeControlItem(
            "edge_camera.svg",
            "Câmera (Privacidade)",
            "Obturador eletrônico da webcam.",
            supported=feat.camera_power,
        )
        self.item_camera.toggled.connect(self.camera_toggled.emit)
        self.item_camera.setVisible(feat.camera_power)
        edge_layout.addWidget(self.item_camera)

        self.item_touchpad = EdgeControlItem(
            "edge_touchpad.svg",
            "Touchpad",
            "Bloqueia toques acidentais.",
            supported=feat.touchpad_control,
        )
        self.item_touchpad.toggled.connect(self.touchpad_toggled.emit)
        self.item_touchpad.setVisible(feat.touchpad_control)
        edge_layout.addWidget(self.item_touchpad)

        self.item_kbd_backlight = KeyboardBacklightEdgeItem(
            supported=feat.kbd_backlight,
            max_level=feat.kbd_max_brightness,
        )
        self.item_kbd_backlight.level_requested.connect(self.kbd_backlight_requested.emit)
        self.item_kbd_backlight.setVisible(feat.kbd_backlight)
        edge_layout.addWidget(self.item_kbd_backlight)

        any_edge_item = any((
            feat.eco_travel, feat.platform_profile, feat.conservation_mode,
            feat.rapid_charge, feat.camera_power, feat.touchpad_control,
            feat.kbd_backlight,
        ))
        self.edge_card.setVisible(any_edge_item)

        edge_layout.addStretch()
        main_layout.addWidget(self.edge_card, stretch=35)

        scroll.setWidget(container)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

    def _make_v_sep(self) -> QFrame:
        sep = QFrame()
        sep.setFixedSize(1, 14)
        sep.setStyleSheet(f"background-color: {ThemeTokens.BORDER_DEFAULT};")
        return sep

    def _add_inline_stat(self, row_layout: QHBoxLayout, label: str, default: str) -> QLabel:
        pair = QHBoxLayout()
        pair.setSpacing(5)
        t = QLabel(label)
        t.setFont(QFont(ThemeTokens.FONT_NAME, 9))
        t.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY};")
        pair.addWidget(t)

        val = QLabel(default)
        val.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        val.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        pair.addWidget(val)
        row_layout.addLayout(pair)
        return val

    def _on_reset_thermal_peaks(self):
        self.live_thermal_chart.reset_peaks()
        self._sync_live_peaks_badge()

    def _sync_live_peaks_badge(self):
        c_pk = self.live_thermal_chart.peak_cpu
        g_pk = self.live_thermal_chart.peak_gpu
        c_str = f"{c_pk:.0f}°C" if c_pk > 0 else "--°C"
        g_str = f"{g_pk:.0f}°C" if g_pk > 0 else "D3cold"
        self.live_peaks_badge.setText(f"Picos: CPU {c_str} | GPU {g_str}")

    def update_telemetry(self):
        """Atualiza todos os sensores e controles do Dashboard."""
        cpu = self.backend.get_cpu_metrics()
        gpu = self.backend.get_gpu_metrics()
        ram = self.backend.get_ram_metrics()
        fan = self.backend.get_fan_metrics()
        disks = self.backend.get_storage_devices()

        # 1. Gauges & Gráfico Térmico ao Vivo + Throttling
        self.gauges_card.update_metrics(cpu, gpu, ram)
        gpu_temp_val = gpu.temperature_c if gpu.available else 0.0
        self.live_thermal_chart.add_sample(cpu.temperature_c, gpu_temp_val)
        self._sync_live_peaks_badge()

        if self.backend.features.thermal_throttling and hasattr(self, "throttling_badge"):
            thr = self.backend.get_throttling_status()
            self.throttling_badge.setText(thr["badge"])
            sev = thr.get("severity", "ok")
            t_col = ThemeTokens.STATUS_DANGER if sev == "thermal" else (
                ThemeTokens.STATUS_WARNING if sev == "power" else ThemeTokens.STATUS_GREEN
            )
            self.throttling_badge.setColor(ThemeTokens.BG_CARD_HOVER, t_col)
            if thr["reasons"]:
                self.throttling_badge.setToolTip("\n".join(thr["reasons"]))
            else:
                self.throttling_badge.setToolTip(
                    f"Sem throttling ativo (Eventos acumulados desde o boot: {thr['cpu_total_events']})"
                )

        # 2. Modo Térmico
        if self.backend.features.platform_profile:
            prof = self.backend.normalize_profile(self.backend.get_platform_profile())
            self.block_quiet.set_active(prof in ("low-power", "quiet"))
            self.block_balanced.set_active(prof == "balanced")
            if self.block_max_power and not self.block_max_power.isHidden():
                self.block_perf.set_active(prof == "performance")
                self.block_max_power.set_active(prof == "max-power")
            else:
                self.block_perf.set_active(prof in ("performance", "max-power"))

        # 3. Rodapé Inline Limpo (SSD, Fans, GPU)
        if disks:
            d0 = disks[0]
            short_ssd = d0.model.split()[0][:16] if d0.model else "NVMe"
            self.lbl_ssd_model.setText(short_ssd)
            if d0.temperature_c > 0:
                self.lbl_ssd_temp.setText(f"{d0.temperature_c:.0f}°C")
            else:
                self.lbl_ssd_temp.setText("N/A")

        fan_txt = fan.status_label
        if "EC" in fan_txt and "RPM" in fan_txt:
            fan_txt = "Auto (EC)"
        self.lbl_fan_rpm.setText(fan_txt)

        if gpu.available:
            self.lbl_gpu_state.setText(f"{gpu.runtime_state} {gpu.pstate}")
        elif self.backend.paths.nvidia_drm_card:
            self.lbl_gpu_state.setText("D3cold")
        else:
            self.lbl_gpu_state.setText("iGPU")

        # 4. Controles do Painel EDGE
        if self.backend.features.eco_travel:
            eco_on = self.backend.get_eco_travel_mode()
            eco_sum = self.backend.get_eco_travel_summary()
            self.item_eco_travel.set_checked(eco_on)
            self.item_eco_travel.setToolTip(eco_sum)
            self.item_eco_travel.set_subtitle(eco_sum, ThemeTokens.STATUS_GREEN if eco_on else "")
        if self.backend.features.platform_profile:
            self.item_game_auto.set_checked(self.backend.get_game_auto_switch())
            active_game = self.backend.get_active_game()
            if active_game:
                self.item_game_auto.set_subtitle(f"JOGO ATIVO: {active_game}", ThemeTokens.STATUS_GREEN)
            else:
                self.item_game_auto.set_subtitle(self._game_auto_default_sub)

        if self.backend.features.conservation_mode:
            self.item_conservation.set_checked(self.backend.get_conservation_mode())
        if self.backend.features.rapid_charge:
            self.item_rapid_charge.set_checked(self.backend.get_rapid_charge())
        if self.backend.features.camera_power:
            self.item_camera.set_checked(self.backend.get_camera_power())
        if self.backend.features.touchpad_control:
            self.item_touchpad.set_checked(self.backend.get_touchpad_status())
        if self.backend.features.kbd_backlight:
            self.item_kbd_backlight.set_level(self.backend.get_kbd_backlight())
