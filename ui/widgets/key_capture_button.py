"""Botão interativo de captura de tecla/atalho global para o Remapper."""

from core.qt_compat import QPushButton, Qt, Signal, QFont, QKeySequence
from ui.theme_tokens import ThemeTokens


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
