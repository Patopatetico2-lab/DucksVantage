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
    QFrame, QScrollArea, QPushButton, QSlider, Qt, Signal, QFont, QMessageBox,
    QPixmap, QPainter, QColor, QPen, QBrush, QLinearGradient, QPointF, QPainterPath
)
from core.models import BatteryHistoryEntry
from ui.theme_tokens import ThemeTokens
from ui.components import ToggleSwitch, StatusBadge
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
        painter.setBrush(QBrush(QColor("#0d1322")))
        painter.drawRoundedRect(bg_rect, 8, 8)

        if not self.entries:
            painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
            painter.setFont(QFont("Segoe UI", 10))
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
        painter.setFont(QFont("Segoe UI", 8))
        grid_steps = 4
        for i in range(grid_steps + 1):
            v = y_min + (y_max - y_min) * (i / float(grid_steps))
            yy = val_to_y(v)
            painter.setPen(QPen(QColor("#1e293b"), 1, Qt.PenStyle.DotLine))
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

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
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
            painter.setPen(QPen(QColor("#0b0f19"), 2))
            painter.setBrush(QBrush(QColor(ThemeTokens.STATUS_GREEN)))
            painter.drawEllipse(pt, 4.5, 4.5)

            # Valor de Wh e % acima do ponto
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(QColor(ThemeTokens.TEXT_WHITE_100))
            lbl_val = f"{entry.energy_full_wh:.1f}Wh ({entry.health_percent:.1f}%)"
            painter.drawText(
                int(pt.x() - 48), int(pt.y() - 20), 96, 16,
                int(Qt.AlignmentFlag.AlignCenter), lbl_val
            )

            # Rótulo inferior: Data curta + Ciclo
            short_date = entry.timestamp[-5:] if len(entry.timestamp) >= 5 else entry.timestamp
            x_lbl = f"{short_date}\nCiclo {entry.cycle_count}"
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
            painter.drawText(
                int(pt.x() - 38), int(pad_top + plot_h + 5), 76, 32,
                int(Qt.AlignmentFlag.AlignCenter), x_lbl
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

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(18)

        # =====================================================================
        # 1. Card de Controles de Carregamento (Exclusão Mútua)
        # =====================================================================
        cons_card = QFrame()
        cons_card.setProperty("class", "card")
        cons_layout = QVBoxLayout(cons_card)
        cons_layout.setContentsMargins(20, 18, 20, 18)
        cons_layout.setSpacing(14)

        # Modo de Conservação
        top_row = QHBoxLayout()
        icon_lbl = QLabel()
        cons_icon_path = os.path.join(ICON_DIR, "edge_conservation.svg")
        if os.path.exists(cons_icon_path):
            icon_lbl.setPixmap(QPixmap(cons_icon_path).scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        top_row.addWidget(icon_lbl)

        title_layout = QVBoxLayout()
        cons_title = QLabel("Modo de Conservação da Bateria (Conservation Mode ~80%)")
        cons_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        cons_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        title_layout.addWidget(cons_title)

        self.cons_status_lbl = QLabel("Suspende o carregamento entre 75% e 80% para preservar a vida útil das células.")
        self.cons_status_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        title_layout.addWidget(self.cons_status_lbl)

        top_row.addLayout(title_layout)
        top_row.addStretch()

        self.toggle_switch = ToggleSwitch()
        self.toggle_switch.setEnabled(self.backend.features.conservation_mode)
        self.toggle_switch.toggled.connect(self._on_conservation_toggled)
        top_row.addWidget(self.toggle_switch)
        cons_layout.addLayout(top_row)

        # Divisor
        div = QFrame()
        div.setStyleSheet(f"background-color: {ThemeTokens.BORDER_DEFAULT}; max-height: 1px;")
        cons_layout.addWidget(div)

        # Carregamento Rápido (Rapid Charge)
        rapid_row = QHBoxLayout()
        rapid_icon = QLabel()
        rapid_icon_path = os.path.join(ICON_DIR, "edge_rapid_charge.svg")
        if os.path.exists(rapid_icon_path):
            rapid_icon.setPixmap(QPixmap(rapid_icon_path).scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        rapid_row.addWidget(rapid_icon)

        rapid_title_layout = QVBoxLayout()
        rapid_title = QLabel("Carregamento Rápido (Rapid Charge)")
        rapid_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        rapid_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        rapid_title_layout.addWidget(rapid_title)

        self.rapid_status_lbl = QLabel("Eleva a taxa de carregamento até 100% (mutuamente exclusivo com o Modo de Conservação).")
        self.rapid_status_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        rapid_title_layout.addWidget(self.rapid_status_lbl)

        rapid_row.addLayout(rapid_title_layout)
        rapid_row.addStretch()

        self.toggle_rapid = ToggleSwitch()
        self.toggle_rapid.setEnabled(self.backend.features.rapid_charge)
        self.toggle_rapid.toggled.connect(self._on_rapid_charge_toggled)
        rapid_row.addWidget(self.toggle_rapid)
        cons_layout.addLayout(rapid_row)

        layout.addWidget(cons_card)

        # =====================================================================
        # 2. Card de Diagnóstico Elétrico com CircularGauge + 6 Cards Elétricos
        # =====================================================================
        health_card = QFrame()
        health_card.setProperty("class", "card")
        health_layout = QVBoxLayout(health_card)
        health_layout.setContentsMargins(20, 18, 20, 18)
        health_layout.setSpacing(16)

        header_health = QHBoxLayout()
        h_icon = QLabel()
        bat_icon_path = os.path.join(ICON_DIR, "power.svg")
        if os.path.exists(bat_icon_path):
            h_icon.setPixmap(QPixmap(bat_icon_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header_health.addWidget(h_icon)

        h_title = QLabel("Diagnóstico Elétrico e Saúde da Bateria (/sys/class/power_supply/BAT*)")
        h_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        h_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        header_health.addWidget(h_title)

        header_health.addStretch()

        self.status_pill = StatusBadge("STATUS", bg_color="#1e293b", text_color="#38bdf8")
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

        layout.addWidget(health_card)

        # =====================================================================
        # 3. ELITE 3: Battery Health Historian (Gráfico de Saúde e Degradação)
        # =====================================================================
        hist_card = QFrame()
        hist_card.setProperty("class", "card")
        hist_layout = QVBoxLayout(hist_card)
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
        hist_title = QLabel("Battery Health Historian • Curva de Degradação & Eficiência da Conservação")
        hist_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        hist_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        hist_title_col.addWidget(hist_title)

        self.hist_sub_lbl = QLabel(
            "Comparativo histórico entre a Capacidade de Fábrica (energy_full_design) e a Capacidade Máxima Real (energy_full)."
        )
        self.hist_sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        hist_title_col.addWidget(self.hist_sub_lbl)
        hist_header.addLayout(hist_title_col)
        hist_header.addStretch()

        self.btn_snapshot = QPushButton("Registrar Leitura Agora")
        self.btn_snapshot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_snapshot.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                color: {ThemeTokens.BORDER_CYAN};
                border: 1px solid {ThemeTokens.BORDER_CYAN};
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.BORDER_CYAN};
                color: #0b0f19;
            }}
        """)
        self.btn_snapshot.clicked.connect(self._on_record_snapshot)
        hist_header.addWidget(self.btn_snapshot)

        hist_layout.addLayout(hist_header)

        self.health_chart = BatteryHealthChart()
        hist_layout.addWidget(self.health_chart)

        # Rodapé analítico de desgaste por ciclo
        self.wear_summary_lbl = QLabel("")
        self.wear_summary_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.wear_summary_lbl.setStyleSheet(f"color: {ThemeTokens.STATUS_GREEN};")
        hist_layout.addWidget(self.wear_summary_lbl)

        layout.addWidget(hist_card)

        # =====================================================================
        # 4. NOVA FUNCIONALIDADE 4: Controle de Economia de Energia de Rede (Wi-Fi / Ethernet)
        # =====================================================================
        net_status = self.backend.get_network_power_status()
        net_card = QFrame()
        net_card.setProperty("class", "card")
        net_layout = QVBoxLayout(net_card)
        net_layout.setContentsMargins(20, 18, 20, 18)
        net_layout.setSpacing(14)

        net_header = QHBoxLayout()
        ic_net = QLabel()
        p_net = os.path.join(ICON_DIR, "network_power.svg")
        if os.path.exists(p_net):
            ic_net.setPixmap(QPixmap(p_net).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        net_header.addWidget(ic_net)

        net_titles = QVBoxLayout()
        nt_lbl = QLabel(
            f"Controle de Economia de Energia de Rede • Wi-Fi ({net_status.wifi_iface} / {net_status.wifi_driver}) & Ethernet ({net_status.eth_iface})"
        )
        nt_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        nt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        net_titles.addWidget(nt_lbl)

        nt_sub = QLabel(
            "Desative o Power Saving do Wi-Fi para eliminar picos de ping e perda de pacotes em jogos competitivos online, ou ative para poupar bateria."
        )
        nt_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        net_titles.addWidget(nt_sub)
        net_header.addLayout(net_titles)
        net_header.addStretch()

        self.net_badge = StatusBadge("REDE OTIMIZADA", bg_color="#155e75", text_color="#38bdf8")
        net_header.addWidget(self.net_badge)
        net_layout.addLayout(net_header)

        # Toggle 1: Modo Jogos Online (Wi-Fi Power Save OFF / Baixa Latência)
        wifi_box = QFrame()
        wifi_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        wifi_row = QHBoxLayout(wifi_box)
        wifi_row.setContentsMargins(8, 6, 8, 6)

        w_info = QVBoxLayout()
        w_title = QLabel(f"Modo Jogos Online Wi-Fi • Baixa Latência ({net_status.wifi_iface} Power Save OFF)")
        w_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        w_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        w_info.addWidget(w_title)

        self.lbl_wifi_ps_desc = QLabel(
            "Quando ativado, desliga a suspensão IEEE 802.11 da placa Wi-Fi para manter latência mínima constante."
        )
        self.lbl_wifi_ps_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        w_info.addWidget(self.lbl_wifi_ps_desc)
        wifi_row.addLayout(w_info)
        wifi_row.addStretch()

        self.sw_wifi_low_latency = ToggleSwitch()
        self.sw_wifi_low_latency.setChecked(not net_status.wifi_power_save_on)
        self.sw_wifi_low_latency.toggled.connect(self._on_wifi_low_latency_toggled)
        wifi_row.addWidget(self.sw_wifi_low_latency)
        net_layout.addWidget(wifi_box)

        # Toggle 2: Economia de Energia PCIe Ethernet Gigabit
        eth_box = QFrame()
        eth_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        eth_row = QHBoxLayout(eth_box)
        eth_row.setContentsMargins(8, 6, 8, 6)

        e_info = QVBoxLayout()
        e_title = QLabel(f"Economia de Energia Ethernet Gigabit PCIe ({net_status.eth_iface} / {net_status.eth_driver})")
        e_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        e_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        e_info.addWidget(e_title)

        self.lbl_eth_ps_desc = QLabel(
            "Suspende automaticamente o controlador Ethernet PCIe (Runtime PM = auto) quando o cabo RJ-45 estiver desconectado."
        )
        self.lbl_eth_ps_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        e_info.addWidget(self.lbl_eth_ps_desc)
        eth_row.addLayout(e_info)
        eth_row.addStretch()

        self.sw_eth_power_save = ToggleSwitch()
        self.sw_eth_power_save.setChecked(net_status.eth_power_save_on)
        self.sw_eth_power_save.toggled.connect(self._on_eth_power_save_toggled)
        eth_row.addWidget(self.sw_eth_power_save)
        net_layout.addWidget(eth_box)

        layout.addWidget(net_card)

        # =====================================================================
        # 5. NOVA FUNCIONALIDADE 5: Monitor de Ciclo de Vida e Alertas Inteligentes da Bateria
        # =====================================================================
        alert_cfg = self.backend.get_battery_alert_settings()
        life_status = self.backend.get_battery_lifecycle_status()

        alert_card = QFrame()
        alert_card.setProperty("class", "card")
        alert_layout = QVBoxLayout(alert_card)
        alert_layout.setContentsMargins(20, 18, 20, 18)
        alert_layout.setSpacing(14)

        alert_header = QHBoxLayout()
        ic_al = QLabel()
        p_al = os.path.join(ICON_DIR, "battery_alert.svg")
        if os.path.exists(p_al):
            ic_al.setPixmap(QPixmap(p_al).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        alert_header.addWidget(ic_al)

        al_titles = QVBoxLayout()
        al_t = QLabel("Monitor de Ciclo de Vida & Alertas Inteligentes (Bandeja KDE Plasma)")
        al_t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        al_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        al_titles.addWidget(al_t)

        self.lbl_lifecycle_rec = QLabel(life_status["recommendation"])
        self.lbl_lifecycle_rec.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        al_titles.addWidget(self.lbl_lifecycle_rec)
        alert_header.addLayout(al_titles)
        alert_header.addStretch()

        self.lifecycle_badge = StatusBadge(
            f"CICLO DE VIDA: {life_status['badge']}",
            bg_color="#064e3b",
            text_color=life_status["color"]
        )
        alert_header.addWidget(self.lifecycle_badge)
        alert_layout.addLayout(alert_header)

        # Linha 1: Notificações Inteligentes na Bandeja + Alerta de 80%
        al_box1 = QFrame()
        al_box1.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        al_row1 = QHBoxLayout(al_box1)
        al_row1.setContentsMargins(8, 6, 8, 6)

        a1_info = QVBoxLayout()
        a1_title = QLabel("Notificar na Bandeja do KDE Plasma ao Atingir 80% (Modo de Conservação)")
        a1_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        a1_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        a1_info.addWidget(a1_title)

        a1_sub = QLabel(
            "Envia alerta nativo quando a carga estaciona em 80% na tomada ou quando há eventos críticos de ciclo de vida."
        )
        a1_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        a1_info.addWidget(a1_sub)
        al_row1.addLayout(a1_info)
        al_row1.addStretch()

        self.sw_bat_alerts = ToggleSwitch()
        self.sw_bat_alerts.setChecked(bool(alert_cfg["alerts_enabled"] and alert_cfg["alert_80_enabled"]))
        self.sw_bat_alerts.toggled.connect(self._on_battery_alert_settings_changed)
        al_row1.addWidget(self.sw_bat_alerts)
        alert_layout.addWidget(al_box1)

        # Linha 2: Limite de Alerta Térmico da Bateria (°C) + Botão Testar Alerta
        al_box2 = QFrame()
        al_box2.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        al_row2 = QHBoxLayout(al_box2)
        al_row2.setContentsMargins(8, 6, 8, 6)
        al_row2.setSpacing(14)

        init_temp_thr = int(round(alert_cfg["temp_threshold_c"]))
        self.lbl_bat_temp_thr = QLabel(
            f"Alerta Térmico da Bateria em Jogos: {init_temp_thr}°C (Atual: {life_status['temperature_c']:.1f}°C)"
        )
        self.lbl_bat_temp_thr.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
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
                background-color: #192338;
                color: {ThemeTokens.BORDER_CYAN};
                border: 1px solid {ThemeTokens.BORDER_CYAN};
                border-radius: 6px;
                padding: 4px 14px;
                font-weight: bold;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.BORDER_CYAN};
                color: #0b0f19;
            }}
        """)
        self.btn_test_bat_alert.clicked.connect(lambda _c: self.test_alert_requested.emit())
        al_row2.addWidget(self.btn_test_bat_alert)

        alert_layout.addWidget(al_box2)
        layout.addWidget(alert_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.refresh_display()

    def _create_info_item(self, grid: QGridLayout, row: int, col: int, label: str, default: str) -> QLabel:
        box = QFrame()
        box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 12px;")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(4)
        box_layout.setContentsMargins(10, 8, 10, 8)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; font-weight: bold;")
        box_layout.addWidget(lbl)

        val_lbl = QLabel(default)
        val_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
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
            self.bat_gauge.set_data(
                percent=float(bat.capacity_percent),
                center_val=f"{bat.energy_now_wh:.1f}",
                center_unit="Wh",
                bottom_sub=f"{ac_str} • {bat.status}"
            )

            raw_st = bat.status.strip()
            status_map = {
                "Charging": ("CARREGANDO (CHARGING)", "#064e3b", "#34d399"),
                "Discharging": ("DESCARREGANDO (DISCHARGING)", "#78350f", "#fbbf24"),
                "Not charging": ("CONSERVAÇÃO / AC (NOT CHARGING)", "#0369a1", "#38bdf8"),
                "Full": ("CARGA COMPLETA (FULL)", "#064e3b", "#34d399"),
            }
            label_text, bg, fg = status_map.get(raw_st, (raw_st.upper(), "#1e293b", "#cbd5e1"))
            self.status_pill.setText(label_text)
            self.status_pill.setColor(bg, fg)

            self.val_health.setText(f"{bat.health_percent:.1f}% ({bat.energy_full_wh:.1f} / {bat.energy_design_wh:.1f} Wh)")
            self.val_cycles.setText(f"{bat.cycle_count} ciclos ({bat.technology})")
            self.val_power.setText(f"{bat.power_draw_w:.2f} W ({raw_st})")
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

            # 5. Atualizar Estado de Economia de Rede e Ciclo de Vida
            net_st = self.backend.get_network_power_status()
            if hasattr(self, "sw_wifi_low_latency"):
                self.sw_wifi_low_latency.blockSignals(True)
                self.sw_wifi_low_latency.setChecked(not net_st.wifi_power_save_on)
                self.sw_wifi_low_latency.blockSignals(False)
                if not net_st.wifi_power_save_on:
                    self.net_badge.setText(f"BAIXA LATÊNCIA ({net_st.wifi_iface.upper()})")
                    self.net_badge.setColor("#581c87", "#e9d5ff")
                else:
                    self.net_badge.setText(f"ECONOMIA WI-FI ({net_st.wifi_iface.upper()})")
                    self.net_badge.setColor("#155e75", "#38bdf8")

            if hasattr(self, "sw_eth_power_save"):
                self.sw_eth_power_save.blockSignals(True)
                self.sw_eth_power_save.setChecked(net_st.eth_power_save_on)
                self.sw_eth_power_save.blockSignals(False)

            life = self.backend.get_battery_lifecycle_status()
            if hasattr(self, "lifecycle_badge"):
                self.lifecycle_badge.setText(f"CICLO DE VIDA: {life['badge']} ({bat.temperature_c:.1f}°C)")
                self.lifecycle_badge.setColor("#064e3b", life["color"])
                self.lbl_lifecycle_rec.setText(life["recommendation"])
                thr_val = self.slider_bat_temp_thr.value()
                self.lbl_bat_temp_thr.setText(
                    f"Alerta Térmico da Bateria em Jogos: {thr_val}°C (Atual: {bat.temperature_c:.1f}°C)"
                )
