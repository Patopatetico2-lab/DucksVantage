"""
Medidores Circulares Reais de Hardware para o Ducksvantage (ui/gauges.py).
Estilo 3 — Vantage Refinado: arcos delgados em paleta aço coesa, tipografia limpa e hierarquia clara.
"""

from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPainter, QPen, QBrush, QColor, QFont, QRectF, QLinearGradient,
    QVariantAnimation, Qt, QSizePolicy
)
from ui.theme_tokens import ThemeTokens


class CircularGauge(QWidget):
    """Medidor circular animado refinado com arco horário delgado."""

    def __init__(self, title: str, grad_start: str, grad_end: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.color_start = QColor(grad_start)
        self.color_end = QColor(grad_end)

        self._target_percent = 0.0
        self._current_percent = 0.0

        # Textos informativos
        self.center_value_text = "--"
        self.center_unit_text = ""
        self.center_sub_text = ""
        self.bottom_sub_text = "Aguardando..."

        self.setMinimumSize(140, 166)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.anim = QVariantAnimation(self)
        self.anim.setDuration(400)
        self.anim.valueChanged.connect(self._on_anim_step)

    def _on_anim_step(self, val):
        self._current_percent = float(val)
        self.update()

    def set_title(self, new_title: str):
        if new_title and new_title != self.title:
            self.title = new_title
            self.update()

    def set_data(
        self,
        percent: float,
        center_val: str,
        center_unit: str = "",
        bottom_sub: str = "",
        center_sub: str = "",
    ):
        """Atualiza os valores do medidor e anima suavemente o arco."""
        new_target = max(0.0, min(100.0, float(percent)))
        self.center_value_text = str(center_val)
        self.center_unit_text = str(center_unit)
        self.center_sub_text = str(center_sub)
        self.bottom_sub_text = str(bottom_sub)

        if abs(new_target - self._current_percent) > 0.5:
            self.anim.stop()
            self.anim.setStartValue(self._current_percent)
            self.anim.setEndValue(new_target)
            self.anim.start()
        else:
            self._current_percent = new_target
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        size = max(108.0, min(w, h) - 34.0)
        x = (w - size) / 2.0
        y = max(4.0, (h - size) / 2.0 - 10.0)

        rect = QRectF(x, y, size, size)
        stroke_width = 6.5

        start_angle = 225 * 16
        span_total = -270 * 16

        # 1. Trilho de Fundo discreto
        track_pen = QPen(QColor("#2a2e36"), stroke_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(rect, start_angle, span_total)

        # 2. Arco Ativo em gradiente aço coeso
        if self._current_percent > 0:
            active_pen = QPen()
            active_pen.setWidthF(stroke_width)
            active_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, self.color_start)
            grad.setColorAt(1.0, self.color_end)

            active_pen.setBrush(QBrush(grad))
            painter.setPen(active_pen)

            span_active = -int((self._current_percent / 100.0) * (270 * 16))
            painter.drawArc(rect, start_angle, span_active)

        # 3. Rótulo superior discreto
        painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
        font_title = QFont(ThemeTokens.FONT_NAME, 8, QFont.Weight.Medium)
        font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.7)
        painter.setFont(font_title)
        title_rect = QRectF(x - 10, y + size * 0.22, size + 20, 18)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, self.title.upper())

        # 4. Valor principal no centro
        painter.setPen(QColor(ThemeTokens.TEXT_WHITE_100))
        val_display = f"{self.center_value_text} {self.center_unit_text}".strip()
        val_pt = 14 if len(val_display) > 7 else 18
        font_val = QFont(ThemeTokens.FONT_NAME, val_pt, QFont.Weight.Bold)
        painter.setFont(font_val)
        val_rect = QRectF(x + 6, y + size * 0.36, size - 12, 28)
        painter.drawText(val_rect, Qt.AlignmentFlag.AlignCenter, val_display)

        # 5. Sub-valor logo abaixo do principal
        sub_center = self.center_sub_text or f"{int(round(self._current_percent))}%"
        painter.setPen(QColor(ThemeTokens.TEXT_WHITE_80))
        font_sub_c = QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.Normal)
        painter.setFont(font_sub_c)
        pct_rect = QRectF(x + 6, y + size * 0.59, size - 12, 18)
        painter.drawText(pct_rect, Qt.AlignmentFlag.AlignCenter, sub_center)

        # 6. Rodapé único discreto fora do anel
        painter.setPen(QColor(ThemeTokens.TEXT_LIGHT_GRAY))
        font_sub = QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.Normal)
        painter.setFont(font_sub)
        sub_rect = QRectF(4, h - 22, w - 8, 18)
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, self.bottom_sub_text)

        painter.end()


