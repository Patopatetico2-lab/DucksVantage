"""
Aba Desempenho Avançado & Gestão Térmica do Ducksvantage (ui/tabs/performance_tab.py).
Inclui:
1. Editor Interativo de Curva de Ventoinhas (Fan Curve Editor: Temperatura °C vs PWM% / RPM arrastável)
   conectado ao Embedded Controller (EC) e limites térmicos Lenovo WMI Other.
2. Overclock e Undervolt Dinâmico (Intel HX MSR 0x150 / AMD Curve Optimizer + WMI AC Offset)
   com Mecanismo de Segurança Watchdog (15s) e Reset de Emergência imediato (0 mV).
3. Gerenciador de Perfis de Energia por Aplicativo (App Rules) integrado ao daemon de Auto-Switching.
4. Controle de CPU Turbo Boost, CPU Scaling Governor e Limites TDP PL1/PL2 via Intel RAPL.
5. Mapeador de Teclas Personalizadas / Remapper (Tecla Copilot F23, F24 e Atalhos).
6. Monitoramento Detalhado da GPU (Estado D3cold / Ativa, Clock, VRAM, Potência e P-State) e Perfis ACPI.
Zero emojis: utiliza exclusivamente ícones vetoriais SVG.
"""

import os
from typing import Dict, Any, List, Tuple, Optional
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QSlider, QComboBox, QLineEdit,
    Qt, QTimer, Signal, QFont, QMessageBox, QPixmap, QKeySequence,
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPointF, QPainterPath
)
from ui.theme_tokens import ThemeTokens
from ui.components import ProfileCard, ToggleSwitch, StatusBadge

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")

AVAILABLE_KEY_ACTIONS: List[Tuple[str, str]] = [
    ("cycle_profile", "Alternar Modo Térmico (Ciclo com OSD)"),
    ("toggle_max_power", "Ativar / Desativar Desempenho Máximo (Max-Power)"),
    ("toggle_eco_mode", "Ativar / Desativar Modo Viagem (Eco-Mode Extremo)"),
    ("toggle_window", "Abrir / Minimizar Janela do Ducksvantage"),
    ("toggle_conservation", "Ativar / Desativar Conservação da Bateria (80%)"),
    ("toggle_mic_mute", "Silenciar / Ativar Microfone (Mute Mic)"),
    ("toggle_touchpad", "Bloquear / Desbloquear Touchpad"),
    ("custom_command", "Executar Comando ou Script Personalizado"),
]

PROFILE_COMBO_ITEMS: List[Tuple[str, str]] = [
    ("max-power", "Desempenho Máximo (Max-Power)"),
    ("performance", "Modo Desempenho (Performance)"),
    ("balanced", "Modo Equilibrado (Balanced)"),
    ("low-power", "Modo Silencioso (Economia)"),
]


