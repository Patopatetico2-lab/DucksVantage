"""
Aba Iluminação RGB 4-Zonas do Ducksvantage (ui/tabs/lighting_tab.py).
Exibida automaticamente APENAS quando o notebook possui teclado RGB 4-zonas
controlado via hidraw ITE (048d:c9xx) ou LEDs multicolor no sysfs.
Zero emojis: utiliza exclusivamente ícones vetoriais SVG.
"""

import os
from typing import List
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QComboBox, QSlider,
    Qt, Signal, QFont, QPixmap, QMessageBox, QColor, QColorDialog
)
from ui.theme_tokens import ThemeTokens
from ui.components import StatusBadge

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")

RGB_EFFECTS = [
    ("static", "Cor Estática por Zona"),
    ("breath", "Respiração Suave (Breath)"),
    ("wave", "Onda RGB Dinâmica (Wave)"),
    ("smooth", "Transição Arco-Íris (Smooth)"),
    ("off", "Iluminação Desligada (Off)"),
]


class LightingTab(QWidget):
    """Controle de Teclado RGB 4-Zonas Lenovo Legion / LOQ."""
    rgb_changed = Signal(str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        state = self.backend.get_rgb_keyboard_state()
        self._zone_colors: List[str] = list(state.get("zones", ["#00d2ff"] * 4))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(18)

        card = QFrame()
        card.setProperty("class", "card")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 18, 20, 18)
        c_layout.setSpacing(14)

        header = QHBoxLayout()
        ic = QLabel()
        ic_path = os.path.join(ICON_DIR, "nav_lighting_active.svg")
        if os.path.exists(ic_path):
            ic.setPixmap(QPixmap(ic_path).scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header.addWidget(ic)

        titles = QVBoxLayout()
        t_lbl = QLabel("Iluminação RGB do Teclado • 4 Zonas Lenovo")
        t_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        titles.addWidget(t_lbl)

        sub_lbl = QLabel("Ajuste efeitos, brilho, velocidade e cores independentes das 4 zonas físicas do teclado.")
        sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        titles.addWidget(sub_lbl)
        header.addLayout(titles, stretch=1)

        self.rgb_badge = StatusBadge(
            f"BACKEND: {str(state.get('backend', 'none')).upper()}",
            bg_color="#1e293b",
            text_color="#00d2ff"
        )
        header.addWidget(self.rgb_badge)
        c_layout.addLayout(header)

        # Efeito + Presets rápidos
        eff_box = QFrame()
        eff_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px 14px;")
        eff_layout = QVBoxLayout(eff_box)
        eff_layout.setSpacing(10)

        eff_row = QHBoxLayout()
        lbl_eff = QLabel("Efeito de Iluminação:")
        lbl_eff.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl_eff.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        eff_row.addWidget(lbl_eff)
        eff_row.addStretch()

        self.combo_mode = QComboBox()
        self.combo_mode.setMinimumWidth(240)
        self.combo_mode.setFixedHeight(30)
        self.combo_mode.setStyleSheet(f"""
            QComboBox {{
                background-color: #192338;
                color: {ThemeTokens.TEXT_WHITE_100};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
            }}
        """)
        for mid, mlabel in RGB_EFFECTS:
            self.combo_mode.addItem(mlabel, mid)
        cur_idx = self.combo_mode.findData(state.get("mode", "static"))
        if cur_idx >= 0:
            self.combo_mode.setCurrentIndex(cur_idx)
        eff_row.addWidget(self.combo_mode)
        eff_layout.addLayout(eff_row)

        # Brilho e Velocidade
        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(16)

        self.lbl_brightness = QLabel(f"Brilho: {state.get('brightness', 2)} / 2")
        self.lbl_brightness.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px; min-width: 95px;")
        sliders_row.addWidget(self.lbl_brightness)

        self.slider_brightness = QSlider(Qt.Orientation.Horizontal)
        self.slider_brightness.setRange(0, 2)
        self.slider_brightness.setValue(int(state.get("brightness", 2)))
        self.slider_brightness.valueChanged.connect(lambda v: self.lbl_brightness.setText(f"Brilho: {v} / 2"))
        sliders_row.addWidget(self.slider_brightness, stretch=1)

        self.lbl_speed = QLabel(f"Velocidade: {state.get('speed', 2)} / 4")
        self.lbl_speed.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; font-size: 11px; min-width: 110px;")
        sliders_row.addWidget(self.lbl_speed)

        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(1, 4)
        self.slider_speed.setValue(int(state.get("speed", 2)))
        self.slider_speed.valueChanged.connect(lambda v: self.lbl_speed.setText(f"Velocidade: {v} / 4"))
        sliders_row.addWidget(self.slider_speed, stretch=1)

        eff_layout.addLayout(sliders_row)
        c_layout.addWidget(eff_box)

        # Seletores das 4 Zonas
        zones_box = QFrame()
        zones_box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 12px 14px;")
        z_v = QVBoxLayout(zones_box)
        z_v.setSpacing(10)

        z_top = QLabel("Cores das 4 Zonas Físicas do Teclado (Esquerda → NumPad)")
        z_top.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        z_top.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        z_v.addWidget(z_top)

        zones_row = QHBoxLayout()
        zones_row.setSpacing(10)
        self.zone_buttons: List[QPushButton] = []
        for idx in range(4):
            btn = QPushButton(f"Zona {idx + 1}\n{self._zone_colors[idx].upper()}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(56)
            btn.clicked.connect(lambda _c=False, i=idx: self._pick_zone_color(i))
            self.zone_buttons.append(btn)
            zones_row.addWidget(btn)
        self._refresh_zone_buttons()
        z_v.addLayout(zones_row)

        # Presets rápidos + Aplicar
        act_row = QHBoxLayout()
        act_row.setSpacing(8)
        for p_title, p_mode, p_cols, p_br in [
            ("Legion Cyan", "static", ["#00d2ff", "#00d2ff", "#00d2ff", "#00d2ff"], 2),
            ("LOQ Red", "static", ["#ef4444", "#ef4444", "#ef4444", "#ef4444"], 2),
            ("Vaporwave", "static", ["#00d2ff", "#6366f1", "#a855f7", "#ec4899"], 2),
            ("Onda RGB", "wave", ["#00d2ff", "#34d399", "#fbbf24", "#ef4444"], 2),
            ("Apagar", "off", ["#000000", "#000000", "#000000", "#000000"], 0),
        ]:
            bp = QPushButton(p_title)
            bp.setCursor(Qt.CursorShape.PointingHandCursor)
            bp.setFixedHeight(28)
            bp.setStyleSheet(f"""
                QPushButton {{
                    background-color: #192338;
                    color: {ThemeTokens.TEXT_LIGHT_GRAY};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border-color: {ThemeTokens.BORDER_CYAN};
                    color: {ThemeTokens.TEXT_WHITE_100};
                }}
            """)
            bp.clicked.connect(lambda _c=False, m=p_mode, cs=p_cols, b=p_br: self._apply_quick_preset(m, cs, b))
            act_row.addWidget(bp)

        act_row.addStretch()

        self.btn_apply_rgb = QPushButton("Aplicar no Teclado")
        self.btn_apply_rgb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_rgb.setFixedHeight(32)
        self.btn_apply_rgb.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeTokens.BORDER_CYAN};
                color: #0b0f19;
                border: none;
                border-radius: 6px;
                padding: 4px 16px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #38bdf8;
            }}
        """)
        self.btn_apply_rgb.clicked.connect(self._on_apply_rgb)
        act_row.addWidget(self.btn_apply_rgb)
        z_v.addLayout(act_row)

        c_layout.addWidget(zones_box)
        layout.addWidget(card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _refresh_zone_buttons(self):
        for idx, btn in enumerate(self.zone_buttons):
            col_hex = self._zone_colors[idx].upper()
            qc = QColor(col_hex)
            luma = (0.299 * qc.red()) + (0.587 * qc.green()) + (0.114 * qc.blue())
            fg = "#0b0f19" if luma > 145 else "#ffffff"
            btn.setText(f"Zona {idx + 1}\n{col_hex}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {col_hex};
                    color: {fg};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    border: 2px solid {ThemeTokens.BORDER_CYAN};
                }}
            """)

    def _pick_zone_color(self, idx: int):
        chosen = QColorDialog.getColor(QColor(self._zone_colors[idx]), self, f"Cor da Zona {idx + 1}")
        if chosen.isValid():
            self._zone_colors[idx] = chosen.name()
            self._refresh_zone_buttons()

    def _apply_quick_preset(self, mode: str, colors: List[str], brightness: int):
        idx = self.combo_mode.findData(mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self._zone_colors = list(colors)
        self.slider_brightness.setValue(brightness)
        self._refresh_zone_buttons()
        self._on_apply_rgb()

    def _on_apply_rgb(self):
        mode = str(self.combo_mode.currentData() or "static")
        br = self.slider_brightness.value()
        spd = self.slider_speed.value()
        ok, msg = self.backend.set_rgb_keyboard_state(mode, self._zone_colors, br, spd)
        if not ok:
            QMessageBox.warning(self, "Iluminação RGB", msg)
            return
        self.rgb_changed.emit(msg)
