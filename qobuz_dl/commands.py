import argparse
import re  # [!] Necessário para injetar as cores
from typing import Any, Union

from qobuz_dl import __version__
from qobuz_dl.color import GREEN, RESET, CYAN, YELLOW, BLUE

def fun_args(subparsers: argparse._SubParsersAction, default_limit: Union[int, str]) -> argparse.ArgumentParser:
    interactive = subparsers.add_parser(
        "interactive",
        description="Interactively search for tracks and albums.",
        help="interactive mode",
        aliases=["i", "fun"],
        formatter_class=QobuzHelpFormatter, # [!] Aplica cores e alinhamento
        add_help=False,                     # [!] Remove o "optional arguments" padrão
        usage=f"qobuz-dl interactive {BLUE}[options]{RESET}" # [!] Limpa a parede de texto do topo
    )
    
    # Criamos um grupo específico com título amarelo
    grp = interactive.add_argument_group(f'{YELLOW}interactive options{RESET}')
    grp.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="show this help message and exit")
    grp.add_argument(
        "-l", "--limit",
        metavar="int",
        default=default_limit,
        help="limit of search results (default: 20)",
    )
    return interactive


def lucky_args(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    lucky = subparsers.add_parser(
        "lucky",
        description="Download the first <n> albums returned from a Qobuz search.",
        help="lucky mode",
        formatter_class=QobuzHelpFormatter,
        add_help=False,
        usage=f"qobuz-dl lucky {BLUE}<QUERY> [options]{RESET}"
    )
    
    grp = lucky.add_argument_group(f'{YELLOW}lucky options{RESET}')
    grp.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="show this help message and exit")
    grp.add_argument(
        "-t", "--type",
        default="album",
        help="type of items to search (artist, album, track, playlist) (default: album)",
    )
    grp.add_argument(
        "-n", "--number",
        metavar="int",
        default=1,
        help="number of results to download (default: 1)",
    )
    grp.add_argument("QUERY", nargs="+", help="search query")
    return lucky


def dl_args(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    download = subparsers.add_parser(
        "dl",
        description="Download by album/track/artist/label/playlist/last.fm-playlist URL.",
        help="input mode",
        formatter_class=QobuzHelpFormatter,
        add_help=False,
        usage=f"qobuz-dl dl {BLUE}<SOURCE> [options]{RESET}"
    )
    
    grp = download.add_argument_group(f'{YELLOW}download options{RESET}')
    grp.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="show this help message and exit")
    grp.add_argument(
        "SOURCE",
        metavar="SOURCE",
        nargs="+",
        help="one or more URLs (space separated) or a text file",
    )
    grp.add_argument(
        "-b", "--blacklist",
        help="Path to a text file containing keywords to blacklist and skip",
        type=str,
        default=None,
    )
    return download


def lyrics_args(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    lyrics = subparsers.add_parser(
        "lyrics",
        description="Retroactively scan a directory and inject missing lyrics into existing audio files.",
        help="lyrics injection mode",
        formatter_class=QobuzHelpFormatter,
        add_help=False,
        usage=f"qobuz-dl lyrics {BLUE}<DIR> [options]{RESET}"
    )
    
    grp = lyrics.add_argument_group(f'{YELLOW}lyrics options{RESET}')
    grp.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="show this help message and exit")
    grp.add_argument(
        "DIR",
        metavar="DIRECTORY",
        help="The local directory containing the music files to be scanned",
    )
    grp.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite existing lyrics and translations in the files",
    )
    return lyrics


def fix_lyrics_args(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    fix_lyrics = subparsers.add_parser(
        "fix-lyrics",
        aliases=["fl"],
        description="Launch an interactive explorer to manually select and fix desynchronized or wrong lyrics.",
        help="interactive lyrics fixer mode",
        formatter_class=QobuzHelpFormatter,
        add_help=False,
        usage=f"qobuz-dl fix-lyrics {BLUE}[DIR]{RESET}"
    )
    
    grp = fix_lyrics.add_argument_group(f'{YELLOW}fix-lyrics options{RESET}')
    grp.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="show this help message and exit")
    grp.add_argument(
        "DIR",
        metavar="DIRECTORY",
        nargs="?",
        default=".",
        help="The local directory containing the music files (default: current directory)",
    )
    return fix_lyrics


