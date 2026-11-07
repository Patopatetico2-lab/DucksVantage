"""
Tema Dark Cyber Vantage para LenovoLOQ-Control.
Inspirado na identidade visual do Lenovo Vantage / Legion Zone no Windows,
otimizado com estética limpa e moderna para o KDE Plasma no CachyOS.
"""

class Theme:
    # Cores Primárias de Fundo
    BG_DARK = "#0d1017"
    BG_SIDEBAR = "#121620"
    BG_CARD = "#171c28"
    BG_CARD_HOVER = "#1e2434"
    BG_CARD_ACTIVE = "#222a3c"

    # Bordas e Divisores
    BORDER_DEFAULT = "#262e42"
    BORDER_HOVER = "#384562"
    BORDER_CYAN = "#00d2ff"

    # Cores de Acento Vantage
    CYAN = "#00d2ff"
    BLUE = "#0ea5e9"
    GREEN = "#10b981"
    AMBER = "#f59e0b"
    RED = "#ef4444"
    PURPLE = "#a855f7"

    # Cores de Texto
    TEXT_PRIMARY = "#f8fafc"
    TEXT_SECONDARY = "#94a3b8"
    TEXT_MUTED = "#64748b"

    # Tipografia
    FONT_FAMILY = "Segoe UI, Inter, Noto Sans, sans-serif"

    @classmethod
    def get_stylesheet(cls) -> str:
        return f"""
        QMainWindow, QWidget#centralWidget {{
            background-color: {cls.BG_DARK};
            color: {cls.TEXT_PRIMARY};
            font-family: {cls.FONT_FAMILY};
        }}

        /* Sidebar de Navegação */
        QFrame#sidebar {{
            background-color: {cls.BG_SIDEBAR};
            border-right: 1px solid {cls.BORDER_DEFAULT};
        }}

        QPushButton#navButton {{
            background-color: transparent;
            color: {cls.TEXT_SECONDARY};
            border: none;
            border-left: 3px solid transparent;
            text-align: left;
            padding: 12px 18px;
            font-size: 13px;
            font-weight: 500;
            border-radius: 0px;
        }}

        QPushButton#navButton:hover {{
            background-color: {cls.BG_CARD_HOVER};
            color: {cls.TEXT_PRIMARY};
        }}

        QPushButton#navButton:checked, QPushButton#navButton[active="true"] {{
            background-color: {cls.BG_CARD_ACTIVE};
            color: {cls.CYAN};
            border-left: 3px solid {cls.CYAN};
            font-weight: 600;
        }}

        /* Barra de Cabeçalho Superior */
        QFrame#headerBar {{
            background-color: {cls.BG_SIDEBAR};
            border-bottom: 1px solid {cls.BORDER_DEFAULT};
            padding: 8px 16px;
        }}

        /* Cards do Dashboard e Conteúdo */
        QFrame.card {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER_DEFAULT};
            border-radius: 12px;
            padding: 16px;
        }}

        QFrame.card:hover {{
            border: 1px solid {cls.BORDER_HOVER};
        }}

        /* Barras de Progresso */
        QProgressBar {{
            background-color: #0f131c;
            border: 1px solid {cls.BORDER_DEFAULT};
            border-radius: 4px;
            text-align: center;
            color: {cls.TEXT_PRIMARY};
            font-size: 10px;
            font-weight: bold;
            height: 10px;
        }}

        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 #0084ff, stop:1 {cls.CYAN});
            border-radius: 3px;
        }}

        /* Botões Padrão */
        QPushButton.primaryButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 #0284c7, stop:1 {cls.CYAN});
            color: #090d16;
            font-weight: bold;
            border: none;
            border-radius: 8px;
            padding: 10px 18px;
            font-size: 13px;
        }}

        QPushButton.primaryButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 #38bdf8, stop:1 #67e8f9);
        }}

        QPushButton.primaryButton:pressed {{
            background-color: #0284c7;
        }}

        QPushButton.secondaryButton {{
            background-color: {cls.BG_CARD_HOVER};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER_DEFAULT};
            border-radius: 8px;
            padding: 8px 14px;
            font-size: 12px;
        }}

        QPushButton.secondaryButton:hover {{
            background-color: {cls.BG_CARD_ACTIVE};
            border-color: {cls.BORDER_CYAN};
        }}

        /* Scrollbars Modernas */
        QScrollBar:vertical {{
            background: {cls.BG_DARK};
            width: 8px;
            margin: 0px;
        }}

        QScrollBar::handle:vertical {{
            background: #2b3348;
            min-height: 25px;
            border-radius: 4px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {cls.CYAN};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        /* Tooltip */
        QToolTip {{
            background-color: {cls.BG_SIDEBAR};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER_CYAN};
            border-radius: 6px;
            padding: 6px;
            font-size: 11px;
        }}
        """

