import sys
import difflib
import string
import re
import configparser
import logging
import os
import signal
import aiohttp
from pathlib import Path
from typing import Union

from qobuz_dl.bundle import Bundle
from qobuz_dl.color import GREEN, RED, YELLOW, OFF, CYAN
from qobuz_dl.commands import qobuz_dl_args
from qobuz_dl.core import QobuzDL
from qobuz_dl.downloader import DEFAULT_FOLDER, DEFAULT_TRACK, abort_event
from qobuz_dl.settings import QobuzDLSettings

logging.basicConfig(level=logging.INFO, format="%(message)s")

# ============================================================
# PATH CONFIGURATIONS (Using Pathlib)
# ============================================================
<<<<<<< HEAD
=======
# ============================================================
# PATH CONFIGURATIONS (Using Pathlib)
# ============================================================
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
def ensure_long_path(path: Union[str, Path]) -> str:
    """Garante o prefixo de long path do Windows (\\\\?\\) quando necessário."""
    if os.name != "nt":
        return str(path)
    try:
        abs_path = str(Path(path).expanduser().resolve())
        if not abs_path.startswith("\\\\?\\"):
            return "\\\\?\\" + abs_path
        return abs_path
    except Exception:
        return str(path)

# --- INÍCIO DA DETECÇÃO DE SISTEMA (COM SUPORTE A IOS) ---
import platform

is_ios = sys.platform == "ios"
# Verificação extra para apps de iOS que podem se identificar apenas como "darwin" (macOS)
if not is_ios and sys.platform == "darwin":
    # Checa arquitetura do processador, variáveis de ambiente de apps específicos ou o caminho típico do iOS
    if platform.machine().startswith(("iPhone", "iPad", "iPod")) or "PYTHONISTA_ROOT" in os.environ or "/var/mobile/" in str(Path.home()):
        is_ios = True

if os.name == "nt":
    OS_CONFIG = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
elif is_ios:
    # No iOS (iPhone/iPad), salva na pasta Documents para evitar PermissionError
    OS_CONFIG = Path.home() / "Documents"
else:
    OS_CONFIG = Path(os.environ.get("HOME") or Path.home()) / ".config"
# --- FIM DA DETECÇÃO ---
<<<<<<< HEAD

CONFIG_PATH = OS_CONFIG / "qobuz-dl"
CONFIG_FILE = CONFIG_PATH / "config.ini"
QOBUZ_DB = CONFIG_PATH / "qobuz_dl.db"



=======

CONFIG_PATH = OS_CONFIG / "qobuz-dl"
CONFIG_FILE = CONFIG_PATH / "config.ini"
QOBUZ_DB = CONFIG_PATH / "qobuz_dl.db"



>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
def validate_config_formats(formats_to_check: dict) -> None:
    """
    Scans the configuration format strings for unknown variables to prevent
    silent KeyErrors during the download process. Includes typo suggestions.
    """
    VALID_KEYS = {
        "artist", "album", "album_id", "album_url", "album_title", 
        "album_title_base", "album_artist", "album_genre", "album_composer", 
        "label", "copyright", "upc", "barcode", "release_date", "year", 
        "media_type", "format", "bit_depth", "sampling_rate", "album_version", 
        "version_tag", "disc_count", "track_count", "ExplicitFlag", "explicit", 
        "release_type", "tracktitle", "track_title", "track_title_base", 
        "track_id", "track_artist", "track_composer", "track_number", 
        "isrc", "version", "disc_number"
    }

    has_errors = False
    
    for config_name, format_string in formats_to_check.items():
        if not format_string:
            continue
            
        try:
            parsed_vars = [tup[1] for tup in string.Formatter().parse(str(format_string)) if tup[1] is not None]
            
            for var in parsed_vars:
                base_var = var.split(':')[0].split('!')[0]
                
                if base_var not in VALID_KEYS:
                    print(f"{YELLOW}[!] Config Warning: Unknown variable '{{{base_var}}}' detected in '{config_name}'.{OFF}")
                    
                    similar_keys = difflib.get_close_matches(base_var, VALID_KEYS, n=1, cutoff=0.6)
                    if similar_keys:
                        print(f"    {GREEN}-> Did you mean '{{{similar_keys[0]}}}'?{OFF}")
                    
                    print(f"    {RED}-> This will cause the entire format string to be discarded during download.{OFF}")
                    has_errors = True
                    
        except ValueError as e:
            print(f"{RED}[!] Config Error: Syntax error in '{config_name}' -> {e}{OFF}")
            has_errors = True

    if has_errors:
        print(f"\n{YELLOW}[*] Tip: Please check your config.ini file or your command line arguments and fix any typos before downloading.{OFF}\n")
        sys.exit(1)