def sync_playlist_args(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    sync_pl = subparsers.add_parser(
        "sync-playlist",
        aliases=["sp"],
        description="Synchronize a local folder with a Qobuz playlist. Downloads missing tracks and removes tracks no longer in the playlist.",
        help="sync a local folder with a Qobuz playlist",
        formatter_class=QobuzHelpFormatter,
        add_help=False,
        usage=f"qobuz-dl sync-playlist {BLUE}<URL> [options]{RESET}"
    )
    
    grp = sync_pl.add_argument_group(f'{YELLOW}sync-playlist options{RESET}')
    grp.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="show this help message and exit")
    grp.add_argument(
        "URL",
        help="Qobuz playlist URL (e.g. https://play.qobuz.com/playlist/12345)",
    )
    grp.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt before deleting/downloading",
    )
    return sync_pl

def add_common_arg(custom_parser: argparse.ArgumentParser, default_folder: str, default_quality: Union[int, str]) -> None:
    """Adiciona os argumentos partilhados por múltiplos comandos."""
    custom_parser.add_argument(
        "-d", "--directory",
        metavar="PATH",
        default=default_folder,
        help=f'directory for downloads (default: "{default_folder}")',
    )
    custom_parser.add_argument(
        "--no-lrc-files",
        dest="lrc_files",
        action="store_false",
        default=argparse.SUPPRESS,
        help="do not save synchronized lyrics to external .lrc files",
    )
    custom_parser.add_argument(
        "-q", "--quality",
        metavar="int",
        type=int,
        default=default_quality,
        choices=[5, 6, 7, 27],
        help=(
            'audio "quality" (5, 6, 7, 27)\n'
            f"[320, LOSSLESS, 24B<=96KHZ, 24B>96KHZ] (default: {default_quality})"
        ),
    )
    custom_parser.add_argument(
        "--albums-only",
        action="store_true",
        help="don't download singles, EPs and VA releases",
    )
    custom_parser.add_argument(
        "--no-m3u",
        action="store_true",
        help="don't create .m3u files when downloading playlists",
    )
    custom_parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="disable quality fallback (skip releases not available in set quality)",
    )
    custom_parser.add_argument(
        "--no-db", action="store_true", help="don't call the database"
    )
    custom_parser.add_argument(
        "-ff", "--folder-format",
        metavar="PATTERN",
        help=(
            'pattern for formatting folder names, e.g "{album_artist} - {album_title} ({year})".\n'
            'available keys: album_id, album_url, album_title, album_artist, album_genre, \n'
            'album_composer, label, copyright, upc, barcode, release_date, year, media_type, \n'
            'format, bit_depth, sampling_rate, album_version, disc_count, track_count.\n'
            'Note: You can use "/" to create subdirectories.'
        ),
    )
    custom_parser.add_argument(
        "-fbff", "--fallback-folder-format",
        metavar="PATTERN", 
        help=(
            'fallback pattern for formatting folder names when the main pattern fails.\n'
            'Uses same keys as --folder-format.'
        ),
    )
    custom_parser.add_argument(
        "-tf", "--track-format",
        metavar="PATTERN",
        help=(
            'pattern for formatting track names. e.g "{track_number} - {track_title}"\n'
            'available keys: album_title, album_title_base, album_artist, track_id, track_artist, \n'
            'track_composer, track_number, isrc, bit_depth, sampling_rate, track_title, \n'
            'version, year, disc_number, release_date.'
        ),
    )
    custom_parser.add_argument(
        "-s", "--smart-discography",
        action="store_true",
        help=(
            "Try to filter out spam-like albums when requesting an artist's discography. "
            "Filters albums not made by requested artist, and deluxe/live/collection albums."
        ),
    )
    
    # --- HUMAN BEHAVIOR DELAY ---
    custom_parser.add_argument(
        "--delay",
        type=int,
        default=0,
        help="Wait a specified number of seconds between track downloads to prevent server bans.",
    )

    # --- NEW COMMANDS FOR ULTIMATE FEATURES ---
    custom_parser.add_argument(
        "--no-lyrics",
        action="store_true",
        help="disable automatic lyrics fetching and injection for this session",
    )
    custom_parser.add_argument(
        "--booklet-only",
        action="store_true",
        help="only download the Digital Booklet and PDF Goodies (skips audio files)",
    )
    custom_parser.add_argument(
        "--native-lang",
        action="store_true",
        help="do not force English; download metadata in the account's native language",
    )
    custom_parser.add_argument(
        "--no-credits",
        action="store_true",
        help="disable the generation of the Digital Booklet.txt (Credits & Review) file",
    )
    custom_parser.add_argument(
        "--with-credits",
        action="store_true",
        help="force the generation of the Digital Booklet.txt (overrides config.ini)",
    )
    custom_parser.add_argument(
        "--multi-tags",
        dest="multi_value_tags",
        action="store_true",
        default=argparse.SUPPRESS,
        help="split comma-separated metadata (genres, artists) into multiple separate tag fields (FLAC only)",
    )

    # Adding tag-related parameters
    tag_group = custom_parser.add_argument_group('tag options')
    tag_group.add_argument("--no-album-artist-tag", action="store_true", help="don't add album artist tag")
    tag_group.add_argument("--no-album-title-tag", action="store_true", help="don't add album title tag")
    tag_group.add_argument("--no-track-artist-tag", action="store_true", help="don't add track artist tag")
    tag_group.add_argument("--no-track-title-tag", action="store_true", help="don't add track title tag")
    tag_group.add_argument("--no-release-date-tag", action="store_true", help="don't add release date tag")
    tag_group.add_argument("--no-media-type-tag", action="store_true", help="don't add media type tag")
    tag_group.add_argument("--no-genre-tag", action="store_true", help="don't add genre tag")
    tag_group.add_argument("--no-track-number-tag", action="store_true", help="don't add track number tag")
    tag_group.add_argument("--no-track-total-tag", action="store_true", help="don't add total tracks tag")
    tag_group.add_argument("--no-disc-number-tag", action="store_true", help="don't add disc number tag")
    tag_group.add_argument("--no-disc-total-tag", action="store_true", help="don't add total discs tag")
    tag_group.add_argument("--no-composer-tag", action="store_true", help="don't add composer tag")
    tag_group.add_argument("--no-explicit-tag", action="store_true", help="don't add explicit advisory tag")
    tag_group.add_argument("--no-copyright-tag", action="store_true", help="don't add copyright tag")
    tag_group.add_argument("--no-label-tag", action="store_true", help="don't add label tag")
    tag_group.add_argument("--no-upc-tag", action="store_true", help="don't add UPC/barcode tag")
    tag_group.add_argument("--no-isrc-tag", action="store_true", help="don't add ISRC tag")

    # Adding artwork-related parameters
    artwork_group = custom_parser.add_argument_group('cover artwork options')
    artwork_group.add_argument("-e", "--embed-art", action="store_true", help="embed cover art into audio files")
    artwork_group.add_argument(
        "--og-cover",
        action="store_true",
        help="download cover art in original quality (Deprecated: use --embedded-art-size and --saved-art-size)",
    )
    artwork_group.add_argument("--no-cover", action="store_true", help="don't download cover art")
    artwork_group.add_argument(
        "--embedded-art-size",
        choices=["50", "100", "150", "300", "600", "max", "org"],
        default="org",
        help="size of embedded artwork (default: org)"
    )
    artwork_group.add_argument(
        "--saved-art-size",
        choices=["50", "100", "150", "300", "600", "max", "org"],
        default="org",
        help="size of saved artwork (default: org)"
    )

    # Adding multiple disc options
    multiple_disc_group = custom_parser.add_argument_group('multiple disc options')
    multiple_disc_group.add_argument(
        "--multiple-disc-prefix",
        default="CD",
        metavar="PREFIX",
        help="Setting folder prefix for multiple discs album (default: CD)"
    )
    multiple_disc_group.add_argument(
        "--multiple-disc-one-dir",
        action="store_true",
        help="store multiple disc releases in one directory",
    )
    multiple_disc_group.add_argument(
        "--multiple-disc-track-format",
        metavar="FORMAT",
        help='track format for multiple disc releases (default: "{disc_number}.{track_number} - {track_title}")',
    )

    # Add parallel download thread count argument group
    parallel_group = custom_parser.add_argument_group('parallel download options')
    parallel_group.add_argument(
        "--max-workers",
        type=int,
        metavar="N",
        help="maximum number of parallel downloads (default: 3)",
    )
    
