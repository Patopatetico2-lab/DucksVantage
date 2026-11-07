"""
Pop-up OSD Não-Intrusivo para Jogos no KDE Plasma / Wayland (ui/osd_overlay.py)
Exibe notificações flutuantes na tela ao pressionar Fn+Q, acionar o Auto-Switch de Jogos,
ativar o Modo Viagem (Eco-Mode) ou pressionar a tecla Copilot remapeada.
Projetado especificamente para NÃO roubar o foco nem minimizar jogos em tela cheia.
"""

import os
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    Qt, QFont, QIcon, QTimer, QVariantAnimation,
    QGraphicsOpacityEffect, QApplication
)
from ui.theme_tokens import ThemeTokens

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icons")


class VantageOSDOverlay(QWidget):
    """Janela flutuante não-intrusiva (On-Screen Display) do Ducksvantage."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Flags obrigatórias para não roubar foco e não minimizar jogos
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.setFixedSize(390, 110)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("osdContainer")
        self.container.setStyleSheet(f"""
            QFrame#osdContainer {{
                background-color: rgba(26, 30, 41, 0.88);
                border: 2px solid #30415a;
                border-radius: {ThemeTokens.RADIUS_OSD}px;
            }}
        """)

        c_layout = QHBoxLayout(self.container)
        c_layout.setContentsMargins(22, 16, 22, 16)
        c_layout.setSpacing(18)

        # Ícone Grande (48x48)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.addWidget(self.icon_label)

        # Textos informativos
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel("Modo Térmico")
        self.title_label.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.title_label.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        text_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("Atalho Fn + Q")
        self.subtitle_label.setFont(QFont("Segoe UI", 10))
        self.subtitle_label.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY};")
        text_layout.addWidget(self.subtitle_label)

        c_layout.addLayout(text_layout)
        c_layout.addStretch()

        root_layout.addWidget(self.container)

        # Efeito de opacidade para fade-out suave
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)

        # Timer de exibição (1.5 segundos)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(1500)
        self.hide_timer.timeout.connect(self._start_fade_out)

        # Animação suave de fade-out
        self.fade_anim = QVariantAnimation(self)
        self.fade_anim.setDuration(350)
        self.fade_anim.valueChanged.connect(self._on_fade_step)
        self.fade_anim.finished.connect(self.hide)

    def _on_fade_step(self, val):
        self.opacity_effect.setOpacity(float(val))

    def _start_fade_out(self):
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.opacity_effect.opacity())
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.start()

    def _reposition(self):
        """Posiciona o pop-up centralizado na parte inferior/central da tela."""
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.geometry()
            x = geom.x() + (geom.width() - self.width()) // 2
            y = geom.y() + int(geom.height() * 0.78)
            self.move(x, y)

    def show_osd(self, title: str, subtitle: str, icon_path: str, accent_color: str):
        """Exibe o OSD com novos valores e reinicia o timer de permanência de 1.5s."""
        self.title_label.setText(title)
        self.title_label.setStyleSheet(f"color: {accent_color};")
        self.subtitle_label.setText(subtitle)

        if os.path.exists(icon_path):
            pix = QIcon(icon_path).pixmap(48, 48)
            self.icon_label.setPixmap(pix)

        self.container.setStyleSheet(f"""
            QFrame#osdContainer {{
                background-color: rgba(26, 30, 41, 0.88);
                border: 2px solid {accent_color};
                border-radius: {ThemeTokens.RADIUS_OSD}px;
            }}
        """)

        self._reposition()

        self.fade_anim.stop()
        self.opacity_effect.setOpacity(1.0)
        self.show()

        self.hide_timer.start()

    def notify_feature_osd(self, title: str, subtitle: str, icon_name: str, accent_color: str):
        """Dispara o OSD para recursos de elite (Auto-Switch Jogo, Modo Viagem, Tecla Copilot)."""
        icon_path = os.path.join(ICON_DIR, icon_name)
        self.show_osd(title=title, subtitle=subtitle, icon_path=icon_path, accent_color=accent_color)

    def notify_thermal_mode(self, mode: str):
        """Dispara o OSD formatado especificamente para a troca de perfil Fn+Q."""
        mode_lower = (mode or "balanced").lower().strip()
        if mode_lower == "max-power" or "max" in mode_lower or "extrem" in mode_lower:
            self.show_osd(
                title="Desempenho Máximo (Max-Power)",
                subtitle="Fn + Q • Rotação Máxima & Potência Total",
                icon_path=os.path.join(ICON_DIR, "thermal_max_power.svg"),
                accent_color=ThemeTokens.THERMAL_CUSTOM
            )
        elif mode_lower == "performance" or "perf" in mode_lower:
            self.show_osd(
                title="Modo Desempenho",
                subtitle="Fn + Q • Envelope Térmico Elevado",
                icon_path=os.path.join(ICON_DIR, "thermal_performance.svg"),
                accent_color=ThemeTokens.THERMAL_PERFORMANCE
            )
        elif mode_lower in ("low-power", "quiet", "silencioso") or "low" in mode_lower or "quiet" in mode_lower:
            self.show_osd(
                title="Modo Silencioso",
                subtitle="Fn + Q • Ventoinhas e Clocks Baixos",
                icon_path=os.path.join(ICON_DIR, "thermal_quiet.svg"),
                accent_color=ThemeTokens.THERMAL_QUIET
            )
        else:
            self.show_osd(
                title="Modo Equilibrado",
                subtitle="Fn + Q • Ajuste Automático Inteligente",
                icon_path=os.path.join(ICON_DIR, "thermal_balanced.svg"),
                accent_color=ThemeTokens.THERMAL_BALANCED
            )
