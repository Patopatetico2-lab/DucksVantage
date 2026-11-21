"""Card selecionável para modos do GPU MUX Switch no Ducksvantage."""

from core.qt_compat import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, Qt, QFont, Signal, QSizePolicy
)
from ui.theme_tokens import ThemeTokens


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
