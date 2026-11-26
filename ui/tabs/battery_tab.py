"""
Aba Alimentação & Bateria do Ducksvantage (ui/tabs/battery_tab.py).
Exibe:
1. Controles de Modo de Conservação (~80%) e Carregamento Rápido com exclusão mútua.
2. Medidor Circular (CircularGauge) para o nível de carga atual e Wh.
3. Os 6 Cards Elétricos Detalhados lendo energy_full vs energy_full_design,
   tensão real, potência em Watts, ciclos e status real de /sys/class/power_supply/BAT*/status.
4. ELITE 3: Painel Gráfico de Saúde e Degradação da Bateria (Battery Health Historian)
   desenhado com QPainter, comparando Capacidade Original (Design Wh) vs Capacidade Real (Full Wh)
   ao longo dos ciclos/semanas para comprovar a eficiência do Modo de Conservação.
Zero emojis: utiliza exclusivamente ícones vetoriais SVG.
"""

import os
from typing import List
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QScrollArea, QStackedWidget, QPushButton, QSlider, QComboBox, QLineEdit,
    Qt, Signal, QFont, QMessageBox, QPixmap, QPainter, QColor,
    QPen, QBrush, QLinearGradient, QPointF, QPainterPath
)
from core.models import BatteryHistoryEntry
from ui.theme_tokens import ThemeTokens
from ui.components import ToggleSwitch, StatusBadge, SubTabSelector
from ui.gauges import CircularGauge

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")


