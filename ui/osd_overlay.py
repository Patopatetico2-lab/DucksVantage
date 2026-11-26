"""
Pop-up OSD Não-Intrusivo para Jogos no KDE Plasma / Wayland (ui/osd_overlay.py)
Exibe notificações flutuantes na tela ao pressionar Fn+Q, acionar o Auto-Switch de Jogos,
ativar o Modo Viagem (Eco-Mode) ou pressionar a tecla Copilot remapeada.
Projetado especificamente para NÃO roubar o foco nem minimizar jogos em tela cheia.
"""

import os
import configparser
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    Qt, QFont, QIcon, QTimer, QVariantAnimation,
    QApplication, QCursor, QGuiApplication,
    QPainter, QColor, QPen, QBrush, QRectF
)
from ui.theme_tokens import ThemeTokens

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icons")


class VantageOSDOverlay(QWidget):
    """Janela flutuante não-intrusiva (On-Screen Display) do Ducksvantage."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.is_wayland = (
            "wayland" in os.environ.get("XDG_SESSION_TYPE", "").lower()
            or bool(os.environ.get("WAYLAND_DISPLAY"))
        )
        self._accent_color = ThemeTokens.BORDER_CYAN
        self._opacity = 1.0
        self._last_kwin_rule_pos = None
        self._pos_changed_for_remap = False
        self.enabled = True
        self.position_mode = "bottom-center"
        self.duration_ms = 1800

        # Usa Qt.WindowType.Tool (xdg_toplevel no Wayland) em vez de ToolTip (xdg_popup),
        # garantindo que o OSD apareça mesmo sem janela-pai visível (ex: app minimizado na bandeja).
        flags = (
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus |
            Qt.WindowType.WindowTransparentForInput
        )

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("ducksvantage-osd")
        self.setWindowTitle("Ducksvantage OSD")

        self.setFixedSize(390, 110)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("osdContainer")
        self.container.setStyleSheet("QFrame#osdContainer { background: transparent; border: none; }")

        c_layout = QHBoxLayout(self.container)
        c_layout.setContentsMargins(22, 16, 22, 16)
        c_layout.setSpacing(18)

        # Ícone Grande (48x48)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        c_layout.addWidget(self.icon_label)

        # Textos informativos
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel("Modo Térmico")
        self.title_label.setFont(QFont(ThemeTokens.FONT_NAME, 13, QFont.Weight.Bold))
        self.title_label.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; background: transparent; border: none;")
        text_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("Atalho Fn + Q")
        self.subtitle_label.setFont(QFont(ThemeTokens.FONT_NAME, 10))
        self.subtitle_label.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; background: transparent; border: none;")
        text_layout.addWidget(self.subtitle_label)

        c_layout.addLayout(text_layout)
        c_layout.addStretch()

        root_layout.addWidget(self.container)

        # Timer de exibição (1.8 segundos)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(1800)
        self.hide_timer.timeout.connect(self._start_fade_out)

        # Animação suave de fade-out via opacidade direta (compatível com Wayland e X11)
        self.fade_anim = QVariantAnimation(self)
        self.fade_anim.setDuration(300)
        self.fade_anim.valueChanged.connect(self._on_fade_step)
        self.fade_anim.finished.connect(self.hide)

    def paintEvent(self, event):
        """Desenha o cartão escuro arredondado com borda luminosa diretamente via QPainter (100% compatível com Wayland)."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(max(0.0, min(1.0, self._opacity)))

        rect = QRectF(self.rect()).adjusted(2.0, 2.0, -2.0, -2.0)
        bg = QColor(24, 26, 30, 240)
        border = QColor(self._accent_color)

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(rect, float(ThemeTokens.RADIUS_OSD), float(ThemeTokens.RADIUS_OSD))
        painter.end()

    def _on_fade_step(self, val):
        self._opacity = float(val)
        if not self.is_wayland:
            try:
                self.setWindowOpacity(self._opacity)
            except Exception:
                pass
        self.update()

    def _start_fade_out(self):
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self._opacity)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.start()

    def _get_target_screen(self):
        """Identifica a tela ativa (sob o cursor do mouse em jogos/apps) com fallback para tela principal."""
        try:
            pos = QCursor.pos()
            screen = QGuiApplication.screenAt(pos)
            if screen:
                return screen
        except Exception:
            pass
        return QApplication.primaryScreen()

    def _ensure_kwin_wayland_rule(self, x: int, y: int) -> None:
        """
        No KDE Plasma 6 (Wayland), o protocolo xdg-shell ignora move(x, y) e WindowStaysOnTopHint
        do lado do cliente. Registra automaticamente uma regra nativa no compositor KWin
        (~/.config/kwinrulesrc) + reconfigure via D-Bus para forçar o OSD sempre no topo (above=true),
        na posição inferior central (x, y) e sem roubar o foco da janela ativa.
        """
        if not self.is_wayland:
            return
        try:
            plat = (QGuiApplication.platformName() or "").lower()
            if plat in ("offscreen", "minimal"):
                return
        except Exception:
            pass

        pos_str = f"{x},{y}"
        if self._last_kwin_rule_pos == pos_str:
            return

        try:
            cfg_dir = os.path.expanduser("~/.config")
            if not os.path.isdir(cfg_dir):
                return
            rules_path = os.path.join(cfg_dir, "kwinrulesrc")
            cp = configparser.ConfigParser(interpolation=None)
            cp.optionxform = str  # Preserva maiúsculas/minúsculas exatas exigidas pelo KConfig (Description)
            if os.path.exists(rules_path):
                cp.read(rules_path, encoding="utf-8")

            if not cp.has_section("General"):
                cp.add_section("General")

            rule_id = "ducksvantage_osd"
            existing_rules = [r.strip() for r in cp.get("General", "rules", fallback="").split(",") if r.strip()]
            if rule_id not in existing_rules:
                existing_rules.append(rule_id)
            cp.set("General", "rules", ",".join(existing_rules))
            cp.set("General", "count", str(len(existing_rules)))

            if not cp.has_section(rule_id):
                cp.add_section(rule_id)

            desired = {
                "Description": "Ducksvantage OSD Overlay",
                "title": "Ducksvantage OSD",
                "titlematch": "1",
                "above": "true",
                "aboverule": "2",
                "noborder": "true",
                "noborderrule": "2",
                "skiptaskbar": "true",
                "skiptaskbarrule": "2",
                "skippager": "true",
                "skippagerrule": "2",
                "skipswitcher": "true",
                "skipswitcherrule": "2",
                "acceptfocus": "false",
                "acceptfocusrule": "2",
                "position": pos_str,
                "positionrule": "2",
                "types": "4294967295",
            }
            changed = False
            for k, v in desired.items():
                if cp.get(rule_id, k, fallback=None) != v:
                    cp.set(rule_id, k, v)
                    changed = True

            if changed or not os.path.exists(rules_path) or os.path.getsize(rules_path) == 0:
                with open(rules_path, "w", encoding="utf-8") as f:
                    cp.write(f, space_around_delimiters=False)
                try:
                    from PyQt6.QtDBus import QDBusConnection, QDBusMessage
                    bus = QDBusConnection.sessionBus()
                    if bus.isConnected():
                        msg = QDBusMessage.createMethodCall("org.kde.KWin", "/KWin", "org.kde.KWin", "reconfigure")
                        bus.call(msg)
                except Exception:
                    pass

            if self._last_kwin_rule_pos is not None and self._last_kwin_rule_pos != pos_str:
                self._pos_changed_for_remap = True
            self._last_kwin_rule_pos = pos_str
        except Exception:
            pass

    def configure(self, enabled: bool = True, position: str = "bottom-center", duration_ms: int = 1800) -> None:
        """Atualiza em tempo real se o OSD está ativo, posição na tela e duração."""
        self.enabled = bool(enabled)
        self.position_mode = position if position in ("bottom-center", "top-center", "top-right") else "bottom-center"
        self.duration_ms = max(1000, min(4000, int(duration_ms)))
        self.hide_timer.setInterval(self.duration_ms)
        if not self.enabled and self.isVisible():
            self.hide()

    def _reposition(self):
        """Posiciona o pop-up na posição configurada na tela ativa com suporte a Wayland e X11."""
        screen = self._get_target_screen()
        if screen:
            geom = screen.availableGeometry() if hasattr(screen, "availableGeometry") else screen.geometry()
            if self.position_mode == "top-center":
                x = geom.x() + (geom.width() - self.width()) // 2
                y = geom.y() + max(28, int(geom.height() * 0.06))
            elif self.position_mode == "top-right":
                x = geom.x() + max(20, geom.width() - self.width() - 32)
                y = geom.y() + max(28, int(geom.height() * 0.06))
            else:
                x = geom.x() + (geom.width() - self.width()) // 2
                y = geom.y() + int(geom.height() * 0.78)

            self._ensure_kwin_wayland_rule(x, y)

            if hasattr(self, "windowHandle") and self.windowHandle():
                try:
                    if self.windowHandle().screen() != screen:
                        self.windowHandle().setScreen(screen)
                except Exception:
                    pass

            self.setGeometry(x, y, self.width(), self.height())
            try:
                self.move(x, y)
            except Exception:
                pass

    def show_osd(self, title: str, subtitle: str, icon_path: str, accent_color: str):
        """Exibe o OSD com novos valores e reinicia o timer de permanência."""
        if not self.enabled:
            return
        self._accent_color = accent_color
        self.title_label.setText(title)
        self.title_label.setStyleSheet(f"color: {accent_color}; background: transparent; border: none;")
        self.subtitle_label.setText(subtitle)

        if os.path.exists(icon_path):
            pix = QIcon(icon_path).pixmap(48, 48)
            self.icon_label.setPixmap(pix)

        self.fade_anim.stop()
        self._opacity = 1.0
        if not self.is_wayland:
            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass

        self._reposition()
        if self._pos_changed_for_remap and self.isVisible():
            self.hide()
        self._pos_changed_for_remap = False
        self.show()
        self.raise_()
        self.update()

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
                subtitle="Fn + Q • Envelope Térmico & Potência Máxima",
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
        elif mode_lower == "custom" or "custom" in mode_lower:
            self.show_osd(
                title="Modo Personalizado (Custom)",
                subtitle="BIOS / WMI • Parâmetros Customizados Ativos",
                icon_path=os.path.join(ICON_DIR, "thermal_custom.svg"),
                accent_color=ThemeTokens.THERMAL_CUSTOM
            )
        else:
            self.show_osd(
                title="Modo Equilibrado",
                subtitle="Fn + Q • Ajuste Automático Inteligente",
                icon_path=os.path.join(ICON_DIR, "thermal_balanced.svg"),
                accent_color=ThemeTokens.THERMAL_BALANCED
            )

    def notify_refresh_rate(self, hz: int, reason: str = ""):
        """Dispara o OSD para a taxa de atualização (Fn + R ou AC/Bateria)."""
        sub = "Fn + R • Taxa de Atualização"
        if reason == "ac":
            sub = "Alimentação AC • Fluidez Máxima"
        elif reason == "battery":
            sub = "Modo Bateria • Economia de Energia"

        self.show_osd(
            title=f"Taxa de Atualização: {hz} Hz",
            subtitle=sub,
            icon_path=os.path.join(ICON_DIR, "refresh.svg"),
            accent_color=ThemeTokens.BORDER_CYAN if hz > 60 else ThemeTokens.STATUS_GREEN
        )

    def notify_gpu_mux(self, mode: str, requires_reboot: bool = False):
        """Dispara o OSD para a alteração de modo do GPU MUX Switch."""
        mode_names = {
            "hybrid": "Modo Híbrido (Optimus)",
            "dedicated": "dGPU Exclusiva (Direct)",
            "integrated": "iGPU Pura (Eco Extremo)",
        }
        title = mode_names.get(mode.lower(), f"GPU {mode.upper()}")
        sub = "Reinicialização necessária para ativar" if requires_reboot else "Modo de GPU alterado com sucesso"
        self.show_osd(
            title=f"GPU MUX: {title}",
            subtitle=sub,
            icon_path=os.path.join(ICON_DIR, "gpu_stack.svg"),
            accent_color=ThemeTokens.BORDER_CYAN if mode != "integrated" else ThemeTokens.STATUS_GREEN
        )

    def notify_lcd_overdrive(self, enabled: bool):
        """Dispara o OSD para alteração do LCD Overdrive."""
        self.show_osd(
            title=f"LCD Overdrive: {'Ativado' if enabled else 'Desativado'}",
            subtitle="Tempo de resposta acelerado (Anti-Ghosting)" if enabled else "Tempo de resposta padrão do painel",
            icon_path=os.path.join(ICON_DIR, "refresh.svg"),
            accent_color=ThemeTokens.BORDER_CYAN if enabled else ThemeTokens.TEXT_LIGHT_GRAY
        )