def _reset_config(config_file: Path) -> int:
    logging.info(f"\n{GREEN}--- QOBUZ-DL: CONFIGURACAO PADRAO ---{OFF}")
    config = configparser.ConfigParser(interpolation=None)
    config["qobuz"] = {}
    
    try:
        print()
        email = input("Enter your Qobuz email: ")
        if not email: sys.exit(1)
        config["qobuz"]["email"] = email.strip()

        print(f"\n{YELLOW}[!] ATTENTION: Qobuz API blocked direct password login for 3rd party apps.{OFF}")
        print(f"{YELLOW}[!] You must use your browser Auth Token (F12 > Storage > Local Storage > localuser > token).{OFF}\n")
        
        auth_token = input("Paste your browser token here: ")
        if not auth_token: sys.exit(1)

        config["qobuz"]["password"] = ""
        config["qobuz"]["auth_token"] = auth_token.strip()

        print("\nDo you want to automatically download and inject lyrics?")
        print("  1) SIM, BAIXAR LETRAS\n  2) NAO, PULE AS LETRAS")
        fetch_lyrics_opt = input("Escolha (1 or 2): ")
        config["qobuz"]["fetch_lyrics"] = "true" if fetch_lyrics_opt.strip() == "1" else "false"

        target_lang = "PT-BR"
        genius_token = ""
        deepl_api_key = ""

        if config["qobuz"]["fetch_lyrics"] == "true":
            print()
            target_lang_input = input("Target language for DeepL translation (e.g. 'PT-BR', 'EN-US') [default: PT-BR]: ")
            if target_lang_input.strip(): target_lang = target_lang_input.strip().upper()

            print(f"\n{YELLOW}[!] To use DeepL translation, enter your DeepL API Key. Leave blank to disable translation.{OFF}")
            deepl_api_key = input("DeepL API Key: ").strip()

            print(f"\n{YELLOW}[!] To use Genius as a fallback, enter your API Token. Leave blank to only use LRCLIB.{OFF}")
            genius_token = input("Genius API Token: ").strip()

        config["qobuz"]["target_lang"] = target_lang
        config["qobuz"]["deepl_api_key"] = deepl_api_key
        config["qobuz"]["genius_token"] = genius_token

        print("\n--- AI Smart Playlists (Optional) ---")
        print("  1) OpenAI (ChatGPT)\n  2) Google Gemini\n  3) Skip")
        ai_choice = input("Choice (1, 2 or 3) [default: 3]: ").strip()

        config["qobuz"]["ai_provider"] = "openai"
        config["qobuz"]["openai_api_key"] = ""
        config["qobuz"]["gemini_api_key"] = ""

        if ai_choice == "1": config["qobuz"]["openai_api_key"] = input("OpenAI API Key (sk-...): ").strip()
        elif ai_choice == "2": 
            config["qobuz"]["ai_provider"] = "gemini"
            config["qobuz"]["gemini_api_key"] = input("Gemini API Key: ").strip()

        print("\n--- Autonomous Watcher / Webhooks (Optional) ---")
        config["qobuz"]["webhook_url"] = input("Enter your n8n / Make.com Webhook URL (Leave blank to skip): ").strip()

        # --- NOVA SEÇÃO DO RADAR ---
        print("\n--- Radar (New Releases) ---")
        dias_busca = input("Days to search back for new releases (Radar) [default: 7]: ").strip()
        config["qobuz"]["dias_de_busca"] = dias_busca if dias_busca else "7"
        # ---------------------------

        print()
        directory = input(f"Download folder [default: Qobuz Downloads]: ").strip()
        config["qobuz"]["directory"] = directory if directory else "Qobuz Downloads"

        print()
        folder_format = input(f"Folder format [default: {DEFAULT_FOLDER}]: ").strip()
        config["qobuz"]["folder_format"] = folder_format if folder_format else DEFAULT_FOLDER

        print("\nDownload quality:")
        print("  27) 24-Bit / >96 kHz (Hi-Res)\n  7)  24-Bit / <96 kHz (Hi-Res)")
        print("  6)  16-Bit / 44.1 kHz (CD / FLAC)\n  5)  320 kbps (MP3)")
        quality = input("Choice (27, 7, 6, 5) [default: 7]: ").strip()
        config["qobuz"]["default_quality"] = quality if quality else "7"

    except KeyboardInterrupt:
        print("\nWizard aborted.")
        sys.exit(1)

    config["qobuz"].update({
        "default_limit": "500", "no_m3u": "false", "albums_only": "false", 
        "no_fallback": "false", "og_cover": "true", "embed_art": "true", 
        "no_cover": "false", "no_database": "false", "no_lrc_files": "false", 
        "legacy_charmap": "false", "blacklist": "blacklist.txt",
        "track_format": "{track_number} - {track_title}",
        "fallback_folder_format": "{artist} - {album}",
        "smart_discography": "false", "no_album_artist_tag": "false",
        "no_album_title_tag": "false", "no_track_artist_tag": "false",
        "no_track_title_tag": "false", "no_release_date_tag": "false",
        "no_media_type_tag": "false", "no_genre_tag": "false",
        "no_track_number_tag": "false", "no_track_total_tag": "false",
        "no_disc_number_tag": "false", "no_disc_total_tag": "false",
        "no_composer_tag": "false", "no_explicit_tag": "false",
        "no_copyright_tag": "false", "no_label_tag": "false",
        "no_credits": "false", "no_upc_tag": "false", "no_isrc_tag": "false",
        "embedded_art_size": "org", "saved_art_size": "org",
        "multiple_disc_prefix": "CD", "multiple_disc_one_dir": "false",
        "multiple_disc_track_format": "{disc_number}.{track_number} - {track_title}",
        "max_workers": "2", "user_auth_token": ""
    })

    print()
    logging.info(f"{YELLOW}Getting tokens. Please wait...{OFF}")
    bundle = Bundle()
    config["qobuz"]["app_id"] = str(bundle.get_app_id())
    config["qobuz"]["secrets"] = ",".join(bundle.get_secrets().values())

    with open(config_file, "w") as configfile:
        config.write(configfile)
        
    logging.info(f"\n{GREEN}[+] Configuration successfully saved in {config_file}!{OFF}")
    return 0


