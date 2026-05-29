"""
Módulo de gestão de cores para o terminal usando a biblioteca Colorama.
"""

from colorama import Style, Fore, init

# O autoreset=True garante que as cores são limpas automaticamente no final de um print() normal.
# No entanto, como usas o módulo 'logging' nas tuas mensagens, as tags de reset ({OFF}) 
# continuam a ser obrigatórias nas tuas f-strings para evitar que as cores vazem.
init(autoreset=True)

# Cores Principais
RED: str = Fore.RED
BLUE: str = Fore.BLUE
GREEN: str = Fore.GREEN
YELLOW: str = Fore.YELLOW
CYAN: str = Fore.CYAN
MAGENTA: str = Fore.MAGENTA

# Estilos de Texto
DF: str = Style.NORMAL
BG: str = Style.BRIGHT

# Fecho de Cor / Reset
# Correção: O 'OFF' deve ser um RESET_ALL para desligar completamente as cores anteriores,
# em vez de ser apenas um 'DIM' (esbatido).
RESET: str = Style.RESET_ALL
OFF: str = Style.RESET_ALL
