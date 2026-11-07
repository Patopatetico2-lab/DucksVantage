"""
Medidores Circulares Reais de Hardware para o Ducksvantage (ui/gauges.py)
Desenhados com QPainter, Antialiasing e animação suave com QVariantAnimation.
Arco configurado com startAngle = 225 * 16 e spanAngle negativo (-270 * 16) no sentido horário,
e títulos/subtítulos em cinza claro (#cbd5e1) para alto contraste em tema escuro.
"""

from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPainter, QPen, QBrush, QColor, QFont, QRectF, QLinearGradient,
    QVariantAnimation, Qt, QSizePolicy
)
from ui.theme_tokens import ThemeTokens


class CircularGauge(QWidget):
    """Medidor circular animado estilo Lenovo Vantage com arco horário."""

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
        self.bottom_sub_text = "Aguardando..."

        self.setMinimumSize(185, 195)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Animação suave para transições de valor
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

    def set_data(self, percent: float, center_val: str, center_unit: str = "", bottom_sub: str = ""):
        """Atualiza os valores e inicia a transição animada suave."""
        new_target = max(0.0, min(100.0, float(percent)))
        self.center_value_text = str(center_val)
        self.center_unit_text = str(center_unit)
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

        w = self.width()
        h = self.height()
        size = min(w, h) - 34
        x = (w - size) / 2.0
        y = (h - size) / 2.0 - 8.0

        rect = QRectF(x, y, size, size)
        stroke_width = 10.0

        # 1. Trilho de Fundo (Track Ring) no sentido horário:
        # startAngle = 225 * 16 (posição 7h30) e spanAngle = -270 * 16 (sentido horário até 4h30)
        start_angle = 225 * 16
        span_total = -270 * 16

        track_pen = QPen(QColor("#253048"), stroke_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(rect, start_angle, span_total)

        # 2. Arco Ativo com Gradiente Linear no sentido horário
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

        # 3. Textos Centrais e Legendas em Cinza Claro (#cbd5e1) e Branco (#fbfdff)
        # Título superior (PROCESSADOR (CPU), GPU ..., MEMÓRIA RAM) em #cbd5e1
        painter.setPen(QColor("#cbd5e1"))
        font_title = QFont("Segoe UI", 9, QFont.Weight.Bold)
        font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        painter.setFont(font_title)
        title_rect = QRectF(x - 10, y + size * 0.21, size + 20, 20)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, self.title.upper())

        # Valor Principal Central (Frequência GHz/MHz ou GB)
        painter.setPen(QColor(ThemeTokens.TEXT_WHITE_100))
        font_val = QFont("Segoe UI", 17, QFont.Weight.Bold)
        painter.setFont(font_val)
        val_rect = QRectF(x, y + size * 0.38, size, 28)
        val_display = f"{self.center_value_text} {self.center_unit_text}".strip()
        painter.drawText(val_rect, Qt.AlignmentFlag.AlignCenter, val_display)

        # Porcentagem de Utilização
        painter.setPen(self.color_end)
        font_pct = QFont("Segoe UI", 11, QFont.Weight.Bold)
        painter.setFont(font_pct)
        pct_rect = QRectF(x, y + size * 0.58, size, 20)
        painter.drawText(pct_rect, Qt.AlignmentFlag.AlignCenter, f"{int(self._current_percent)}% USO")

        # Subtítulo inferior (Temperatura °C, Consumo W ou Capacidade) em #cbd5e1
        painter.setPen(QColor("#cbd5e1"))
        font_sub = QFont("Segoe UI", 9, QFont.Weight.Medium)
        painter.setFont(font_sub)
        sub_rect = QRectF(2, h - 24, w - 4, 20)
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, self.bottom_sub_text)

        painter.end()


class HardwareGaugesCard(QFrame):
    """Card contendo os 3 Medidores Circulares lado a lado (CPU, GPU e RAM)."""

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
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Cabeçalho do Card
        header = QHBoxLayout()
        title = QLabel("Telemetria em Tempo Real (Hardware Monitor)")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        header.addWidget(title)

        header.addStretch()

        legend = QLabel("Sensores Ativos")
        legend.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        legend.setStyleSheet(
            f"color: {ThemeTokens.BORDER_CYAN}; background-color: #253048; "
            f"padding: 4px 10px; border-radius: 4px;"
        )
        header.addWidget(legend)
        layout.addLayout(header)

        # Linha com os 3 Gauges Circulares
        gauges_row = QHBoxLayout()
        gauges_row.setSpacing(14)

        self.cpu_gauge = CircularGauge("Processador (CPU)", ThemeTokens.GRAD_CPU[0], ThemeTokens.GRAD_CPU[1])
        self.gpu_gauge = CircularGauge("Placa Gráfica (GPU)", ThemeTokens.GRAD_GPU[0], ThemeTokens.GRAD_GPU[1])
        self.ram_gauge = CircularGauge("Memória RAM", ThemeTokens.GRAD_RAM[0], ThemeTokens.GRAD_RAM[1])

        gauges_row.addWidget(self.cpu_gauge)
        gauges_row.addWidget(self.gpu_gauge)
        gauges_row.addWidget(self.ram_gauge)

        layout.addLayout(gauges_row)

    def update_metrics(self, cpu, gpu, ram):
        """Atualiza os 3 medidores circulares com frequência, temperatura °C e consumo W."""
        # 1. CPU
        freq_ghz = f"{cpu.frequency_mhz / 1000.0:.2f}" if cpu.frequency_mhz > 0 else "--"
        self.cpu_gauge.set_data(
            percent=cpu.usage_percent,
            center_val=freq_ghz,
            center_unit="GHz",
            bottom_sub=f"{cpu.temperature_c:.0f}°C • {cpu.cores_count} Threads ({cpu.governor})"
        )

        # 2. GPU (adapta título dinamicamente para NVIDIA, AMD Radeon ou Intel)
        self.gpu_gauge.set_title(gpu.short_name or "Placa Gráfica (GPU)")
        if gpu.available:
            if gpu.clock_mhz > 0:
                center_val = str(gpu.clock_mhz)
                center_unit = "MHz"
            else:
                center_val = f"{gpu.temperature_c:.0f}"
                center_unit = "°C"

            if gpu.power_draw_w > 0:
                sub = f"{gpu.temperature_c:.0f}°C • {gpu.power_draw_w:.1f} W • VRAM {gpu.memory_used_mb} MB"
            elif gpu.memory_total_mb > 0:
                sub = f"{gpu.temperature_c:.0f}°C • VRAM {gpu.memory_used_mb}/{gpu.memory_total_mb} MB"
            else:
                sub = f"{gpu.temperature_c:.0f}°C • {gpu.runtime_state}"

            self.gpu_gauge.set_data(
                percent=float(gpu.utilization_percent),
                center_val=center_val,
                center_unit=center_unit,
                bottom_sub=sub
            )
        else:
            self.gpu_gauge.set_data(
                percent=0.0,
                center_val=gpu.runtime_state or "D3cold",
                center_unit="",
                bottom_sub="dGPU em Economia de Energia (0.0 W)"
            )

        # 3. RAM
        ram_sub = f"{ram.used_gb:.1f} / {ram.total_gb:.1f} GB"
        if ram.temperature_c > 0:
            ram_sub += f" • {ram.temperature_c:.0f}°C"
        else:
            ram_sub += f" ({ram.free_gb:.1f} GB livres)"

        self.ram_gauge.set_data(
            percent=ram.usage_percent,
            center_val=f"{ram.used_gb:.1f}",
            center_unit="GB",
            bottom_sub=ram_sub
        )