class FanCurveWidget(QWidget):
    """
    Editor Vetorial Interativo em QPainter da Curva de Ventoinhas (Temperatura °C vs PWM% / RPM).
    Permite arrastar os pontos de controle com o mouse para definir curvas personalizadas
    (incluindo modo passivo 0% / 0 RPM em baixas temperaturas e rampa agressiva para jogos).
    """
    curve_changed = Signal(list)

    MAX_RPM = 5500.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = "balanced"
        self.cpu_temp_c = 45.0
        self.fan1_rpm = 0
        self.fan2_rpm = 0
        self.custom_enabled = False
        self.custom_points: List[List[int]] = [
            [35, 0],
            [48, 25],
            [60, 45],
            [72, 70],
            [82, 90],
            [92, 100],
        ]
        self._drag_index: int = -1
        self._hover_index: int = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(235)

    def set_custom_curve(self, points: List[List[int]], enabled: bool):
        if points and len(points) >= 3:
            self.custom_points = [[int(p[0]), max(0, min(100, int(p[1])))] for p in points]
            self.custom_points.sort(key=lambda x: x[0])
        self.custom_enabled = bool(enabled)
        self.update()

    def get_custom_points(self) -> List[List[int]]:
        return [[int(p[0]), int(p[1])] for p in self.custom_points]

    def update_state(self, profile: str, cpu_temp_c: float, fan1_rpm: int, fan2_rpm: int):
        self.profile = profile.lower().strip()
        self.cpu_temp_c = cpu_temp_c
        self.fan1_rpm = fan1_rpm
        self.fan2_rpm = fan2_rpm
        self.update()

    def _plot_bounds(self) -> Tuple[float, float, float, float]:
        w = float(self.width())
        h = float(self.height())
        pad_left = 72.0
        pad_right = 24.0
        pad_top = 36.0
        pad_bottom = 34.0
        plot_w = max(60.0, w - pad_left - pad_right)
        plot_h = max(50.0, h - pad_top - pad_bottom)
        return pad_left, pad_top, plot_w, plot_h

    def _temp_to_x(self, t_c: float) -> float:
        pad_left, _, plot_w, _ = self._plot_bounds()
        norm = (max(30.0, min(100.0, t_c)) - 30.0) / 70.0
        return pad_left + norm * plot_w

    def _pwm_to_y(self, pwm_pct: float) -> float:
        _, pad_top, _, plot_h = self._plot_bounds()
        norm = max(0.0, min(100.0, pwm_pct)) / 100.0
        return pad_top + plot_h * (1.0 - norm)

    def _x_to_temp(self, x: float) -> int:
        pad_left, _, plot_w, _ = self._plot_bounds()
        norm = max(0.0, min(1.0, (x - pad_left) / plot_w))
        return int(round(30.0 + norm * 70.0))

    def _y_to_pwm(self, y: float) -> int:
        _, pad_top, _, plot_h = self._plot_bounds()
        norm = 1.0 - max(0.0, min(1.0, (y - pad_top) / plot_h))
        return int(round(norm * 100.0))

    def _get_active_curve_pwm(self) -> Tuple[List[List[int]], str, str]:
        """Retorna os pontos [Temp °C, PWM %], cor de destaque e título da curva exibida."""
        if self.custom_enabled:
            return (
                self.custom_points,
                ThemeTokens.THERMAL_CUSTOM,
                "Curva Customizada Interativa (EC Ativo • Arraste os Pontos)"
            )
        if "max" in self.profile:
            return (
                [[30, 40], [45, 56], [60, 75], [75, 90], [90, 98], [100, 100]],
                ThemeTokens.THERMAL_CUSTOM,
                "Curva Extrema (Max-Power • Clique em um Ponto para Customizar)"
            )
        if "perf" in self.profile:
            return (
                [[30, 30], [45, 45], [60, 62], [75, 80], [90, 92], [100, 96]],
                ThemeTokens.THERMAL_PERFORMANCE,
                "Curva Agressiva (Performance • Clique em um Ponto para Customizar)"
            )
        if "low" in self.profile or "quiet" in self.profile:
            return (
                [[30, 0], [45, 0], [58, 28], [72, 42], [85, 55], [100, 65]],
                ThemeTokens.THERMAL_QUIET,
                "Curva Silenciosa 0 RPM (Low-Power • Clique em um Ponto para Customizar)"
            )
        return (
            [[35, 0], [48, 25], [60, 45], [72, 70], [82, 90], [92, 100]],
            ThemeTokens.THERMAL_BALANCED,
            "Curva Dinâmica EC (Balanced • Arraste qualquer Ponto para Editar)"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position() if hasattr(event, "position") else QPointF(event.pos())
            pts = self.custom_points
            for idx, (t, pwm) in enumerate(pts):
                px = self._temp_to_x(t)
                py = self._pwm_to_y(pwm)
                if ((pos.x() - px) ** 2 + (pos.y() - py) ** 2) <= 196.0:
                    self._drag_index = idx
                    if not self.custom_enabled:
                        self.custom_enabled = True
                    self.update()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else QPointF(event.pos())
        if self._drag_index >= 0:
            idx = self._drag_index
            new_pwm = self._y_to_pwm(pos.y())
            new_temp = self._x_to_temp(pos.x())

            min_t = 30 if idx == 0 else self.custom_points[idx - 1][0] + 3
            max_t = 100 if idx == len(self.custom_points) - 1 else self.custom_points[idx + 1][0] - 3
            clamped_t = max(min_t, min(max_t, new_temp))
            clamped_pwm = max(0, min(100, new_pwm))

            self.custom_points[idx] = [clamped_t, clamped_pwm]
            self.update()
            return

        # Atualizar hover sobre os pontos de controle
        found_hover = -1
        for idx, (t, pwm) in enumerate(self.custom_points):
            px = self._temp_to_x(t)
            py = self._pwm_to_y(pwm)
            if ((pos.x() - px) ** 2 + (pos.y() - py) ** 2) <= 196.0:
                found_hover = idx
                break

        if found_hover != self._hover_index:
            self._hover_index = found_hover
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if found_hover >= 0 else Qt.CursorShape.ArrowCursor
            )
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_index >= 0:
            self._drag_index = -1
            self.curve_changed.emit(self.get_custom_points())
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(ThemeTokens.BORDER_DEFAULT), 1))
        painter.setBrush(QBrush(QColor("#0d1322")))
        painter.drawRoundedRect(rect, 8, 8)

        pad_left, pad_top, plot_w, plot_h = self._plot_bounds()

        # Grade horizontal (PWM % e RPM estimado)
        painter.setFont(QFont("Segoe UI", 8))
        for pwm_val in (0, 25, 50, 75, 100):
            yy = self._pwm_to_y(pwm_val)
            rpm_est = int(round((pwm_val / 100.0) * self.MAX_RPM))
            painter.setPen(QPen(QColor("#1e293b"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(pad_left), int(yy), int(pad_left + plot_w), int(yy))
            painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
            label_y = "0% (0 RPM)" if pwm_val == 0 else f"{pwm_val}% ({rpm_est // 100 * 100})"
            painter.drawText(
                4, int(yy - 8), int(pad_left - 8), 16,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                label_y
            )

        # Grade vertical (Temperatura °C)
        for t_val in (30, 45, 60, 75, 90, 100):
            xx = self._temp_to_x(t_val)
            painter.setPen(QPen(QColor("#1e293b"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(xx), int(pad_top), int(xx), int(pad_top + plot_h))
            painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
            painter.drawText(
                int(xx - 20), int(pad_top + plot_h + 6), 40, 18,
                int(Qt.AlignmentFlag.AlignCenter), f"{t_val}°C"
            )

        curve_pts, accent_hex, curve_title = self._get_active_curve_pwm()
        # Quando custom_enabled estiver desativado, ainda mostramos os pontos customizáveis para o usuário poder arrastar
        draw_pts = self.custom_points if self.custom_enabled else curve_pts
        qpoints = [QPointF(self._temp_to_x(t), self._pwm_to_y(pwm)) for t, pwm in draw_pts]

        # Área sob a curva
        area = QPainterPath()
        area.moveTo(qpoints[0].x(), pad_top + plot_h)
        for pt in qpoints:
            area.lineTo(pt.x(), pt.y())
        area.lineTo(qpoints[-1].x(), pad_top + plot_h)
        area.closeSubpath()

        grad = QLinearGradient(0, pad_top, 0, pad_top + plot_h)
        c1 = QColor(accent_hex)
        c1.setAlpha(90)
        c2 = QColor(accent_hex)
        c2.setAlpha(8)
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        painter.fillPath(area, QBrush(grad))

        # Linha da curva
        path = QPainterPath()
        path.moveTo(qpoints[0])
        for pt in qpoints[1:]:
            path.lineTo(pt)
        painter.setPen(QPen(QColor(accent_hex), 2.6))
        painter.drawPath(path)

        # Desenhar nós interativos arrastáveis
        for idx, ((t, pwm), pt) in enumerate(zip(draw_pts, qpoints)):
            is_active_node = (idx == self._drag_index or idx == self._hover_index)
            radius = 7.5 if is_active_node else 5.2
            if is_active_node:
                halo = QColor(accent_hex)
                halo.setAlpha(95)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(halo))
                painter.drawEllipse(pt, 12.0, 12.0)

            painter.setPen(QPen(QColor("#0b0f19"), 2.0))
            painter.setBrush(QBrush(QColor("#ffffff" if is_active_node else accent_hex)))
            painter.drawEllipse(pt, radius, radius)

            # Rótulo do ponto quando arrastado ou sob o mouse
            if is_active_node:
                rpm_pt = int(round((pwm / 100.0) * self.MAX_RPM))
                tag = f"{t}°C • {pwm}% (~{rpm_pt} RPM)"
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    int(pt.x() - 55), int(max(pad_top - 4, pt.y() - 22)), 110, 16,
                    int(Qt.AlignmentFlag.AlignCenter), tag
                )

        # Ponto de operação em tempo real (Temperatura atual da CPU vs PWM/RPM real)
        live_rpm = float(max(self.fan1_rpm, self.fan2_rpm))
        if live_rpm > 0:
            live_pwm = min(100.0, (live_rpm / self.MAX_RPM) * 100.0)
        else:
            live_pwm = 0.0
            for i in range(len(draw_pts) - 1):
                t0, p0 = draw_pts[i]
                t1, p1 = draw_pts[i + 1]
                if t0 <= self.cpu_temp_c <= t1:
                    ratio = (self.cpu_temp_c - t0) / max(1.0, float(t1 - t0))
                    live_pwm = p0 + ratio * (p1 - p0)
                    break
            if self.cpu_temp_c >= draw_pts[-1][0]:
                live_pwm = float(draw_pts[-1][1])
            live_rpm = (live_pwm / 100.0) * self.MAX_RPM

        op_pt = QPointF(self._temp_to_x(self.cpu_temp_c), self._pwm_to_y(live_pwm))
        glow = QColor(ThemeTokens.STATUS_GREEN)
        glow.setAlpha(85)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(op_pt, 10.0, 10.0)

        painter.setPen(QPen(QColor("#0b0f19"), 2))
        painter.setBrush(QBrush(QColor(ThemeTokens.STATUS_GREEN)))
        painter.drawEllipse(op_pt, 5.2, 5.2)

        # Cabeçalho interno do gráfico
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QColor(accent_hex))
        painter.drawText(int(pad_left + 4), 22, curve_title)

        rpm_label = (
            f"Fan 1: {self.fan1_rpm} RPM | Fan 2: {self.fan2_rpm} RPM ({self.cpu_temp_c:.1f}°C)"
            if (self.fan1_rpm > 0 or self.fan2_rpm > 0)
            else f"Operação Atual: {self.cpu_temp_c:.1f}°C -> {int(round(live_pwm))}% PWM (~{int(live_rpm)} RPM)"
        )
        painter.setPen(QColor(ThemeTokens.STATUS_GREEN))
        painter.drawText(
            int(pad_left), 8, int(plot_w), 18,
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            rpm_label
        )

        painter.end()


class KeyCaptureButton(QPushButton):
    """Botão interativo que captura a próxima tecla/atalho pressionado (ex: F23 / Tecla Copilot)."""
    shortcut_captured = Signal(str)

    def __init__(self, initial_shortcut: str = "F23", parent=None):
        super().__init__(initial_shortcut, parent)
        self._capturing = False
        self._current_seq = initial_shortcut
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self.setMinimumWidth(110)
        self.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.clicked.connect(self._start_capture)
        self._update_style()

    def _start_capture(self):
        self._capturing = True
        self.setText("Pressione tecla...")
        self._update_style()
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return

        if key == Qt.Key.Key_Escape:
            self._capturing = False
            self.setText(self._current_seq)
            self._update_style()
            return

        seq = QKeySequence(event.modifiers().value | key).toString()
        if not seq:
            seq = "F23"
        self._current_seq = seq
        self._capturing = False
        self.setText(seq)
        self._update_style()
        self.shortcut_captured.emit(seq)

    def _update_style(self):
        if self._capturing:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ThemeTokens.THERMAL_CUSTOM};
                    color: #ffffff;
                    border: 1px solid {ThemeTokens.THERMAL_CUSTOM};
                    border-radius: 6px;
                    padding: 4px 10px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #192338;
                    color: {ThemeTokens.BORDER_CYAN};
                    border: 1px solid {ThemeTokens.BORDER_CYAN};
                    border-radius: 6px;
                    padding: 4px 10px;
                }}
                QPushButton:hover {{
                    background-color: {ThemeTokens.BORDER_CYAN};
                    color: #0b0f19;
                }}
            """)


class PerformanceTab(QWidget):
    """Controles avançados de desempenho de CPU, Fan Curve Editor, Undervolt, App Rules, GPU e Perfis ACPI."""
    profile_changed = Signal(str)
    shortcuts_updated = Signal()
    custom_action_requested = Signal(str, str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.cards = {}
        self.gov_buttons = {}
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
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(18)

        # =====================================================================
        # 1. Controles Avançados da CPU (Turbo Boost + Scaling Governor)
        # =====================================================================
        cpu_card = QFrame()
        cpu_card.setProperty("class", "card")
        cpu_layout = QVBoxLayout(cpu_card)
        cpu_layout.setContentsMargins(20, 18, 20, 18)
        cpu_layout.setSpacing(14)

        cpu_header = QHBoxLayout()
        ic_cpu = QLabel()
        p_cpu = os.path.join(ICON_DIR, "turbo.svg")
        if os.path.exists(p_cpu):
            ic_cpu.setPixmap(QPixmap(p_cpu).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        cpu_header.addWidget(ic_cpu)

        cpu_titles = QVBoxLayout()
        self.cpu_title_lbl = QLabel(f"Controle Avançado de Processador • {self.backend.system_info.cpu_model}")
        self.cpu_title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.cpu_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        cpu_titles.addWidget(self.cpu_title_lbl)

        cpu_sub = QLabel("Ajuste direto de frequências dinâmicas (Turbo Boost) e governador do escalonador Linux.")
        cpu_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        cpu_titles.addWidget(cpu_sub)
        cpu_header.addLayout(cpu_titles)
        cpu_header.addStretch()

        self.cpu_freq_badge = StatusBadge("-- MHz", bg_color="#1e293b", text_color="#00d2ff")
        cpu_header.addWidget(self.cpu_freq_badge)
        cpu_layout.addLayout(cpu_header)

        # Linha 1: Chave CPU Turbo Boost
        turbo_box = QFrame()
        turbo_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        turbo_row = QHBoxLayout(turbo_box)
        turbo_row.setContentsMargins(8, 6, 8, 6)

        t_info = QVBoxLayout()
        t_lbl = QLabel("CPU Turbo Boost (Intel P-State / AMD Core Performance Boost)")
        t_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        t_info.addWidget(t_lbl)

        self.turbo_desc_lbl = QLabel("Permite que o processador alcance frequências máximas acima do clock base.")
        self.turbo_desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        t_info.addWidget(self.turbo_desc_lbl)
        turbo_row.addLayout(t_info)
        turbo_row.addStretch()

        self.turbo_switch = ToggleSwitch()
        self.turbo_switch.setEnabled(self.backend.features.turbo_boost)
        self.turbo_switch.toggled.connect(self._on_turbo_toggled)
        turbo_row.addWidget(self.turbo_switch)
        cpu_layout.addWidget(turbo_box)

        # Linha 2: Seletor de CPU Scaling Governor
        gov_box = QFrame()
        gov_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        gov_row = QHBoxLayout(gov_box)
        gov_row.setContentsMargins(8, 6, 8, 6)

        g_info = QVBoxLayout()
        g_lbl = QLabel("CPU Scaling Governor (/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor)")
        g_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        g_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        g_info.addWidget(g_lbl)

        g_desc = QLabel("Define a política de escalonamento de frequência de todos os núcleos.")
        g_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        g_info.addWidget(g_desc)
        gov_row.addLayout(g_info)
        gov_row.addStretch()

        avail_govs = self.backend.get_available_cpu_governors()
        for gov_name in ("powersave", "performance"):
            if gov_name in avail_govs or not avail_govs:
                btn = QPushButton(gov_name.upper())
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setFixedHeight(30)
                btn.setMinimumWidth(115)
                btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                btn.clicked.connect(lambda checked, g=gov_name: self._on_governor_selected(g))
                gov_row.addWidget(btn)
                self.gov_buttons[gov_name] = btn

        cpu_layout.addWidget(gov_box)
        layout.addWidget(cpu_card)

        # =====================================================================
        # 2. NOVA FUNCIONALIDADE 1: Editor de Curva de Ventoinhas Personalizada + Limites TDP/WMI
        # =====================================================================
        tdp_card = QFrame()
        tdp_card.setProperty("class", "card")
        tdp_layout = QVBoxLayout(tdp_card)
        tdp_layout.setContentsMargins(20, 18, 20, 18)
        tdp_layout.setSpacing(14)

        tdp_header = QHBoxLayout()
        ic_tdp = QLabel()
        p_tdp = os.path.join(ICON_DIR, "fan_curve.svg")
        if not os.path.exists(p_tdp):
            p_tdp = os.path.join(ICON_DIR, "mode_custom.svg")
        if os.path.exists(p_tdp):
            ic_tdp.setPixmap(QPixmap(p_tdp).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        tdp_header.addWidget(ic_tdp)

        tdp_titles = QVBoxLayout()
        tdp_t = QLabel("Gestão Térmica • Editor de Curva de Ventoinhas (EC) & Limites TDP (PL1/PL2)")
        tdp_t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        tdp_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        tdp_titles.addWidget(tdp_t)

        tdp_sub = QLabel(
            "Arraste os pontos de controle (°C vs PWM% / RPM) para criar curvas passivas 0 RPM ou rampas agressivas no EC da Lenovo."
        )
        tdp_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        tdp_titles.addWidget(tdp_sub)
        tdp_header.addLayout(tdp_titles)
        tdp_header.addStretch()

        self.tdp_badge = StatusBadge("PL1: --W | PL2: --W", bg_color="#581c87", text_color="#e9d5ff")
        tdp_header.addWidget(self.tdp_badge)
        tdp_layout.addLayout(tdp_header)

        # Barra de ativação da Curva Customizada no Embedded Controller
        fan_cfg = self.backend.get_custom_fan_curve()
        fan_ctrl_box = QFrame()
        fan_ctrl_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        fan_ctrl_layout = QVBoxLayout(fan_ctrl_box)
        fan_ctrl_layout.setSpacing(10)

        fc_top = QHBoxLayout()
        fc_lbl_v = QVBoxLayout()
        fc_title = QLabel("Forçar Curva de Ventoinhas Personalizada no Embedded Controller (EC)")
        fc_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        fc_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        fc_lbl_v.addWidget(fc_title)

        self.lbl_fan_curve_status = QLabel(
            "Arraste os pontos no gráfico abaixo ou escolha um preset térmico (0 RPM Passivo em baixa carga, rampa rápida em jogos)."
        )
        self.lbl_fan_curve_status.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        fc_lbl_v.addWidget(self.lbl_fan_curve_status)
        fc_top.addLayout(fc_lbl_v)
        fc_top.addStretch()

        self.sw_custom_fan = ToggleSwitch()
        self.sw_custom_fan.setChecked(bool(fan_cfg.get("enabled", False)))
        self.sw_custom_fan.toggled.connect(self._on_custom_fan_toggled)
        fc_top.addWidget(self.sw_custom_fan)
        fan_ctrl_layout.addLayout(fc_top)

        # Gráfico Interativo de Curva de Ventoinhas
        self.fan_curve_widget = FanCurveWidget()
        self.fan_curve_widget.set_custom_curve(fan_cfg.get("points", []), bool(fan_cfg.get("enabled", False)))
        self.fan_curve_widget.curve_changed.connect(self._on_fan_curve_points_dragged)
        fan_ctrl_layout.addWidget(self.fan_curve_widget)

        # Sliders de Limites Térmicos WMI (CPU Temp Limit & GPU Temp Limit)
        wmi_temp_row = QHBoxLayout()
        wmi_temp_row.setSpacing(16)

        init_cpu_t = int(fan_cfg.get("cpu_temp_limit", 94))
        init_gpu_t = int(fan_cfg.get("gpu_temp_limit", 87))

        self.lbl_wmi_cpu_temp = QLabel(f"Alvo Térmico WMI CPU: {init_cpu_t}°C")
        self.lbl_wmi_cpu_temp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_wmi_cpu_temp.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 170px;")
        wmi_temp_row.addWidget(self.lbl_wmi_cpu_temp)

        self.slider_wmi_cpu_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_wmi_cpu_temp.setRange(85, 100)
        self.slider_wmi_cpu_temp.setValue(init_cpu_t)
        self.slider_wmi_cpu_temp.valueChanged.connect(
            lambda v: self.lbl_wmi_cpu_temp.setText(f"Alvo Térmico WMI CPU: {v}°C")
        )
        wmi_temp_row.addWidget(self.slider_wmi_cpu_temp, stretch=1)

        self.lbl_wmi_gpu_temp = QLabel(f"Alvo Térmico WMI GPU: {init_gpu_t}°C")
        self.lbl_wmi_gpu_temp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_wmi_gpu_temp.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 170px;")
        wmi_temp_row.addWidget(self.lbl_wmi_gpu_temp)

        self.slider_wmi_gpu_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_wmi_gpu_temp.setRange(75, 87)
        self.slider_wmi_gpu_temp.setValue(init_gpu_t)
        self.slider_wmi_gpu_temp.valueChanged.connect(
            lambda v: self.lbl_wmi_gpu_temp.setText(f"Alvo Térmico WMI GPU: {v}°C")
        )
        wmi_temp_row.addWidget(self.slider_wmi_gpu_temp, stretch=1)
        fan_ctrl_layout.addLayout(wmi_temp_row)

        # Linha de Presets da Curva de Ventoinhas + Botão Aplicar no EC
        fc_preset_row = QHBoxLayout()
        fc_preset_row.setSpacing(8)
        presets = self.backend.get_fan_curve_presets()
        for p_key, p_title in [
            ("passive_gaming", "Passivo 0 RPM + Gaming"),
            ("silent", "Ultra Silencioso"),
            ("balanced", "Equilibrado EC"),
            ("aggressive", "Rampa Agressiva 100%"),
        ]:
            btn_fp = QPushButton(p_title)
            btn_fp.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_fp.setFixedHeight(28)
            btn_fp.setStyleSheet(f"""
                QPushButton {{
                    background-color: #192338;
                    color: {ThemeTokens.TEXT_LIGHT_GRAY};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border-color: {ThemeTokens.BORDER_CYAN};
                    color: {ThemeTokens.TEXT_WHITE_100};
                }}
            """)
            btn_fp.clicked.connect(lambda _c, k=p_key: self._apply_fan_curve_preset(k))
            fc_preset_row.addWidget(btn_fp)

        fc_preset_row.addStretch()

        self.btn_apply_fan_curve = QPushButton("Aplicar Curva no EC")
        self.btn_apply_fan_curve.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_fan_curve.setFixedHeight(30)
        self.btn_apply_fan_curve.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.BORDER_CYAN};
                color: #0b0f19;
                border: none;
                border-radius: 6px;
                padding: 4px 16px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #38bdf8;
            }}
        """)
        self.btn_apply_fan_curve.clicked.connect(self._on_apply_custom_fan_curve)
        fc_preset_row.addWidget(self.btn_apply_fan_curve)
        fan_ctrl_layout.addLayout(fc_preset_row)

        tdp_layout.addWidget(fan_ctrl_box)

        # Sliders PL1 e PL2 (Intel RAPL)
        init_pl1, init_pl2 = self.backend.get_cpu_tdp_limits()
        sliders_box = QFrame()
        sliders_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 12px;")
        s_layout = QVBoxLayout(sliders_box)
        s_layout.setSpacing(10)

        pl1_row = QHBoxLayout()
        self.lbl_pl1_title = QLabel(f"PL1 • Potência Sustentada (Long-Term): {init_pl1} W")
        self.lbl_pl1_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_pl1_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 270px;")
        pl1_row.addWidget(self.lbl_pl1_title)

        self.slider_pl1 = QSlider(Qt.Orientation.Horizontal)
        self.slider_pl1.setRange(15, 90)
        self.slider_pl1.setValue(init_pl1)
        self.slider_pl1.setEnabled(self.backend.features.custom_tdp)
        self.slider_pl1.valueChanged.connect(self._on_pl1_slider_changed)
        pl1_row.addWidget(self.slider_pl1, stretch=1)
        s_layout.addLayout(pl1_row)

        pl2_row = QHBoxLayout()
        self.lbl_pl2_title = QLabel(f"PL2 • Potência de Pico Boost (Short-Term): {init_pl2} W")
        self.lbl_pl2_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_pl2_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 270px;")
        pl2_row.addWidget(self.lbl_pl2_title)

        self.slider_pl2 = QSlider(Qt.Orientation.Horizontal)
        self.slider_pl2.setRange(20, 115)
        self.slider_pl2.setValue(init_pl2)
        self.slider_pl2.setEnabled(self.backend.features.custom_tdp)
        self.slider_pl2.valueChanged.connect(self._on_pl2_slider_changed)
        pl2_row.addWidget(self.slider_pl2, stretch=1)
        s_layout.addLayout(pl2_row)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        for label_p, p1, p2 in [
            ("Preset Silencioso (20W / 30W)", 20, 30),
            ("Preset Equilibrado (45W / 65W)", 45, 65),
            ("Preset Gaming (60W / 80W)", 60, 80),
        ]:
            b_pre = QPushButton(label_p)
            b_pre.setCursor(Qt.CursorShape.PointingHandCursor)
            b_pre.setFixedHeight(28)
            b_pre.setStyleSheet(f"""
                QPushButton {{
                    background-color: #192338;
                    color: {ThemeTokens.TEXT_LIGHT_GRAY};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border-color: {ThemeTokens.BORDER_CYAN};
                    color: {ThemeTokens.TEXT_WHITE_100};
                }}
            """)
            b_pre.clicked.connect(lambda checked, a=p1, b=p2: self._set_tdp_sliders(a, b))
            preset_row.addWidget(b_pre)

        preset_row.addStretch()

        self.btn_apply_tdp = QPushButton("Aplicar Limites TDP")
        self.btn_apply_tdp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_tdp.setFixedHeight(30)
        self.btn_apply_tdp.setEnabled(self.backend.features.custom_tdp)
        self.btn_apply_tdp.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.THERMAL_CUSTOM};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 4px 16px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #b45cff;
            }}
        """)
        self.btn_apply_tdp.clicked.connect(self._on_apply_tdp)
        preset_row.addWidget(self.btn_apply_tdp)
        s_layout.addLayout(preset_row)

        tdp_layout.addWidget(sliders_box)
        layout.addWidget(tdp_card)

        # =====================================================================
        # 3. NOVA FUNCIONALIDADE 2: Overclock e Undervolt Dinâmico (Intel HX / AMD)
        # =====================================================================
        uv_status = self.backend.get_undervolt_status()
        uv_card = QFrame()
        uv_card.setProperty("class", "card")
        uv_layout = QVBoxLayout(uv_card)
        uv_layout.setContentsMargins(20, 18, 20, 18)
        uv_layout.setSpacing(12)

        uv_header = QHBoxLayout()
        ic_uv = QLabel()
        p_uv = os.path.join(ICON_DIR, "undervolt.svg")
        if os.path.exists(p_uv):
            ic_uv.setPixmap(QPixmap(p_uv).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        uv_header.addWidget(ic_uv)

        uv_titles = QVBoxLayout()
        uv_t = QLabel(f"Overclock & Undervolt Dinâmico • {uv_status.method}")
        uv_t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        uv_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        uv_titles.addWidget(uv_t)

        uv_sub = QLabel(
            "Offsets negativos seguros de tensão para processadores série HX (Core & Cache) e Boost AC WMI com Watchdog Anti-Kernel Panic."
        )
        uv_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        uv_titles.addWidget(uv_sub)
        uv_header.addLayout(uv_titles)
        uv_header.addStretch()

        self.uv_badge = StatusBadge(
            f"CORE: {uv_status.core_offset_mv} mV | CACHE: {uv_status.cache_offset_mv} mV",
            bg_color="#1e293b",
            text_color="#00d2ff",
        )
        uv_header.addWidget(self.uv_badge)
        uv_layout.addLayout(uv_header)

        # Banner de Confirmação Watchdog (15s) / Recuperação de Emergência
        self.uv_watchdog_frame = QFrame()
        self.uv_watchdog_frame.setStyleSheet(
            "background-color: #3f1d2e; border: 1px solid #ff9f0a; border-radius: 8px; padding: 8px 12px;"
        )
        wd_row = QHBoxLayout(self.uv_watchdog_frame)
        self.lbl_uv_watchdog = QLabel(
            "Watchdog de Segurança Ativo: Confirme a estabilidade em 15s ou as tensões voltarão automaticamente para 0 mV."
        )
        self.lbl_uv_watchdog.setStyleSheet("color: #fde68a; font-weight: bold; font-size: 11px;")
        wd_row.addWidget(self.lbl_uv_watchdog, stretch=1)

        self.btn_confirm_uv = QPushButton("Confirmar Estabilidade (Manter Offset)")
        self.btn_confirm_uv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm_uv.setFixedHeight(28)
        self.btn_confirm_uv.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.STATUS_GREEN};
                color: #0b0f19;
                border: none;
                border-radius: 5px;
                padding: 3px 12px;
                font-weight: bold;
                font-size: 10px;
            }}
        """)
        self.btn_confirm_uv.clicked.connect(self._on_confirm_undervolt)
        wd_row.addWidget(self.btn_confirm_uv)
        self.uv_watchdog_frame.setVisible(False)
        uv_layout.addWidget(self.uv_watchdog_frame)

        # Box de Sliders de Tensão (Core, Cache e GPU AC Offset)
        uv_box = QFrame()
        uv_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 12px;")
        uv_box_layout = QVBoxLayout(uv_box)
        uv_box_layout.setSpacing(10)

        # Core Offset (-150 mV a 0 mV)
        core_row = QHBoxLayout()
        self.lbl_uv_core = QLabel(f"CPU Core Voltage Offset (Plane 0): {uv_status.core_offset_mv} mV")
        self.lbl_uv_core.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_uv_core.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 285px;")
        core_row.addWidget(self.lbl_uv_core)

        self.slider_uv_core = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_core.setRange(-150, 0)
        self.slider_uv_core.setValue(uv_status.core_offset_mv)
        self.slider_uv_core.valueChanged.connect(self._on_uv_slider_changed)
        core_row.addWidget(self.slider_uv_core, stretch=1)
        uv_box_layout.addLayout(core_row)

        # Cache Offset (-150 mV a 0 mV)
        cache_row = QHBoxLayout()
        self.lbl_uv_cache = QLabel(f"CPU Ring/Cache Voltage Offset (Plane 2): {uv_status.cache_offset_mv} mV")
        self.lbl_uv_cache.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_uv_cache.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 285px;")
        cache_row.addWidget(self.lbl_uv_cache)

        self.slider_uv_cache = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_cache.setRange(-150, 0)
        self.slider_uv_cache.setValue(uv_status.cache_offset_mv)
        self.slider_uv_cache.valueChanged.connect(self._on_uv_slider_changed)
        cache_row.addWidget(self.slider_uv_cache, stretch=1)
        uv_box_layout.addLayout(cache_row)

        # GPU / AC Dynamic Boost Offset (10 W a 30 W via Lenovo WMI Other)
        ac_off_row = QHBoxLayout()
        self.lbl_uv_gpu_offset = QLabel(f"Lenovo WMI GPU / AC Dynamic Power Offset: +{uv_status.gpu_ac_offset_w} W")
        self.lbl_uv_gpu_offset.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_uv_gpu_offset.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 285px;")
        ac_off_row.addWidget(self.lbl_uv_gpu_offset)

        self.slider_uv_gpu_offset = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_gpu_offset.setRange(10, 30)
        self.slider_uv_gpu_offset.setValue(uv_status.gpu_ac_offset_w)
        self.slider_uv_gpu_offset.valueChanged.connect(self._on_uv_slider_changed)
        ac_off_row.addWidget(self.slider_uv_gpu_offset, stretch=1)
        uv_box_layout.addLayout(ac_off_row)

        # Linha de Presets Seguros + Botão de Emergência (0 mV) + Botão Aplicar Undervolt
        uv_actions = QHBoxLayout()
        uv_actions.setSpacing(8)
        for uv_lbl, c_mv, ca_mv in [
            ("Padrão Seguro (0 mV)", 0, 0),
            ("Undervolt Leve (-50 mV / -40 mV)", -50, -40),
            ("Otimizado HX (-80 mV / -60 mV)", -80, -60),
        ]:
            b_uvp = QPushButton(uv_lbl)
            b_uvp.setCursor(Qt.CursorShape.PointingHandCursor)
            b_uvp.setFixedHeight(28)
            b_uvp.setStyleSheet(f"""
                QPushButton {{
                    background-color: #192338;
                    color: {ThemeTokens.TEXT_LIGHT_GRAY};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border-color: {ThemeTokens.BORDER_CYAN};
                    color: {ThemeTokens.TEXT_WHITE_100};
                }}
            """)
            b_uvp.clicked.connect(lambda _c, cm=c_mv, cam=ca_mv: self._set_uv_sliders(cm, cam))
            uv_actions.addWidget(b_uvp)

        uv_actions.addStretch()

        self.btn_emergency_reset_uv = QPushButton("Reset de Emergência (0 mV)")
        self.btn_emergency_reset_uv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_emergency_reset_uv.setFixedHeight(30)
        self.btn_emergency_reset_uv.setStyleSheet(f"""
            QPushButton {{
                background-color: #7f1d1d;
                color: #ffffff;
                border: 1px solid {ThemeTokens.LEGION_RED};
                border-radius: 6px;
                padding: 4px 14px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.LEGION_RED};
            }}
        """)
        self.btn_emergency_reset_uv.clicked.connect(self._on_emergency_reset_undervolt)
        uv_actions.addWidget(self.btn_emergency_reset_uv)

        self.btn_apply_uv = QPushButton("Aplicar Offsets com Watchdog")
        self.btn_apply_uv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_uv.setFixedHeight(30)
        self.btn_apply_uv.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.THERMAL_CUSTOM};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 4px 16px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #b45cff;
            }}
        """)
        self.btn_apply_uv.clicked.connect(self._on_apply_undervolt)
        uv_actions.addWidget(self.btn_apply_uv)
        uv_box_layout.addLayout(uv_actions)

        self.lbl_uv_status = QLabel(
            uv_status.last_emergency_reset
            if uv_status.last_emergency_reset
            else "Trava de Segurança: Offsets limitados a [-150 mV, 0 mV]. Em caso de falha, o Watchdog restaura 0 mV no boot."
        )
        self.lbl_uv_status.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        uv_box_layout.addWidget(self.lbl_uv_status)

        uv_layout.addWidget(uv_box)
        layout.addWidget(uv_card)

        # =====================================================================
        # 4. NOVA FUNCIONALIDADE 3: Gerenciador de Perfis de Energia por Aplicativo (App Rules)
        # =====================================================================
        rules_card = QFrame()
        rules_card.setProperty("class", "card")
        rules_layout = QVBoxLayout(rules_card)
        rules_layout.setContentsMargins(20, 18, 20, 18)
        rules_layout.setSpacing(12)

        rules_header = QHBoxLayout()
        ic_rules = QLabel()
        p_rules = os.path.join(ICON_DIR, "app_rules.svg")
        if os.path.exists(p_rules):
            ic_rules.setPixmap(QPixmap(p_rules).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        rules_header.addWidget(ic_rules)

        rules_titles = QVBoxLayout()
        rt_title = QLabel("Gerenciador de Perfis de Energia por Aplicativo (App Rules)")
        rt_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        rt_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        rules_titles.addWidget(rt_title)

        rt_sub = QLabel(
            "Vincule executáveis específicos (ex: blender, resolve, kdenlive, firefox) a perfis térmicos automáticos."
        )
        rt_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        rules_titles.addWidget(rt_sub)
        rules_header.addLayout(rules_titles)
        rules_header.addStretch()

        self.app_rules_badge = StatusBadge("AUTO-SWITCH ATIVO", bg_color="#064e3b", text_color="#34d399")
        rules_header.addWidget(self.app_rules_badge)
        rules_layout.addLayout(rules_header)

        # Barra para adicionar nova regra de aplicativo
        add_rule_box = QFrame()
        add_rule_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 12px;")
        add_row = QHBoxLayout(add_rule_box)
        add_row.setContentsMargins(6, 4, 6, 4)
        add_row.setSpacing(10)

        self.combo_app_exec = QComboBox()
        self.combo_app_exec.setEditable(True)
        self.combo_app_exec.setMinimumWidth(210)
        self.combo_app_exec.setFixedHeight(30)
        self.combo_app_exec.setStyleSheet(f"""
            QComboBox {{
                background-color: #0d1322;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
            }}
        """)
        self._populate_running_apps_combo()
        add_row.addWidget(self.combo_app_exec, stretch=1)

        self.edit_app_label = QLineEdit()
        self.edit_app_label.setPlaceholderText("Descrição opcional (ex: Blender 3D Render)")
        self.edit_app_label.setFixedHeight(30)
        self.edit_app_label.setStyleSheet(f"""
            QLineEdit {{
                background-color: #0d1322;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
            }}
        """)
        add_row.addWidget(self.edit_app_label, stretch=1)

        self.combo_app_profile = QComboBox()
        self.combo_app_profile.setMinimumWidth(210)
        self.combo_app_profile.setFixedHeight(30)
        self.combo_app_profile.setStyleSheet(f"""
            QComboBox {{
                background-color: #192338;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
            }}
        """)
        for prof_id, prof_label in PROFILE_COMBO_ITEMS:
            self.combo_app_profile.addItem(prof_label, prof_id)
        add_row.addWidget(self.combo_app_profile)

        btn_add_rule = QPushButton("Adicionar Regra")
        btn_add_rule.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_rule.setFixedHeight(30)
        btn_add_rule.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.BORDER_CYAN};
                color: #0b0f19;
                border: none;
                border-radius: 6px;
                padding: 4px 14px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #38bdf8;
            }}
        """)
        btn_add_rule.clicked.connect(self._on_add_app_rule)
        add_row.addWidget(btn_add_rule)

        rules_layout.addWidget(add_rule_box)

        # Container dinâmico das regras cadastradas
        self.rules_list_container = QWidget()
        self.rules_list_layout = QVBoxLayout(self.rules_list_container)
        self.rules_list_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_list_layout.setSpacing(8)
        rules_layout.addWidget(self.rules_list_container)
        self._rebuild_app_rules_list()

        layout.addWidget(rules_card)

        # =====================================================================
        # 5. ELITE 5: Mapeador de Teclas Personalizadas (Tecla Copilot F23 & Órfãs)
        # =====================================================================
        remap_card = QFrame()
        remap_card.setProperty("class", "card")
        remap_layout = QVBoxLayout(remap_card)
        remap_layout.setContentsMargins(20, 18, 20, 18)
        remap_layout.setSpacing(12)

        remap_header = QHBoxLayout()
        ic_key = QLabel()
        p_key = os.path.join(ICON_DIR, "copilot_key.svg")
        if os.path.exists(p_key):
            ic_key.setPixmap(QPixmap(p_key).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        remap_header.addWidget(ic_key)

        remap_titles = QVBoxLayout()
        rt_lbl = QLabel("Mapeador de Teclas Personalizadas (Tecla Copilot F23 & Teclas Especiais)")
        rt_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        rt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        remap_titles.addWidget(rt_lbl)

        rs_lbl = QLabel(
            "Transforme teclas órfãs do Windows (como a tecla Copilot F23 ou F24) em atalhos de elite com OSD nativo."
        )
        rs_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        remap_titles.addWidget(rs_lbl)
        remap_header.addLayout(remap_titles)
        remap_header.addStretch()
        remap_layout.addLayout(remap_header)

        self._slot_widgets: Dict[str, Dict[str, Any]] = {}
        mappings = self.backend.get_key_mappings()
        for slot_id, slot_cfg in mappings.items():
            row_frame = self._create_key_slot_row(slot_id, slot_cfg)
            remap_layout.addWidget(row_frame)

        layout.addWidget(remap_card)

        # =====================================================================
        # 6. Monitoramento Detalhado da GPU (Estado D3cold / Ativa)
        # =====================================================================
        gpu_card = QFrame()
        gpu_card.setProperty("class", "card")
        gpu_layout = QVBoxLayout(gpu_card)
        gpu_layout.setContentsMargins(20, 18, 20, 18)
        gpu_layout.setSpacing(12)

        gpu_header = QHBoxLayout()
        ic_gpu = QLabel()
        p_gpu = os.path.join(ICON_DIR, "gpu_stack.svg")
        if os.path.exists(p_gpu):
            ic_gpu.setPixmap(QPixmap(p_gpu).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        gpu_header.addWidget(ic_gpu)

        gpu_titles = QVBoxLayout()
        self.gpu_title_lbl = QLabel(f"Monitoramento Detalhado da GPU • {self.backend.system_info.gpu_model}")
        self.gpu_title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.gpu_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        gpu_titles.addWidget(self.gpu_title_lbl)

        gpu_sub = QLabel("Telemetria em tempo real de energia, VRAM, frequências e estado de suspensão D3cold.")
        gpu_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gpu_titles.addWidget(gpu_sub)
        gpu_header.addLayout(gpu_titles)
        gpu_header.addStretch()

        self.gpu_state_badge = StatusBadge("ATIVA", bg_color="#064e3b", text_color="#34d399")
        gpu_header.addWidget(self.gpu_state_badge)
        gpu_layout.addLayout(gpu_header)

        gpu_grid = QGridLayout()
        gpu_grid.setSpacing(10)
        self.lbl_gpu_clock = self._create_stat_box(gpu_grid, 0, 0, "Frequência Core", "-- MHz")
        self.lbl_gpu_temp = self._create_stat_box(gpu_grid, 0, 1, "Temperatura GPU", "-- °C")
        self.lbl_gpu_power = self._create_stat_box(gpu_grid, 0, 2, "Consumo Elétrico", "-- W")
        self.lbl_gpu_vram = self._create_stat_box(gpu_grid, 1, 0, "Memória VRAM", "-- / -- MB")
        self.lbl_gpu_util = self._create_stat_box(gpu_grid, 1, 1, "Carga do Núcleo", "-- %")
        self.lbl_gpu_pstate = self._create_stat_box(gpu_grid, 1, 2, "Estado Runtime / P-State", "--")

        gpu_layout.addLayout(gpu_grid)
        layout.addWidget(gpu_card)

        # =====================================================================
        # 7. Perfis Térmicos ACPI (Platform Profile)
        # =====================================================================
        prof_card = QFrame()
        prof_card.setProperty("class", "card")
        prof_layout = QVBoxLayout(prof_card)
        prof_layout.setContentsMargins(20, 18, 20, 18)
        prof_layout.setSpacing(12)

        prof_header = QHBoxLayout()
        prof_title = QLabel("Perfis Térmicos ACPI (Fn + Q)")
        prof_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        prof_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        prof_header.addWidget(prof_title)
        prof_header.addStretch()

        self.current_badge = StatusBadge("EQUILIBRADO", bg_color="#0369a1", text_color="#38bdf8")
        prof_header.addWidget(self.current_badge)
        prof_layout.addLayout(prof_header)

        card_quiet = ProfileCard(
            profile_id="low-power",
            icon_source=os.path.join(ICON_DIR, "thermal_quiet.svg"),
            title="Modo Silencioso (Quiet / Low-Power)",
            desc="Reduz o limite térmico (PL1/PL2) e mantém as ventoinhas em rotação silenciosa para máxima autonomia.",
            accent_color=ThemeTokens.THERMAL_QUIET
        )
        card_quiet.clicked.connect(self._on_card_selected)
        prof_layout.addWidget(card_quiet)
        self.cards["low-power"] = card_quiet
        self.cards["quiet"] = card_quiet

        card_bal = ProfileCard(
            profile_id="balanced",
            icon_source=os.path.join(ICON_DIR, "thermal_balanced.svg"),
            title="Modo Equilibrado (Balanced)",
            desc="Equilíbrio automático gerenciado pelo Embedded Controller (EC) conforme a demanda de CPU e GPU.",
            accent_color=ThemeTokens.THERMAL_BALANCED
        )
        card_bal.clicked.connect(self._on_card_selected)
        prof_layout.addWidget(card_bal)
        self.cards["balanced"] = card_bal

        card_perf = ProfileCard(
            profile_id="performance",
            icon_source=os.path.join(ICON_DIR, "thermal_performance.svg"),
            title="Modo Desempenho (Performance)",
            desc="Libera o envelope de potência elevado para CPU e GPU com curva acelerada de refrigeração.",
            accent_color=ThemeTokens.THERMAL_PERFORMANCE
        )
        card_perf.clicked.connect(self._on_card_selected)
        prof_layout.addWidget(card_perf)
        self.cards["performance"] = card_perf

        choices = self.backend.get_platform_profile_choices()
        if "max-power" in choices or self.backend.features.max_power_profile:
            card_max = ProfileCard(
                profile_id="max-power",
                icon_source=os.path.join(ICON_DIR, "thermal_max_power.svg"),
                title="Desempenho Máximo (Max-Power)",
                desc="Perfil avançado descoberto no kernel (incluído no ciclo Fn + Q) para potência máxima sustentada e rotação máxima das ventoinhas.",
                accent_color=ThemeTokens.THERMAL_CUSTOM
            )
            card_max.clicked.connect(self._on_card_selected)
            prof_layout.addWidget(card_max)
            self.cards["max-power"] = card_max

        layout.addWidget(prof_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.refresh_profile_state()

    # =========================================================================
    # Métodos da Curva de Ventoinhas Personalizada (Fan Curve Editor)
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
            "Curva personalizada editada: "
            + " | ".join(f"{t}°C:{p}%" for t, p in new_points)
            + " (Clique em 'Aplicar Curva no EC' para gravar)"
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
        ok, msg = self.backend.set_custom_fan_curve(pts, enabled, cpu_lim, gpu_lim)
        self.lbl_fan_curve_status.setText(msg)
        self.refresh_profile_state()

    # =========================================================================
    # Métodos de Overclock & Undervolt Dinâmico + Watchdog de Segurança (15s)
    # =========================================================================
    def _on_uv_slider_changed(self, _val: int = 0):
        core_mv = self.slider_uv_core.value()
        cache_mv = self.slider_uv_cache.value()
        gpu_w = self.slider_uv_gpu_offset.value()
        hex_core = hex(self.backend._encode_intel_msr_undervolt_offset(0, core_mv))
        self.lbl_uv_core.setText(f"CPU Core Voltage Offset (Plane 0): {core_mv} mV ({hex_core})")
        self.lbl_uv_cache.setText(f"CPU Ring/Cache Voltage Offset (Plane 2): {cache_mv} mV")
        self.lbl_uv_gpu_offset.setText(f"Lenovo WMI GPU / AC Dynamic Power Offset: +{gpu_w} W")

    def _set_uv_sliders(self, core_mv: int, cache_mv: int):
        self.slider_uv_core.setValue(core_mv)
        self.slider_uv_cache.setValue(cache_mv)

    def _on_apply_undervolt(self):
        core_mv = self.slider_uv_core.value()
        cache_mv = self.slider_uv_cache.value()
        gpu_w = self.slider_uv_gpu_offset.value()
        ok, msg = self.backend.apply_undervolt_offsets(core_mv, cache_mv, gpu_w)
        self.lbl_uv_status.setText(msg)
        self.uv_badge.setText(f"CORE: {core_mv} mV | CACHE: {cache_mv} mV")

        if core_mv < 0 or cache_mv < 0:
            self._watchdog_seconds = 15
            self.uv_watchdog_frame.setVisible(True)
            self.lbl_uv_watchdog.setText(
                f"Watchdog de Segurança Ativo ({self._watchdog_seconds}s): Confirme a estabilidade ou o sistema voltará para 0 mV."
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
            f"Watchdog de Segurança Ativo ({self._watchdog_seconds}s): Confirme a estabilidade ou o sistema voltará para 0 mV."
        )

    def _on_confirm_undervolt(self):
        self._watchdog_timer.stop()
        self.uv_watchdog_frame.setVisible(False)
        ok, msg = self.backend.confirm_undervolt_stability()
        self.lbl_uv_status.setText(msg)

    def _on_emergency_reset_undervolt(self, _checked: bool = False, reason: str = "Reset de Emergência manual"):
        self._watchdog_timer.stop()
        self.uv_watchdog_frame.setVisible(False)
        ok, msg = self.backend.emergency_reset_undervolt(reason=reason)
        self.slider_uv_core.setValue(0)
        self.slider_uv_cache.setValue(0)
        self.slider_uv_gpu_offset.setValue(20)
        self.uv_badge.setText("CORE: 0 mV | CACHE: 0 mV")
        self.lbl_uv_status.setText(msg)

    # =========================================================================
    # Métodos do Gerenciador de Perfis por Aplicativo (App Rules)
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
            pinfo = self.backend.get_profile_info(prof_id)

            row_f = QFrame()
            row_f.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 7px; padding: 6px 12px;")
            r_lay = QHBoxLayout(row_f)
            r_lay.setContentsMargins(6, 4, 6, 4)
            r_lay.setSpacing(10)

            lbl_exec = QLabel(f"{exec_name}")
            lbl_exec.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl_exec.setStyleSheet(f"color: {ThemeTokens.BORDER_CYAN}; min-width: 110px;")
            r_lay.addWidget(lbl_exec)

            lbl_desc = QLabel(label_txt)
            lbl_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px;")
            r_lay.addWidget(lbl_desc, stretch=1)

            badge = StatusBadge(pinfo["badge"], bg_color=pinfo["badge_bg"], text_color="#ffffff")
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
                    background-color: #192338;
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
        prof_id = self.combo_app_profile.currentData() or "performance"
        ok, msg = self.backend.add_app_power_rule(exec_name, prof_id, label_txt)
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

    # =========================================================================
    # Métodos do Mapeador de Teclas Personalizadas (Copilot Key Remapper)
    # =========================================================================
    def _create_key_slot_row(self, slot_id: str, slot_cfg: Dict[str, Any]) -> QFrame:
        box = QFrame()
        box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 12px;")
        v_layout = QVBoxLayout(box)
        v_layout.setContentsMargins(6, 6, 6, 6)
        v_layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)

        lbl_name = QLabel(str(slot_cfg.get("label", slot_id)))
        lbl_name.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl_name.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 195px;")
        top.addWidget(lbl_name)

        cap_btn = KeyCaptureButton(str(slot_cfg.get("qt_shortcut", "F23")))
        cap_btn.shortcut_captured.connect(lambda seq, s=slot_id: self._on_slot_modified(s))
        top.addWidget(cap_btn)

        combo = QComboBox()
        combo.setMinimumWidth(260)
        combo.setFixedHeight(30)
        combo.setStyleSheet(f"""
            QComboBox {{
                background-color: #192338;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
            }}
        """)
        current_act = str(slot_cfg.get("action", "cycle_profile"))
        sel_idx = 0
        for idx, (act_id, act_label) in enumerate(AVAILABLE_KEY_ACTIONS):
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
                background-color: #192338;
                color: {ThemeTokens.STATUS_GREEN};
                border: 1px solid {ThemeTokens.STATUS_GREEN};
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: bold;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.STATUS_GREEN};
                color: #0b0f19;
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
        cmd_edit.setPlaceholderText("Digite o comando ou caminho do script (ex: /usr/bin/konsole ou ~/.local/bin/meu_script.sh)")
        cmd_edit.setVisible(current_act == "custom_command")
        cmd_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: #0d1322;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 11px;
            }}
        """)
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

        cfg = w["cfg"]
        cfg["qt_shortcut"] = w["cap_btn"].text()
        cfg["action"] = act_id
        cfg["custom_command"] = w["cmd_edit"].text().strip()
        cfg["enabled"] = w["switch"].isChecked()

        self.backend.update_key_mapping(slot_id, cfg)
        self.shortcuts_updated.emit()

    def _on_test_slot(self, slot_id: str):
        w = self._slot_widgets.get(slot_id)
        if not w:
            return
        act_id = w["combo"].currentData()
        cmd = w["cmd_edit"].text().strip()
        self.custom_action_requested.emit(act_id, cmd)

    def _on_pl1_slider_changed(self, val: int):
        self.lbl_pl1_title.setText(f"PL1 • Potência Sustentada (Long-Term): {val} W")
        if self.slider_pl2.value() < val:
            self.slider_pl2.setValue(val)

    def _on_pl2_slider_changed(self, val: int):
        if val < self.slider_pl1.value():
            val = self.slider_pl1.value()
            self.slider_pl2.setValue(val)
        self.lbl_pl2_title.setText(f"PL2 • Potência de Pico Boost (Short-Term): {val} W")

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
                f"Não foi possível aplicar os limites TDP (PL1={pl1}W / PL2={pl2}W):\n{msg}"
            )
        else:
            self.refresh_profile_state()

    def _create_stat_box(self, grid: QGridLayout, r: int, c: int, label: str, default: str) -> QLabel:
        box = QFrame()
        box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 6px; padding: 8px 10px;")
        b_layout = QVBoxLayout(box)
        b_layout.setSpacing(2)
        b_layout.setContentsMargins(6, 5, 6, 5)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY};")
        b_layout.addWidget(lbl)

        val = QLabel(default)
        val.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        val.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        b_layout.addWidget(val)

        grid.addWidget(box, r, c)
        return val

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

    def _on_card_selected(self, profile_id: str):
        success, msg = self.backend.set_platform_profile(profile_id)
        if not success:
            QMessageBox.warning(
                self, "Permissão de Escrita Necessária",
                f"Não foi possível aplicar o perfil '{profile_id}':\n{msg}\n\n"
                "Repare as regras UDEV na aba 'Sobre o Dispositivo' para aplicar sem senha."
            )
        else:
            self.profile_changed.emit(profile_id)
            self.refresh_profile_state()

    def refresh_profile_state(self):
        """Atualiza os estados de CPU, TDP, Curva de Ventoinhas, Undervolt, App Rules, GPU e Perfis Térmicos na aba."""
        cpu = self.backend.get_cpu_metrics()
        gpu = self.backend.get_gpu_metrics()
        fan = self.backend.get_fan_metrics()
        active_prof = self.backend.normalize_profile(self.backend.get_platform_profile())

        # 1. CPU Turbo, Governor e TDP
        self.cpu_freq_badge.setText(f"{cpu.frequency_mhz:.0f} MHz • {cpu.temperature_c:.0f}°C")
        self.turbo_switch.blockSignals(True)
        self.turbo_switch.setChecked(cpu.turbo_enabled)
        self.turbo_switch.blockSignals(False)

        self.tdp_badge.setText(f"PL1: {cpu.pl1_w}W | PL2: {cpu.pl2_w}W")
        self.fan_curve_widget.update_state(active_prof, cpu.temperature_c, fan.rpm, fan.second_rpm)

        # Status do App Rules
        active_game = self.backend.get_active_game()
        if active_game:
            self.app_rules_badge.setText(f"ATIVO: {active_game[:22].upper()}")
            self.app_rules_badge.setColor("#581c87", "#e9d5ff")
        else:
            self.app_rules_badge.setText("AUTO-SWITCH ATIVO")
            self.app_rules_badge.setColor("#064e3b", "#34d399")

        for gname, btn in self.gov_buttons.items():
            is_active = (gname == cpu.governor)
            if is_active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BORDER_CYAN};
                        color: #0b0f19;
                        border: 1px solid {ThemeTokens.BORDER_CYAN};
                        border-radius: 6px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #192338;
                        color: {ThemeTokens.TEXT_LIGHT_GRAY};
                        border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        border-color: {ThemeTokens.BORDER_CYAN};
                    }}
                """)

        # 2. GPU Detalhada
        self.gpu_title_lbl.setText(f"Monitoramento Detalhado da GPU • {gpu.name}")
        if gpu.available:
            self.gpu_state_badge.setText(f"{gpu.runtime_state.upper()} ({gpu.pstate})")
            self.gpu_state_badge.setColor("#064e3b", "#34d399")
            self.lbl_gpu_clock.setText(f"{gpu.clock_mhz} MHz" if gpu.clock_mhz > 0 else "Dinâmico")
            self.lbl_gpu_temp.setText(f"{gpu.temperature_c:.1f} °C")
            self.lbl_gpu_power.setText(f"{gpu.power_draw_w:.1f} W" if gpu.power_draw_w > 0 else "Integrada")
            if gpu.memory_total_mb > 0:
                self.lbl_gpu_vram.setText(f"{gpu.memory_used_mb} / {gpu.memory_total_mb} MB")
            else:
                self.lbl_gpu_vram.setText("Memória Compartilhada")
            self.lbl_gpu_util.setText(f"{gpu.utilization_percent}%")
            self.lbl_gpu_pstate.setText(f"Ativa • {gpu.pstate}")
        else:
            self.gpu_state_badge.setText("D3COLD (SUSPENSA)")
            self.gpu_state_badge.setColor("#1e293b", "#38bdf8")
            self.lbl_gpu_clock.setText("0 MHz (D3cold)")
            self.lbl_gpu_temp.setText("Repouso")
            self.lbl_gpu_power.setText("0.0 W")
            self.lbl_gpu_vram.setText("Desligada")
            self.lbl_gpu_util.setText("0%")
            self.lbl_gpu_pstate.setText("Runtime Suspended (D3cold)")

        # 3. Perfis ACPI
        for pid, card in self.cards.items():
            if pid in ("low-power", "quiet"):
                card.set_active(active_prof in ("low-power", "quiet"))
            else:
                card.set_active(pid == active_prof)

        if active_prof == "max-power":
            self.current_badge.setText("MAX-POWER")
            self.current_badge.setColor("#581c87", ThemeTokens.THERMAL_CUSTOM)
        elif active_prof == "performance":
            self.current_badge.setText("DESEMPENHO")
            self.current_badge.setColor("#7f1d1d", ThemeTokens.THERMAL_PERFORMANCE)
        elif active_prof in ("low-power", "quiet"):
            self.current_badge.setText("SILENCIOSO")
            self.current_badge.setColor("#0369a1", ThemeTokens.THERMAL_QUIET)
        else:
            self.current_badge.setText("EQUILIBRADO")
            self.current_badge.setColor("#155e75", ThemeTokens.THERMAL_BALANCED)
