import sys
import difflib
import string
import re
import configparser
import logging
import glob
import os
import getpass
import hashlib
import signal
import aiohttp

from qobuz_dl.bundle import Bundle
from qobuz_dl.color import GREEN, RED, YELLOW, OFF, CYAN
from qobuz_dl.commands import qobuz_dl_args
from qobuz_dl.core import QobuzDL
from qobuz_dl.downloader import DEFAULT_FOLDER, DEFAULT_TRACK
from qobuz_dl.settings import QobuzDLSettings
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)

# ============================================================
# HELPER: Windows Long Path Support (evita duplicação)
# ============================================================
def ensure_long_path(path: str) -> str:
    # """Garante o prefixo de long path do Windows (\\\\?\\) quando necessário."""
    if os.name != "nt":
        return path
    try:
        abs_path = os.path.abspath(os.path.expanduser(path))
        if not abs_path.startswith("\\\\?\\"):
            return "\\\\?\\" + abs_path
        return abs_path
    except Exception:
        return path


if os.name == "nt":
    OS_CONFIG = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
else:
    home = os.environ.get("HOME") or str(Path.home())
    OS_CONFIG = os.path.join(home, ".config")

CONFIG_PATH = os.path.join(OS_CONFIG, "qobuz-dl")
CONFIG_FILE = os.path.join(CONFIG_PATH, "config.ini")
QOBUZ_DB = os.path.join(CONFIG_PATH, "qobuz_dl.db")


def validate_config_formats(formats_to_check):
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
    
    C_RED = '\033[91m'
    C_YEL = '\033[93m'
    C_GRE = '\033[92m'
    C_OFF = '\033[0m'

    for config_name, format_string in formats_to_check.items():
        if not format_string:
            continue
            
        try:
            parsed_vars = [tup[1] for tup in string.Formatter().parse(str(format_string)) if tup[1] is not None]
            
            for var in parsed_vars:
                base_var = var.split(':')[0].split('!')[0]
                
                if base_var not in VALID_KEYS:
                    print(f"{C_YEL}[!] Config Warning: Unknown variable '{{{base_var}}}' detected in '{config_name}'.{C_OFF}")
                    
                    similar_keys = difflib.get_close_matches(base_var, VALID_KEYS, n=1, cutoff=0.6)
                    if similar_keys:
                        print(f"    {C_GRE}-> Did you mean '{{{similar_keys[0]}}}'?{C_OFF}")
                    
                    print(f"    {C_RED}-> This will cause the entire format string to be discarded during download.{C_OFF}")
                    has_errors = True
                    
        except ValueError as e:
            print(f"{C_RED}[!] Config Error: Syntax error in '{config_name}' -> {e}{C_OFF}")
            has_errors = True

    if has_errors:
        print(f"\n{C_YEL}[*] Tip: Please check your config.ini file or your command line arguments and fix any typos before downloading.{C_OFF}\n")
        sys.exit(1)


