"""
Dashboard Principal do Ducksvantage (ui/dashboard.py)
Layout assimétrico oficial do Lenovo Vantage (65% Esquerda / 35% Direita):
- Esquerda (65%): 3 Gauges Circulares + Seletor de Modo Térmico (incluindo Max-Power dinâmico)
  + Card de Armazenamento & Refrigeração.
- Direita (35%): Painel dinâmico (LEGION EDGE / LOQ EDGE / LENOVO EDGE) com Modo Viagem (1-Clique),
  Auto-Switch em Jogos, Feature Discovery e controle compacto de brilho do teclado (Desligado, Baixo, Alto).
Zero emojis de texto: utiliza exclusivamente ícones vetoriais SVG oficiais.
"""

import os
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QScrollArea, QPushButton, Qt, QFont, QIcon,
    Signal, QSizePolicy
)
from ui.theme_tokens import ThemeTokens
from ui.gauges import HardwareGaugesCard
from ui.components import ToggleSwitch, StatusBadge

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icons")


def get_asset_icon(name: str) -> QIcon:
    path = os.path.join(ICON_DIR, name)
    if os.path.exists(path):
        return QIcon(path)
    return QIcon()


class ThermalBlock(QFrame):
    """Botão em bloco individual para seleção de perfil térmico."""
    clicked = Signal(str)

    def __init__(self, mode_id: str, title: str, subtitle: str, icon_file: str, accent_color: str, parent=None):
        super().__init__(parent)
        self.mode_id = mode_id
        self.accent_color = accent_color
        self.is_active = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header do bloco: Ícone SVG + Badge ATIVO
        top = QHBoxLayout()
        self.icon_lbl = QLabel()
        icon = get_asset_icon(icon_file)
        if not icon.isNull():
            self.icon_lbl.setPixmap(icon.pixmap(26, 26))
        top.addWidget(self.icon_lbl)

        top.addStretch()

        self.badge = QLabel("ATIVO")
        self.badge.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.badge.setVisible(False)
        top.addWidget(self.badge)
        layout.addLayout(top)

        # Título
        self.title_lbl = QLabel(title)
        self.title_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        layout.addWidget(self.title_lbl)

        # Subtítulo
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
                ThermalBlock {{
                    background-color: {ThemeTokens.BG_CARD_ACTIVE};
                    border: 2px solid {self.accent_color};
                    border-radius: {ThemeTokens.RADIUS_CARD}px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                ThermalBlock {{
                    background-color: {ThemeTokens.BG_CARD_HOVER};
                    border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                    border-radius: {ThemeTokens.RADIUS_CARD}px;
                }}
                ThermalBlock:hover {{
                    border-color: {self.accent_color};
                }}
            """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mode_id)
        super().mousePressEvent(event)


class EdgeControlItem(QFrame):
    """Item individual da lista vertical compacta do painel Lenovo/LOQ/Legion EDGE."""
    toggled = Signal(bool)

    def __init__(self, icon_file: str, title: str, subtitle: str, supported: bool = True, parent=None):
        super().__init__(parent)
        self.supported = supported
        self.setStyleSheet(f"""
            EdgeControlItem {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 8px;
            }}
            EdgeControlItem:hover {{
                border-color: {ThemeTokens.BORDER_HOVER};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)

        # Ícone SVG à esquerda
        icon = get_asset_icon(icon_file)
        if not icon.isNull():
            ic_lbl = QLabel()
            ic_lbl.setPixmap(icon.pixmap(22, 22))
            layout.addWidget(ic_lbl)

        # Textos centrais
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.t_label = QLabel(title)
        self.t_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.t_label.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        text_layout.addWidget(self.t_label)

        self.sub_label = QLabel(subtitle if supported else "Não suportado pelo ACPI deste modelo")
        self.sub_label.setFont(QFont("Segoe UI", 9))
        self.sub_label.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY if supported else ThemeTokens.TEXT_WHITE_40};")
        text_layout.addWidget(self.sub_label)

        layout.addLayout(text_layout)
        layout.addStretch()

        # Toggle Switch à direita
        self.switch = ToggleSwitch()
        self.switch.setEnabled(supported)
        self.switch.toggled.connect(self.toggled.emit)
        layout.addWidget(self.switch)

    def set_checked(self, checked: bool):
        if self.switch.isChecked() != checked:
            self.switch.blockSignals(True)
            self.switch.setChecked(checked)
            self.switch.blockSignals(False)

    def set_subtitle(self, text: str, highlight_color: str = ""):
        self.sub_label.setText(text)
        col = highlight_color if highlight_color else (ThemeTokens.TEXT_LIGHT_GRAY if self.supported else ThemeTokens.TEXT_WHITE_40)
        self.sub_label.setStyleSheet(f"color: {col};")


class KeyboardBacklightEdgeItem(QFrame):
    """Widget compacto no painel EDGE para o brilho do teclado (Desligado, Baixo, Alto)."""
    level_requested = Signal(int)

    def __init__(self, supported: bool = True, parent=None):
        super().__init__(parent)
        self.supported = supported
        self.current_level = 0

        self.setStyleSheet(f"""
            KeyboardBacklightEdgeItem {{
                background-color: {ThemeTokens.BG_CARD_HOVER};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(8)

        # Linha superior: Ícone + Título + Status
        top = QHBoxLayout()
        top.setSpacing(10)
        icon = get_asset_icon("edge_backlight.svg")
        if not icon.isNull():
            ic_lbl = QLabel()
            ic_lbl.setPixmap(icon.pixmap(22, 22))
            top.addWidget(ic_lbl)

        t_col = QVBoxLayout()
        t_col.setSpacing(1)
        title = QLabel("Luz do Teclado (Backlight)")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        t_col.addWidget(title)

        sub_txt = (
            "Controle via /sys/class/leds/platform::kbd_backlight"
            if supported else "Controlado via EC de Hardware (Atalho Fn + Espaço)"
        )
        self.sub_lbl = QLabel(sub_txt)
        self.sub_lbl.setFont(QFont("Segoe UI", 8))
        self.sub_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY};")
        t_col.addWidget(self.sub_lbl)
        top.addLayout(t_col)
        top.addStretch()
        layout.addLayout(top)

        # Linha inferior: 3 botões compactos (Desligado, Baixo, Alto)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.buttons = []
        labels = [("Desligado", 0), ("Baixo", 1), ("Alto", 2)]

        for text, lvl in labels:
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor if supported else Qt.CursorShape.ArrowCursor)
            btn.setEnabled(supported)
            btn.setFixedHeight(26)
            btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            btn.clicked.connect(lambda checked, l=lvl: self.level_requested.emit(l))
            btn_row.addWidget(btn)
            self.buttons.append((btn, lvl))

        layout.addLayout(btn_row)
        self.set_level(0)

    def set_level(self, level: int):
        self.current_level = level
        for btn, lvl in self.buttons:
            is_sel = (lvl == level) and self.supported
            if is_sel:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {ThemeTokens.BORDER_CYAN};
                        color: #0b0f19;
                        border: 1px solid {ThemeTokens.BORDER_CYAN};
                        border-radius: 5px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #192338;
                        color: {ThemeTokens.TEXT_LIGHT_GRAY if self.supported else ThemeTokens.TEXT_WHITE_40};
                        border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                        border-radius: 5px;
                    }}
                    QPushButton:hover {{
                        border-color: {ThemeTokens.BORDER_CYAN};
                    }}
                """)


class VantageDashboardView(QWidget):
    """Visualização principal do Dashboard Ducksvantage (65% Esquerda / 35% Direita)."""
    profile_requested = Signal(str)
    fn_q_cycle_requested = Signal()
    eco_travel_toggled = Signal(bool)
    game_auto_toggled = Signal(bool)
    conservation_toggled = Signal(bool)
    rapid_charge_toggled = Signal(bool)
    fn_lock_toggled = Signal(bool)
    camera_toggled = Signal(bool)
    usb_charging_toggled = Signal(bool)
    touchpad_toggled = Signal(bool)
    auto_power_toggled = Signal(bool)
    kbd_backlight_requested = Signal(int)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        feat = self.backend.features

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        main_layout = QHBoxLayout(container)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(18)

        # =====================================================================
        # COLUNA ESQUERDA (65% de largura)
        # =====================================================================
        left_col = QVBoxLayout()
        left_col.setSpacing(16)

        # 1. Topo: Card com os 3 Medidores Circulares (CPU, GPU, RAM)
        self.gauges_card = HardwareGaugesCard()
        left_col.addWidget(self.gauges_card)

        # 2. Meio: Seletor Visual de Modo Térmico (Thermal Mode + Max-Power Dinâmico)
        thermal_card = QFrame()
        thermal_card.setProperty("class", "vantageCard")
        thermal_card.setStyleSheet(f"""
            QFrame.vantageCard {{
                background-color: {ThemeTokens.BG_CARD};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: {ThemeTokens.RADIUS_CARD}px;
                padding: 16px;
            }}
        """)
        th_layout = QVBoxLayout(thermal_card)
        th_layout.setSpacing(12)

        th_header = QHBoxLayout()
        ic_gear = QLabel()
        ic_gear.setPixmap(get_asset_icon("gear.svg").pixmap(20, 20))
        th_header.addWidget(ic_gear)

        th_title = QLabel("Modo Térmico (ACPI Platform Profile)")
        th_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        th_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        th_header.addWidget(th_title)

        th_header.addStretch()

        shortcut_btn = QPushButton("Atalho Fn + Q  •  Ciclar")
        shortcut_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        shortcut_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        shortcut_btn.setToolTip(
            "Pressione Fn + Q no teclado ou clique aqui para alternar entre Silencioso, Equilibrado, Desempenho e Max-Power."
        )
        shortcut_btn.setStyleSheet(f"""
            QPushButton {{
                color: {ThemeTokens.BORDER_CYAN};
                background-color: {ThemeTokens.BG_CARD_HOVER};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                padding: 4px 12px;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                border-color: {ThemeTokens.BORDER_CYAN};
                background-color: #192338;
            }}
        """)
        shortcut_btn.clicked.connect(self.fn_q_cycle_requested.emit)
        th_header.addWidget(shortcut_btn)
        th_layout.addLayout(th_header)

        blocks_row = QHBoxLayout()
        blocks_row.setSpacing(10)

        self.block_quiet = ThermalBlock(
            "low-power", "Silencioso",
            "Menor ruído acústico e eficiência energética.",
            "thermal_quiet.svg", ThemeTokens.THERMAL_QUIET
        )
        self.block_quiet.clicked.connect(self.profile_requested.emit)
        blocks_row.addWidget(self.block_quiet)

        self.block_balanced = ThermalBlock(
            "balanced", "Equilibrado",
            "Ajuste dinâmico inteligente de potência e cooler.",
            "thermal_balanced.svg", ThemeTokens.THERMAL_BALANCED
        )
        self.block_balanced.clicked.connect(self.profile_requested.emit)
        blocks_row.addWidget(self.block_balanced)

        self.block_perf = ThermalBlock(
            "performance", "Desempenho",
            "TDP elevado e curva acelerada de refrigeração.",
            "thermal_performance.svg", ThemeTokens.THERMAL_PERFORMANCE
        )
        self.block_perf.clicked.connect(self.profile_requested.emit)
        blocks_row.addWidget(self.block_perf)

        # Descoberta Dinâmica do Perfil 'max-power' no Kernel (Incluído no ciclo Fn+Q)
        if feat.max_power_profile:
            self.block_max_power = ThermalBlock(
                "max-power", "Max-Power",
                "Potência extrema e rotação máxima das ventoinhas.",
                "thermal_max_power.svg", ThemeTokens.THERMAL_CUSTOM
            )
            self.block_max_power.clicked.connect(self.profile_requested.emit)
            blocks_row.addWidget(self.block_max_power)
        else:
            self.block_max_power = None

        th_layout.addLayout(blocks_row)
        left_col.addWidget(thermal_card)

        # 3. Base: Card Limpo de "Armazenamento & Refrigeração"
        storage_fan_card = QFrame()
        storage_fan_card.setProperty("class", "vantageCard")
        storage_fan_card.setStyleSheet(f"""
            QFrame.vantageCard {{
                background-color: {ThemeTokens.BG_CARD};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: {ThemeTokens.RADIUS_CARD}px;
                padding: 16px;
            }}
        """)
        sf_layout = QVBoxLayout(storage_fan_card)
        sf_layout.setSpacing(12)

        sf_header = QHBoxLayout()
        ic_ssd = QLabel()
        ic_ssd.setPixmap(get_asset_icon("storage.svg").pixmap(22, 22))
        sf_header.addWidget(ic_ssd)

        sf_title = QLabel("Armazenamento NVMe/SATA & Sistema de Refrigeração")
        sf_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        sf_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        sf_header.addWidget(sf_title)

        sf_header.addStretch()

        self.storage_badge = StatusBadge("NVMe ATIVO", bg_color="#064e3b", text_color="#34d399")
        sf_header.addWidget(self.storage_badge)
        sf_layout.addLayout(sf_header)

        sf_grid = QGridLayout()
        sf_grid.setSpacing(10)

        self.lbl_ssd_model = self._add_stat(sf_grid, 0, 0, "Unidade Principal", "--")
        self.lbl_ssd_usage = self._add_stat(sf_grid, 0, 1, "Espaço Utilizado", "-- / -- GB")
        self.lbl_ssd_temp = self._add_stat(sf_grid, 0, 2, "Temperatura do SSD", "-- °C")
        self.lbl_fan_rpm = self._add_stat(sf_grid, 1, 0, "Rotação das Ventoinhas", "-- RPM")
        self.lbl_cpu_gov = self._add_stat(sf_grid, 1, 1, "CPU Governor / TDP", "--")
        self.lbl_gpu_state = self._add_stat(sf_grid, 1, 2, "Estado de Energia GPU", "--")

        sf_layout.addLayout(sf_grid)
        left_col.addWidget(storage_fan_card)
        left_col.addStretch()

        main_layout.addLayout(left_col, stretch=65)

        # =====================================================================
        # COLUNA DIREITA (35% de largura) - PAINEL VERTICAL DINÂMICO EDGE
        # =====================================================================
        edge_card = QFrame()
        edge_card.setProperty("class", "vantageCard")
        edge_card.setStyleSheet(f"""
            QFrame.vantageCard {{
                background-color: {ThemeTokens.BG_CARD};
                border: 1px solid {ThemeTokens.BORDER_DEFAULT};
                border-radius: {ThemeTokens.RADIUS_CARD}px;
                padding: 16px;
            }}
        """)
        edge_layout = QVBoxLayout(edge_card)
        edge_layout.setSpacing(8)

        # Cabeçalho Dinâmico (LEGION EDGE / LOQ EDGE / LENOVO EDGE • CONTROLES RÁPIDOS)
        edge_header = QHBoxLayout()
        ic_edge = QLabel()
        ic_edge.setPixmap(get_asset_icon("tools.svg").pixmap(20, 20))
        edge_header.addWidget(ic_edge)

        self.edge_title_lbl = QLabel(self.backend.system_info.edge_panel_title)
        self.edge_title_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.edge_title_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100}; letter-spacing: 0.8px;")
        edge_header.addWidget(self.edge_title_lbl)

        edge_header.addStretch()
        edge_layout.addLayout(edge_header)

        # ELITE 6: Modo Viagem / Eco-Mode Extremo (1-Clique)
        self.item_eco_travel = EdgeControlItem(
            "eco_travel.svg",
            "Modo Viagem (Eco-Mode Extremo)",
            "1-Clique: Conservação 80% + GPU D3cold + Turbo Off",
            supported=True
        )
        self.item_eco_travel.toggled.connect(self.eco_travel_toggled.emit)
        edge_layout.addWidget(self.item_eco_travel)

        # ELITE 2: Auto-Switching por Jogo (Steam / Heroic / Proton)
        self.item_game_auto = EdgeControlItem(
            "game_controller.svg",
            "Auto-Switch em Jogos (Smart)",
            "Ativa Max-Power / Desempenho ao detectar jogo",
            supported=feat.platform_profile
        )
        self.item_game_auto.toggled.connect(self.game_auto_toggled.emit)
        edge_layout.addWidget(self.item_game_auto)

        # 1. Modo de Conservação
        self.item_conservation = EdgeControlItem(
            "edge_conservation.svg",
            "Modo de Conservação",
            "Limita carga em ~80% para proteger a bateria.",
            supported=feat.conservation_mode
        )
        self.item_conservation.toggled.connect(self.conservation_toggled.emit)
        edge_layout.addWidget(self.item_conservation)

        # 2. Carregamento Rápido (Rapid Charge)
        self.item_rapid_charge = EdgeControlItem(
            "edge_rapid_charge.svg",
            "Carregamento Rápido",
            "Eleva a corrente de carga até 100%.",
            supported=feat.rapid_charge
        )
        self.item_rapid_charge.toggled.connect(self.rapid_charge_toggled.emit)
        edge_layout.addWidget(self.item_rapid_charge)

        # 3. Trava de Teclas Fn (Fn-Lock)
        self.item_fn_lock = EdgeControlItem(
            "edge_fn_lock.svg",
            "Trava de Teclas Fn (Fn-Lock)",
            "Alterna F1-F12 diretos vs teclas multimídia.",
            supported=feat.fn_lock
        )
        self.item_fn_lock.toggled.connect(self.fn_lock_toggled.emit)
        edge_layout.addWidget(self.item_fn_lock)

        # 4. Obturador Eletrônico da Câmera (E-Shutter)
        self.item_camera = EdgeControlItem(
            "edge_camera.svg",
            "Câmera (Privacy E-Shutter)",
            "Controla alimentação física da webcam.",
            supported=feat.camera_power
        )
        self.item_camera.toggled.connect(self.camera_toggled.emit)
        edge_layout.addWidget(self.item_camera)

        # 5. Always-On USB Charging (Exibido se existir no ACPI)
        if feat.usb_charging:
            self.item_usb = EdgeControlItem(
                "edge_usb.svg",
                "Always-On USB Charging",
                "Mantém portas USB energizadas em repouso.",
                supported=True
            )
            self.item_usb.toggled.connect(self.usb_charging_toggled.emit)
            edge_layout.addWidget(self.item_usb)
        else:
            self.item_usb = None

        # 6. Bloqueio do Touchpad
        self.item_touchpad = EdgeControlItem(
            "edge_touchpad.svg",
            "Trava do Touchpad",
            "Evita toques acidentais durante jogos.",
            supported=feat.touchpad_control
        )
        self.item_touchpad.toggled.connect(self.touchpad_toggled.emit)
        edge_layout.addWidget(self.item_touchpad)

        # 7. Transição Automática AC / Bateria
        self.item_auto_power = EdgeControlItem(
            "power.svg",
            "Transição Automática AC",
            "Alterna perfil ao conectar/remover tomada.",
            supported=feat.platform_profile
        )
        self.item_auto_power.toggled.connect(self.auto_power_toggled.emit)
        edge_layout.addWidget(self.item_auto_power)

        # 8. Controle de Brilho do Teclado (Desligado, Baixo, Alto)
        self.item_kbd_backlight = KeyboardBacklightEdgeItem(supported=feat.kbd_backlight)
        self.item_kbd_backlight.level_requested.connect(self.kbd_backlight_requested.emit)
        edge_layout.addWidget(self.item_kbd_backlight)

        edge_layout.addStretch()
        main_layout.addWidget(edge_card, stretch=35)

        scroll.setWidget(container)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

    def _add_stat(self, grid: QGridLayout, r: int, c: int, title: str, default: str) -> QLabel:
        box = QFrame()
        box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 6px; padding: 8px 10px;")
        layout = QVBoxLayout(box)
        layout.setSpacing(3)
        layout.setContentsMargins(6, 5, 6, 5)

        t = QLabel(title)
        t.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY};")
        layout.addWidget(t)

        val = QLabel(default)
        val.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        val.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        layout.addWidget(val)

        grid.addWidget(box, r, c)
        return val

    def update_telemetry(self):
        """Atualiza todos os sensores do Dashboard sem poluição ou repetição."""
        cpu = self.backend.get_cpu_metrics()
        gpu = self.backend.get_gpu_metrics()
        ram = self.backend.get_ram_metrics()
        fan = self.backend.get_fan_metrics()
        disks = self.backend.get_storage_devices()

        # 1. Gauges Circulares
        self.gauges_card.update_metrics(cpu, gpu, ram)

        # 2. Thermal Mode (incluindo Max-Power dinâmico)
        prof = self.backend.normalize_profile(self.backend.get_platform_profile())
        self.block_quiet.set_active(prof in ("low-power", "quiet"))
        self.block_balanced.set_active(prof == "balanced")
        if self.block_max_power:
            self.block_perf.set_active(prof == "performance")
            self.block_max_power.set_active(prof == "max-power")
        else:
            self.block_perf.set_active(prof in ("performance", "max-power"))

        # 3. Card de Armazenamento & Refrigeração
        if disks:
            d0 = disks[0]
            self.lbl_ssd_model.setText(d0.model[:22])
            self.lbl_ssd_usage.setText(f"{d0.used_gb:.1f} / {d0.total_gb:.0f} GB ({d0.usage_percent:.0f}%)")
            if d0.temperature_c > 0:
                self.lbl_ssd_temp.setText(f"{d0.temperature_c:.1f} °C")
                if d0.temperature_c >= 65:
                    self.storage_badge.setText(f"SSD: {d0.temperature_c:.0f}°C (QUENTE)")
                    self.storage_badge.setColor("#78350f", "#fbbf24")
                else:
                    self.storage_badge.setText(f"SSD SAUDÁVEL ({d0.temperature_c:.0f}°C)")
                    self.storage_badge.setColor("#064e3b", "#34d399")
            else:
                self.lbl_ssd_temp.setText("N/A")

        self.lbl_fan_rpm.setText(fan.status_label)
        boost_str = "Boost ON" if cpu.turbo_enabled else "Boost OFF"
        self.lbl_cpu_gov.setText(f"{cpu.governor} • {boost_str} ({cpu.pl1_w}/{cpu.pl2_w}W)")
        self.lbl_gpu_state.setText(f"{gpu.runtime_state} ({gpu.pstate})" if gpu.available else "D3cold (Suspensa)")

        # 4. Sincronizar Switches do Painel EDGE
        self.item_eco_travel.set_checked(self.backend.get_eco_travel_mode())
        self.item_game_auto.set_checked(self.backend.get_game_auto_switch())
        active_game = self.backend.get_active_game()
        if active_game:
            self.item_game_auto.set_subtitle(f"JOGO ATIVO: {active_game}", ThemeTokens.STATUS_GREEN)
        else:
            self.item_game_auto.set_subtitle("Ativa Max-Power / Desempenho ao detectar jogo")

        if self.backend.features.conservation_mode:
            self.item_conservation.set_checked(self.backend.get_conservation_mode())
        if self.backend.features.rapid_charge:
            self.item_rapid_charge.set_checked(self.backend.get_rapid_charge())
        if self.backend.features.fn_lock:
            self.item_fn_lock.set_checked(self.backend.get_fn_lock())
        if self.backend.features.camera_power:
            self.item_camera.set_checked(self.backend.get_camera_power())
        if self.item_usb and self.backend.features.usb_charging:
            self.item_usb.set_checked(self.backend.get_usb_charging())

        self.item_touchpad.set_checked(self.backend.get_touchpad_status())
        self.item_auto_power.set_checked(self.backend.get_auto_power_transition())

        if self.backend.features.kbd_backlight:
            self.item_kbd_backlight.set_level(self.backend.get_kbd_backlight())
