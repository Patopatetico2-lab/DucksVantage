"""Widget de gráfico térmico em tempo real (CPU/GPU °C) do Ducksvantage."""

from core.qt_compat import (
    QWidget, QPainter, QColor, QPen, QPainterPath, QPointF, Qt, QFont
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
        painter.setPen(QPen(QColor(ThemeTokens.BORDER_DEFAULT), 1))
        painter.setBrush(QColor("#0d1322"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

        pad_l, pad_r, pad_t, pad_b = 36.0, 14.0, 16.0, 18.0
        pw = max(30.0, w - pad_l - pad_r)
        ph = max(30.0, h - pad_t - pad_b)
        y_min, y_max = 30.0, 105.0

        def ty(v: float) -> float:
            norm = max(0.0, min(1.0, (v - y_min) / (y_max - y_min)))
            return pad_t + ph * (1.0 - norm)

        painter.setFont(QFont("Segoe UI", 8))
        for deg in (40, 60, 80, 90):
            yy = ty(float(deg))
            is_warn = (deg == 90)
            painter.setPen(QPen(QColor("#7f1d1d" if is_warn else "#1e293b"), 1, Qt.PenStyle.DashLine if is_warn else Qt.PenStyle.DotLine))
            painter.drawLine(int(pad_l), int(yy), int(pad_l + pw), int(yy))
            painter.setPen(QColor("#f87171" if is_warn else ThemeTokens.TEXT_LIGHT_GRAY))
            painter.drawText(2, int(yy - 7), int(pad_l - 6), 14, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{deg}°")

        n = len(self.cpu_samples)
        if n >= 2:
            for samples, col in ((self.cpu_samples, ThemeTokens.BORDER_CYAN), (self.gpu_samples, ThemeTokens.THERMAL_CUSTOM)):
                if not any(s > 0.0 for s in samples):
                    continue
                path = QPainterPath()
                for idx, val in enumerate(samples):
                    xx = pad_l + (idx / float(max(1, n - 1))) * pw
                    yy = ty(val if val > 0.0 else y_min)
                    pt = QPointF(xx, yy)
                    if idx == 0:
                        path.moveTo(pt)
                    else:
                        path.lineTo(pt)
                painter.setPen(QPen(QColor(col), 2.0))
                painter.drawPath(path)

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(QColor(ThemeTokens.BORDER_CYAN))
        painter.drawText(int(pad_l + 6), int(h - 14), "■ CPU °C")
        painter.setPen(QColor(ThemeTokens.THERMAL_CUSTOM))
        painter.drawText(int(pad_l + 68), int(h - 14), "■ GPU °C")
        painter.end()
