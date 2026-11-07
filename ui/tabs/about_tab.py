"""
Aba Sobre o Dispositivo do Ducksvantage (ui/tabs/about_tab.py).
Apresenta informações completas e dinâmicas de DMI/BIOS, Processador, GPU, Kernel e SSDs,
além de um card compacto de status UDEV com botão de reparo (sem blocos de código que gerem scroll horizontal).
Zero emojis: utiliza exclusivamente ícones vetoriais SVG.
"""

import os
from core.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QPushButton, QScrollArea, Qt, Signal, QFont,
    QMessageBox, QApplication, QIcon, QPixmap
)
from ui.theme_tokens import ThemeTokens
from ui.components import StatusBadge
from core.permissions import PermissionsManager

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "icons")


class AboutTab(QWidget):
    """Informações completas de DMI/BIOS do sistema e reparo compacto de permissões UDEV."""
    permissions_updated = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(18)

        # =====================================================================
        # 1. Card de Identificação DMI / BIOS / Hardware do Dispositivo
        # =====================================================================
        info_card = QFrame()
        info_card.setProperty("class", "card")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(20, 18, 20, 18)
        info_layout.setSpacing(16)

        info_header = QHBoxLayout()
        icon = QLabel()
        dv_path = os.path.join(ICON_DIR, "ducksvantage_logo.svg")
        if os.path.exists(dv_path):
            icon.setPixmap(QPixmap(dv_path).scaled(34, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        info_header.addWidget(icon)

        sys = self.backend.system_info
        title_box = QVBoxLayout()
        title = QLabel(f"Ducksvantage • {sys.display_model_name} ({sys.product_name})")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {ThemeTokens.BORDER_CYAN};")
        title_box.addWidget(title)

        subtitle = QLabel("Substituto universal e leve do Lenovo Vantage para notebooks Legion, LOQ, IdeaPad e Yoga no Linux.")
        subtitle.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        title_box.addWidget(subtitle)
        info_header.addLayout(title_box)

        info_header.addStretch()

        ver_badge = StatusBadge("DUCKSVANTAGE v2.0", bg_color="#1e293b", text_color="#00d2ff")
        info_header.addWidget(ver_badge)

        info_layout.addLayout(info_header)

        # Grid completo com especificações dinâmicas (Zero Hardcoding)
        grid = QGridLayout()
        grid.setSpacing(10)

        self._add_spec_item(grid, 0, 0, "Fabricante & Linha", f"{sys.sys_vendor} ({sys.laptop_line})")
        self._add_spec_item(grid, 0, 1, "Modelo / Produto DMI", f"{sys.display_model_name} ({sys.product_name})")
        self._add_spec_item(grid, 0, 2, "Versão & Data da BIOS", f"{sys.bios_version} ({sys.bios_date})")
        self._add_spec_item(grid, 1, 0, "Processador (CPU)", sys.cpu_model)
        self._add_spec_item(grid, 1, 1, "Placa Gráfica (GPU)", sys.gpu_model)
        self._add_spec_item(grid, 1, 2, "Armazenamento (SSDs)", sys.ssd_summary)
        self._add_spec_item(grid, 2, 0, "Sistema Operacional", sys.os_name)
        self._add_spec_item(grid, 2, 1, "Versão do Kernel", sys.kernel_version)
        self._add_spec_item(grid, 2, 2, "Placa-Mãe (Board)", sys.board_name)

        info_layout.addLayout(grid)
        layout.addWidget(info_card)

        # =====================================================================
        # 2. Card Compacto de Status UDEV e Reparo de Permissões (Sem Bloco Gigante)
        # =====================================================================
        udev_card = QFrame()
        udev_card.setProperty("class", "card")
        udev_layout = QVBoxLayout(udev_card)
        udev_layout.setContentsMargins(20, 18, 20, 18)
        udev_layout.setSpacing(12)

        udev_top = QHBoxLayout()
        u_icon = QLabel()
        gear_path = os.path.join(ICON_DIR, "shield.svg")
        if os.path.exists(gear_path):
            u_icon.setPixmap(QPixmap(gear_path).scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        udev_top.addWidget(u_icon)

        u_titles = QVBoxLayout()
        u_title = QLabel("Status de Permissões do Kernel (/sys/ & Regras UDEV)")
        u_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        u_title.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        u_titles.addWidget(u_title)

        self.udev_desc_lbl = QLabel(
            "Concede acesso direto sem senha (chmod 0666) aos controles de ACPI, bateria, teclado e CPU."
        )
        self.udev_desc_lbl.setWordWrap(True)
        self.udev_desc_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 11px;")
        u_titles.addWidget(self.udev_desc_lbl)
        udev_top.addLayout(u_titles)

        udev_top.addStretch()

        self.perm_badge = StatusBadge("VERIFICANDO", bg_color="#1e293b", text_color="#cbd5e1")
        udev_top.addWidget(self.perm_badge)
        udev_layout.addLayout(udev_top)

        # Barra compacta de ações
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_install_udev = QPushButton("Instalar / Reparar Permissões UDEV")
        self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))
        self.btn_install_udev.setProperty("class", "primaryButton")
        self.btn_install_udev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install_udev.clicked.connect(self._install_udev_action)
        btn_layout.addWidget(self.btn_install_udev)

        btn_copy = QPushButton("Copiar Regra UDEV")
        btn_copy.setIcon(QIcon(os.path.join(ICON_DIR, "copy.svg")))
        btn_copy.setProperty("class", "secondaryButton")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(self._copy_rules_action)
        btn_layout.addWidget(btn_copy)

        btn_layout.addStretch()
        udev_layout.addLayout(btn_layout)

        layout.addWidget(udev_card)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.update_permission_status()

    def _add_spec_item(self, grid: QGridLayout, row: int, col: int, label: str, value: str):
        box = QFrame()
        box.setStyleSheet(f"background-color: {ThemeTokens.BG_CARD_HOVER}; border-radius: 8px; padding: 10px;")
        b_layout = QVBoxLayout(box)
        b_layout.setSpacing(3)
        b_layout.setContentsMargins(10, 8, 10, 8)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_LIGHT_GRAY}; font-size: 10px; font-weight: bold;")
        b_layout.addWidget(lbl)

        val_lbl = QLabel(value)
        val_lbl.setWordWrap(True)
        val_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        val_lbl.setStyleSheet(f"color: {ThemeTokens.TEXT_WHITE_100};")
        b_layout.addWidget(val_lbl)

        grid.addWidget(box, row, col)

    def update_permission_status(self):
        """Verifica o status atual de escrita nos diretórios do kernel."""
        has_perms = self.backend.has_full_write_permissions()
        is_installed = PermissionsManager.is_udev_rule_installed()

        if has_perms:
            self.perm_badge.setText("UDEV ATIVO • SEM SUDO")
            self.perm_badge.setColor("#064e3b", "#34d399")
            self.btn_install_udev.setText("Reaplicar / Reparar Permissões UDEV")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "check_circle.svg")))
        elif is_installed:
            self.perm_badge.setText("REQUER REPARO")
            self.perm_badge.setColor("#78350f", "#fbbf24")
            self.btn_install_udev.setText("Reparar Permissões UDEV Agora")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))
        else:
            self.perm_badge.setText("REQUER CONFIGURAÇÃO")
            self.perm_badge.setColor("#78350f", "#fbbf24")
            self.btn_install_udev.setText("Instalar Regras UDEV (Sem Sudo)")
            self.btn_install_udev.setIcon(QIcon(os.path.join(ICON_DIR, "shield.svg")))

    def _install_udev_action(self):
        active_paths = self.backend.get_active_writable_paths()
        success, message = PermissionsManager.install_udev_rules(active_paths)
        if success:
            QMessageBox.information(self, "Ducksvantage UDEV", message)
            self.update_permission_status()
            self.permissions_updated.emit()
        else:
            QMessageBox.critical(self, "Erro na Instalação UDEV", message)

    def _copy_rules_action(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(PermissionsManager.get_udev_rule_content())
            QMessageBox.information(
                self, "Regra UDEV Copiada",
                "As regras UDEV foram copiadas para a área de transferência.\n"
                "Alternativamente, você pode executar no terminal:\n"
                "sudo ./setup_udev.sh"
            )