def _reset_config(config_file):
    logging.info(f"\n{YELLOW}--- QOBUZ-DL CONFIGURATION WIZARD (2026 Update) ---{OFF}")
    config = configparser.ConfigParser(interpolation=None)
    
    config["qobuz"] = {}
    
    try:
        print()
        email = input("Enter your Qobuz email: ")
        if not email: sys.exit(1)
        config["qobuz"]["email"] = email.strip()

        print(f"\n{YELLOW}[!] ATTENTION: Qobuz API blocked direct password login for 3rd party apps.{OFF}")
        print(f"{YELLOW}[!] You must use your browser Auth Token (F12 > Storage > Local Storage > localuser > token).{OFF}")
        print()
        auth_token = input("Paste your browser token here: ")
        if not auth_token: sys.exit(1)

        config["qobuz"]["password"] = ""
        config["qobuz"]["auth_token"] = auth_token.strip()

        print("\nDo you want to automatically download and inject lyrics?")
        print("  1) Yes, download lyrics")
        print("  2) No, skip lyrics")
        fetch_lyrics_opt = input("Choice (1 or 2): ")
        config["qobuz"]["fetch_lyrics"] = "true" if fetch_lyrics_opt.strip() == "1" else "false"

        target_lang = "PT-BR"
        genius_token = ""
        deepl_api_key = ""

        if config["qobuz"]["fetch_lyrics"] == "true":
            print()
            target_lang_input = input("Target language for DeepL translation (e.g. 'PT-BR', 'EN-US') [default: PT-BR]: ")
            if target_lang_input.strip():
                target_lang = target_lang_input.strip().upper()

            print(f"\n{YELLOW}[!] To use DeepL translation, enter your DeepL API Key. Leave blank to disable translation.{OFF}")
            deepl_input = input("DeepL API Key: ")
            deepl_api_key = deepl_input.strip()

            print(f"\n{YELLOW}[!] To use Genius as a fallback for missing lyrics, enter your API Token. Leave blank to only use LRCLIB.{OFF}")
            genius_token_input = input("Genius API Token: ")
            genius_token = genius_token_input.strip()

        config["qobuz"]["target_lang"] = target_lang
        config["qobuz"]["deepl_api_key"] = deepl_api_key
        config["qobuz"]["genius_token"] = genius_token

        print("\n--- AI Smart Playlists (Optional) ---")
        print("To generate AI-curated .m3u playlists, you can provide an API key.")
        print("  1) OpenAI (ChatGPT)")
        print("  2) Google Gemini")
        print("  3) Skip")
        ai_choice = input("Choice (1, 2 or 3) [default: 3]: ")

        config["qobuz"]["ai_provider"] = "openai"
        config["qobuz"]["openai_api_key"] = ""
        config["qobuz"]["gemini_api_key"] = ""

        if ai_choice.strip() == "1":
            config["qobuz"]["ai_provider"] = "openai"
            config["qobuz"]["openai_api_key"] = input("OpenAI API Key (sk-...): ").strip()
        elif ai_choice.strip() == "2":
            config["qobuz"]["ai_provider"] = "gemini"
            config["qobuz"]["gemini_api_key"] = input("Gemini API Key: ").strip()

        print("\n--- Autonomous Watcher / Webhooks (Optional) ---")
        print("To receive real-time notifications about new releases from your favorite artists.")
        webhook_url = input("Enter your n8n / Make.com Webhook URL (Leave blank to skip): ").strip()
        config["qobuz"]["webhook_url"] = webhook_url

        print()
        directory = input(f"Download folder [default: Qobuz Downloads]: ")
        if not directory.strip(): directory = "Qobuz Downloads"
        config["qobuz"]["directory"] = directory.strip()

        print()
        folder_format = input(f"Folder format [default: {DEFAULT_FOLDER}]: ")
        if not folder_format.strip(): folder_format = DEFAULT_FOLDER
        config["qobuz"]["folder_format"] = folder_format.strip()

        print("\nDownload quality:")
        print("  27) 24-Bit / >96 kHz (Hi-Res)")
        print("  7)  24-Bit / <96 kHz (Hi-Res)")
        print("  6)  16-Bit / 44.1 kHz (CD / FLAC)")
        print("  5)  320 kbps (MP3)")
        quality = input("Choice (27, 7, 6, 5) [default: 7]: ")
        if not quality.strip(): quality = "7"
        config["qobuz"]["default_quality"] = quality.strip()

    except KeyboardInterrupt:
        print("\nWizard aborted.")
        sys.exit(1)

    config["qobuz"]["default_limit"] = "500"
    config["qobuz"]["no_m3u"] = "false"
    config["qobuz"]["albums_only"] = "false"
    config["qobuz"]["no_fallback"] = "false"
    config["qobuz"]["og_cover"] = "true"
    config["qobuz"]["embed_art"] = "true"
    config["qobuz"]["no_cover"] = "false"
    config["qobuz"]["no_database"] = "false"
    config["qobuz"]["no_lrc_files"] = "false"
    config["qobuz"]["legacy_charmap"] = "false"
    config["qobuz"]["blacklist"] = "blacklist.txt"

    print()
    logging.info(f"{YELLOW}Getting tokens. Please wait...{OFF}")
    bundle = Bundle()
    config["qobuz"]["app_id"] = str(bundle.get_app_id())
    config["qobuz"]["secrets"] = ",".join(bundle.get_secrets().values())

    config["qobuz"]["track_format"] = "{track_number} - {track_title}"
    config["qobuz"]["fallback_folder_format"] = "{artist} - {album}"
    config["qobuz"]["smart_discography"] = "false"

    config["qobuz"]["no_album_artist_tag"] = "false"
    config["qobuz"]["no_album_title_tag"] = "false"
    config["qobuz"]["no_track_artist_tag"] = "false"
    config["qobuz"]["no_track_title_tag"] = "false"
    config["qobuz"]["no_release_date_tag"] = "false"
    config["qobuz"]["no_media_type_tag"] = "false"
    config["qobuz"]["no_genre_tag"] = "false"
    config["qobuz"]["no_track_number_tag"] = "false"
    config["qobuz"]["no_track_total_tag"] = "false"
    config["qobuz"]["no_disc_number_tag"] = "false"
    config["qobuz"]["no_disc_total_tag"] = "false"
    config["qobuz"]["no_composer_tag"] = "false"
    
    config["qobuz"]["no_explicit_tag"] = "false"
    config["qobuz"]["no_copyright_tag"] = "false"
    config["qobuz"]["no_label_tag"] = "false"
    
    config["qobuz"]["no_credits"] = "false"
    
    config["qobuz"]["no_upc_tag"] = "false"
    config["qobuz"]["no_isrc_tag"] = "false"
          
    config["qobuz"]["embedded_art_size"] = "org"
    config["qobuz"]["saved_art_size"] = "org"
    
    config["qobuz"]["multiple_disc_prefix"] = "CD"
    config["qobuz"]["multiple_disc_one_dir"] = "false"
    config["qobuz"]["multiple_disc_track_format"] = "{disc_number}.{track_number} - {track_title}"
    
    config["qobuz"]["max_workers"] = "3"
    config["qobuz"]["user_auth_token"] = ""
    
    with open(config_file, "w") as configfile:
        config.write(configfile)
        
    logging.info(f"\n{GREEN}[+] Configuration successfully saved in {config_file}!{OFF}")
    