class QobuzHelpFormatter(argparse.RawTextHelpFormatter):
    """Custom formatter para corrigir alinhamento e injetar cores nos comandos nativamente."""
    
    def __init__(self, prog, indent_increment=2, max_help_position=45, width=None):
        # O max_help_position=45 é o que impede o "interactive (i, fun)" de quebrar a linha!
        super().__init__(prog, indent_increment, max_help_position, width)

    def _format_action(self, action):
        # 1. O argparse calcula as strings sem cor para não estragar a contagem de caracteres
        result = super()._format_action(action)
        
        # 2. Regex para fatiar a string gerada em 4 partes:
        # Grupo 1: (\s+)    -> A margem esquerda (espaços iniciais)
        # Grupo 2: (.*?)    -> O nome do comando ou argumento (ex: "-h, --help" ou "dl")
        # Grupo 3: (\s{2,}) -> Os 2 ou mais espaços que separam o comando da descrição
        # Grupo 4: (.*)     -> O texto de ajuda (descrição)
        match = re.match(r'^(\s+)(.*?)(\s{2,})(.*)', result, flags=re.DOTALL)
        
        if match:
            indent = match.group(1)      
            invocation = match.group(2)  
            padding = match.group(3)     
            help_text = match.group(4)   
            
            # Se a coluna do comando não estiver vazia, injetamos o CYAN nela!
            if invocation.strip():
                result = f"{indent}{BLUE}{invocation}{RESET}{padding}{help_text}"
                
        return result