class HardwareGaugesCard(QFrame):
    """Card contendo os 3 medidores circulares refinados (CPU, GPU e RAM)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "vantageCard")
        self.setStyleSheet(f"""
            HardwareGaugesCard {{
                background-color: {ThemeTokens.BG_CARD};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: {ThemeTokens.RADIUS_CARD}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Telemetria em Tempo Real")
        title.setFont(QFont(ThemeTokens.FONT_NAME, 12, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        gauges_row = QHBoxLayout()
        gauges_row.setSpacing(12)

        self.cpu_gauge = CircularGauge("CPU", ThemeTokens.GRAD_CPU[0], ThemeTokens.GRAD_CPU[1])
        self.gpu_gauge = CircularGauge("GPU", ThemeTokens.GRAD_GPU[0], ThemeTokens.GRAD_GPU[1])
        self.ram_gauge = CircularGauge("RAM", ThemeTokens.GRAD_RAM[0], ThemeTokens.GRAD_RAM[1])

        gauges_row.addWidget(self.cpu_gauge)
        gauges_row.addWidget(self.gpu_gauge)
        gauges_row.addWidget(self.ram_gauge)

        layout.addLayout(gauges_row)

    def update_metrics(self, cpu, gpu, ram):
        """Atualiza os 3 medidores com leitura direta e concisa."""
        # 1. CPU
        freq_ghz = f"{cpu.frequency_mhz / 1000.0:.2f} GHz" if cpu.frequency_mhz > 0 else "-- GHz"
        gov_txt = cpu.governor or f"{cpu.cores_count}T"
        self.cpu_gauge.set_data(
            percent=cpu.usage_percent,
            center_val=f"{int(round(cpu.usage_percent))}%",
            center_sub=freq_ghz,
            bottom_sub=f"{cpu.temperature_c:.0f}°C • {gov_txt}",
        )

        # 2. GPU
        self.gpu_gauge.set_title("GPU")
        short_gpu = (gpu.short_name or "GPU").strip()
        if short_gpu.upper().startswith("GPU "):
            short_gpu = short_gpu[4:].strip()
        if gpu.available:
            pwr_part = f" • {gpu.power_draw_w:.1f}W" if gpu.power_draw_w > 0 else ""
            c_sub = f"{gpu.temperature_c:.0f}°C{pwr_part}"
            if gpu.memory_total_mb > 0 and gpu.power_draw_w <= 0:
                b_sub = f"VRAM {gpu.memory_used_mb}/{gpu.memory_total_mb} MB"
            else:
                b_sub = f"{gpu.clock_mhz} MHz" if gpu.clock_mhz > 0 else gpu.runtime_state

            self.gpu_gauge.set_data(
                percent=float(gpu.utilization_percent),
                center_val=short_gpu,
                center_sub=c_sub,
                bottom_sub=b_sub,
            )
        else:
            self.gpu_gauge.set_data(
                percent=0.0,
                center_val=short_gpu or "dGPU",
                center_sub=gpu.runtime_state or "D3cold",
                bottom_sub="Suspensa • 0.0W",
            )

        # 3. RAM
        self.ram_gauge.set_data(
            percent=ram.usage_percent,
            center_val=f"{int(round(ram.usage_percent))}%",
            center_sub=f"{ram.used_gb:.1f} GB",
            bottom_sub=f"{ram.total_gb:.0f} GB total"
            if ram.temperature_c <= 0
            else f"{ram.total_gb:.0f} GB • {ram.temperature_c:.0f}°C",
        )