def _remove_leftovers(directory):
    directory = os.path.join(directory, "**", ".*.tmp")
    for i in glob.glob(directory, recursive=True):
        try:
            os.remove(i)
        except:
            pass


async def _handle_commands(qobuz, arguments):
    def sigint_handler(sig, frame):
        print(f"\n\n\033[91m[!] Download forcibly interrupted by the user.\033[0m")
        print(f"\033[93mPartially downloaded files will be ignored or overwritten on the next run.\033[0m")
        try:
            _remove_leftovers(qobuz.directory)
        except Exception:
            pass
        sys.exit(1)
        
    signal.signal(signal.SIGINT, sigint_handler)

    try:
        if arguments.command == "dl":
            await qobuz.download_list_of_urls(arguments.SOURCE)
        elif arguments.command in ("sync-playlist", "sp"):
            from qobuz_dl.sync_playlist import sync_playlist
            await sync_playlist(
                qobuz,
                arguments.URL,
                qobuz.directory,
                auto_confirm=arguments.yes,
            )
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
    if not os.path.isdir(CONFIG_PATH) or not os.path.isfile(CONFIG_FILE):
        os.makedirs(CONFIG_PATH, exist_ok=True)
        _reset_config(CONFIG_FILE)

    if len(sys.argv) < 2:
        sys.exit(qobuz_dl_args().print_help())


async def check_for_updates():
    import datetime

    check_file = os.path.join(CONFIG_PATH, "last_update_check")

    try:
        with open(check_file, "r") as f:
            last_check_str = f.read().strip()
        last_check = datetime.date.fromisoformat(last_check_str)
        if last_check >= datetime.date.today():
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
        current_version_str = __version__
        
        def parse_version(v: str):
            parts = re.findall(r'\d+', v)
            return tuple(int(p) for p in parts[:3])
        
        latest_tuple = parse_version(latest_version_str)
        current_tuple = parse_version(current_version_str)
        
        if latest_tuple > current_tuple:
            print(f"\n{YELLOW}[*] UPDATE AVAILABLE: Master Edition v{latest_version_str} is out!{OFF}")
            print(f"{YELLOW}    - PyPI: run 'pip install -U qobuz-dl-master'{OFF}")
            print(f"{YELLOW}    - Docker: pull the latest image{OFF}")
            print(f"{YELLOW}    - Standalone: download the new release from GitHub{OFF}\n")

        try:
            with open(check_file, "w") as f:
                f.write(str(datetime.date.today()))
        except Exception:
            pass
            
    except Exception:
        pass