def qobuz_dl_args(default_quality: Union[int, str] = 6, default_limit: Union[int, str] = 20, default_folder: str = "QobuzDownloads") -> argparse.ArgumentParser:
    
    # [!] Definimos o usage manualmente para limpar o topo e podermos tirar o metavar
    custom_usage = f"qobuz-dl [-h] [-r] [-p] [--sync-db [PATH]] [-sc] {BLUE}<command>{RESET} ..."
    
    parser = argparse.ArgumentParser(
        prog="qobuz-dl",
        usage=custom_usage,
        description=(
            f"{GREEN}  \t\t\t\t[VERSÃO {__version__}] \n\n{RESET}"
            f'''{BLUE}\t       /$$$$$$   /$$$$$$  /$$$$$$$  /$$   /$$ /$$$$$$$$       /$$$$$$$  /$$      
              / $$__ $$ /$$__  $$| $$__  $$| $$  | $$|_____/$$/      | $$__  $$| $$      
              | $$  \ $| $$  \ $$| $$  \ $$| $$  | $$   /  $$/       | $$  \ $$| $$      
              | $$  | $| $$  | $$| $$$$$$$ | $$  | $$  /  $$/        | $$  | $$| $$      
              | $$  | $| $$  | $$| $$__  $$| $$  | $$ /  $$/    ===  | $$  | $$| $$      
              | $$/$$ $| $$  | $$| $$  \ $$| $$  | $$|  $$/          | $$  | $$| $$      
              |  $$$$$$|  $$$$$$/| $$$$$$$/|  $$$$$$/|_$$$$$$$$      | $$$$$$$/| $$$$$$$$
               \____ $$$ \______/ |_______/  \______/|________/      |_______/ |________/
                    \_$$                             {RESET}'''),
        formatter_class=QobuzHelpFormatter, # [!] Chamando nosso formatter colorido!
        add_help=False
    )
    
    # --- GLOBAL OPTIONS ---
    global_group = parser.add_argument_group(f'{YELLOW}global options{RESET}') # Título amarelo
    global_group.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="show this help message and exit")
    global_group.add_argument("-r", "--reset", action="store_true", help="create/reset config file")
    global_group.add_argument("-p", "--purge", action="store_true", help="purge/delete downloaded-IDs database")
    global_group.add_argument(
        "--sync-db",
        metavar="PATH",
        nargs="?",
        const="DEFAULT",
        help="scan local directory to restore missing Qobuz IDs into the database",
    )
    global_group.add_argument("-sc", "--show-config", action="store_true", help="show configuration")

    # --- COMMANDS ---
    subparsers = parser.add_subparsers(
        title=f"{YELLOW}commands{RESET}", # Título amarelo
        description="run qobuz-dl <command> --help for more info (e.g. qobuz-dl dl --help)",
        dest="command",
        
    )
    
    interactive = fun_args(subparsers, default_limit)
    download = dl_args(subparsers)
    lucky = lucky_args(subparsers)
    lyrics_cmd = lyrics_args(subparsers)
    fix_lyrics_cmd = fix_lyrics_args(subparsers)
    sync_pl_cmd = sync_playlist_args(subparsers)
    

    # Comandos "Standalone" (Interceptados pelo sys.argv antes do argparse)

    subparsers.add_parser(
        "radar",
        description="Autonomous radar to fetch and download new releases based on config.",
        help="scan and download new releases (radar mode)"
    )

    subparsers.add_parser(
        "ost_hunter",
        aliases=["ost"],
        description="Search and selectively download Soundtrack Albums or generate OST playlists.",
        help="hunt and collect movie/anime soundtracks (ost mode)"
    )

    subparsers.add_parser(
        "stats",
        description="Generate and display detailed statistics of your local downloaded library.",
        help="show local library statistics and analytics"
    )

    subparsers.add_parser(
        "transfer",
        aliases=["tr"],
        description="Transfer favorites (albums, artists, tracks, playlists) between two Qobuz accounts.",
        help="transfer favorites between Qobuz accounts (transfer mode)"
    )

    for cmd in (interactive, download, lucky, sync_pl_cmd):
        add_common_arg(cmd, default_folder, default_quality)

    return parser