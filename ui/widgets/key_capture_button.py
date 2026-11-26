"""Botão interativo de captura de tecla/atalho global para o Remapper (Qt + evdev)."""

from typing import Iterable, List, Optional
from core.qt_compat import QPushButton, Qt, Signal, QFont, QKeySequence, QTimer
from core.key_mapper import (
    MODIFIER_ORDER,
    format_shortcut,
    is_valid_shortcut,
    normalize_modifiers,
    parse_shortcut_to_evdev,
)
from ui.theme_tokens import ThemeTokens


_QT_MODIFIER_KEYS = tuple(
    getattr(Qt.Key, name)
    for name in (
        "Key_Control",
        "Key_Shift",
        "Key_Alt",
        "Key_Meta",
        "Key_AltGr",
        "Key_Super_L",
        "Key_Super_R",
        "Key_Hyper_L",
        "Key_Hyper_R",
    )
    if hasattr(Qt.Key, name)
)


class KeyCaptureButton(QPushButton):
    """
    Botão interativo que captura a próxima tecla/atalho pressionado
    combinando leitura direta do kernel (evdev, essencial para F8/Copilot/XF86Assistant no Wayland)
    com fallback Qt seguro que nunca salva strings incompletas como 'Meta+Shift+'.
    """

    shortcut_captured = Signal(str)
    capture_completed = Signal(str, int, list)

    def __init__(
        self,
        initial_shortcut: str = "Meta+Shift+F23",
        backend=None,
        evdev_code: int = 0,
        evdev_modifiers: Optional[Iterable[str]] = None,
        parent=None,
    ):
        clean_initial = str(initial_shortcut or "").strip()
        if not is_valid_shortcut(clean_initial):
            clean_initial = format_shortcut(int(evdev_code or 0), evdev_modifiers or ()) or "Meta+Shift+F23"

        super().__init__(clean_initial, parent)
        self.backend = backend
        self._capturing = False
        self._evdev_capturing = False
        self._current_seq = clean_initial

        parsed_code, parsed_mods = parse_shortcut_to_evdev(clean_initial)
        self.evdev_code: int = int(evdev_code or 0) or parsed_code
        self.evdev_modifiers: List[str] = (
            normalize_modifiers(evdev_modifiers) if evdev_modifiers is not None else parsed_mods
        )
        if not self.evdev_modifiers and parsed_mods:
            self.evdev_modifiers = parsed_mods

        self._evdev_timer = QTimer(self)
        self._evdev_timer.setInterval(30)
        self._evdev_timer.timeout.connect(self._poll_evdev_capture)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self.setMinimumWidth(148)
        self.setFont(QFont(ThemeTokens.FONT_NAME, 9, QFont.Weight.DemiBold))
        self.setToolTip(
            "Clique e pressione qualquer tecla física ou atalho (ex: Copilot/F8, F24, Ctrl+Alt+E). Esc cancela."
        )
        self.clicked.connect(self._start_capture)
        self._update_style()

    def set_shortcut_state(
        self,
        shortcut: str,
        evdev_code: int = 0,
        evdev_modifiers: Optional[Iterable[str]] = None,
    ) -> None:
        """Atualiza visualmente e internamente o atalho associado sem emitir sinal."""
        self._stop_capture(restore_text=False)
        clean = str(shortcut or "").strip()
        if not is_valid_shortcut(clean):
            clean = format_shortcut(int(evdev_code or 0), evdev_modifiers or ()) or "Meta+Shift+F23"
        parsed_code, parsed_mods = parse_shortcut_to_evdev(clean)
        self._current_seq = clean
        self.evdev_code = int(evdev_code or 0) or parsed_code
        self.evdev_modifiers = (
            normalize_modifiers(evdev_modifiers) if evdev_modifiers is not None else parsed_mods
        )
        self.setText(self._current_seq)
        self._update_style()

    def _start_capture(self):
        self._capturing = True
        self._evdev_capturing = False
        if self.backend and hasattr(self.backend, "start_evdev_capture"):
            try:
                self._evdev_capturing = bool(self.backend.start_evdev_capture())
            except Exception:
                self._evdev_capturing = False

        self.setText("Pressione tecla...")
        self._update_style()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self._evdev_capturing:
            self._evdev_timer.start()

    def _stop_capture(self, restore_text: bool = True):
        if self._evdev_timer.isActive():
            self._evdev_timer.stop()
        if self._evdev_capturing and self.backend and hasattr(self.backend, "stop_evdev_capture"):
            try:
                self.backend.stop_evdev_capture()
            except Exception:
                pass
        self._evdev_capturing = False
        self._capturing = False
        if restore_text:
            self.setText(self._current_seq)
        self._update_style()

    def _commit_captured(self, seq: str, evdev_code: int, evdev_modifiers: List[str]):
        self._stop_capture(restore_text=False)
        self._current_seq = seq
        self.evdev_code = int(evdev_code or 0)
        self.evdev_modifiers = normalize_modifiers(evdev_modifiers)
        self.setText(seq)
        self._update_style()
        self.shortcut_captured.emit(seq)
        self.capture_completed.emit(seq, self.evdev_code, list(self.evdev_modifiers))

    def _poll_evdev_capture(self) -> bool:
        if not self._capturing or not self._evdev_capturing:
            return False
        if not self.backend or not hasattr(self.backend, "poll_evdev_capture"):
            return False

        try:
            res = self.backend.poll_evdev_capture()
        except Exception:
            return False

        if not res:
            if hasattr(self.backend, "get_evdev_capture_preview"):
                try:
                    preview = self.backend.get_evdev_capture_preview()
                    self.setText(preview if preview else "Pressione tecla...")
                except Exception:
                    pass
            return False

        if res.get("cancelled"):
            self._stop_capture(restore_text=True)
            return True

        seq = str(res.get("qt_shortcut", "") or "").strip()
        ev_code = int(res.get("evdev_code", 0) or 0)
        ev_mods = normalize_modifiers(res.get("evdev_modifiers") or [])
        if not is_valid_shortcut(seq) and ev_code > 0:
            seq = format_shortcut(ev_code, ev_mods)
        if is_valid_shortcut(seq):
            self._commit_captured(seq, ev_code, ev_mods)
            return True

        self._stop_capture(restore_text=True)
        return True

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return

        event.accept()

        # Tenta primeiro capturar o pacote bruto do kernel antes que Wayland/Qt deformem a tecla
        if self._evdev_capturing and self._poll_evdev_capture():
            return

        key = int(event.key())
        if key in _QT_MODIFIER_KEYS:
            return

        if key == int(Qt.Key.Key_Escape):
            self._stop_capture(restore_text=True)
            return

        mods_enum = event.modifiers()
        raw_mods: List[str] = []
        if mods_enum & Qt.KeyboardModifier.ControlModifier:
            raw_mods.append("Ctrl")
        if mods_enum & Qt.KeyboardModifier.AltModifier:
            raw_mods.append("Alt")
        if mods_enum & Qt.KeyboardModifier.MetaModifier:
            raw_mods.append("Meta")
        if mods_enum & Qt.KeyboardModifier.ShiftModifier:
            raw_mods.append("Shift")
        mods_list = [m for m in MODIFIER_ORDER if m in raw_mods]

        # Tratamento explícito para XF86Assistant / XKB keycode 201/202 quando evdev não estiver disponível
        native_vk = int(getattr(event, "nativeVirtualKey", lambda: 0)() or 0)
        native_sc = int(getattr(event, "nativeScanCode", lambda: 0)() or 0)
        if native_vk == 0x1008FFAC or native_sc == 201:
            seq = format_shortcut(193, mods_list)
            self._commit_captured(seq, 193, mods_list)
            return
        if native_sc == 202:
            seq = format_shortcut(194, mods_list)
            self._commit_captured(seq, 194, mods_list)
            return

        # Nunca aceita key==0 ou Key_unknown (causava o bug 'Meta+Shift+')
        if key in (0, int(Qt.Key.Key_unknown)):
            return

        key_str = QKeySequence(key).toString().strip()
        if not key_str or key_str.endswith("+"):
            return

        seq = "+".join([*mods_list, key_str]) if mods_list else key_str
        if not is_valid_shortcut(seq):
            return

        parsed_code, parsed_mods = parse_shortcut_to_evdev(seq)
        self._commit_captured(seq, parsed_code, parsed_mods or mods_list)

    def focusOutEvent(self, event):
        if self._capturing:
            self._stop_capture(restore_text=True)
        super().focusOutEvent(event)

    def hideEvent(self, event):
        if self._capturing:
            self._stop_capture(restore_text=True)
        super().hideEvent(event)

    def _update_style(self):
        if self._capturing:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ThemeTokens.ACCENT_STEEL};
                    color: {ThemeTokens.BG_APP};
                    border: 1px solid {ThemeTokens.ACCENT_STEEL};
                    border-radius: 6px;
                    padding: 4px 10px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                    color: {ThemeTokens.ACCENT_STEEL};
                    border: 1px solid {ThemeTokens.ACCENT_STEEL};
                    border-radius: 6px;
                    padding: 4px 10px;
                }}
                QPushButton:hover {{
                    background-color: {ThemeTokens.ACCENT_STEEL};
                    color: {ThemeTokens.BG_APP};
                }}
            """)
