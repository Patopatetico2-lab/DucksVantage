"""
Tokens de Design e Constantes Visuais do Ducksvantage (ui/theme_tokens.py).
Estilo 3 — Vantage Refinado: paleta obsidiana/grafite fosca com destaque azul-aço sóbrio.
Todas as cores utilizam códigos hexadecimais puros para total compatibilidade com QPainter e QSS.
"""


class ThemeTokens:
    # -------------------------------------------------------------------------
    # Superfícies Neutras Foscas (Estilo Obsidiana / Grafite Industrial)
    # -------------------------------------------------------------------------
    BG_APP = "#141517"                 # Fundo principal da janela
    BG_SIDEBAR = "#16171a"             # Barra lateral de navegação
    BG_HEADER = "#181a1d"              # Cabeçalho superior fino
    BG_CARD = "#1c1e22"                # Cartões principais
    BG_CARD_HOVER = "#23262b"          # Superfície secundária / hover
    BG_CARD_ACTIVE = "#222936"         # Item / bloco selecionado
    BG_POPUP = "#202328"               # Diálogos e menus
    BG_OSD = "#181a1e"                 # Fundo do popup OSD flutuante
    BG_SURFACE_DEEP = "#121316"        # Fundos de gráficos e campos de entrada

    # Bordas e Destaque Coeso
    BORDER_DEFAULT = "#2c3037"         # Divisor e contorno padrão 1px
    BORDER_HOVER = "#3d434d"           # Contorno em hover
    BORDER_CYAN = "#60a5fa"            # Alias preservado: Azul-aço refinado
    ACCENT_STEEL = "#60a5fa"           # Azul-aço principal de destaque
    ACCENT_MUTED = "#94a3b8"           # Ardósia suave para séries secundárias

    # Tipografia, Textos e Ícones
    TEXT_WHITE_100 = "#f4f5f7"         # Texto primário
    TEXT_LIGHT_GRAY = "#8f96a3"        # Labels secundários e metadados
    TEXT_WHITE_80 = "#c9ced6"          # Texto intermediário
    TEXT_WHITE_60 = "#8f96a3"          # Subtítulos secundários
    TEXT_WHITE_40 = "#666d7a"          # Textos auxiliares discretos
    ICON_INACTIVE = "#7b8290"          # Cor base de ícones inativos

    # Cores dos Perfis Térmicos (Sóbrias)
    THERMAL_QUIET = "#60a5fa"          # Azul-aço Modo Silencioso
    THERMAL_BALANCED = "#93c5fd"       # Azul claro Modo Equilibrado
    THERMAL_PERFORMANCE = "#ef4444"    # Vermelho discreto Modo Desempenho
    THERMAL_CUSTOM = "#818cf8"         # Índigo suave Modo Custom / Max-Power

    # Cores de Ação e Status
    COLOR_PRIMARY = "#3b82f6"
    COLOR_PRIMARY_HOVER = "#60a5fa"
    COLOR_SUCCESS = "#34d399"
    STATUS_GREEN = "#34d399"
    COLOR_WARNING = "#f59e0b"
    STATUS_WARNING = "#f59e0b"
    COLOR_DANGER = "#ef4444"
    STATUS_DANGER = "#ef4444"
    LEGION_RED = "#ef4444"

    # Gradientes Coesos dos Medidores (Paleta Aço Refinada)
    GRAD_CPU = ("#3b82f6", "#60a5fa")
    GRAD_GPU = ("#60a5fa", "#93c5fd")
    GRAD_RAM = ("#3b82f6", "#60a5fa")
    GRAD_STORAGE = ("#3b82f6", "#60a5fa")
    GRAD_BATTERY = ("#10b981", "#34d399")
    GRAD_BUTTON = ("#2563eb", "#3b82f6")

    # Geometria e Raios de Borda
    RADIUS_CARD = 10
    RADIUS_BUTTON = 6
    RADIUS_TAG = 5
    RADIUS_OSD = 14

    # Tipografia
    FONT_NAME = "Inter"
    FONT_FAMILY = '"Inter", "Noto Sans", "Segoe UI", "Roboto", sans-serif'
    FONT_SIZE_TITLE = 18
    FONT_SIZE_SUBTITLE = 14
    FONT_SIZE_BODY = 12
    FONT_SIZE_SMALL = 10
