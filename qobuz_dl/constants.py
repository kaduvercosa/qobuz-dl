"""
Constantes globais e formatações padrão para o projeto qobuz-dl.
"""

from typing import Final
from pathlib import Path
import os

# Formatação padrão para nomes de pastas e ficheiros de áudio
DEFAULT_FOLDER: Final[str] = "{release_type}/{album_artist} - {album_title} ({year}) [{format} {bit_depth}]"
DEFAULT_TRACK: Final[str] = "{track_number} - {track_title_base}"
DEFAULT_MULTIPLE_DISC_TRACK: Final[str] = "{disc_number}.{track_number} - {track_title_base}"

# Limite de segurança para o tamanho máximo do caminho do ficheiro.
# Evita erros graves em sistemas operativos com limite de carateres (como o Windows).
OK_MAX_CHARACTER_LENGTH: Final[int] = 180

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "qobuz-dl"