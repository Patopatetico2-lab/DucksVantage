"""Widget de gráfico térmico em tempo real (CPU/GPU °C) no Estilo 3."""

from core.qt_compat import (
    QWidget, QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QPointF, Qt, QFont
)
from ui.theme_tokens import ThemeTokens


class LiveThermalChart(QWidget):
    """Gráfico leve em QPainter com os últimos ~2 minutos de temperatura de CPU e GPU (°C)."""

    MAX_SAMPLES = 80

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cpu_samples: list[float] = []
        self.gpu_samples: list[float] = []
        self.peak_cpu: float = 0.0
        self.peak_gpu: float = 0.0
        self.setMinimumHeight(130)

    def add_sample(self, cpu_temp: float, gpu_temp: float = 0.0) -> None:
        c_val = max(0.0, float(cpu_temp))
        g_val = max(0.0, float(gpu_temp))
        self.cpu_samples.append(c_val)
        self.gpu_samples.append(g_val)
        if len(self.cpu_samples) > self.MAX_SAMPLES:
            self.cpu_samples = self.cpu_samples[-self.MAX_SAMPLES:]
            self.gpu_samples = self.gpu_samples[-self.MAX_SAMPLES:]
        if c_val > self.peak_cpu:
            self.peak_cpu = c_val
        if g_val > self.peak_gpu:
            self.peak_gpu = g_val
        self.update()

    def reset_peaks(self) -> None:
        self.peak_cpu = self.cpu_samples[-1] if self.cpu_samples else 0.0
        self.peak_gpu = self.gpu_samples[-1] if self.gpu_samples else 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        w = float(self.width())
        h = float(self.height())
        painter.setPen(QPen(QColor("#262930"), 1))
        painter.setBrush(QColor(ThemeTokens.BG_APP))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

        pad_l, pad_r, pad_t, pad_b = 38.0, 14.0, 20.0, 14.0
        pw = max(30.0, w - pad_l - pad_r)
        ph = max(30.0, h - pad_t - pad_b)
        y_min, y_max = 30.0, 105.0

        def ty(v: float) -> float:
            norm = max(0.0, min(1.0, (v - y_min) / (y_max - y_min)))
            return pad_t + ph * (1.0 - norm)

        painter.setFont(QFont(ThemeTokens.FONT_NAME, 8))
        for deg in (40, 60, 80, 90):
            yy = ty(float(deg))
            is_warn = (deg == 90)
            painter.setPen(
                QPen(
                    QColor("#5b2121" if is_warn else "#22252b"),
                    1,
                    Qt.PenStyle.DashLine if is_warn else Qt.PenStyle.DotLine,
                )
            )
            painter.drawLine(int(pad_l), int(yy), int(pad_l + pw), int(yy))
            painter.setPen(QColor("#f87171" if is_warn else ThemeTokens.TEXT_WHITE_40))
            painter.drawText(
                2,
                int(yy - 7),
                int(pad_l - 6),
                14,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{deg}°",
            )

        n = len(self.cpu_samples)
        if n >= 2:
            series = (
                (self.gpu_samples, ThemeTokens.ACCENT_MUTED, 1.7, 25),
                (self.cpu_samples, ThemeTokens.ACCENT_STEEL, 2.0, 48),
            )
            for samples, col, width_px, fill_alpha in series:
                if not any(s > 0.0 for s in samples):
                    continue
                path = QPainterPath()
                area = QPainterPath()
                for idx, val in enumerate(samples):
                    xx = pad_l + (idx / float(max(1, n - 1))) * pw
                    yy = ty(val if val > 0.0 else y_min)
                    pt = QPointF(xx, yy)
                    if idx == 0:
                        path.moveTo(pt)
                        area.moveTo(xx, pad_t + ph)
                        area.lineTo(pt)
                    else:
                        path.lineTo(pt)
                        area.lineTo(pt)
                area.lineTo(pad_l + pw, pad_t + ph)
                area.closeSubpath()

                grad = QLinearGradient(0, pad_t, 0, pad_t + ph)
                c_top = QColor(col)
                c_top.setAlpha(fill_alpha)
                c_bot = QColor(col)
                c_bot.setAlpha(0)
                grad.setColorAt(0.0, c_top)
                grad.setColorAt(1.0, c_bot)
                painter.fillPath(area, QBrush(grad))

                painter.setPen(QPen(QColor(col), width_px))
                painter.drawPath(path)

        painter.setFont(QFont(ThemeTokens.FONT_NAME, 8, QFont.Weight.DemiBold))
        painter.setPen(QColor(ThemeTokens.ACCENT_STEEL))
        painter.drawText(int(w - 118), 14, "— CPU")
        painter.setPen(QColor(ThemeTokens.ACCENT_MUTED))
        painter.drawText(int(w - 64), 14, "— GPU")
        painter.end()