def _remove_leftovers(directory):
    """Limpa ficheiros temporários .tmp que possam ter ficado em caso de erro."""
    for tmp_file in Path(directory).rglob(".*.tmp"):
        try:
            tmp_file.unlink(missing_ok=True)
        except Exception:
            pass


async def _handle_commands(qobuz, arguments):
    def sigint_handler(sig, frame):
        print(f"\n\n{RED}[!] Download forcibly interrupted by the user.{OFF}")
        print(f"{YELLOW}Securing files and aborting gracefully....{OFF}")
        abort_event.set()
        raise KeyboardInterrupt
        
    signal.signal(signal.SIGINT, sigint_handler)

    try:
        if arguments.command == "dl":
            await qobuz.download_list_of_urls(arguments.SOURCE)
        elif arguments.command in ("sync-playlist", "sp"):
            from qobuz_dl.sync_playlist import sync_playlist
            await sync_playlist(qobuz, arguments.URL, qobuz.directory, auto_confirm=arguments.yes)
        elif arguments.command == "lucky":
            query = " ".join(arguments.QUERY)
            qobuz.lucky_type = arguments.type
            qobuz.lucky_limit = arguments.number
            await qobuz.lucky_mode(query)
        else:
            qobuz.interactive_limit = arguments.limit
            await qobuz.interactive()
    except KeyboardInterrupt:
        pass
    finally:
        _remove_leftovers(qobuz.directory)


