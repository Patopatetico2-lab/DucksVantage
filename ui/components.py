"""
Componentes Reutilizáveis de Interface para o LenovoLOQ-Control.
Inclui Chave de Alternância (Toggle Switch), Cartões de Métricas e Cartões de Perfis.
Zero emojis: suporte completo a ícones SVG oficiais e tokens Vantage.
"""

import os
from core.qt_compat import (
    QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout,
    QProgressBar, QPushButton, Qt, Signal, QColor, QPainter,
    QBrush, QPen, QLinearGradient, QFont, QSizePolicy, QPixmap, QIcon
)
from ui.theme_tokens import ThemeTokens

class ToggleSwitch(QWidget):
    """Chave de alternância estilizada moderna (estilo Vantage / iOS)."""
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(50, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self.update()
            self.toggled.emit(self._checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fundo do trilho
        track_color = QColor(ThemeTokens.BORDER_CYAN) if self._checked else QColor("#2a3245")
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 13, 13)

        # Círculo deslizante
        thumb_color = QColor("#ffffff")
        painter.setBrush(QBrush(thumb_color))
        x_pos = self.width() - 22 if self._checked else 4
        painter.drawEllipse(x_pos, 4, 18, 18)
        painter.end()


class StatusBadge(QFrame):
    """Pílula / Badge de status com cor de fundo semitransparente."""
    def __init__(self, text: str, bg_color: str = ThemeTokens.BORDER_CYAN, text_color: str = "#0f172a", parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 3, 8, 3)

        self.label = QLabel(text)
        self.label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.label.setStyleSheet(f"color: {text_color};")
        self.layout.addWidget(self.label)

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 6px;
            }}
        """)

    def setText(self, text: str):
        self.label.setText(text)

    def setColor(self, bg_color: str, text_color: str = "#ffffff"):
        self.label.setStyleSheet(f"color: {text_color};")
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 6px;
            }}
        """)


class MetricCard(QFrame):
    """Card de exibição de telemetria com barra gráfica e valores em tempo real."""

    def __init__(self, icon_path_or_text: str, title: str, unit: str = "%", parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.unit = unit

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Topo: Ícone + Título + Valor Principal
        top_layout = QHBoxLayout()

        icon_label = QLabel()
        if os.path.exists(icon_path_or_text):
            icon_label.setPixmap(QPixmap(icon_path_or_text).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            # Fallback se não for caminho
            icon_label.setText(icon_path_or_text if not any(ord(c) > 127 for c in icon_path_or_text) else "")
        top_layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_label.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_80};")
        top_layout.addWidget(title_label)

        top_layout.addStretch()

        self.value_label = QLabel(f"-- {unit}")
        self.value_label.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        self.value_label.setStyleSheet(f"color: {ThemeTokens.BORDER_CYAN};")
        top_layout.addWidget(self.value_label)

        layout.addLayout(top_layout)

        # Barra de Progresso / Nível
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        layout.addWidget(self.progress_bar)

        # Rodapé: Subtítulo ou Detalhe
        self.sub_label = QLabel("Aguardando telemetria...")
        self.sub_label.setFont(QFont("Segoe UI", 9))
        self.sub_label.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_40};")
        layout.addWidget(self.sub_label)

    def update_metric(self, value: float, max_value: float = 100.0, subtitle: str = ""):
        self.value_label.setText(f"{value:.1f} {self.unit}" if isinstance(value, float) else f"{value} {self.unit}")
        pct = int(min(max((value / max_value) * 100.0, 0), 100)) if max_value > 0 else 0
        self.progress_bar.setValue(pct)
        if subtitle:
            self.sub_label.setText(subtitle)

    def set_color_accent(self, color_start: str, color_end: str):
        """Customiza o gradiente da barra."""
        self.progress_bar.setStyleSheet(f"""
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                             stop:0 {color_start}, stop:1 {color_end});
                border-radius: 4px;
            }}
        """)


class ProfileCard(QFrame):
    """Card interativo para selecionar perfis de energia ACPI (Quiet, Balanced, Performance)."""
    clicked = Signal(str)

    def __init__(self, profile_id: str, icon_source: str, title: str, desc: str, accent_color: str, parent=None):
        super().__init__(parent)
        self.profile_id = profile_id
        self.accent_color = accent_color
        self.is_active = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        # Topo com Ícone, Título e Tag de Status
        header = QHBoxLayout()
        icon_lbl = QLabel()
        if os.path.exists(icon_source):
            icon_lbl.setPixmap(QPixmap(icon_source).scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header.addWidget(icon_lbl)

        self.title_lbl = QLabel(title)
        self.title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        header.addWidget(self.title_lbl)

        header.addStretch()

        self.status_tag = QLabel("")
        self.status_tag.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.status_tag.setVisible(False)
        header.addWidget(self.status_tag)

        layout.addLayout(header)

        # Descrição do modo
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setFont(QFont("Segoe UI", 10))
        desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_60};")
        layout.addWidget(desc_lbl)

        self.update_style()

    def set_active(self, active: bool):
        self.is_active = active
        self.status_tag.setVisible(active)
        if active:
            self.status_tag.setText("ATIVO")
            self.status_tag.setStyleSheet(f"""
                background-color: {self.accent_color};
                color: #090d16;
                padding: 3px 8px;
                border-radius: 6px;
                font-weight: bold;
            """)
        self.update_style()

    def update_style(self):
        if self.is_active:
            self.setStyleSheet(f"""
                ProfileCard {{
                    background-color: {ThemeTokens.BG_CARD_ACTIVE};
                    border: 2px solid {self.accent_color};
                    border-radius: 12px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                ProfileCard {{
                    background-color: {ThemeTokens.BG_CARD};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 12px;
                }}
                ProfileCard:hover {{
                    border: 1px solid {self.accent_color};
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                }}
            """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.profile_id)
        super().mousePressEvent(event)
