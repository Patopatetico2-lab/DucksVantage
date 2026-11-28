"""
Componentes Reutilizáveis de Interface para o Ducksvantage.
Inclui Chave de Alternância (Toggle Switch), Pílulas de Status e Seletor de Sub-abas.
"""

from typing import List, Tuple
from core.qt_compat import (
    QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, Qt, Signal, QColor, QPainter,
    QBrush, QPen, QFont
)
from ui.theme_tokens import ThemeTokens

class ToggleSwitch(QWidget):
    """Chave de alternância estilizada moderna e compacta."""
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self.update()
            self.toggled.emit(self._checked)

    def mousePressEvent(self, event):
        if not self.isEnabled():
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)

        # Fundo do trilho
        track_color = QColor(ThemeTokens.ACCENT_STEEL) if self._checked else QColor("#2b2f36")
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)

        # Círculo deslizante
        thumb_color = QColor("#f8fafc")
        painter.setBrush(QBrush(thumb_color))
        x_pos = self.width() - 21 if self._checked else 3
        painter.drawEllipse(x_pos, 3, 18, 18)
        painter.end()


class StatusBadge(QFrame):
    """Pílula / Indicador discreto de status."""
    def __init__(self, text: str, bg_color: str = ThemeTokens.BG_CARD_HOVER, text_color: str = ThemeTokens.TEXT_WHITE_80, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 3, 8, 3)

        self.label = QLabel(text)
        self.label.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.label.setStyleSheet(f"color: {text_color}; background: transparent;")
        self._layout.addWidget(self.label)

        self.setColor(bg_color, text_color)

    def setText(self, text: str):
        self.label.setText(text)

    def setColor(self, bg_color: str, text_color: str = "#f4f5f7"):
        self.label.setStyleSheet(f"color: {text_color}; background: transparent; border: none;")
        if bg_color == "transparent":
            self._layout.setContentsMargins(2, 2, 2, 2)
            self.setStyleSheet("StatusBadge { background-color: transparent; border: none; }")
        else:
            self._layout.setContentsMargins(8, 3, 8, 3)
            self.setStyleSheet(f"""
                StatusBadge {{
                    background-color: {bg_color};
                    border: none;
                    border-radius: {ThemeTokens.RADIUS_TAG}px;
                }}
            """)


class SubTabSelector(QFrame):
    """Barra segmentada compacta em pílulas para organizar sub-abas sem rolagem longa."""
    tab_selected = Signal(int)

    def __init__(self, tabs: List[Tuple[str, str]], parent=None):
        super().__init__(parent)
        self._current_index = 0
        self.buttons: List[QPushButton] = []

        self.setObjectName("subTabSelector")
        self.setStyleSheet("""
            QFrame#subTabSelector {
                background-color: #181a1d;
                border: 1px solid #2c3037;
                border-radius: 8px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        for idx, (tab_id, label) in enumerate(tabs):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setProperty("subtab_id", tab_id)
            btn.setFont(QFont(ThemeTokens.FONT_NAME, 10, QFont.Weight.DemiBold))
            btn.clicked.connect(lambda _c=False, i=idx: self._on_button_clicked(i))
            layout.addWidget(btn)
            self.buttons.append(btn)

        layout.addStretch()
        self.set_current_index(0)

    def _on_button_clicked(self, index: int):
        self.set_current_index(index)
        self.tab_selected.emit(index)

    def set_current_index(self, index: int):
        if not self.buttons:
            return
        idx = max(0, min(len(self.buttons) - 1, int(index)))
        self._current_index = idx
        for i, btn in enumerate(self.buttons):
            active = (i == idx)
            btn.blockSignals(True)
            btn.setChecked(active)
            btn.blockSignals(False)
            if active:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #22252b;
                        color: #f4f5f7;
                        border: 1px solid #60a5fa;
                        border-radius: 6px;
                        padding: 0px 14px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #8f96a3;
                        border: 1px solid transparent;
                        border-radius: 6px;
                        padding: 0px 14px;
                    }
                    QPushButton:hover {
                        color: #f4f5f7;
                        background-color: #202328;
                    }
                """)

    def set_tab_visible(self, index: int, visible: bool):
        if 0 <= index < len(self.buttons):
            self.buttons[index].setVisible(bool(visible))

    def set_tab_title(self, index: int, title: str):
        if 0 <= index < len(self.buttons):
            self.buttons[index].setText(str(title))


class BasicModeHintBar(QFrame):
    """Banner discreto no Modo Básico explicando recursos avançados ocultos com botão de atalho."""
    switch_advanced_requested = Signal()

    def __init__(self, hint_text: str, parent=None):
        super().__init__(parent)
        self.setProperty("class", "subBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        self.label = QLabel(hint_text)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px; border: none;")
        lay.addWidget(self.label, stretch=1)

        self.btn_switch = QPushButton("Ativar Modo Avançado")
        self.btn_switch.setProperty("class", "secondaryButton")
        self.btn_switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_switch.setFixedHeight(28)
        self.btn_switch.clicked.connect(self.switch_advanced_requested.emit)
        lay.addWidget(self.btn_switch)

    def set_text(self, hint_text: str):
        self.label.setText(hint_text)