def _initial_checks():
    if not CONFIG_PATH.is_dir() or not CONFIG_FILE.is_file():
        CONFIG_PATH.mkdir(parents=True, exist_ok=True)
        _reset_config(CONFIG_FILE)

    if len(sys.argv) < 2:
        sys.exit(qobuz_dl_args().print_help())


async def check_for_updates():
    import datetime
    check_file = CONFIG_PATH / "last_update_check"

    try:
        if check_file.is_file():
            last_check_str = check_file.read_text().strip()
            if datetime.date.fromisoformat(last_check_str) >= datetime.date.today():
                return
    except Exception:
        pass

    try:
        from qobuz_dl import __version__
        url = "https://api.github.com/repos/kaduvercosa/qobuz-dl/releases/latest"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=2) as response:
                response.raise_for_status()
                data = await response.json()
        
        latest_version_str = data.get("tag_name", "").replace("v", "")
        
        def parse_version(v: str):
            return tuple(int(p) for p in re.findall(r'\d+', v)[:3])
        
        if parse_version(latest_version_str) > parse_version(__version__):
            print(f"\n{YELLOW}[*] UPDATE AVAILABLE: Master Edition v{latest_version_str} is out!{OFF}")
            print(f"{YELLOW}    - PyPI: run 'pip install -U qobuz-dl-master'{OFF}")
            print(f"{YELLOW}    - Docker: pull the latest image{OFF}")
            print(f"{YELLOW}    - Standalone: download the new release from GitHub{OFF}\n")

        check_file.write_text(str(datetime.date.today()))
    except Exception:
        pass


async def amain():
    await check_for_updates()

    if len(sys.argv) > 1 and sys.argv[1] == "radar":
        from qobuz_dl.radar import _async_run_radar
        try:
            await _async_run_radar()
        except KeyboardInterrupt:
            print(f"\n\n{RED}[!] Radar manualmente interrompido.. (CTRL+C).{OFF}")
        sys.exit(0)

<<<<<<< HEAD
    # --- INÍCIO DA INTEGRAÇÃO DO OST HUNTER ---
    if len(sys.argv) > 1 and sys.argv[1] in ("ost", "ost_hunter"):
        from qobuz_dl.ost_hunter import amain as _async_run_ost
        try:
            # Passa a busca do usuário (se houver) manipulando o sys.argv temporariamente
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            await _async_run_ost()
        except KeyboardInterrupt:
            print(f"\n\n{RED}[!] Caçador de Trilhas manualmente interrompido.. (CTRL+C).{OFF}")
        sys.exit(0)
    # --- FIM DA INTEGRAÇÃO DO OST HUNTER ---

