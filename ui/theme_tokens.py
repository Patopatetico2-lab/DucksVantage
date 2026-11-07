"""
Tokens de Design e Constantes Visuais do Ducksvantage (ui/theme_tokens.py).
Compilado a partir da engenharia reversa dos arquivos SCSS/CSS do Lenovo Vantage
(VAN-11517, app.theme.scss, widget-legion-edge.component.scss).
Todas as cores utilizam códigos hexadecimais puros para total compatibilidade com QPainter e QSS.
"""


class ThemeTokens:
    # -------------------------------------------------------------------------
    # Paleta de Cores Hexadecimal Oficial (Lenovo Vantage / Legion Zone)
    # -------------------------------------------------------------------------
    BG_APP = "#11192c"                 # Fundo principal ($gaming_bg, VAN-11517)
    BG_SIDEBAR = "#151f36"             # Sidebar ($gaming_rightbg)
    BG_HEADER = "#151f36"              # Cabeçalho superior
    BG_CARD = "#1f2a42"                # Fundo dos cartões ($gaming_darkest / $darkCell)
    BG_CARD_HOVER = "#253048"          # Hover em cartões ($gaming_darker)
    BG_CARD_ACTIVE = "#293c4f"         # Estado selecionado ($gaming_dark)
    BG_POPUP = "#293757"               # Fundo de diálogos e modais ($darkPopup)
    BG_OSD = "#1a1e29"                 # Fundo do popup OSD translúcido

    # Bordas e Divisores
    BORDER_DEFAULT = "#30415a"         # $gaming-slate-blue
    BORDER_HOVER = "#425067"           # $gaming_blue_grey_light
    BORDER_CYAN = "#00d2ff"            # Destaque Ciano Elétrico

    # Tipografia, Textos e Ícones (Hex puros compatíveis com QColor e QSS)
    TEXT_WHITE_100 = "#fbfdff"         # Texto primário branco puro
    TEXT_LIGHT_GRAY = "#cbd5e1"        # Títulos de gauges e subtítulos claros (#cbd5e1)
    TEXT_WHITE_80 = "#cbd5e1"          # Subtítulos primários (#cbd5e1)
    TEXT_WHITE_60 = "#cbd5e1"          # Subtítulos secundários (#cbd5e1)
    TEXT_WHITE_40 = "#8b949e"          # Textos auxiliares e legendas discretas (#8b949e)
    ICON_INACTIVE = "#8b949e"          # Cor de ícones inativos (#8b949e)

    # Cores dos Perfis Térmicos Oficiais (Thermal Modes)
    THERMAL_QUIET = "#00d2ff"          # Azul Modo Silencioso (#00d2ff)
    THERMAL_BALANCED = "#2ec5eb"       # Branco/Ciano Modo Equilibrado (#2ec5eb)
    THERMAL_PERFORMANCE = "#ff3b30"    # Vermelho Legion Modo Desempenho (#ff3b30)
    THERMAL_CUSTOM = "#9e3dff"         # Roxo Neon Modo Custom / Max-Power

    # Cores de Ação e Status
    COLOR_PRIMARY = "#0160d6"          # $btn_primary_color
    COLOR_PRIMARY_HOVER = "#257eff"    # $btn_secondary_color
    COLOR_SUCCESS = "#2cd283"          # $go
    STATUS_GREEN = "#2cd283"           # Alias verde neon de status
    COLOR_WARNING = "#ffb703"          # Âmbar
    STATUS_WARNING = "#ffb703"
    COLOR_DANGER = "#ff3b30"           # Vermelho Alerta
    STATUS_DANGER = "#ff3b30"
    LEGION_RED = "#ff3b30"             # Vermelho Legion Oficial

    # Gradientes de Hardware (Início, Fim)
    GRAD_CPU = ("#2D58DE", "#00FAF3")     # Anel da CPU (Azul -> Ciano)
    GRAD_GPU = ("#FF9F00", "#FF2815")     # Anel da GPU (Laranja -> Vermelho)
    GRAD_RAM = ("#7800BF", "#FF2AE8")     # Anel da RAM (Roxo -> Magenta Neon)
    GRAD_STORAGE = ("#0ea5e9", "#2cd283") # Armazenamento (Azul -> Verde)
    GRAD_BATTERY = ("#2fcc74", "#33dfa6") # Carga da Bateria (Verde)
    GRAD_BUTTON = ("#2e62d9", "#4980fc")  # Botão Primário

    # Geometria e Raios de Borda
    RADIUS_CARD = 9                    # $border_radius = 0.9rem
    RADIUS_BUTTON = 6                  # $border_radius_sm = 0.6rem
    RADIUS_TAG = 4
    RADIUS_OSD = 16                    # Cantos arredondados do pop-up OSD

    # Tipografia
    FONT_FAMILY = '"Segoe UI", "Inter", "Roboto", "Noto Sans", sans-serif'
    FONT_SIZE_TITLE = 18
    FONT_SIZE_SUBTITLE = 14
    FONT_SIZE_BODY = 12
    FONT_SIZE_SMALL = 10
