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
import shutil
from typing import Dict, Any, List, Tuple, Optional
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QSlider, QComboBox, QLineEdit,
    Qt, QTimer, Signal, QFont, QMessageBox, QPixmap, QKeySequence,
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPointF, QPainterPath,
    QSizePolicy
)
from ui.theme_tokens import ThemeTokens
from ui.components import ProfileCard, ToggleSwitch, StatusBadge

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")

AVAILABLE_KEY_ACTIONS: List[Tuple[str, str]] = [
    ("cycle_profile", "Alternar Modo Térmico (Ciclo com OSD)"),
    ("cycle_refresh_rate", "Alternar Taxa de Atualização de Tela (Fn+R)"),
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


class GpuModeBlock(QFrame):
    """Bloco seletor individual de modo para o GPU MUX Switch (Híbrido vs dGPU vs iGPU)."""
    clicked = Signal(str)

    def __init__(self, mode_id: str, title: str, subtitle: str, accent_color: str, parent=None):
        super().__init__(parent)
        self.mode_id = mode_id
        self.accent_color = accent_color
        self.is_active = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.badge = QLabel("ATIVO")
        self.badge.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.badge.setVisible(False)
        top.addStretch()
        top.addWidget(self.badge)
        layout.addLayout(top)

        self.title_lbl = QLabel(title)
        self.title_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        layout.addWidget(self.title_lbl)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setWordWrap(True)
        self.sub_lbl.setFont(QFont("Segoe UI", 9))
        self.sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY};")
        layout.addWidget(self.sub_lbl)

        self.update_style()

    def set_active(self, active: bool):
        self.is_active = active
        self.badge.setVisible(active)
        if active:
            self.badge.setStyleSheet(f"""
                background-color: {self.accent_color};
                color: #0b0f19;
                padding: 2px 7px;
                border-radius: 4px;
            """)
        self.update_style()

    def update_style(self):
        if self.is_active:
            self.setStyleSheet(f"""
                GpuModeBlock {{
                    background-color: {ThemeTokens.BG_CARD_ACTIVE};
                    border: 2px solid {self.accent_color};
                    border-radius: {ThemeTokens.RADIUS_CARD}px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                GpuModeBlock {{
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: {ThemeTokens.RADIUS_CARD}px;
                }}
                GpuModeBlock:hover {{
                    border-color: {self.accent_color};
                }}
            """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mode_id)
        super().mousePressEvent(event)



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
    gpu_mux_changed = Signal(str, bool)
    refresh_rate_changed = Signal(int)
    lcd_overdrive_changed = Signal(bool)
    preset_applied = Signal(str, str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.cards = {}
        self.gov_buttons = {}
        self.mux_blocks: Dict[str, GpuModeBlock] = {}
        self.refresh_rate_buttons: Dict[int, QPushButton] = {}
        self.bios_attr_widgets: Dict[str, Any] = {}
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
        feat = self.backend.features
        self.cpu_card = QFrame()
        self.cpu_card.setProperty("class", "card")
        cpu_layout = QVBoxLayout(self.cpu_card)
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

        if feat.turbo_boost and feat.cpu_governor:
            cpu_sub_txt = "Ajuste direto de frequências dinâmicas (Turbo Boost) e governador do escalonador Linux."
        elif feat.turbo_boost:
            cpu_sub_txt = "Ajuste direto de frequências dinâmicas (Turbo Boost) do processador."
        else:
            cpu_sub_txt = "Seleção do governador de frequência do escalonador Linux."
        cpu_sub = QLabel(cpu_sub_txt)
        cpu_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        cpu_titles.addWidget(cpu_sub)
        cpu_header.addLayout(cpu_titles)
        cpu_header.addStretch()

        self.cpu_freq_badge = StatusBadge("-- MHz", bg_color="#1e293b", text_color="#00d2ff")
        cpu_header.addWidget(self.cpu_freq_badge)
        cpu_layout.addLayout(cpu_header)

        # Linha 1: Chave CPU Turbo Boost
        self.turbo_box = QFrame()
        self.turbo_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        turbo_row = QHBoxLayout(self.turbo_box)
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
        self.turbo_switch.setEnabled(feat.turbo_boost)
        self.turbo_switch.toggled.connect(self._on_turbo_toggled)
        turbo_row.addWidget(self.turbo_switch)
        self.turbo_box.setVisible(feat.turbo_boost)
        cpu_layout.addWidget(self.turbo_box)

        # Linha 2: Seletor de CPU Scaling Governor
        self.gov_box = QFrame()
        self.gov_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        gov_row = QHBoxLayout(self.gov_box)
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
        ordered_govs = [g for g in ("powersave", "performance", "schedutil", "ondemand", "conservative") if g in avail_govs]
        for g in avail_govs:
            if g not in ordered_govs:
                ordered_govs.append(g)
        for gov_name in ordered_govs:
            btn = QPushButton(gov_name.upper())
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(30)
            btn.setMinimumWidth(115)
            btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            btn.clicked.connect(lambda checked, g=gov_name: self._on_governor_selected(g))
            gov_row.addWidget(btn)
            self.gov_buttons[gov_name] = btn

        self.gov_box.setVisible(bool(feat.cpu_governor and self.gov_buttons))
        cpu_layout.addWidget(self.gov_box)
        self.cpu_card.setVisible(bool(feat.turbo_boost or (feat.cpu_governor and self.gov_buttons)))
        layout.addWidget(self.cpu_card)

        # =====================================================================
        # 2. NOVA FUNCIONALIDADE 1: Editor de Curva de Ventoinhas Personalizada + Limites TDP/WMI
        # =====================================================================
        self.tdp_card = QFrame()
        self.tdp_card.setProperty("class", "card")
        tdp_layout = QVBoxLayout(self.tdp_card)
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
        if feat.fan_control and feat.custom_tdp:
            tdp_title_txt = "Gestão Térmica • Editor de Curva de Ventoinhas (EC) & Limites TDP (PL1/PL2)"
            tdp_sub_txt = "Arraste os pontos de controle (°C vs PWM% / RPM) e ajuste os limites de potência PL1/PL2 da CPU."
        elif feat.fan_control:
            tdp_title_txt = "Gestão Térmica • Editor de Curva de Ventoinhas (EC)"
            tdp_sub_txt = "Arraste os pontos de controle (°C vs PWM% / RPM) para criar curvas passivas 0 RPM ou rampas agressivas."
        else:
            tdp_title_txt = "Gestão Térmica • Limites de Potência TDP (PL1/PL2)"
            tdp_sub_txt = "Ajuste os limites de potência sustentada (PL1) e de pico (PL2) da CPU via Intel RAPL."
        tdp_t = QLabel(tdp_title_txt)
        tdp_t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        tdp_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        tdp_titles.addWidget(tdp_t)

        tdp_sub = QLabel(tdp_sub_txt)
        tdp_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        tdp_titles.addWidget(tdp_sub)
        tdp_header.addLayout(tdp_titles)
        tdp_header.addStretch()

        self.tdp_badge = StatusBadge("PL1: --W | PL2: --W", bg_color="#581c87", text_color="#e9d5ff")
        self.tdp_badge.setVisible(feat.custom_tdp)
        tdp_header.addWidget(self.tdp_badge)
        tdp_layout.addLayout(tdp_header)

        # Barra de ativação da Curva Customizada no Embedded Controller
        fan_cfg = self.backend.get_custom_fan_curve()
        self.fan_ctrl_box = QFrame()
        self.fan_ctrl_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        fan_ctrl_layout = QVBoxLayout(self.fan_ctrl_box)
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

        # Sliders de Limites Térmicos WMI (exibidos apenas se o hardware expuser cpu_temp / gpu_temp)
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
        self.lbl_wmi_cpu_temp = QLabel(f"Alvo Térmico WMI CPU: {init_cpu_t}°C")
        self.lbl_wmi_cpu_temp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_wmi_cpu_temp.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 170px;")
        wmi_cpu_l.addWidget(self.lbl_wmi_cpu_temp)

        self.slider_wmi_cpu_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_wmi_cpu_temp.setRange(85, 100)
        self.slider_wmi_cpu_temp.setValue(init_cpu_t)
        self.slider_wmi_cpu_temp.valueChanged.connect(
            lambda v: self.lbl_wmi_cpu_temp.setText(f"Alvo Térmico WMI CPU: {v}°C")
        )
        wmi_cpu_l.addWidget(self.slider_wmi_cpu_temp, stretch=1)
        self.wmi_cpu_temp_widget.setVisible(feat.wmi_cpu_temp)
        wmi_temp_row.addWidget(self.wmi_cpu_temp_widget, stretch=1)

        self.wmi_gpu_temp_widget = QWidget()
        wmi_gpu_l = QHBoxLayout(self.wmi_gpu_temp_widget)
        wmi_gpu_l.setContentsMargins(0, 0, 0, 0)
        wmi_gpu_l.setSpacing(8)
        self.lbl_wmi_gpu_temp = QLabel(f"Alvo Térmico WMI GPU: {init_gpu_t}°C")
        self.lbl_wmi_gpu_temp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_wmi_gpu_temp.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 170px;")
        wmi_gpu_l.addWidget(self.lbl_wmi_gpu_temp)

        self.slider_wmi_gpu_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_wmi_gpu_temp.setRange(75, 87)
        self.slider_wmi_gpu_temp.setValue(init_gpu_t)
        self.slider_wmi_gpu_temp.valueChanged.connect(
            lambda v: self.lbl_wmi_gpu_temp.setText(f"Alvo Térmico WMI GPU: {v}°C")
        )
        wmi_gpu_l.addWidget(self.slider_wmi_gpu_temp, stretch=1)
        self.wmi_gpu_temp_widget.setVisible(feat.wmi_gpu_temp)
        wmi_temp_row.addWidget(self.wmi_gpu_temp_widget, stretch=1)

        self.wmi_temp_widget.setVisible(bool(feat.wmi_cpu_temp or feat.wmi_gpu_temp))
        fan_ctrl_layout.addWidget(self.wmi_temp_widget)

        # Linha de Presets da Curva de Ventoinhas + Botão Aplicar no EC
        fc_preset_row = QHBoxLayout()
        fc_preset_row.setSpacing(8)
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

        self.fan_ctrl_box.setVisible(feat.fan_control)
        tdp_layout.addWidget(self.fan_ctrl_box)

        # Sliders PL1 e PL2 (Intel RAPL)
        init_pl1, init_pl2 = self.backend.get_cpu_tdp_limits()
        self.sliders_box = QFrame()
        self.sliders_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 12px;")
        s_layout = QVBoxLayout(self.sliders_box)
        s_layout.setSpacing(10)

        pl1_row = QHBoxLayout()
        self.lbl_pl1_title = QLabel(f"PL1 • Potência Sustentada (Long-Term): {init_pl1} W")
        self.lbl_pl1_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_pl1_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 270px;")
        pl1_row.addWidget(self.lbl_pl1_title)

        self.slider_pl1 = QSlider(Qt.Orientation.Horizontal)
        self.slider_pl1.setRange(15, 90)
        self.slider_pl1.setValue(init_pl1)
        self.slider_pl1.setEnabled(feat.custom_tdp)
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
        self.slider_pl2.setEnabled(feat.custom_tdp)
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
        self.btn_apply_tdp.setEnabled(feat.custom_tdp)
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

        self.sliders_box.setVisible(feat.custom_tdp)
        tdp_layout.addWidget(self.sliders_box)
        self.tdp_card.setVisible(bool(feat.fan_control or feat.custom_tdp))
        layout.addWidget(self.tdp_card)

        # =====================================================================
        # 3. NOVA FUNCIONALIDADE 2: Overclock e Undervolt Dinâmico (Intel HX / AMD / WMI)
        # =====================================================================
        uv_status = self.backend.get_undervolt_status()
        has_cpu_uv = feat.cpu_undervolt
        has_gpu_off = feat.wmi_gpu_ac_offset
        is_amd_uv = (uv_status.cpu_vendor == "AMD")

        self.uv_card = QFrame()
        self.uv_card.setProperty("class", "card")
        uv_layout = QVBoxLayout(self.uv_card)
        uv_layout.setContentsMargins(20, 18, 20, 18)
        uv_layout.setSpacing(12)

        uv_header = QHBoxLayout()
        ic_uv = QLabel()
        p_uv = os.path.join(ICON_DIR, "undervolt.svg")
        if os.path.exists(p_uv):
            ic_uv.setPixmap(QPixmap(p_uv).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        uv_header.addWidget(ic_uv)

        uv_titles = QVBoxLayout()
        uv_title_txt = (
            f"Overclock & Undervolt Dinâmico • {uv_status.method}"
            if has_cpu_uv
            else "Boost Dinâmico de Potência GPU (Lenovo WMI)"
        )
        uv_t = QLabel(uv_title_txt)
        uv_t.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        uv_t.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        uv_titles.addWidget(uv_t)

        uv_sub_txt = (
            "Offsets negativos seguros de tensão com Watchdog Anti-Kernel Panic"
            + (" e Boost AC WMI." if has_gpu_off else ".")
            if has_cpu_uv
            else "Ajuste direto do offset dinâmico de potência da GPU NVIDIA via Lenovo WMI."
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
        self.uv_core_row_widget = QWidget()
        core_row = QHBoxLayout(self.uv_core_row_widget)
        core_row.setContentsMargins(0, 0, 0, 0)
        core_lbl_prefix = "AMD Curve Optimizer Offset (All Cores)" if is_amd_uv else "CPU Core Voltage Offset (Plane 0)"
        self.lbl_uv_core = QLabel(f"{core_lbl_prefix}: {uv_status.core_offset_mv} mV")
        self.lbl_uv_core.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_uv_core.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 285px;")
        core_row.addWidget(self.lbl_uv_core)

        self.slider_uv_core = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_core.setRange(-150, 0)
        self.slider_uv_core.setValue(uv_status.core_offset_mv)
        self.slider_uv_core.valueChanged.connect(self._on_uv_slider_changed)
        core_row.addWidget(self.slider_uv_core, stretch=1)
        self.uv_core_row_widget.setVisible(has_cpu_uv)
        uv_box_layout.addWidget(self.uv_core_row_widget)

        # Cache Offset (-150 mV a 0 mV — exclusivo Intel)
        self.uv_cache_row_widget = QWidget()
        cache_row = QHBoxLayout(self.uv_cache_row_widget)
        cache_row.setContentsMargins(0, 0, 0, 0)
        self.lbl_uv_cache = QLabel(f"CPU Ring/Cache Voltage Offset (Plane 2): {uv_status.cache_offset_mv} mV")
        self.lbl_uv_cache.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_uv_cache.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 285px;")
        cache_row.addWidget(self.lbl_uv_cache)

        self.slider_uv_cache = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_cache.setRange(-150, 0)
        self.slider_uv_cache.setValue(uv_status.cache_offset_mv)
        self.slider_uv_cache.valueChanged.connect(self._on_uv_slider_changed)
        cache_row.addWidget(self.slider_uv_cache, stretch=1)
        self.uv_cache_row_widget.setVisible(bool(has_cpu_uv and not is_amd_uv))
        uv_box_layout.addWidget(self.uv_cache_row_widget)

        # GPU / AC Dynamic Boost Offset (10 W a 30 W via Lenovo WMI Other)
        self.uv_gpu_offset_widget = QWidget()
        ac_off_row = QHBoxLayout(self.uv_gpu_offset_widget)
        ac_off_row.setContentsMargins(0, 0, 0, 0)
        self.lbl_uv_gpu_offset = QLabel(f"Lenovo WMI GPU / AC Dynamic Power Offset: +{uv_status.gpu_ac_offset_w} W")
        self.lbl_uv_gpu_offset.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_uv_gpu_offset.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 285px;")
        ac_off_row.addWidget(self.lbl_uv_gpu_offset)

        self.slider_uv_gpu_offset = QSlider(Qt.Orientation.Horizontal)
        self.slider_uv_gpu_offset.setRange(10, 30)
        self.slider_uv_gpu_offset.setValue(uv_status.gpu_ac_offset_w)
        self.slider_uv_gpu_offset.valueChanged.connect(self._on_uv_slider_changed)
        ac_off_row.addWidget(self.slider_uv_gpu_offset, stretch=1)
        self.uv_gpu_offset_widget.setVisible(has_gpu_off)
        uv_box_layout.addWidget(self.uv_gpu_offset_widget)

        # Linha de Presets Seguros + Botão de Emergência (0 mV) + Botão Aplicar Undervolt
        uv_actions = QHBoxLayout()
        uv_actions.setSpacing(8)
        self._uv_preset_buttons: List[QPushButton] = []
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
            b_uvp.setVisible(has_cpu_uv)
            self._uv_preset_buttons.append(b_uvp)
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
        self.btn_emergency_reset_uv.setVisible(has_cpu_uv)
        uv_actions.addWidget(self.btn_emergency_reset_uv)

        self.btn_apply_uv = QPushButton("Aplicar Offsets com Watchdog" if has_cpu_uv else "Aplicar Offset WMI")
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

        default_uv_note = (
            "Trava de Segurança: Offsets limitados a [-150 mV, 0 mV]. Em caso de falha, o Watchdog restaura 0 mV no boot."
            if has_cpu_uv
            else "Ajusta diretamente o nó Lenovo WMI gpu_nv_ac_offset dentro dos limites seguros da BIOS (10W a 30W)."
        )
        self.lbl_uv_status = QLabel(
            uv_status.last_emergency_reset
            if uv_status.last_emergency_reset
            else default_uv_note
        )
        self.lbl_uv_status.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        uv_box_layout.addWidget(self.lbl_uv_status)

        uv_layout.addWidget(uv_box)
        self.uv_card.setVisible(bool(has_cpu_uv or has_gpu_off))
        layout.addWidget(self.uv_card)

        supported_profiles = self.backend.get_supported_canonical_profiles()

        # =====================================================================
        # 3.5 Perfis Personalizados Salváveis (Presets em 1 Clique)
        # =====================================================================
        self.presets_card = QFrame()
        self.presets_card.setProperty("class", "card")
        presets_layout = QVBoxLayout(self.presets_card)
        presets_layout.setContentsMargins(20, 18, 20, 18)
        presets_layout.setSpacing(12)

        presets_header = QHBoxLayout()
        ic_pre = QLabel()
        p_pre = os.path.join(ICON_DIR, "mode_custom.svg")
        if os.path.exists(p_pre):
            ic_pre.setPixmap(QPixmap(p_pre).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        presets_header.addWidget(ic_pre)

        presets_titles = QVBoxLayout()
        pt_title = QLabel("Perfis Personalizados • Presets em 1 Clique")
        pt_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        pt_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        presets_titles.addWidget(pt_title)

        pt_sub = QLabel(
            "Salve a combinação atual (Perfil Térmico, Governor, Turbo Boost, TDP e Hz) e aplique com 1 clique."
        )
        pt_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        presets_titles.addWidget(pt_sub)
        presets_header.addLayout(presets_titles)
        presets_header.addStretch()

        self.presets_count_badge = StatusBadge("0 PRESETS", bg_color="#1e293b", text_color="#a78bfa")
        presets_header.addWidget(self.presets_count_badge)
        presets_layout.addLayout(presets_header)

        add_preset_box = QFrame()
        add_preset_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 12px;")
        add_p_row = QHBoxLayout(add_preset_box)
        add_p_row.setContentsMargins(6, 4, 6, 4)
        add_p_row.setSpacing(10)

        self.edit_preset_name = QLineEdit()
        self.edit_preset_name.setPlaceholderText("Nome do preset (ex: Render Silencioso, Competitivo 144Hz, Faculdade)")
        self.edit_preset_name.setFixedHeight(30)
        self.edit_preset_name.setStyleSheet(f"""
            QLineEdit {{
                background-color: #0d1322;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
            }}
        """)
        add_p_row.addWidget(self.edit_preset_name, stretch=1)

        self.btn_save_preset = QPushButton("Salvar Estado Atual")
        self.btn_save_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_preset.setFixedHeight(30)
        self.btn_save_preset.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.THERMAL_CUSTOM};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 4px 14px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #b45cff;
            }}
        """)
        self.btn_save_preset.clicked.connect(self._on_save_user_preset)
        add_p_row.addWidget(self.btn_save_preset)
        presets_layout.addWidget(add_preset_box)

        self.presets_list_container = QWidget()
        self.presets_list_layout = QVBoxLayout(self.presets_list_container)
        self.presets_list_layout.setContentsMargins(0, 0, 0, 0)
        self.presets_list_layout.setSpacing(8)
        presets_layout.addWidget(self.presets_list_container)
        self._rebuild_user_presets_list()

        has_preset_ctrl = any((
            bool(feat.platform_profile and supported_profiles),
            bool(feat.cpu_governor and self.gov_buttons),
            feat.turbo_boost,
            feat.custom_tdp,
            feat.refresh_rate,
        ))
        self.presets_card.setVisible(bool(has_preset_ctrl))
        layout.addWidget(self.presets_card)

        # =====================================================================
        # 4. NOVA FUNCIONALIDADE 3: Gerenciador de Perfis de Energia por Aplicativo (App Rules)
        # =====================================================================
        self.rules_card = QFrame()
        self.rules_card.setProperty("class", "card")
        rules_layout = QVBoxLayout(self.rules_card)
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

        # Sub-painel de Configurações do Auto-Switch em Jogos
        self.game_switch_opts_box = QFrame()
        self.game_switch_opts_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        gopts_layout = QVBoxLayout(self.game_switch_opts_box)
        gopts_layout.setContentsMargins(6, 6, 6, 6)
        gopts_layout.setSpacing(10)

        gopts_title_row = QHBoxLayout()
        ic_game = QLabel()
        p_game = os.path.join(ICON_DIR, "game_controller.svg")
        if os.path.exists(p_game):
            ic_game.setPixmap(QPixmap(p_game).scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        gopts_title_row.addWidget(ic_game)

        gopts_title = QLabel("Configurações do Auto-Switch em Jogos")
        gopts_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        gopts_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        gopts_title_row.addWidget(gopts_title)
        gopts_title_row.addStretch()
        gopts_layout.addLayout(gopts_title_row)

        self.game_target_row_widget = QWidget()
        gt_row = QHBoxLayout(self.game_target_row_widget)
        gt_row.setContentsMargins(0, 0, 0, 0)
        gt_row.setSpacing(10)
        gt_lbl = QLabel("Perfil térmico ao detectar jogos (Steam, Heroic, Sober, Wine, Minecraft):")
        gt_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        gt_row.addWidget(gt_lbl)
        gt_row.addStretch()

        self.combo_game_target_profile = QComboBox()
        self.combo_game_target_profile.setMinimumWidth(230)
        self.combo_game_target_profile.setFixedHeight(28)
        self.combo_game_target_profile.setStyleSheet(f"""
            QComboBox {{
                background-color: #192338;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
            }}
        """)
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
        gr_lbl = QLabel("Elevar taxa de atualização do painel para o máximo (Hz) durante o jogo e restaurar ao sair")
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

        rules_layout.addWidget(self.game_switch_opts_box)

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
            if prof_id in supported_profiles:
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

        self.rules_card.setVisible(bool(feat.platform_profile and supported_profiles))
        layout.addWidget(self.rules_card)

        # =====================================================================
        # 5. ELITE 5: Mapeador de Teclas Personalizadas (Tecla Copilot F23 & Órfãs)
        # =====================================================================
        self.remap_card = QFrame()
        self.remap_card.setProperty("class", "card")
        remap_layout = QVBoxLayout(self.remap_card)
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
            if slot_id == "refresh_rate_hotkey" and not feat.refresh_rate:
                row_frame.setVisible(False)
            elif slot_id == "eco_hotkey" and not feat.eco_travel:
                row_frame.setVisible(False)
            remap_layout.addWidget(row_frame)

        layout.addWidget(self.remap_card)

        # =====================================================================
        # 6. Monitoramento Detalhado da GPU (Estado D3cold / Ativa)
        # =====================================================================
        self.gpu_card = QFrame()
        self.gpu_card.setProperty("class", "card")
        gpu_layout = QVBoxLayout(self.gpu_card)
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
        self.gpu_card.setVisible(feat.gpu_telemetry)
        layout.addWidget(self.gpu_card)

        # =====================================================================
        # RECURSO 1: GPU MUX Switch (Exibe apenas os modos realmente liberados!)
        # =====================================================================
        self.mux_card = QFrame()
        self.mux_card.setProperty("class", "card")
        mux_layout = QVBoxLayout(self.mux_card)
        mux_layout.setContentsMargins(20, 18, 20, 18)
        mux_layout.setSpacing(14)

        mux_header = QHBoxLayout()
        ic_mux = QLabel()
        p_mux = os.path.join(ICON_DIR, "gpu_stack.svg")
        if os.path.exists(p_mux):
            ic_mux.setPixmap(QPixmap(p_mux).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        mux_header.addWidget(ic_mux)

        mux_titles = QVBoxLayout()
        self.mux_title_lbl = QLabel("GPU MUX Switch • Comutador de Gráficos Lenovo")
        self.mux_title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.mux_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        mux_titles.addWidget(self.mux_title_lbl)

        self.mux_sub_lbl = QLabel("Alterne entre os modos gráficos suportados pelo seu notebook.")
        self.mux_sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        mux_titles.addWidget(self.mux_sub_lbl)
        mux_header.addLayout(mux_titles)
        mux_header.addStretch()

        self.mux_backend_badge = StatusBadge("BACKEND: N/A", bg_color="#1e293b", text_color="#00d2ff")
        mux_header.addWidget(self.mux_backend_badge)
        mux_layout.addLayout(mux_header)

        self.mux_reboot_banner = QLabel("⚠ A alteração de modo de GPU exige reinicialização do sistema ou da sessão gráfica.")
        self.mux_reboot_banner.setStyleSheet("""
            background-color: rgba(239, 68, 68, 0.15);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.35);
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.mux_reboot_banner.setVisible(False)
        mux_layout.addWidget(self.mux_reboot_banner)

        mux_blocks_layout = QHBoxLayout()
        mux_blocks_layout.setSpacing(12)

        self.block_mux_hybrid = GpuModeBlock(
            "hybrid",
            "Modo Híbrido (Optimus)",
            "iGPU renderiza a tela. Aceleração dGPU sob demanda em jogos.",
            ThemeTokens.BORDER_CYAN
        )
        self.block_mux_hybrid.clicked.connect(self._on_mux_mode_selected)
        self.mux_blocks["hybrid"] = self.block_mux_hybrid
        mux_blocks_layout.addWidget(self.block_mux_hybrid)

        self.block_mux_dedicated = GpuModeBlock(
            "dedicated",
            "dGPU Direta (Exclusiva)",
            "Conexão física direta no monitor. Menor latência & G-Sync.",
            ThemeTokens.THERMAL_CUSTOM
        )
        self.block_mux_dedicated.clicked.connect(self._on_mux_mode_selected)
        self.mux_blocks["dedicated"] = self.block_mux_dedicated
        mux_blocks_layout.addWidget(self.block_mux_dedicated)

        self.block_mux_integrated = GpuModeBlock(
            "integrated",
            "iGPU Pura (Eco Extremo)",
            "Placa dedicada desligada em nível PCIe. Autonomia máxima de bateria.",
            ThemeTokens.STATUS_GREEN
        )
        self.block_mux_integrated.clicked.connect(self._on_mux_mode_selected)
        self.mux_blocks["integrated"] = self.block_mux_integrated
        mux_blocks_layout.addWidget(self.block_mux_integrated)

        mux_layout.addLayout(mux_blocks_layout)
        layout.addWidget(self.mux_card)

        # =====================================================================
        # RECURSO 2: Taxa de Atualização de Tela (Exibido apenas se painel tiver >1 Hz controlável!)
        # =====================================================================
        self.ref_card = QFrame()
        self.ref_card.setProperty("class", "card")
        ref_layout = QVBoxLayout(self.ref_card)
        ref_layout.setContentsMargins(20, 18, 20, 18)
        ref_layout.setSpacing(14)

        ref_header = QHBoxLayout()
        ic_ref = QLabel()
        p_ref = os.path.join(ICON_DIR, "refresh.svg")
        if os.path.exists(p_ref):
            ic_ref.setPixmap(QPixmap(p_ref).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        ref_header.addWidget(ic_ref)

        ref_titles = QVBoxLayout()
        self.ref_title_lbl = QLabel("Taxa de Atualização do Painel • Lenovo Display Control")
        self.ref_title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.ref_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        ref_titles.addWidget(self.ref_title_lbl)

        ref_sub = QLabel("Gerenciamento dinâmico de fluidez (Hz) compatível com Wayland (KDE / wlroots) e X11.")
        ref_sub.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        ref_titles.addWidget(ref_sub)
        ref_header.addLayout(ref_titles)
        ref_header.addStretch()

        self.ref_rate_badge = StatusBadge("-- Hz", bg_color="#1e293b", text_color="#00d2ff")
        ref_header.addWidget(self.ref_rate_badge)
        ref_layout.addLayout(ref_header)

        ref_ctrl_box = QFrame()
        ref_ctrl_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        ref_ctrl_row = QHBoxLayout(ref_ctrl_box)
        ref_ctrl_row.setContentsMargins(8, 6, 8, 6)

        ref_info = QVBoxLayout()
        self.ref_display_name_lbl = QLabel("Painel Interno (eDP-1)")
        self.ref_display_name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.ref_display_name_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        ref_info.addWidget(self.ref_display_name_lbl)

        ref_desc = QLabel("Selecione a frequência do painel ou use o atalho Fn + R (Alt + R).")
        ref_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        ref_info.addWidget(ref_desc)
        ref_ctrl_row.addLayout(ref_info)
        ref_ctrl_row.addStretch()

        self.ref_buttons_layout = QHBoxLayout()
        self.ref_buttons_layout.setSpacing(8)
        ref_ctrl_row.addLayout(self.ref_buttons_layout)

        self.btn_cycle_ref = QPushButton("Ciclar Fn + R")
        self.btn_cycle_ref.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cycle_ref.setStyleSheet(f"""
            QPushButton {{
                background-color: #192338;
                color: {ThemeTokens.BORDER_CYAN};
                border: 1px solid {ThemeTokens.BORDER_CYAN};
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {ThemeTokens.BORDER_CYAN};
                color: #0b0f19;
            }}
        """)
        self.btn_cycle_ref.clicked.connect(self._on_cycle_refresh_rate_clicked)
        ref_ctrl_row.addWidget(self.btn_cycle_ref)
        ref_layout.addWidget(ref_ctrl_box)

        self.ref_auto_box = QFrame()
        self.ref_auto_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        ref_auto_row = QHBoxLayout(self.ref_auto_box)
        ref_auto_row.setContentsMargins(8, 6, 8, 6)

        ra_info = QVBoxLayout()
        ra_lbl = QLabel("Alternância Automática de Taxa (Carregador AC vs Bateria)")
        ra_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        ra_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        ra_info.addWidget(ra_lbl)

        self.ra_desc = QLabel("Reduz para a menor taxa ao desconectar da tomada para poupar bateria, e restaura taxa máxima no AC.")
        self.ra_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        ra_info.addWidget(self.ra_desc)
        ref_auto_row.addLayout(ra_info)
        ref_auto_row.addStretch()

        self.ref_auto_switch = ToggleSwitch()
        self.ref_auto_switch.setChecked(self.backend.get_auto_refresh_rate_transition())
        self.ref_auto_switch.toggled.connect(self._on_ref_auto_toggled)
        ref_auto_row.addWidget(self.ref_auto_switch)
        self.ref_auto_box.setVisible(feat.battery)
        ref_layout.addWidget(self.ref_auto_box)

        layout.addWidget(self.ref_card)

        # =====================================================================
        # RECURSO 3: LCD Overdrive & Ajustes de BIOS / Lenovo WMI (Zero Hardcoding)
        # =====================================================================
        self.bios_card = QFrame()
        self.bios_card.setProperty("class", "card")
        bios_layout = QVBoxLayout(self.bios_card)
        bios_layout.setContentsMargins(20, 18, 20, 18)
        bios_layout.setSpacing(14)

        bios_header = QHBoxLayout()
        ic_bios = QLabel()
        p_bios = os.path.join(ICON_DIR, "tools.svg")
        if os.path.exists(p_bios):
            ic_bios.setPixmap(QPixmap(p_bios).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        bios_header.addWidget(ic_bios)

        bios_titles = QVBoxLayout()
        self.bios_title_lbl = QLabel("Ajustes de Firmware Lenovo (BIOS / WMI)")
        self.bios_title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.bios_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        bios_titles.addWidget(self.bios_title_lbl)

        self.bios_sub_lbl = QLabel("Nós de BIOS descobertos dinamicamente no hardware deste notebook.")
        self.bios_sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        bios_titles.addWidget(self.bios_sub_lbl)
        bios_header.addLayout(bios_titles)
        bios_header.addStretch()

        self.bios_count_badge = StatusBadge("-- ITENS", bg_color="#1e293b", text_color="#38bdf8")
        bios_header.addWidget(self.bios_count_badge)
        bios_layout.addLayout(bios_header)

        self.od_box = QFrame()
        self.od_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        od_row = QHBoxLayout(self.od_box)
        od_row.setContentsMargins(8, 6, 8, 6)

        od_info = QVBoxLayout()
        od_lbl = QLabel("LCD Overdrive (Tempo de Resposta Acelerado)")
        od_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        od_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        od_info.addWidget(od_lbl)

        od_desc = QLabel("Reduz o ghosting e motion blur em jogos de ação acelerando a transição de cinza-para-cinza (GtG).")
        od_desc.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
        od_info.addWidget(od_desc)
        od_row.addLayout(od_info)
        od_row.addStretch()

        self.lcd_overdrive_switch = ToggleSwitch()
        is_od_supp = self.backend.is_lcd_overdrive_supported()
        self.lcd_overdrive_switch.setEnabled(is_od_supp)
        self.lcd_overdrive_switch.setChecked(self.backend.get_lcd_overdrive() if is_od_supp else False)
        self.lcd_overdrive_switch.toggled.connect(self._on_lcd_overdrive_toggled)
        od_row.addWidget(self.lcd_overdrive_switch)
        # Oculta completamente o bloco de LCD Overdrive quando o painel/BIOS não o libera!
        self.od_box.setVisible(is_od_supp)
        bios_layout.addWidget(self.od_box)

        self.bios_dyn_container = QVBoxLayout()
        self.bios_dyn_container.setSpacing(10)
        bios_layout.addLayout(self.bios_dyn_container)

        self._build_dynamic_bios_attributes()
        layout.addWidget(self.bios_card)

        # =====================================================================
        # 7. Perfis Térmicos ACPI (Platform Profile — exibe apenas perfis suportados)
        # =====================================================================
        self.prof_card = QFrame()
        self.prof_card.setProperty("class", "card")
        prof_layout = QVBoxLayout(self.prof_card)
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
        card_quiet.setVisible("low-power" in supported_profiles)
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
        card_bal.setVisible("balanced" in supported_profiles)
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
        card_perf.setVisible("performance" in supported_profiles)
        prof_layout.addWidget(card_perf)
        self.cards["performance"] = card_perf

        max_power_desc = (
            "Perfil avançado descoberto no kernel (incluído no ciclo Fn + Q) para potência máxima sustentada e rotação máxima das ventoinhas."
            if feat.fan_control
            else "Perfil avançado descoberto no kernel (incluído no ciclo Fn + Q) para potência máxima sustentada (ventoinhas controladas pelo EC)."
        )
        card_max = ProfileCard(
            profile_id="max-power",
            icon_source=os.path.join(ICON_DIR, "thermal_max_power.svg"),
            title="Desempenho Máximo (Max-Power)",
            desc=max_power_desc,
            accent_color=ThemeTokens.THERMAL_CUSTOM
        )
        card_max.clicked.connect(self._on_card_selected)
        card_max.setVisible(bool(feat.max_power_profile or "max-power" in supported_profiles))
        prof_layout.addWidget(card_max)
        self.cards["max-power"] = card_max

        self.prof_card.setVisible(bool(feat.platform_profile and supported_profiles))
        layout.addWidget(self.prof_card)
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
        if self.backend.get_cpu_vendor() == "AMD":
            self.lbl_uv_core.setText(f"AMD Curve Optimizer Offset (All Cores): {core_mv} mV")
        else:
            hex_core = hex(self.backend._encode_intel_msr_undervolt_offset(0, core_mv))
            self.lbl_uv_core.setText(f"CPU Core Voltage Offset (Plane 0): {core_mv} mV ({hex_core})")
        self.lbl_uv_cache.setText(f"CPU Ring/Cache Voltage Offset (Plane 2): {cache_mv} mV")
        self.lbl_uv_gpu_offset.setText(f"Lenovo WMI GPU / AC Dynamic Power Offset: +{gpu_w} W")

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

    def _on_game_target_profile_changed(self):
        prof = self.combo_game_target_profile.currentData()
        if prof:
            self.backend.set_game_target_profile(str(prof))

    def _on_game_refresh_max_toggled(self, checked: bool):
        self.backend.set_game_auto_refresh_max(checked)

    def _on_game_lock_touchpad_toggled(self, checked: bool):
        self.backend.set_game_auto_lock_touchpad(checked)

    # =========================================================================
    # Métodos de Perfis Personalizados Salváveis (Presets em 1 Clique)
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
            empty_lbl = QLabel("Nenhum preset salvo ainda. Ajuste os controles desejados e clique em 'Salvar Estado Atual'.")
            empty_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px; padding: 4px 2px;")
            self.presets_list_layout.addWidget(empty_lbl)
            return

        for p in presets:
            pid = str(p.get("id", ""))
            pname = str(p.get("name", pid))
            summary = self.backend.format_user_preset_summary(p)

            row_f = QFrame()
            row_f.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 7px; padding: 6px 12px;")
            r_lay = QHBoxLayout(row_f)
            r_lay.setContentsMargins(6, 4, 6, 4)
            r_lay.setSpacing(10)

            lbl_name = QLabel(pname)
            lbl_name.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl_name.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; min-width: 140px;")
            r_lay.addWidget(lbl_name)

            lbl_sum = QLabel(summary)
            lbl_sum.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
            r_lay.addWidget(lbl_sum, stretch=1)

            btn_apply = QPushButton("Aplicar")
            btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_apply.setFixedHeight(26)
            btn_apply.setStyleSheet(f"""
                QPushButton {{
                    background-color: #192338;
                    color: {ThemeTokens.BORDER_CYAN};
                    border: 1px solid {ThemeTokens.BORDER_CYAN};
                    border-radius: 5px;
                    padding: 2px 12px;
                    font-weight: bold;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    background-color: {ThemeTokens.BORDER_CYAN};
                    color: #0b0f19;
                }}
            """)
            btn_apply.clicked.connect(lambda _c=False, p_id=pid, p_name=pname: self._on_apply_user_preset(p_id, p_name))
            r_lay.addWidget(btn_apply)

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

    def _on_apply_user_preset(self, preset_id: str, preset_name: str):
        ok, msg = self.backend.apply_user_preset(preset_id)
        if not ok:
            QMessageBox.warning(self, "Preset Personalizado", f"Não foi possível aplicar o preset '{preset_name}':\n{msg}")
            return
        self.refresh_profile_state()
        self.preset_applied.emit(preset_name, msg)

    def _on_delete_user_preset(self, preset_id: str):
        self.backend.delete_user_preset(preset_id)
        self._rebuild_user_presets_list()

    # =========================================================================
    # Métodos do Mapeador de Teclas Personalizadas (Copilot Key Remapper)
    # =========================================================================
    def _get_supported_key_actions(self) -> List[Tuple[str, str]]:
        """Filtra as ações do remapper exibindo apenas recursos realmente liberados neste sistema."""
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
            if act_id == "toggle_touchpad" and not feat.touchpad_control:
                continue
            if act_id == "toggle_mic_mute" and not has_mic_tool:
                continue
            filtered.append((act_id, act_label))
        return filtered

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

        # Status do App Rules e opções do Auto-Switch
        active_game = self.backend.get_active_game()
        if active_game:
            self.app_rules_badge.setText(f"ATIVO: {active_game[:22].upper()}")
            self.app_rules_badge.setColor("#581c87", "#e9d5ff")
        else:
            self.app_rules_badge.setText("AUTO-SWITCH ATIVO")
            self.app_rules_badge.setColor("#064e3b", "#34d399")

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
        elif active_prof == "custom":
            self.current_badge.setText("CUSTOM")
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

        # 4. Atualizar GPU MUX, Taxa de Atualização e LCD Overdrive / BIOS
        self.refresh_mux_state()
        self.refresh_display_state()
        self.refresh_bios_state()

    # =========================================================================
    # Métodos do GPU MUX Switch (Recurso 1)
    # =========================================================================
    def _on_mux_mode_selected(self, mode: str):
        ok, msg, req_reboot = self.backend.set_gpu_mux_mode(mode)
        if ok:
            self.refresh_mux_state()
            self.gpu_mux_changed.emit(mode, req_reboot)
        else:
            QMessageBox.warning(self, "GPU MUX Switch", f"Não foi possível alterar o modo de GPU:\n{msg}")

    def refresh_mux_state(self):
        mux = self.backend.get_gpu_mux_info()
        show_mux = bool(mux.available and mux.available_modes and mux.backend_name not in ("none", "software"))
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

    # =========================================================================
    # Métodos da Taxa de Atualização de Tela (Recurso 2)
    # =========================================================================
    def _on_refresh_rate_button_clicked(self, hz: int):
        ok, msg = self.backend.set_refresh_rate(hz)
        if ok:
            self.refresh_display_state()
            self.refresh_rate_changed.emit(hz)
        else:
            QMessageBox.warning(self, "Taxa de Atualização", f"Não foi possível alterar a taxa para {hz} Hz:\n{msg}")

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
            f"Reduz para {min_hz} Hz ao desconectar da tomada para poupar bateria, e restaura {max_hz} Hz no AC."
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
                        background-color: {ThemeTokens.BORDER_CYAN};
                        color: #0b0f19;
                        border: 1px solid {ThemeTokens.BORDER_CYAN};
                        border-radius: 6px;
                        padding: 6px 14px;
                        font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #192338;
                        color: {ThemeTokens.TEXT_LIGHT_GRAY};
                        border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                        border-radius: 6px;
                        padding: 6px 14px;
                    }}
                    QPushButton:hover {{
                        border-color: {ThemeTokens.BORDER_CYAN};
                    }}
                """)

        self.ref_auto_switch.blockSignals(True)
        self.ref_auto_switch.setChecked(info.auto_switch_ac)
        self.ref_auto_switch.blockSignals(False)

    # =========================================================================
    # Métodos de LCD Overdrive e BIOS / Firmware Attributes (Recurso 3)
    # =========================================================================
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
        """Constrói dinamicamente os controles visuais baseados estritamente nos nós que a BIOS expõe (Zero Hardcoding)."""
        while self.bios_dyn_container.count():
            item = self.bios_dyn_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.bios_attr_widgets.clear()
        is_od_supp = self.backend.is_lcd_overdrive_supported()
        self.od_box.setVisible(is_od_supp)

        attrs = self.backend.get_bios_attributes()
        visible_attrs = [a for a in attrs if a.attr_id.lower() not in ("lcd_overdrive",)]
        total_items = len(visible_attrs) + (1 if is_od_supp else 0)
        self.bios_count_badge.setText(f"{total_items} {'ITEM' if total_items == 1 else 'ITENS'}")

        if is_od_supp and visible_attrs:
            self.bios_title_lbl.setText("LCD Overdrive & Ajustes de Firmware Lenovo (BIOS / WMI)")
            self.bios_sub_lbl.setText("Aceleração de resposta do monitor (anti-ghosting) e nós de BIOS descobertos dinamicamente no hardware.")
        elif is_od_supp:
            self.bios_title_lbl.setText("LCD Overdrive • Aceleração de Painel")
            self.bios_sub_lbl.setText("Aceleração de tempo de resposta do monitor (anti-ghosting) liberada pela BIOS deste notebook.")
        else:
            self.bios_title_lbl.setText("Ajustes de Firmware Lenovo (BIOS / WMI)")
            self.bios_sub_lbl.setText("Parâmetros de firmware descobertos dinamicamente na BIOS deste notebook.")

        # Oculta o card inteiro se o notebook não liberar nem LCD Overdrive nem atributos WMI da BIOS
        self.bios_card.setVisible(bool(is_od_supp or visible_attrs))
        if not visible_attrs:
            return

        for a in visible_attrs:

            row_box = QFrame()
            row_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
            r_layout = QHBoxLayout(row_box)
            r_layout.setContentsMargins(8, 6, 8, 6)

            info_layout = QVBoxLayout()
            h_top = QHBoxLayout()
            title_lbl = QLabel(a.display_name)
            title_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
            h_top.addWidget(title_lbl)

            cat_badge = StatusBadge(a.category.upper(), bg_color="#1e293b", text_color="#38bdf8")
            h_top.addWidget(cat_badge)
            h_top.addStretch()
            info_layout.addLayout(h_top)

            desc_lbl = QLabel(f"Atributo sysfs: {a.attr_id} • Tipo: {a.attr_type.capitalize()}")
            desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px;")
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
                val_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                val_lbl.setStyleSheet(f"color: {ThemeTokens.BORDER_CYAN}; min-width: 38px;")

                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(min_v, max_v)
                sl.setValue(cur_v)
                sl.setFixedWidth(130)
                sl.valueChanged.connect(lambda v, lbl=val_lbl: lbl.setText(str(v)))

                btn_apply = QPushButton("Aplicar")
                btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_apply.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #192338;
                        color: {ThemeTokens.BORDER_CYAN};
                        border: 1px solid {ThemeTokens.BORDER_CYAN};
                        border-radius: 6px;
                        padding: 4px 10px;
                        font-weight: bold;
                        font-size: 10px;
                    }}
                    QPushButton:hover {{
                        background-color: {ThemeTokens.BORDER_CYAN};
                        color: #0b0f19;
                    }}
                """)
                btn_apply.clicked.connect(lambda _c=False, aid=a.attr_id, s=sl, l=val_lbl: self._on_apply_bios_int_attribute(aid, s, l))

                self.bios_attr_widgets[a.attr_id] = (sl, val_lbl)
                ctrl_layout.addWidget(sl)
                ctrl_layout.addWidget(val_lbl)
                ctrl_layout.addWidget(btn_apply)

            else:  # enumeration
                combo = QComboBox()
                combo.setStyleSheet(f"""
                    QComboBox {{
                        background-color: #192338;
                        color: {ThemeTokens.TEXT_WHITE_100};
                        border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                        border-radius: 6px;
                        padding: 4px 10px;
                        min-width: 110px;
                    }}
                """)
                poss = a.possible_values if a.possible_values else [a.current_value]
                for p in poss:
                    combo.addItem(p)
                idx = combo.findText(a.current_value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

                btn_apply = QPushButton("Aplicar")
                btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_apply.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #192338;
                        color: {ThemeTokens.BORDER_CYAN};
                        border: 1px solid {ThemeTokens.BORDER_CYAN};
                        border-radius: 6px;
                        padding: 4px 10px;
                        font-weight: bold;
                        font-size: 10px;
                    }}
                    QPushButton:hover {{
                        background-color: {ThemeTokens.BORDER_CYAN};
                        color: #0b0f19;
                    }}
                """)
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
            self.refresh_profile_state()
            QMessageBox.information(self, "Ajuste de BIOS Aplicado", f"{attr_id}: {val}\n{msg}")
        else:
            QMessageBox.warning(self, "Falha ao Gravar BIOS", f"{attr_id}:\n{msg}")

    def _on_apply_bios_enum_attribute(self, attr_id: str, combo: QComboBox):
        val = combo.currentText()
        ok, msg = self.backend.set_bios_attribute(attr_id, val)
        if ok:
            self.refresh_profile_state()
            QMessageBox.information(self, "Ajuste de BIOS Aplicado", f"{attr_id}: {val}\n{msg}")
        else:
            QMessageBox.warning(self, "Falha ao Gravar BIOS", f"{attr_id}:\n{msg}")

    def _on_toggle_bios_bool_attribute(self, attr_id: str, checked: bool):
        val = "1" if checked else "0"
        ok, msg = self.backend.set_bios_attribute(attr_id, val)
        if ok:
            self.refresh_profile_state()
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
        self.bios_card.setVisible(bool(is_od_supp or self.bios_attr_widgets))