=======
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        from qobuz_dl.db import get_folder_stats
        _cfg = configparser.ConfigParser(interpolation=None)
        _cfg.read(CONFIG_FILE)
        _sec = "qobuz" if _cfg.has_section("qobuz") else "DEFAULT"
        scan_dir = os.path.expanduser(_cfg.get(_sec, "directory", fallback=None) or _cfg.get(_sec, "default_folder", fallback="Qobuz Downloads"))

        print(f"\n{CYAN}--- QOBUZ-DL MASTER -- LIBRARY STATISTICS ---{OFF}")
        print(f"{YELLOW}Scanning: {scan_dir}{OFF}\n")

        if not Path(scan_dir).is_dir():
            print(f"{RED}[!] Directory not found: {scan_dir}{OFF}")
            print(f"{YELLOW}    Make sure your download folder exists and is correctly set in config.ini{OFF}\n")
            sys.exit(1)

        stats = get_folder_stats(scan_dir)

        if stats['total_tracks'] == 0:
            print(f"{YELLOW}No audio files found. Start downloading to populate your library!{OFF}")
        else:
            size_bytes = stats['total_size_bytes']
            size_str = f"{size_bytes / 1_073_741_824:.2f} GB" if size_bytes >= 1_073_741_824 else f"{size_bytes / 1_048_576:.1f} MB"

            print(f"Total Tracks on Disk:  {GREEN}{stats['total_tracks']}{OFF}")
            print(f"Total Album Folders:   {GREEN}{stats['total_albums']}{OFF}")
            print(f"Total Unique Artists:  {GREEN}{stats['total_artists']}{OFF}")
            print(f"Library Size:          {GREEN}{size_str}{OFF}\n")

            if stats.get('quality_distribution'):
                print(f"{YELLOW}Quality Distribution:{OFF}")
                for q_label, count in sorted(stats['quality_distribution'].items(), reverse=True):
                    print(f"  {q_label}: {count} tracks")
                print()

            if stats.get('top_artists'):
                print(f"{YELLOW}Top Artists:{OFF}")
                for i, (artist, count) in enumerate(stats['top_artists'], 1):
                    print(f"  {i}. {artist} ({count} tracks)")

        print(f"\n{CYAN}--------------------------------------------{OFF}\n")
        sys.exit(0)

    config = configparser.ConfigParser(interpolation=None)
    config.read(CONFIG_FILE)

    try:
        section = "qobuz" if config.has_section("qobuz") else "DEFAULT"
        email = config.get(section, "email")
        token = config.get(section, "auth_token", fallback="")
        password = token if token else config.get(section, "password")
        
        fetch_lyrics = config.getboolean(section, "fetch_lyrics", fallback=False)
        genius_token = config.get(section, "genius_token", fallback=None)
        deepl_api_key = config.get(section, "deepl_api_key", fallback=None)
        target_lang = config.get(section, "target_lang", fallback="PT-BR")
        
        directory_val = config.get(section, "directory", fallback=None)
        if directory_val is not None:
            default_folder = directory_val
        else:
            legacy_val = config.get(section, "default_folder", fallback=None)
            if legacy_val is not None:
                print(f"{YELLOW}[!] Notice: 'default_folder' in config.ini is deprecated. Please rename it to 'directory' for future updates.{OFF}")
                default_folder = legacy_val
            else:
                default_folder = "Qobuz Downloads"

        default_limit = config.get(section, "default_limit")
        default_quality = config.get(section, "default_quality")
        no_lrc_files_config = config.getboolean(section, "no_lrc_files", fallback=False)
        no_credits_config = config.getboolean(section, "no_credits", fallback=False)
        blacklist_config = config.get(section, "blacklist", fallback="blacklist.txt")
        app_id = config.get(section, "app_id")
        secrets = [s.strip() for s in config.get(section, "secrets", fallback="").split(",") if s.strip()]
        
        arguments = qobuz_dl_args(default_quality, default_limit, default_folder).parse_args()
        if getattr(arguments, 'no_lyrics', False): fetch_lyrics = False
            
        force_english = not getattr(arguments, 'native_lang', False)
        no_credits_flag = getattr(arguments, 'no_credits', False) or no_credits_config 
        
    except (configparser.Error, KeyError) as error:
        arguments = qobuz_dl_args().parse_args()
        if not arguments.reset:
            sys.exit(f"{RED}Invalid or corrupted configuration ({error}).\n{OFF}{YELLOW}Run 'python -m qobuz_dl -r' to fix this.{OFF}")

    if arguments.reset:
        sys.exit(_reset_config(CONFIG_FILE))

    if arguments.show_config:
        print(f"Configuration: {CONFIG_FILE}\nDatabase: {QOBUZ_DB}\n---")
        with open(CONFIG_FILE, "r") as f:
            print(f.read())
        sys.exit()

    if arguments.purge:
        try:
            QOBUZ_DB.unlink()
        except FileNotFoundError:
            pass
        sys.exit(f"{GREEN}Database has been purged.{OFF}")

    if getattr(arguments, 'sync_db', None):
        from qobuz_dl.sync import sync_database
        from qobuz_dl.qopy import Client
        sync_client = Client(email, password, app_id, secrets, user_auth_token=token, force_english=force_english)
        sync_dir = ensure_long_path(default_folder if arguments.sync_db == "DEFAULT" else arguments.sync_db)
        