class BatteryHealthChart(QWidget):
    """
    Gráfico vetorial (QPainter) do Histórico de Saúde e Retenção Química da Bateria:
    Compara a Capacidade de Fábrica (energy_full_design Wh) com a Capacidade Real (energy_full Wh)
    ao longo das semanas e ciclos de carga.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[BatteryHistoryEntry] = []
        self.setMinimumHeight(210)

    def set_history(self, entries: List[BatteryHistoryEntry]):
        self.entries = entries or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        w = float(self.width())
        h = float(self.height())

        # Fundo escuro do gráfico
        bg_rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(ThemeTokens.BORDER_DEFAULT), 1))
        painter.setBrush(QBrush(QColor(ThemeTokens.BG_APP)))
        painter.drawRoundedRect(bg_rect, 8, 8)

        if not self.entries:
            painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
            painter.setFont(QFont(ThemeTokens.FONT_NAME, 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Sem dados históricos de bateria disponíveis.")
            painter.end()
            return

        pad_left = 58.0
        pad_right = 26.0
        pad_top = 34.0
        pad_bottom = 42.0
        plot_w = max(50.0, w - pad_left - pad_right)
        plot_h = max(50.0, h - pad_top - pad_bottom)

        design_wh = max(e.energy_design_wh for e in self.entries) if self.entries else 60.0
        min_wh = min(e.energy_full_wh for e in self.entries) if self.entries else 45.0
        y_max = round(design_wh * 1.05, 1)
        y_min = max(0.0, round(min(min_wh * 0.88, design_wh * 0.75), 1))
        if y_max <= y_min:
            y_max = y_min + 10.0

        def val_to_y(val_wh: float) -> float:
            norm = (val_wh - y_min) / (y_max - y_min)
            norm = max(0.0, min(1.0, norm))
            return pad_top + plot_h * (1.0 - norm)

        # Grade horizontal + Rótulos Wh à esquerda
        painter.setFont(QFont(ThemeTokens.FONT_NAME, 8))
        grid_steps = 4
        for i in range(grid_steps + 1):
            v = y_min + (y_max - y_min) * (i / float(grid_steps))
            yy = val_to_y(v)
            painter.setPen(QPen(QColor("#22252b"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(pad_left), int(yy), int(pad_left + plot_w), int(yy))
            painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
            painter.drawText(
                4, int(yy - 8), int(pad_left - 8), 16,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{v:.1f} Wh"
            )

        # Linha tracejada da Capacidade Original de Fábrica (Design Wh)
        y_design = val_to_y(design_wh)
        pen_design = QPen(QColor(ThemeTokens.BORDER_CYAN), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen_design)
        painter.drawLine(int(pad_left), int(y_design), int(pad_left + plot_w), int(y_design))

        painter.setFont(QFont(ThemeTokens.FONT_NAME, 8, QFont.Weight.Bold))
        painter.setPen(QColor(ThemeTokens.BORDER_CYAN))
        painter.drawText(
            int(pad_left + 8), int(max(14.0, y_design - 6)),
            f"Capacidade de Fábrica (Design): {design_wh:.2f} Wh (100%)"
        )

        # Coordenadas dos pontos históricos de energy_full_wh
        n = len(self.entries)
        points: List[QPointF] = []
        for idx, entry in enumerate(self.entries):
            if n == 1:
                xx = pad_left + plot_w / 2.0
            else:
                xx = pad_left + (idx / float(n - 1)) * plot_w
            yy = val_to_y(entry.energy_full_wh)
            points.append(QPointF(xx, yy))

        # Preenchimento em gradiente sob a curva real
        if len(points) >= 2:
            area_path = QPainterPath()
            area_path.moveTo(points[0].x(), pad_top + plot_h)
            for pt in points:
                area_path.lineTo(pt.x(), pt.y())
            area_path.lineTo(points[-1].x(), pad_top + plot_h)
            area_path.closeSubpath()

            grad = QLinearGradient(0, pad_top, 0, pad_top + plot_h)
            c_top = QColor(ThemeTokens.STATUS_GREEN)
            c_top.setAlpha(95)
            c_bot = QColor(ThemeTokens.STATUS_GREEN)
            c_bot.setAlpha(8)
            grad.setColorAt(0.0, c_top)
            grad.setColorAt(1.0, c_bot)
            painter.fillPath(area_path, QBrush(grad))

            # Linha principal da Capacidade Real (energy_full_wh)
            line_path = QPainterPath()
            line_path.moveTo(points[0])
            for pt in points[1:]:
                line_path.lineTo(pt)
            painter.setPen(QPen(QColor(ThemeTokens.STATUS_GREEN), 2.6))
            painter.drawPath(line_path)

        # Desenhar nós, valores em Wh e rótulos do eixo X (Data + Ciclos)
        for idx, (pt, entry) in enumerate(zip(points, self.entries)):
            if getattr(entry, "is_estimated", False):
                painter.setPen(QPen(QColor(ThemeTokens.ACCENT_MUTED), 2))
                painter.setBrush(QBrush(QColor(ThemeTokens.BG_APP)))
            else:
                painter.setPen(QPen(QColor(ThemeTokens.BG_APP), 2))
                painter.setBrush(QBrush(QColor(ThemeTokens.STATUS_GREEN)))
            painter.drawEllipse(pt, 4.5, 4.5)

            # Valor de Wh e % acima do ponto
            painter.setFont(QFont(ThemeTokens.FONT_NAME, 8, QFont.Weight.Bold))
            painter.setPen(QColor("#94a3b8" if getattr(entry, "is_estimated", False) else ThemeTokens.TEXT_WHITE_100))
            lbl_val = f"{entry.energy_full_wh:.1f}Wh ({entry.health_percent:.1f}%)"
            painter.drawText(
                int(pt.x() - 48), int(pt.y() - 20), 96, 16,
                int(Qt.AlignmentFlag.AlignCenter), lbl_val
            )

            # Rótulo inferior: Data curta + Ciclo
            short_date = entry.timestamp[-5:] if len(entry.timestamp) >= 5 else entry.timestamp
            x_lbl = f"{short_date}\nCiclo {entry.cycle_count}"
            painter.setFont(QFont(ThemeTokens.FONT_NAME, 8))
            painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
            painter.drawText(
                int(pt.x() - 38), int(pad_top + plot_h + 5), 76, 32,
                int(Qt.AlignmentFlag.AlignCenter), x_lbl
            )

        # Legenda discreta no canto superior direito
        painter.setFont(QFont(ThemeTokens.FONT_NAME, 8))
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(
            int(w - 230), 6, 214, 16,
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            "● Medição Real   ○ Estimativa Inicial"
        )

        painter.end()


class BatteryTab(QWidget):
    """Controle de energia, conservação, diagnóstico elétrico, economia de rede e alertas inteligentes da bateria."""
    conservation_changed = Signal(bool)
    rapid_charge_changed = Signal(bool)
    test_alert_requested = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._advanced_mode = self.backend.is_advanced_mode()
        self._has_wifi = False
        self._has_eth = False

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(22, 18, 22, 20)
        root_layout.setSpacing(14)

        self.sub_tabs = SubTabSelector([
            ("charge", "Carga & Saúde"),
            ("net_usb", "Rede, Wi-Fi & Mochila"),
        ])
        root_layout.addWidget(self.sub_tabs)

        self.sub_stack = QStackedWidget()
        self.sub_tabs.tab_selected.connect(self.sub_stack.setCurrentIndex)
        root_layout.addWidget(self.sub_stack, stretch=1)

        page_charge = QWidget()
        layout = QVBoxLayout(page_charge)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # =====================================================================
        # 1. Card de Controles de Carregamento (Exclusão Mútua — exibe só o suportado)
        # =====================================================================
        feat = self.backend.features
        self.cons_card = QFrame()
        self.cons_card.setProperty("class", "card")
        cons_layout = QVBoxLayout(self.cons_card)
        cons_layout.setContentsMargins(20, 18, 20, 18)
        cons_layout.setSpacing(14)

        # Modo de Conservação
        self.cons_row_widget = QWidget()
        top_row = QHBoxLayout(self.cons_row_widget)
        top_row.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel()
        cons_icon_path = os.path.join(ICON_DIR, "edge_conservation.svg")
        if os.path.exists(cons_icon_path):
            icon_lbl.setPixmap(QPixmap(cons_icon_path).scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        top_row.addWidget(icon_lbl)

        title_layout = QVBoxLayout()
        cons_title = QLabel("Modo de Conservação (Limite de 80%)")
        cons_title.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.Bold))
        cons_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        title_layout.addWidget(cons_title)

        self.cons_status_lbl = QLabel("Suspende o carregamento entre 75% e 80% para preservar a vida útil das células.")
        self.cons_status_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        title_layout.addWidget(self.cons_status_lbl)

        top_row.addLayout(title_layout)
        top_row.addStretch()

        self.toggle_switch = ToggleSwitch()
        self.toggle_switch.setEnabled(feat.conservation_mode)
        self.toggle_switch.toggled.connect(self._on_conservation_toggled)
        top_row.addWidget(self.toggle_switch)
        self.cons_row_widget.setVisible(feat.conservation_mode)
        cons_layout.addWidget(self.cons_row_widget)

        # Divisor (apenas quando ambos os controles estão disponíveis)
        self.cons_div = QFrame()
        self.cons_div.setStyleSheet(f"background-color: {ThemeTokens.BORDER_DEFAULT}; max-height: 1px;")
        self.cons_div.setVisible(bool(feat.conservation_mode and feat.rapid_charge))
        cons_layout.addWidget(self.cons_div)

        # Carregamento Rápido (Rapid Charge)
        self.rapid_row_widget = QWidget()
        rapid_row = QHBoxLayout(self.rapid_row_widget)
        rapid_row.setContentsMargins(0, 0, 0, 0)
        rapid_icon = QLabel()
        rapid_icon_path = os.path.join(ICON_DIR, "edge_rapid_charge.svg")
        if os.path.exists(rapid_icon_path):
            rapid_icon.setPixmap(QPixmap(rapid_icon_path).scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        rapid_row.addWidget(rapid_icon)

        rapid_title_layout = QVBoxLayout()
        rapid_title = QLabel("Carregamento Rápido (Rapid Charge)")
        rapid_title.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.Bold))
        rapid_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        rapid_title_layout.addWidget(rapid_title)

        self.rapid_status_lbl = QLabel("Eleva a taxa de carregamento até 100% (mutuamente exclusivo com o Modo de Conservação).")
        self.rapid_status_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        rapid_title_layout.addWidget(self.rapid_status_lbl)

        rapid_row.addLayout(rapid_title_layout)
        rapid_row.addStretch()

        self.toggle_rapid = ToggleSwitch()
        self.toggle_rapid.setEnabled(feat.rapid_charge)
        self.toggle_rapid.toggled.connect(self._on_rapid_charge_toggled)
        rapid_row.addWidget(self.toggle_rapid)
        self.rapid_row_widget.setVisible(feat.rapid_charge)
        cons_layout.addWidget(self.rapid_row_widget)

        self.cons_card.setVisible(bool(feat.conservation_mode or feat.rapid_charge))
        layout.addWidget(self.cons_card)

        # =====================================================================
        # 2. Card de Diagnóstico Elétrico com CircularGauge + 6 Cards Elétricos
        # =====================================================================
        self.health_card = QFrame()
        self.health_card.setProperty("class", "card")
        health_layout = QVBoxLayout(self.health_card)
        health_layout.setContentsMargins(20, 18, 20, 18)
        health_layout.setSpacing(16)

        header_health = QHBoxLayout()
        h_icon = QLabel()
        bat_icon_path = os.path.join(ICON_DIR, "power.svg")
        if os.path.exists(bat_icon_path):
            h_icon.setPixmap(QPixmap(bat_icon_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header_health.addWidget(h_icon)

        h_title = QLabel("Saúde e Diagnóstico da Bateria")
        h_title.setToolTip("Leitura direta via /sys/class/power_supply/BAT*")
        h_title.setWordWrap(True)
        h_title.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.Bold))
        h_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        header_health.addWidget(h_title, stretch=1)

        self.status_pill = StatusBadge("STATUS", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        header_health.addWidget(self.status_pill)
        health_layout.addLayout(header_health)

        # Layout Horizontal: CircularGauge da Bateria à Esquerda + 6 Cards Elétricos à Direita
        body_row = QHBoxLayout()
        body_row.setSpacing(18)

        self.bat_gauge = CircularGauge(
            "Carga da Bateria",
            ThemeTokens.GRAD_BATTERY[0],
            ThemeTokens.GRAD_BATTERY[1]
        )
        self.bat_gauge.setFixedSize(200, 200)
        body_row.addWidget(self.bat_gauge)

        # Grade dos 6 Cards Elétricos Detalhados
        details_grid = QGridLayout()
        details_grid.setSpacing(12)

        self.val_health = self._create_info_item(details_grid, 0, 0, "1. Saúde da Bateria (Full vs Design)", "--%")
        self.val_cycles = self._create_info_item(details_grid, 0, 1, "2. Ciclos de Carga & Química", "--")
        self.val_power = self._create_info_item(details_grid, 0, 2, "3. Taxa / Potência Elétrica", "-- W")
        self.val_voltage = self._create_info_item(details_grid, 1, 0, "4. Tensão Atual (Voltage)", "-- V")
        self.val_full_wh = self._create_info_item(details_grid, 1, 1, "5. Energia Atual / Capacidade Cheia", "-- / -- Wh")
        self.val_design_wh = self._create_info_item(details_grid, 1, 2, "6. Capacidade de Fábrica (Design)", "-- Wh")

        body_row.addLayout(details_grid, stretch=1)
        health_layout.addLayout(body_row)

        self.health_card.setVisible(feat.battery)
        layout.addWidget(self.health_card)

        # =====================================================================
        # 3. ELITE 3: Battery Health Historian (Gráfico de Saúde e Degradação)
        # =====================================================================
        self.hist_card = QFrame()
        self.hist_card.setProperty("class", "card")
        hist_layout = QVBoxLayout(self.hist_card)
        hist_layout.setContentsMargins(20, 18, 20, 18)
        hist_layout.setSpacing(12)

        hist_header = QHBoxLayout()
        hist_icon = QLabel()
        chart_ic_path = os.path.join(ICON_DIR, "chart_health.svg")
        if os.path.exists(chart_ic_path):
            hist_icon.setPixmap(QPixmap(chart_ic_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        hist_header.addWidget(hist_icon)

        hist_title_col = QVBoxLayout()
        hist_title_col.setSpacing(2)
        hist_title = QLabel("Histórico de Saúde da Bateria")
        hist_title.setToolTip("Battery Health Historian: energy_full_design vs energy_full em Wh")
        hist_title.setWordWrap(True)
        hist_title.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.Bold))
        hist_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        hist_title_col.addWidget(hist_title)

        self.hist_sub_lbl = QLabel(
            "Evolução da capacidade máxima real comparada à capacidade original de fábrica."
        )
        self.hist_sub_lbl.setWordWrap(True)
        self.hist_sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        hist_title_col.addWidget(self.hist_sub_lbl)
        hist_header.addLayout(hist_title_col, stretch=1)

        self.btn_snapshot = QPushButton("Registrar Leitura Agora")
        self.btn_snapshot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_snapshot.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                color: {ThemeTokens.ACCENT_STEEL};
                border: 1px solid {ThemeTokens.ACCENT_STEEL};
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.ACCENT_STEEL};
                color: {ThemeTokens.BG_APP};
            }}
        """)
        self.btn_snapshot.clicked.connect(self._on_record_snapshot)
        hist_header.addWidget(self.btn_snapshot)

        hist_layout.addLayout(hist_header)

        self.health_chart = BatteryHealthChart()
        hist_layout.addWidget(self.health_chart)

        # Rodapé analítico de desgaste por ciclo
        self.wear_summary_lbl = QLabel("")
        self.wear_summary_lbl.setWordWrap(True)
        self.wear_summary_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.Bold))
        self.wear_summary_lbl.setStyleSheet(f"color: {ThemeTokens.STATUS_GREEN};")
        hist_layout.addWidget(self.wear_summary_lbl)

        self.hist_card.setVisible(feat.battery)
        layout.addWidget(self.hist_card)

        # =====================================================================
        # 4. Controle de Economia de Energia de Rede (Página 2: Rede, Wi-Fi & Mochila)
        # =====================================================================
        page_net = QWidget()
        net_page_layout = QVBoxLayout(page_net)
        net_page_layout.setContentsMargins(0, 0, 0, 0)
        net_page_layout.setSpacing(16)

        net_status = self.backend.get_network_power_status()
        has_wifi = bool(net_status.wifi_available and feat.wifi_power_save)
        has_eth = bool(net_status.eth_available and feat.eth_power_save)
        self._has_wifi = has_wifi
        self._has_eth = has_eth

        self.net_card = QFrame()
        self.net_card.setProperty("class", "card")
        net_layout = QVBoxLayout(self.net_card)
        net_layout.setContentsMargins(20, 18, 20, 18)
        net_layout.setSpacing(14)

        net_header = QHBoxLayout()
        ic_net = QLabel()
        p_net = os.path.join(ICON_DIR, "network_power.svg")
        if os.path.exists(p_net):
            ic_net.setPixmap(QPixmap(p_net).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        net_header.addWidget(ic_net)

        net_titles = QVBoxLayout()
        net_iface_parts = []
        if has_wifi:
            net_iface_parts.append(f"Wi-Fi ({net_status.wifi_iface} / {net_status.wifi_driver})")
        if has_eth:
            net_iface_parts.append(f"Ethernet ({net_status.eth_iface})")
        net_title_suffix = " & ".join(net_iface_parts) if net_iface_parts else "Interfaces de Rede"
        nt_lbl = QLabel("Rede & Economia de Energia")
        nt_lbl.setToolTip(f"Interfaces detectadas: {net_title_suffix}")
        nt_lbl.setWordWrap(True)
        nt_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.Bold))
        nt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        net_titles.addWidget(nt_lbl)

        nt_sub = QLabel(
            "Otimize o Wi-Fi para jogos online sem travamentos ou reduza consumo de rede."
        )
        nt_sub.setWordWrap(True)
        nt_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        net_titles.addWidget(nt_sub)
        net_header.addLayout(net_titles, stretch=1)

        self.net_badge = StatusBadge("REDE OTIMIZADA", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.ACCENT_STEEL)
        net_header.addWidget(self.net_badge)
        net_layout.addLayout(net_header)

        # Toggle 1: Modo Jogos Online (Wi-Fi Power Save OFF / Baixa Latência)
        self.wifi_box = QFrame()
        self.wifi_box.setProperty("class", "subBox")
        wifi_row = QHBoxLayout(self.wifi_box)
        wifi_row.setContentsMargins(14, 10, 14, 10)

        w_info = QVBoxLayout()
        w_title = QLabel("Baixa Latência no Wi-Fi (Modo Jogos Online)")
        w_title.setToolTip(f"{net_status.wifi_iface} ({net_status.wifi_driver}): IEEE 802.11 Power Save OFF")
        w_title.setWordWrap(True)
        w_title.setFont(QFont(ThemeTokens.FONT_NAME, 11, QFont.Weight.Bold))
        w_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        w_info.addWidget(w_title)

        self.lbl_wifi_ps_desc = QLabel(
            "Mantém o Wi-Fi ativo sem micro-suspensões para evitar oscilações de ping em partidas."
        )
        self.lbl_wifi_ps_desc.setWordWrap(True)
        self.lbl_wifi_ps_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        w_info.addWidget(self.lbl_wifi_ps_desc)
        wifi_row.addLayout(w_info, stretch=1)

        self.sw_wifi_low_latency = ToggleSwitch()
        self.sw_wifi_low_latency.setChecked(not net_status.wifi_power_save_on)
        self.sw_wifi_low_latency.toggled.connect(self._on_wifi_low_latency_toggled)
        wifi_row.addWidget(self.sw_wifi_low_latency)
        self.wifi_box.setVisible(has_wifi)
        net_layout.addWidget(self.wifi_box)

        # Toggle 2: Economia de Energia PCIe Ethernet Gigabit
        self.eth_box = QFrame()
        self.eth_box.setProperty("class", "subBox")
        eth_row = QHBoxLayout(self.eth_box)
        eth_row.setContentsMargins(14, 10, 14, 10)

        e_info = QVBoxLayout()
        e_title = QLabel("Economia de Energia na Porta Cabo (RJ-45)")
        e_title.setToolTip(f"{net_status.eth_iface} / {net_status.eth_driver}: PCIe Runtime PM = auto")
        e_title.setWordWrap(True)
        e_title.setFont(QFont(ThemeTokens.FONT_NAME, 11, QFont.Weight.Bold))
        e_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        e_info.addWidget(e_title)

        self.lbl_eth_ps_desc = QLabel(
            "Desliga o controlador de rede cabeada automaticamente quando nenhum cabo estiver conectado."
        )
        self.lbl_eth_ps_desc.setWordWrap(True)
        self.lbl_eth_ps_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        e_info.addWidget(self.lbl_eth_ps_desc)
        eth_row.addLayout(e_info, stretch=1)

        self.sw_eth_power_save = ToggleSwitch()
        self.sw_eth_power_save.setChecked(net_status.eth_power_save_on)
        self.sw_eth_power_save.toggled.connect(self._on_eth_power_save_toggled)
        eth_row.addWidget(self.sw_eth_power_save)
        self.eth_box.setVisible(has_eth)
        net_layout.addWidget(self.eth_box)

        # Regras Automáticas por Rede Wi-Fi (SSID)
        self.wifi_rules_box = QFrame()
        self.wifi_rules_box.setProperty("class", "subBox")
        wr_v = QVBoxLayout(self.wifi_rules_box)
        wr_v.setContentsMargins(14, 10, 14, 10)
        wr_v.setSpacing(8)

        wr_top = QHBoxLayout()
        wr_t = QLabel("Regras Automáticas por Rede Wi-Fi (SSID)")
        wr_t.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
        wr_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        wr_top.addWidget(wr_t)
        wr_top.addStretch()
        self.lbl_cur_ssid = QLabel("Wi-Fi: --")
        self.lbl_cur_ssid.setStyleSheet(f"color: {ThemeTokens.ACCENT_STEEL}; font-size: 11px;")
        wr_top.addWidget(self.lbl_cur_ssid)
        wr_v.addLayout(wr_top)

        wr_add = QHBoxLayout()
        wr_add.setSpacing(8)
        self.edit_wifi_ssid = QLineEdit()
        self.edit_wifi_ssid.setPlaceholderText("Nome da rede (SSID ex: Trabalho, AndroidAP)")
        self.edit_wifi_ssid.setFixedHeight(28)
        wr_add.addWidget(self.edit_wifi_ssid, stretch=1)

        btn_use_cur_ssid = QPushButton("Usar Atual")
        btn_use_cur_ssid.setProperty("class", "secondaryButton")
        btn_use_cur_ssid.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_use_cur_ssid.setFixedHeight(28)
        btn_use_cur_ssid.clicked.connect(self._on_fill_current_ssid)
        wr_add.addWidget(btn_use_cur_ssid)

        self.combo_wifi_action = QComboBox()
        self.combo_wifi_action.setFixedHeight(28)
        self.combo_wifi_action.setMinimumWidth(185)
        self.combo_wifi_action.addItem("Modo Equilibrado", ("balanced", False, 0))
        self.combo_wifi_action.addItem("Modo Desempenho", ("performance", False, 0))
        self.combo_wifi_action.addItem("Modo Silencioso", ("low-power", False, 0))
        self.combo_wifi_action.addItem("Eco-Mode Extremo", ("low-power", True, 0))
        if feat.refresh_rate:
            self.combo_wifi_action.addItem("Eco-Mode + 60 Hz", ("low-power", True, 60))
        wr_add.addWidget(self.combo_wifi_action)

        btn_add_ssid = QPushButton("Adicionar Regra")
        btn_add_ssid.setProperty("class", "primaryButton")
        btn_add_ssid.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_ssid.setFixedHeight(28)
        btn_add_ssid.clicked.connect(self._on_add_wifi_rule)
        wr_add.addWidget(btn_add_ssid)
        wr_v.addLayout(wr_add)

        self.wifi_rules_list_container = QWidget()
        self.wifi_rules_list_layout = QVBoxLayout(self.wifi_rules_list_container)
        self.wifi_rules_list_layout.setContentsMargins(0, 0, 0, 0)
        self.wifi_rules_list_layout.setSpacing(6)
        wr_v.addWidget(self.wifi_rules_list_container)

        self.wifi_rules_box.setVisible(has_wifi)
        net_layout.addWidget(self.wifi_rules_box)

        self.net_card.setVisible(bool(has_wifi or (self._advanced_mode and has_eth)))
        net_page_layout.addWidget(self.net_card)

        # =====================================================================
        # 4.5 Bloqueio de Wake-on-USB na Suspensão
        # =====================================================================
        self.usb_wake_card = QFrame()
        self.usb_wake_card.setProperty("class", "card")
        usb_layout = QHBoxLayout(self.usb_wake_card)
        usb_layout.setContentsMargins(20, 16, 20, 16)
        usb_layout.setSpacing(14)

        usb_titles = QVBoxLayout()
        usb_titles.setSpacing(3)
        uwt_lbl = QLabel("Bloqueio de Wake-on-USB na Suspensão (Modo Mochila)")
        uwt_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        uwt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        usb_titles.addWidget(uwt_lbl)

        self.lbl_usb_wake_devices = QLabel(
            "Impede que receptores wireless 2.4 GHz (mouse/teclado USB) acordem o notebook fechado."
        )
        self.lbl_usb_wake_devices.setWordWrap(True)
        self.lbl_usb_wake_devices.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        usb_titles.addWidget(self.lbl_usb_wake_devices)
        usb_layout.addLayout(usb_titles, stretch=1)

        self.usb_wake_badge = StatusBadge("DESATIVADO", bg_color=ThemeTokens.BG_CARD_HOVER, text_color=ThemeTokens.TEXT_WHITE_80)
        usb_layout.addWidget(self.usb_wake_badge)

        self.sw_usb_wakeup_block = ToggleSwitch(checked=self.backend.get_usb_wakeup_blocked() if feat.usb_wakeup else False)
        self.sw_usb_wakeup_block.toggled.connect(self._on_usb_wakeup_toggled)
        usb_layout.addWidget(self.sw_usb_wakeup_block)

        self.usb_wake_card.setVisible(bool(feat.usb_wakeup))
        net_page_layout.addWidget(self.usb_wake_card)

        # =====================================================================
        # 4.8 Top 5 Processos Drenando Bateria / CPU
        # =====================================================================
        self.top_procs_card = QFrame()
        self.top_procs_card.setProperty("class", "card")
        tp_layout = QVBoxLayout(self.top_procs_card)
        tp_layout.setContentsMargins(20, 16, 20, 16)
        tp_layout.setSpacing(10)

        tp_header = QHBoxLayout()
        tp_titles = QVBoxLayout()
        tp_titles.setSpacing(2)
        tpt_lbl = QLabel("Top 5 Processos Consumindo Bateria / CPU")
        tpt_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        tpt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        tp_titles.addWidget(tpt_lbl)
        tps_lbl = QLabel("Identifica rapidamente aplicativos ativos drenando bateria ou elevando o uso da CPU.")
        tps_lbl.setWordWrap(True)
        tps_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        tp_titles.addWidget(tps_lbl)
        tp_header.addLayout(tp_titles, stretch=1)

        btn_refresh_tp = QPushButton("Atualizar")
        btn_refresh_tp.setProperty("class", "secondaryButton")
        btn_refresh_tp.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh_tp.setFixedHeight(28)
        btn_refresh_tp.clicked.connect(lambda _c=False: self._rebuild_top_processes_list(force=True))
        tp_header.addWidget(btn_refresh_tp)
        tp_layout.addLayout(tp_header)

        self.top_procs_container = QWidget()
        self.top_procs_list_layout = QVBoxLayout(self.top_procs_container)
        self.top_procs_list_layout.setContentsMargins(0, 0, 0, 0)
        self.top_procs_list_layout.setSpacing(6)
        tp_layout.addWidget(self.top_procs_container)

        self.top_procs_card.setVisible(bool(self._advanced_mode and feat.battery))
        net_page_layout.addWidget(self.top_procs_card)
        net_page_layout.addStretch()

        # =====================================================================
        # 5. Monitor de Ciclo de Vida e Alertas Inteligentes (Página 1: Carga & Saúde)
        # =====================================================================
        alert_cfg = self.backend.get_battery_alert_settings()
        life_status = self.backend.get_battery_lifecycle_status()

        self.alert_card = QFrame()
        self.alert_card.setProperty("class", "card")
        alert_layout = QVBoxLayout(self.alert_card)
        alert_layout.setContentsMargins(20, 18, 20, 18)
        alert_layout.setSpacing(14)

        alert_header = QHBoxLayout()
        ic_al = QLabel()
        p_al = os.path.join(ICON_DIR, "battery_alert.svg")
        if os.path.exists(p_al):
            ic_al.setPixmap(QPixmap(p_al).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        alert_header.addWidget(ic_al)

        al_titles = QVBoxLayout()
        al_t = QLabel("Alertas de Carga e Temperatura")
        al_t.setWordWrap(True)
        al_t.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.Bold))
        al_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        al_titles.addWidget(al_t)

        self.lbl_lifecycle_rec = QLabel(life_status["recommendation"])
        self.lbl_lifecycle_rec.setWordWrap(True)
        self.lbl_lifecycle_rec.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        al_titles.addWidget(self.lbl_lifecycle_rec)
        alert_header.addLayout(al_titles, stretch=1)

        self.lifecycle_badge = StatusBadge(
            f"CICLO DE VIDA: {life_status['badge']}",
            bg_color=ThemeTokens.BG_CARD_HOVER,
            text_color=life_status["color"]
        )
        alert_header.addWidget(self.lifecycle_badge)
        alert_layout.addLayout(alert_header)

        # Linha 1: Notificações Inteligentes na Bandeja + Alerta de 80%
        self.al_box1 = QFrame()
        self.al_box1.setProperty("class", "subBox")
        al_row1 = QHBoxLayout(self.al_box1)
        al_row1.setContentsMargins(14, 10, 14, 10)

        a1_info = QVBoxLayout()
        a1_title = QLabel("Avisar ao Atingir 80% de Carga (Modo de Conservação)")
        a1_title.setWordWrap(True)
        a1_title.setFont(QFont(ThemeTokens.FONT_NAME, 11, QFont.Weight.Bold))
        a1_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        a1_info.addWidget(a1_title)

        a1_sub = QLabel(
            "Envia alerta nativo quando a carga estaciona em 80% na tomada ou quando há eventos críticos de ciclo de vida."
        )
        a1_sub.setWordWrap(True)
        a1_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        a1_info.addWidget(a1_sub)
        al_row1.addLayout(a1_info, stretch=1)

        self.sw_bat_alerts = ToggleSwitch()
        self.sw_bat_alerts.setChecked(bool(alert_cfg["alerts_enabled"] and alert_cfg["alert_80_enabled"]))
        self.sw_bat_alerts.toggled.connect(self._on_battery_alert_settings_changed)
        al_row1.addWidget(self.sw_bat_alerts)
        self.al_box1.setVisible(feat.conservation_mode)
        alert_layout.addWidget(self.al_box1)

        # Linha 2: Limite de Alerta Térmico da Bateria (°C) + Botão Testar Alerta
        al_box2 = QFrame()
        al_box2.setProperty("class", "subBox")
        al_row2 = QHBoxLayout(al_box2)
        al_row2.setContentsMargins(14, 10, 14, 10)
        al_row2.setSpacing(14)

        init_temp_thr = int(round(alert_cfg["temp_threshold_c"]))
        self.lbl_bat_temp_thr = QLabel(
            f"Alerta Térmico da Bateria em Jogos: {init_temp_thr}°C (Atual: {life_status['temperature_c']:.1f}°C)"
        )
        self.lbl_bat_temp_thr.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.Bold))
        self.lbl_bat_temp_thr.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 280px;")
        al_row2.addWidget(self.lbl_bat_temp_thr)

        self.slider_bat_temp_thr = QSlider(Qt.Orientation.Horizontal)
        self.slider_bat_temp_thr.setRange(36, 50)
        self.slider_bat_temp_thr.setValue(init_temp_thr)
        self.slider_bat_temp_thr.valueChanged.connect(self._on_battery_alert_settings_changed)
        al_row2.addWidget(self.slider_bat_temp_thr, stretch=1)

        self.btn_test_bat_alert = QPushButton("Testar Alerta no KDE Plasma")
        self.btn_test_bat_alert.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_bat_alert.setFixedHeight(30)
        self.btn_test_bat_alert.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                color: {ThemeTokens.ACCENT_STEEL};
                border: 1px solid {ThemeTokens.ACCENT_STEEL};
                border-radius: 6px;
                padding: 4px 14px;
                font-weight: 600;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.ACCENT_STEEL};
                color: {ThemeTokens.BG_APP};
            }}
        """)
        self.btn_test_bat_alert.clicked.connect(lambda _c: self.test_alert_requested.emit())
        al_row2.addWidget(self.btn_test_bat_alert)

        alert_layout.addWidget(al_box2)
        self.alert_card.setVisible(feat.battery)
        layout.addWidget(self.alert_card)
        layout.addStretch()

        self.sub_stack.addWidget(page_charge)
        self.sub_stack.addWidget(page_net)

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.set_advanced_mode(self._advanced_mode)
        self.refresh_display()

    def set_advanced_mode(self, advanced: bool):
        """Alterna visibilidade dos blocos avançados de Bateria & Rede conforme o modo da interface."""
        self._advanced_mode = bool(advanced)
        feat = self.backend.features
        self.hist_card.setVisible(bool(self._advanced_mode and feat.battery))
        self.eth_box.setVisible(bool(self._advanced_mode and self._has_eth))
        self.wifi_rules_box.setVisible(bool(self._advanced_mode and self._has_wifi))
        self.net_card.setVisible(bool(self._has_wifi or (self._advanced_mode and self._has_eth)))
        self.top_procs_card.setVisible(bool(self._advanced_mode and feat.battery))

        has_net_page_items = not (
            self.usb_wake_card.isHidden()
            and self.net_card.isHidden()
            and self.top_procs_card.isHidden()
        )
        self.sub_tabs.setVisible(has_net_page_items)
        if not has_net_page_items and self.sub_stack.currentIndex() != 0:
            self.sub_tabs.set_current_index(0)
            self.sub_stack.setCurrentIndex(0)
        if self._advanced_mode and feat.battery:
            self._rebuild_top_processes_list(force=False)

    def _create_info_item(self, grid: QGridLayout, row: int, col: int, label: str, default: str) -> QLabel:
        box = QFrame()
        box.setProperty("class", "subBox")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(4)
        box_layout.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel(label)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; font-weight: bold;")
        box_layout.addWidget(lbl)

        val_lbl = QLabel(default)
        val_lbl.setWordWrap(True)
        val_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.Bold))
        val_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        box_layout.addWidget(val_lbl)

        grid.addWidget(box, row, col)
        return val_lbl

    def _on_record_snapshot(self):
        entries = self.backend.record_battery_snapshot()
        self.health_chart.set_history(entries)
        self.refresh_display()

    def _on_conservation_toggled(self, checked: bool):
        success, msg = self.backend.set_conservation_mode(checked)
        if not success:
            self.toggle_switch.blockSignals(True)
            self.toggle_switch.setChecked(not checked)
            self.toggle_switch.blockSignals(False)
            QMessageBox.warning(
                self, "Permissão Necessária",
                f"Não foi possível alterar o Modo de Conservação:\n{msg}\n\n"
                "Para operar sem senha root, repare as Regras UDEV na aba 'Sobre o Dispositivo'."
            )
        else:
            if checked:
                self.toggle_rapid.blockSignals(True)
                self.toggle_rapid.setChecked(False)
                self.toggle_rapid.blockSignals(False)
            self.conservation_changed.emit(checked)
            self.refresh_display()

    def _on_rapid_charge_toggled(self, checked: bool):
        success, msg = self.backend.set_rapid_charge(checked)
        if not success:
            self.toggle_rapid.blockSignals(True)
            self.toggle_rapid.setChecked(not checked)
            self.toggle_rapid.blockSignals(False)
            QMessageBox.warning(self, "Permissão Necessária", f"Não foi possível alterar o Carregamento Rápido:\n{msg}")
        else:
            if checked:
                self.toggle_switch.blockSignals(True)
                self.toggle_switch.setChecked(False)
                self.toggle_switch.blockSignals(False)
            self.rapid_charge_changed.emit(checked)
            self.refresh_display()

    def _on_wifi_low_latency_toggled(self, low_latency_active: bool):
        # low_latency_active == True significa Power Save OFF (enable_saving = False)
        ok, msg = self.backend.set_wifi_power_saving(enable_saving=not low_latency_active)
        if not ok:
            self.sw_wifi_low_latency.blockSignals(True)
            self.sw_wifi_low_latency.setChecked(not low_latency_active)
            self.sw_wifi_low_latency.blockSignals(False)
            self.lbl_wifi_ps_desc.setText(msg)
            QMessageBox.warning(self, "Economia de Rede Wi-Fi", msg)
            return
        self.lbl_wifi_ps_desc.setText(msg)
        self.refresh_display()

    def _on_eth_power_save_toggled(self, enable_saving: bool):
        ok, msg = self.backend.set_ethernet_power_saving(enable_saving=enable_saving)
        self.lbl_eth_ps_desc.setText(msg)
        self.refresh_display()

    def _on_battery_alert_settings_changed(self, _val=None):
        alerts_on = self.sw_bat_alerts.isChecked()
        thr_c = float(self.slider_bat_temp_thr.value())
        self.backend.set_battery_alert_settings(alerts_on, alerts_on, thr_c)
        bat = self.backend.get_battery_info()
        self.lbl_bat_temp_thr.setText(
            f"Alerta Térmico da Bateria em Jogos: {int(thr_c)}°C (Atual: {bat.temperature_c:.1f}°C)"
        )

    def refresh_display(self):
        """Atualiza os controles, os 6 cards elétricos e o gráfico Battery Health Historian."""
        bat = self.backend.get_battery_info()

        # 1. Modo de Conservação
        if self.backend.features.conservation_mode:
            is_active = self.backend.get_conservation_mode()
            self.toggle_switch.blockSignals(True)
            self.toggle_switch.setChecked(is_active)
            self.toggle_switch.blockSignals(False)

            if is_active:
                self.cons_status_lbl.setText("ATIVO • Limite de proteção (~80%) habilitado no chip EC.")
                self.cons_status_lbl.setStyleSheet(f"color: {ThemeTokens.COLOR_SUCCESS}; font-weight: bold; font-size: 11px;")
            else:
                self.cons_status_lbl.setText("DESATIVADO • Carregamento completo até 100%.")
                self.cons_status_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        else:
            self.toggle_switch.setEnabled(False)
            self.cons_status_lbl.setText("Recurso não disponível neste modelo Lenovo.")

        # 2. Rapid Charge
        rapid_active = self.backend.get_rapid_charge()
        self.toggle_rapid.blockSignals(True)
        self.toggle_rapid.setChecked(rapid_active)
        self.toggle_rapid.blockSignals(False)
        if rapid_active:
            self.rapid_status_lbl.setText("ATIVO • Carregamento Rápido habilitado.")
            self.rapid_status_lbl.setStyleSheet(f"color: {ThemeTokens.COLOR_WARNING}; font-weight: bold; font-size: 11px;")
        else:
            self.rapid_status_lbl.setText("DESATIVADO • Velocidade de carga padrão.")
            self.rapid_status_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")

        # 3. Medidor Circular e 6 Cards Elétricos
        if bat.available:
            ac_str = "Tomada AC" if bat.ac_connected else "Na Bateria"
            est_sub = bat.estimated_label or f"{ac_str} • {bat.status}"
            self.bat_gauge.set_data(
                percent=float(bat.capacity_percent),
                center_val=f"{bat.energy_now_wh:.1f}",
                center_unit="Wh",
                bottom_sub=est_sub
            )

            raw_st = bat.status.strip()
            status_map = {
                "Charging": ("CARREGANDO (CHARGING)", ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN),
                "Discharging": ("DESCARREGANDO (DISCHARGING)", ThemeTokens.BG_CARD_HOVER, ThemeTokens.COLOR_WARNING),
                "Not charging": ("CONSERVAÇÃO / AC (NOT CHARGING)", ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL),
                "Full": ("CARGA COMPLETA (FULL)", ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN),
            }
            label_text, bg, fg = status_map.get(raw_st, (raw_st.upper(), ThemeTokens.BG_CARD_HOVER, ThemeTokens.TEXT_WHITE_80))
            self.status_pill.setText(label_text)
            self.status_pill.setColor(bg, fg)

            self.val_health.setText(f"{bat.health_percent:.1f}% ({bat.energy_full_wh:.1f} / {bat.energy_design_wh:.1f} Wh)")
            self.val_cycles.setText(f"{bat.cycle_count} ciclos ({bat.technology})")
            pwr_extra = f" • {bat.estimated_label}" if bat.estimated_label else f" ({raw_st})"
            self.val_power.setText(f"{bat.power_draw_w:.2f} W{pwr_extra}")
            self.val_voltage.setText(f"{bat.voltage_v:.2f} V")
            self.val_full_wh.setText(f"{bat.energy_now_wh:.2f} / {bat.energy_full_wh:.2f} Wh")
            self.val_design_wh.setText(f"{bat.energy_design_wh:.2f} Wh ({bat.manufacturer} {bat.model_name})")

            # 4. Atualizar Gráfico Battery Health Historian
            entries = self.backend.get_battery_history()
            self.health_chart.set_history(entries)
            wear_pct = max(0.0, 100.0 - bat.health_percent)
            cycles = max(1, bat.cycle_count)
            wear_per_cycle = wear_pct / float(cycles)
            cons_note = "Proteção ~80% Ativa" if bat.conservation_mode_active else "Ative o Modo de Conservação para reduzir desgaste"
            self.wear_summary_lbl.setText(
                f"Retenção Química: {bat.health_percent:.1f}% ({bat.energy_full_wh:.2f} Wh de {bat.energy_design_wh:.2f} Wh)  •  "
                f"Desgaste Médio: {wear_per_cycle:.3f}% por ciclo ({bat.cycle_count} ciclos)  •  {cons_note}"
            )

            life = self.backend.get_battery_lifecycle_status()
            if hasattr(self, "lifecycle_badge"):
                self.lifecycle_badge.setText(f"CICLO DE VIDA: {life['badge']} ({bat.temperature_c:.1f}°C)")
                self.lifecycle_badge.setColor(ThemeTokens.BG_CARD_HOVER, life["color"])
                self.lbl_lifecycle_rec.setText(life["recommendation"])
                thr_val = self.slider_bat_temp_thr.value()
                self.lbl_bat_temp_thr.setText(
                    f"Alerta Térmico da Bateria em Jogos: {thr_val}°C (Atual: {bat.temperature_c:.1f}°C)"
                )

        # 5. Atualizar Estado de Economia de Rede (independente de bateria)
        net_st = self.backend.get_network_power_status()
        has_wifi = bool(net_st.wifi_available and self.backend.features.wifi_power_save)
        has_eth = bool(net_st.eth_available and self.backend.features.eth_power_save)
        self._has_wifi = has_wifi
        self._has_eth = has_eth
        self.wifi_box.setVisible(has_wifi)
        self.eth_box.setVisible(bool(self._advanced_mode and has_eth))
        self.net_card.setVisible(bool(has_wifi or (self._advanced_mode and has_eth)))

        if has_wifi and hasattr(self, "sw_wifi_low_latency"):
            self.sw_wifi_low_latency.blockSignals(True)
            self.sw_wifi_low_latency.setChecked(not net_st.wifi_power_save_on)
            self.sw_wifi_low_latency.blockSignals(False)
            if not net_st.wifi_power_save_on:
                self.net_badge.setText(f"BAIXA LATÊNCIA ({net_st.wifi_iface.upper()})")
                self.net_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)
            else:
                self.net_badge.setText(f"ECONOMIA WI-FI ({net_st.wifi_iface.upper()})")
                self.net_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)
        elif has_eth:
            if net_st.eth_power_save_on:
                self.net_badge.setText(f"ECO ETHERNET ({net_st.eth_iface.upper()})")
                self.net_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.STATUS_GREEN)
            else:
                self.net_badge.setText(f"ETHERNET ATIVA ({net_st.eth_iface.upper()})")
                self.net_badge.setColor(ThemeTokens.BG_CARD_HOVER, ThemeTokens.ACCENT_STEEL)

        if has_eth and hasattr(self, "sw_eth_power_save"):
            self.sw_eth_power_save.blockSignals(True)
            self.sw_eth_power_save.setChecked(net_st.eth_power_save_on)
            self.sw_eth_power_save.blockSignals(False)

        if has_wifi and self._advanced_mode and hasattr(self, "wifi_rules_box"):
            self.wifi_rules_box.setVisible(True)
            self._refresh_wifi_rules_ui()
        elif hasattr(self, "wifi_rules_box"):
            self.wifi_rules_box.setVisible(False)

        if hasattr(self, "usb_wake_card"):
            self._refresh_usb_wakeup_ui()

        if self._advanced_mode and self.backend.features.battery and hasattr(self, "top_procs_card"):
            self._rebuild_top_processes_list(force=False)

    def _on_usb_wakeup_toggled(self, blocked: bool):
        ok, msg = self.backend.set_usb_wakeup_blocked(blocked, allow_elevation=True)
        if not ok:
            self.sw_usb_wakeup_block.blockSignals(True)
            self.sw_usb_wakeup_block.setChecked(not blocked)
            self.sw_usb_wakeup_block.blockSignals(False)
            QMessageBox.warning(self, "Wake-on-USB", msg)
        self._refresh_usb_wakeup_ui()

    def _refresh_usb_wakeup_ui(self):
        feat_usb = self.backend.features.usb_wakeup
        self.usb_wake_card.setVisible(bool(feat_usb))
        if not feat_usb:
            return
        devs = self.backend.get_usb_wakeup_devices()
        blocked = self.backend.get_usb_wakeup_blocked()
        self.sw_usb_wakeup_block.blockSignals(True)
        self.sw_usb_wakeup_block.setChecked(blocked)
        self.sw_usb_wakeup_block.blockSignals(False)
        self.usb_wake_badge.setText("BLOQUEADO (SEGURO)" if blocked else "WAKEUP LIBERADO")
        self.usb_wake_badge.setColor(
            ThemeTokens.BG_CARD_HOVER,
            ThemeTokens.STATUS_GREEN if blocked else ThemeTokens.STATUS_WARNING,
        )
        if devs:
            names = ", ".join(f"{d['name'][:26]} ({'ON' if d['enabled'] else 'OFF'})" for d in devs[:4])
            self.lbl_usb_wake_devices.setText(f"Dispositivos: {names}")

    def _on_fill_current_ssid(self):
        ssid = self.backend.get_current_wifi_ssid(force=True)
        if ssid:
            self.edit_wifi_ssid.setText(ssid)
        else:
            QMessageBox.information(self, "Wi-Fi SSID", "Nenhuma conexão Wi-Fi ativa foi detectada neste momento.")

    def _on_add_wifi_rule(self):
        ssid = self.edit_wifi_ssid.text().strip()
        prof, eco_mode, req_hz = self.combo_wifi_action.currentData() or ("balanced", False, 0)
        ok, msg = self.backend.add_wifi_power_rule(ssid, profile=prof, eco_mode=eco_mode, refresh_hz=req_hz)
        if not ok:
            QMessageBox.warning(self, "Regras Wi-Fi", msg)
            return
        self.edit_wifi_ssid.clear()
        self._refresh_wifi_rules_ui()

    def _refresh_wifi_rules_ui(self):
        cur_ssid = self.backend.get_current_wifi_ssid(force=False)
        self.lbl_cur_ssid.setText(f"Conectado: {cur_ssid}" if cur_ssid else "Wi-Fi desconectado")
        while self.wifi_rules_list_layout.count():
            item = self.wifi_rules_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rules = self.backend.get_wifi_power_rules()
        if not rules:
            lbl = QLabel("Nenhuma regra por Wi-Fi adicionada.")
            lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_40}; font-size: 10px;")
            self.wifi_rules_list_layout.addWidget(lbl)
            return
        for r in rules:
            ssid = str(r.get("ssid", ""))
            desc = "Eco-Mode" if r.get("eco_mode") else str(r.get("profile", "balanced")).upper()
            if int(r.get("refresh_hz", 0) or 0) > 0:
                desc += f" + {r['refresh_hz']}Hz"
            row_f = QFrame()
            row_f.setProperty("class", "subBox")
            rl = QHBoxLayout(row_f)
            rl.setContentsMargins(10, 6, 10, 6)
            rl.setSpacing(8)
            s_lbl = QLabel(ssid)
            s_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
            s_lbl.setStyleSheet(f"color: {ThemeTokens.ACCENT_STEEL}; min-width: 120px;")
            rl.addWidget(s_lbl)
            d_lbl = QLabel(desc)
            d_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
            rl.addWidget(d_lbl, stretch=1)
            sw = ToggleSwitch(checked=bool(r.get("enabled", True)))
            sw.toggled.connect(lambda chk, sid=ssid: self.backend.toggle_wifi_power_rule(sid, chk))
            rl.addWidget(sw)
            btn_rem = QPushButton("Remover")
            btn_rem.setProperty("class", "secondaryButton")
            btn_rem.setFixedHeight(24)
            btn_rem.clicked.connect(lambda _c=False, sid=ssid: self._on_remove_wifi_rule(sid))
            rl.addWidget(btn_rem)
            self.wifi_rules_list_layout.addWidget(row_f)

    def _on_remove_wifi_rule(self, ssid: str):
        self.backend.remove_wifi_power_rule(ssid)
        self._refresh_wifi_rules_ui()

    def _rebuild_top_processes_list(self, force: bool = False):
        if not hasattr(self, "top_procs_list_layout"):
            return
        while self.top_procs_list_layout.count():
            item = self.top_procs_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        procs = self.backend.get_top_power_processes(limit=5, force=force)
        if not procs:
            lbl = QLabel("Coletando amostra inicial de CPU dos processos...")
            lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
            self.top_procs_list_layout.addWidget(lbl)
            return
        for p in procs:
            row_f = QFrame()
            row_f.setProperty("class", "subBox")
            rl = QHBoxLayout(row_f)
            rl.setContentsMargins(12, 6, 12, 6)
            rl.setSpacing(10)
            n_lbl = QLabel(f"{p['name'][:26]}")
            n_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
            n_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 155px;")
            rl.addWidget(n_lbl)
            pid_lbl = QLabel(f"PID {p['pid']}")
            pid_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
            rl.addWidget(pid_lbl, stretch=1)
            ram_lbl = QLabel(f"{p['ram_mb']} MB")
            ram_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
            rl.addWidget(ram_lbl)
            cpu_lbl = QLabel(f"{p['cpu_percent']:.1f}% CPU  •  ~{p['est_watts']:.1f}W")
            cpu_lbl.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
            cpu_lbl.setStyleSheet(f"color: {ThemeTokens.ACCENT_STEEL};")
            rl.addWidget(cpu_lbl)
            self.top_procs_list_layout.addWidget(row_f)
