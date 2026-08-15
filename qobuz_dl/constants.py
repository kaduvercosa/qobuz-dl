"""
Constantes globais e formatações padrão para o projeto qobuz-dl.
"""

from typing import Final
from pathlib import Path
import os
import sys
import platform

# Formatação padrão para nomes de pastas e ficheiros de áudio
DEFAULT_FOLDER: Final[str] = "{release_type}/{album_artist} - {album_title} ({year}) [{format} {bit_depth}]"
DEFAULT_TRACK: Final[str] = "{track_number} - {track_title_base}"
DEFAULT_MULTIPLE_DISC_TRACK: Final[str] = "{disc_number}.{track_number} - {track_title_base}"

# Limite de segurança para o tamanho máximo do caminho do ficheiro.
OK_MAX_CHARACTER_LENGTH: Final[int] = 180

# --- Detecção de iOS (a-Shell, Pythonista, iSH, etc.) ---
def _detect_ios() -> bool:
    if sys.platform == "ios":
        return True
    if sys.platform == "darwin":
        if platform.machine().startswith(("iPhone", "iPad", "iPod")):
            return True
        if "PYTHONISTA_ROOT" in os.environ:
            return True
        if "/var/mobile/" in str(Path.home()):
            return True
    return False

IS_IOS: Final[bool] = _detect_ios()

# --- Caminhos base dependentes da plataforma ---
if IS_IOS:
    # No iOS tudo fica em ~/Documents para ser acessível no Files
    _BASE = Path.home() / "Documents"
else:
    _BASE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

CONFIG_PATH: Final[Path] = _BASE / "qobuz-dl"

# Pasta padrão de downloads
DEFAULT_DOWNLOAD_DIR: Final[str] = str(_BASE / "Qobuz Downloads") if IS_IOS else "Qobuz Downloads"