<<<<<<< HEAD
=======
        # [!] Correção Crítica: O sync_database é agora uma função assíncrona!
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
        await sync_database(sync_dir, str(QOBUZ_DB), sync_client)
        
        sys.exit(f"\n{GREEN}Database synchronization finished successfully.{OFF}")

    if arguments.command == "lyrics":
        from qobuz_dl.retro_tagger import inject_lyrics_retroactively
        try:
            await inject_lyrics_retroactively(ensure_long_path(arguments.DIR), genius_token=genius_token, deepl_api_key=deepl_api_key, overwrite=getattr(arguments, 'overwrite', False), target_lang=target_lang)
        except KeyboardInterrupt:
            print(f"\n\n{RED}[!] Operation manually interrupted by the user (CTRL+C).{OFF}\n{YELLOW}Already processed files are safe. Exiting...{OFF}")
        sys.exit(0)

    elif arguments.command in ("fix-lyrics", "fl"):
        from qobuz_dl.retro_tagger import interactive_fix_lyrics
        try:
            await interactive_fix_lyrics(ensure_long_path(arguments.DIR), genius_token=genius_token, deepl_api_key=deepl_api_key, target_lang=target_lang)
        except KeyboardInterrupt:
            print(f"\n\n{RED}[!] Operation manually interrupted by the user (CTRL+C).{OFF}")
        sys.exit(0)

    directory_to_use = ensure_long_path(os.path.expanduser(arguments.directory if hasattr(arguments, 'directory') and arguments.directory else default_folder))
    settings = QobuzDLSettings.from_arguments_configparser(arguments, config)
    settings.legacy_charmap = config.getboolean(section, "legacy_charmap", fallback=False)
    
    validate_config_formats({
        "folder_format": getattr(arguments, 'folder_format', None) or config.get(section, "folder_format", fallback=DEFAULT_FOLDER),
        "track_format": getattr(arguments, 'track_format', None) or config.get(section, "track_format", fallback=DEFAULT_TRACK),
        "fallback_folder_format": config.get(section, "fallback_folder_format", fallback="{artist} - {album}"),
        "multiple_disc_track_format": config.get(section, "multiple_disc_track_format", fallback="{disc_number}.{track_number} - {track_title}")
    })

    qobuz = QobuzDL(
        directory_to_use,
        getattr(arguments, 'quality', None) or default_quality,
        getattr(arguments, 'embed_art', False) or config.getboolean(section, "embed_art", fallback=True),
        ignore_singles_eps=getattr(arguments, 'albums_only', False) or config.getboolean(section, "albums_only", fallback=False),
        no_m3u_for_playlists=getattr(arguments, 'no_m3u', False) or config.getboolean(section, "no_m3u", fallback=False),
        quality_fallback=not getattr(arguments, 'no_fallback', False) or not config.getboolean(section, "no_fallback", fallback=False),
        cover_og_quality=getattr(arguments, 'og_cover', False) or config.getboolean(section, "og_cover", fallback=True),
        no_cover=getattr(arguments, 'no_cover', False) or config.getboolean(section, "no_cover", fallback=False),
        downloads_db=None if config.getboolean(section, "no_database", fallback=False) or getattr(arguments, 'no_db', False) else str(QOBUZ_DB),
        folder_format=getattr(arguments, 'folder_format', None) or config.get(section, "folder_format", fallback=DEFAULT_FOLDER),
        track_format=getattr(arguments, 'track_format', None) or config.get(section, "track_format", fallback=DEFAULT_TRACK),
        smart_discography=getattr(arguments, 'smart_discography', False) or config.getboolean(section, "smart_discography", fallback=False),
        fetch_lyrics=fetch_lyrics,
        no_lrc_files=("--no-lrc-files" in sys.argv) or no_lrc_files_config,
        genius_token=genius_token,
        deepl_api_key=deepl_api_key,
        target_lang=target_lang,
        force_english=force_english,
        no_credits=no_credits_flag,
        settings=settings,
        booklet_only=getattr(arguments, 'booklet_only', False),
        blacklist=getattr(arguments, 'blacklist', None) or blacklist_config,
    )
    
    await qobuz.initialize_client(email, password, app_id, secrets)

    try:
        await _handle_commands(qobuz, arguments)
    finally:
        if hasattr(qobuz, 'client') and qobuz.client:
            await qobuz.client.close()


def main():
    import asyncio
    if len(sys.argv) > 1 and sys.argv[1].lower() == "-r":
        sys.exit(_reset_config(CONFIG_FILE))

    _initial_checks()

    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()