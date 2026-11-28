"""Editor gráfico interativo de curva de ventoinhas (Temperatura vs PWM/RPM)."""

from typing import List, Tuple
from core.qt_compat import (
    QWidget, Qt, Signal, QFont,
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPointF, QPainterPath
)
from ui.theme_tokens import ThemeTokens


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
        painter.setBrush(QBrush(QColor(ThemeTokens.BG_APP)))
        painter.drawRoundedRect(rect, 8, 8)

        pad_left, pad_top, plot_w, plot_h = self._plot_bounds()

        # Grade horizontal (PWM % e RPM estimado)
        painter.setFont(QFont(ThemeTokens.FONT_NAME, 8))
        for pwm_val in (0, 25, 50, 75, 100):
            yy = self._pwm_to_y(pwm_val)
            rpm_est = int(round((pwm_val / 100.0) * self.MAX_RPM))
            painter.setPen(QPen(QColor("#22252b"), 1, Qt.PenStyle.DotLine))
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
            painter.setPen(QPen(QColor("#22252b"), 1, Qt.PenStyle.DotLine))
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

            painter.setPen(QPen(QColor(ThemeTokens.BG_APP), 2.0))
            painter.setBrush(QBrush(QColor("#f4f5f7" if is_active_node else accent_hex)))
            painter.drawEllipse(pt, radius, radius)

            # Rótulo do ponto quando arrastado ou sob o mouse
            if is_active_node:
                rpm_pt = int(round((pwm / 100.0) * self.MAX_RPM))
                tag = f"{t}°C • {pwm}% (~{rpm_pt} RPM)"
                painter.setFont(QFont(ThemeTokens.FONT_NAME, 8, QFont.Weight.Bold))
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

        painter.setPen(QPen(QColor(ThemeTokens.BG_APP), 2))
        painter.setBrush(QBrush(QColor(ThemeTokens.STATUS_GREEN)))
        painter.drawEllipse(op_pt, 5.2, 5.2)

        # Cabeçalho interno do gráfico
        painter.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.Bold))
        painter.setPen(QColor(accent_hex))
        painter.drawText(int(pad_left + 4), 22, curve_title)

        if self.fan1_rpm > 0 and self.fan2_rpm > 0:
            rpm_label = f"Fan 1: {self.fan1_rpm} RPM | Fan 2: {self.fan2_rpm} RPM ({self.cpu_temp_c:.1f}°C)"
        elif self.fan1_rpm > 0:
            rpm_label = f"Ventoinha: {self.fan1_rpm} RPM ({self.cpu_temp_c:.1f}°C)"
        elif self.fan2_rpm > 0:
            rpm_label = f"Ventoinha 2: {self.fan2_rpm} RPM ({self.cpu_temp_c:.1f}°C)"
        else:
            rpm_label = f"Operação Atual: {self.cpu_temp_c:.1f}°C -> {int(round(live_pwm))}% PWM (~{int(live_rpm)} RPM)"
        painter.setPen(QColor(ThemeTokens.STATUS_GREEN))
        painter.drawText(
            int(pad_left), 8, int(plot_w), 18,
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            rpm_label
        )

        painter.end()
