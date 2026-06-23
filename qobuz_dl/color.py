"""
Módulo central de gestão de cores e temas visuais do qobuz-dl-master.
"""
from colorama import init

# Inicializa o colorama para manter a compatibilidade caso execute no Windows
init(autoreset=True)

class Tema:
    """
    =========================================
    🎨 PAINEL CENTRAL DE CORES DO SISTEMA
    =========================================
    """
    # --- 1. FORMATADORES E CORES BÁSICAS ---
    OFF       = "\033[0m"
    BOLD      = "\033[1m"
    TXT_WHITE = "\033[97m"
    TXT_BLACK = "\033[30m"

    CYAN      = "\033[36m"
    GREEN     = "\033[38;2;112;162;136m"  # Verde suave para melhor leitura
    LIGHTGREEN= "\033[38;5;150m"
    YELLOW    = "\033[33m"
    RED       = "\033[38;2;192;0;33m"
    BLUE      = "\033[38;2;100;181;246m"
    PURPLE    = "\033[35m"
    
    # Novos códigos de fundo
    BG_BLUE   = "\033[48;2;104;202;249m\033[1m"
    BG_WHITE  = "\033[47m"

    # --- 2. PALETAS TRUE COLOR (CRACHÁS E DEGRADÊS) --- 
    PAD = 70
    
    # ÁLBUM (Marinho / Noite)
    BG_ALBUM      = "\033[48;2;64;145;108m"    # Fundo do badge "💿 ALBUM" / "💽 EP" (cabeçalho do álbum)
    BG_ALBUM_SEC  = "\033[48;2;116;198;157m"   # Fundo da linha "▶ [01/12] 🎵 Artista - Faixa" de cada faixa do álbum
    TXT_ALBUM     = "\033[38;2;116;198;157m" # Cor de [INFO]/[CAPA]/[ÁUDIO]/[AVISO]/[LETRA]/[FINAL] e da árvore (├──/└──/│) em modo álbum

    # PLAYLIST (roxo/lilás) (OK)
    BG_PLAYLIST   = "\033[48;2;145;99;203m"    # Fundo do badge "📋 PLAYLIST"
    BG_PLAYLIST_SEC = "\033[48;2;177;133;219m" # Fundo da linha de cada faixa dentro de uma playlist
    TXT_PLAYLIST  = "\033[38;2;177;133;219m"   # Cor das siglas/árvore em modo playlist

    # LOTE DE SINGLES (turquesa) (OK)
    BG_LOTE       = "\033[48;2;7;190;184m"  # Fundo do badge "🎵 LOTE DE SINGLES"
    BG_LOTE_SEC   = "\033[48;2;104;216;214m"  # Fundo da linha de cada faixa dentro de um lote de singles
    TXT_LOTE      = "\033[38;2;104;216;214m" # Cor das siglas/árvore em modo lote de singles

    # SINGLE (azul) (OK)
    BG_SINGLE     = "\033[48;2;0;119;182m"    # Fundo do badge "🎵 SINGLE" (download de uma faixa avulsa)
    BG_SINGLE_SEC = "\033[48;2;0;180;216m"  # Fundo da linha "▶ [01/01] 🎵 ..." de um single
    TXT_SINGLE    = "\033[38;2;0;180;216m"  # Cor das siglas/árvore em modo single

    # --- 3. ALIASES SEMÂNTICOS (Mensagens) ---
    TITULO    = BOLD       # Nome do álbum/faixa em destaque nas mensagens de "Concluído"
    SUCESSO   = LIGHTGREEN # "[✔] Finalizado" / "[✔] Faixa Concluída" / "[✔] Lançamento
    AVISO     = YELLOW     # "[AVISO]" de downgrade, "⏳ Aguardando delay", "Pulando (Já existe)"
    ERRO      = RED        # "❌ Descartada", "Erro na API", "CTRL+C Interceptado"
    DETALHES  = ""         # Reservado (sem cor própria atualmente)
    TAG       = BLUE       # Alias genérico de tag azul (compatibilidade)

    # --- 4. PREFIXOS PADRONIZADOS DE SISTEMA ---
    SYS       = f"{BLUE}[SISTEMA]{OFF}  ❯ "
    URL       = f"{BLUE}[URL]{OFF}      ❯ "
    BUSCA     = f"{BLUE}[BUSCA]{OFF}    ❯ "
    TERMO     = f"{BLUE}[TERMO]{OFF}    ❯ "
    TEXTO     = f"{BLUE}[TEXTO]{OFF}    ❯ "
    FILA      = f"{BLUE}[FILA]{OFF}     ❯ "
    ALERTA    = f"{YELLOW}[AVISO]{OFF}  ❯ "
    
    # Prefixos exclusivos dos motores de extração
    MAESTRO   = f"{TXT_LOTE}{BOLD}[MAESTRO]{OFF} ❯ "
    ANIME     = f"{TXT_SINGLE}{BOLD}[ANIME]{OFF}   ❯ "
    OST       = f"{TXT_PLAYLIST}{BOLD}[OST]{OFF}     ❯ "

# -------------------------------------------------------------------
# COMPATIBILIDADE LEGADA (Para cli.py, account_transfer.py, etc.)
# -------------------------------------------------------------------
RED     = Tema.RED
BLUE    = Tema.BLUE
GREEN   = Tema.GREEN
YELLOW  = Tema.YELLOW
CYAN    = Tema.CYAN
MAGENTA = Tema.PURPLE
RESET   = Tema.OFF
OFF     = Tema.OFF