async def amain():
    await check_for_updates()

    if len(sys.argv) > 1 and sys.argv[1] == "radar":
        from qobuz_dl.radar import run_radar
        try:
            run_radar()
        except KeyboardInterrupt:
            print("\n\n\033[91m[!] Radar manually interrupted by the user (CTRL+C).\033[0m")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        from qobuz_dl.db import get_folder_stats

        _cfg = configparser.ConfigParser(interpolation=None)
        _cfg.read(CONFIG_FILE)
        _sec = "qobuz" if _cfg.has_section("qobuz") else "DEFAULT"
        scan_dir = os.path.expanduser(
            _cfg.get(_sec, "directory", fallback=None)
            or _cfg.get(_sec, "default_folder", fallback="Qobuz Downloads")
        )

        print(f"\n{CYAN}--- QOBUZ-DL MASTER — LIBRARY STATISTICS ---{OFF}")
        print(f"{YELLOW}Scanning: {scan_dir}{OFF}\n")

        if not os.path.isdir(scan_dir):
            print(f"{RED}[!] Directory not found: {scan_dir}{OFF}")
            print(f"{YELLOW}    Make sure your download folder exists and is correctly set in config.ini{OFF}\n")
            sys.exit(1)

        stats = get_folder_stats(scan_dir)

        if stats['total_tracks'] == 0:
            print(f"{YELLOW}No audio files found. Start downloading to populate your library!{OFF}")
        else:
            size_bytes = stats['total_size_bytes']
            if size_bytes >= 1_073_741_824:
                size_str = f"{size_bytes / 1_073_741_824:.2f} GB"
            else:
                size_str = f"{size_bytes / 1_048_576:.1f} MB"

            print(f"Total Tracks on Disk:  {GREEN}{stats['total_tracks']}{OFF}")
            print(f"Total Album Folders:   {GREEN}{stats['total_albums']}{OFF}")
            print(f"Total Unique Artists:  {GREEN}{stats['total_artists']}{OFF}")
            print(f"Library Size:          {GREEN}{size_str}{OFF}\n")

            quality_dist = stats.get('quality_distribution', {})
            if quality_dist:
                print(f"{YELLOW}Quality Distribution:{OFF}")
                for q_label, count in sorted(quality_dist.items(), reverse=True):
                    print(f"  {q_label}: {count} tracks")
                print()

            top_artists = stats.get('top_artists', [])
            if top_artists:
                print(f"{YELLOW}Top Artists:{OFF}")
                for i, (artist, count) in enumerate(top_artists, 1):
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
                print(f"\033[93m[!] Notice: 'default_folder' in config.ini is deprecated. Please rename it to 'directory' for future updates.\033[0m")
                default_folder = legacy_val
            else:
                default_folder = "Qobuz Downloads"

        default_limit = config.get(section, "default_limit")
        default_quality = config.get(section, "default_quality")
        
        no_m3u = config.getboolean(section, "no_m3u", fallback=False)
        no_lrc_files_config = config.getboolean(section, "no_lrc_files", fallback=False)
        albums_only = config.getboolean(section, "albums_only", fallback=False)
        no_fallback = config.getboolean(section, "no_fallback", fallback=False)
        og_cover = config.getboolean(section, "og_cover", fallback=True)
        embed_art = config.getboolean(section, "embed_art", fallback=True)
        no_cover = config.getboolean(section, "no_cover", fallback=False)
        no_database = config.getboolean(section, "no_database", fallback=False)
        legacy_charmap = config.getboolean(section, "legacy_charmap", fallback=False)
        
        no_credits_config = config.getboolean(section, "no_credits", fallback=False)
        blacklist_config = config.get(section, "blacklist", fallback="blacklist.txt")
        
        app_id = config.get(section, "app_id")
        secrets_raw = config.get(section, "secrets", fallback="")
        secrets = [s.strip() for s in secrets_raw.split(",") if s.strip()]
        
        smart_discography = config.getboolean(section, "smart_discography", fallback=False)
        folder_format = config.get(section, "folder_format", fallback=DEFAULT_FOLDER)
        track_format = config.get(section, "track_format", fallback=DEFAULT_TRACK)

        arguments = qobuz_dl_args(
            default_quality, default_limit, default_folder
        ).parse_args()
        
        if getattr(arguments, 'no_lyrics', False):
            fetch_lyrics = False
            
        force_english = not getattr(arguments, 'native_lang', False)
        no_credits_flag = getattr(arguments, 'no_credits', False) or no_credits_config 
        
    except (configparser.Error, KeyError) as error:
        arguments = qobuz_dl_args().parse_args()
        if not arguments.reset:
            RED_C = '\033[91m'
            YELLOW_C = '\033[93m'
            OFF_C = '\033[0m'
            sys.exit(
                f"{RED_C}Invalid or corrupted configuration ({error}).\n{OFF_C}"
                f"{YELLOW_C}Run 'python -m qobuz_dl -r' to fix this.{OFF_C}"
            )

    if arguments.reset:
        sys.exit(_reset_config(CONFIG_FILE))

    if arguments.show_config:
        print(f"Configuration: {CONFIG_FILE}\nDatabase: {QOBUZ_DB}\n---")
        with open(CONFIG_FILE, "r") as f:
            print(f.read())
        sys.exit()

    if arguments.purge:
        try:
            os.remove(QOBUZ_DB)
        except FileNotFoundError:
            pass
        sys.exit(f"{GREEN}Database has been purged.{OFF}")

    if getattr(arguments, 'sync_db', None):
        from qobuz_dl.sync import sync_database
        from qobuz_dl.qopy import Client
                
        sync_client = Client(email, password, app_id, secrets, user_auth_token=token, force_english=force_english)
        
        sync_dir = default_folder if arguments.sync_db == "DEFAULT" else arguments.sync_db
        sync_dir = ensure_long_path(sync_dir)
                
        sync_database(sync_dir, QOBUZ_DB, sync_client)
        sys.exit(f"\n{GREEN}Database synchronization finished successfully.{OFF}")

    if arguments.command == "lyrics":
        from qobuz_dl.retro_tagger import inject_lyrics_retroactively
        
        target_dir = arguments.DIR
        target_dir = ensure_long_path(target_dir)
        
        try:
            overwrite_flag = getattr(arguments, 'overwrite', False)
            await inject_lyrics_retroactively(target_dir, genius_token=genius_token, deepl_api_key=deepl_api_key, overwrite=overwrite_flag, target_lang=target_lang)
        except KeyboardInterrupt:
            print("\n\n\033[91m[!] Operation manually interrupted by the user (CTRL+C).\033[0m")
            print("\033[93mAlready processed files are safe. Exiting...\033[0m")
        sys.exit(0)

    elif arguments.command in ("fix-lyrics", "fl"):
        from qobuz_dl.retro_tagger import interactive_fix_lyrics

        target_dir = arguments.DIR
        target_dir = ensure_long_path(target_dir)

        try:
            await interactive_fix_lyrics(target_dir, genius_token=genius_token, deepl_api_key=deepl_api_key, target_lang=target_lang)
        except KeyboardInterrupt:
            print("\n\n\033[91m[!] Operation manually interrupted by the user (CTRL+C).\033[0m")
        sys.exit(0)

    directory_to_use = arguments.directory if hasattr(arguments, 'directory') and arguments.directory else default_folder
    directory_to_use = os.path.expanduser(directory_to_use)
    directory_to_use = ensure_long_path(directory_to_use)

    settings = QobuzDLSettings.from_arguments_configparser(arguments, config)
    settings.legacy_charmap = legacy_charmap
    
    formats_to_validate = {
        "folder_format": getattr(arguments, 'folder_format', None) or folder_format,
        "track_format": getattr(arguments, 'track_format', None) or track_format,
        "fallback_folder_format": config.get(section, "fallback_folder_format", fallback="{artist} - {album}"),
        "multiple_disc_track_format": config.get(section, "multiple_disc_track_format", fallback="{disc_number}.{track_number} - {track_title}")
    }
    validate_config_formats(formats_to_validate)

    qobuz = QobuzDL(
        directory_to_use,
        getattr(arguments, 'quality', None) or default_quality,
        getattr(arguments, 'embed_art', False) or embed_art,
        ignore_singles_eps=getattr(arguments, 'albums_only', False) or albums_only,
        no_m3u_for_playlists=getattr(arguments, 'no_m3u', False) or no_m3u,
        quality_fallback=not getattr(arguments, 'no_fallback', False) or not no_fallback,
        cover_og_quality=getattr(arguments, 'og_cover', False) or og_cover,
        no_cover=getattr(arguments, 'no_cover', False) or no_cover,
        downloads_db=None if no_database or getattr(arguments, 'no_db', False) else QOBUZ_DB,
        folder_format=getattr(arguments, 'folder_format', None) or folder_format,
        track_format=getattr(arguments, 'track_format', None) or track_format,
        smart_discography=getattr(arguments, 'smart_discography', False) or smart_discography,
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

    import sys

    if len(sys.argv) > 1 and sys.argv[1].lower() == "-r":
        sys.exit(_reset_config(CONFIG_FILE))

    _initial_checks()

    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()