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
from qobuz_dl.color import GREEN, RED, YELLOW, OFF, CYAN, BLUE
from qobuz_dl.commands import qobuz_dl_args
from qobuz_dl.core import QobuzDL
from qobuz_dl.downloader import DEFAULT_FOLDER, DEFAULT_TRACK, abort_event
from qobuz_dl.settings import QobuzDLSettings

logging.basicConfig(level=logging.INFO, format="%(message)s")

# ============================================================
# PATH CONFIGURATIONS (Using Pathlib)
# ============================================================

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

CONFIG_PATH = OS_CONFIG / "qobuz-dl"
CONFIG_FILE = CONFIG_PATH / "config.ini"
QOBUZ_DB = CONFIG_PATH / "qobuz_dl.db"

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
    logging.info(f"\n{BLUE}╭──────────────────────────────────────────────────╮{OFF}")
    logging.info(f"{BLUE}│       QOBUZ-DL MASTER : CONFIGURAÇÃO INICIAL     │{OFF}")
    logging.info(f"{BLUE}╰──────────────────────────────────────────────────╯{OFF}")
    
    config = configparser.ConfigParser(interpolation=None)
    config["qobuz"] = {}
    
    try:
        print(f"\n{YELLOW}--- 1. Credenciais da Conta ---{OFF}")
        email = input("  ❯ Email do Qobuz: ")
        if not email: sys.exit(1)
        config["qobuz"]["email"] = email.strip()

        print(f"\n  {RED}[!] ATENÇÃO: A Qobuz bloqueou o login direto por senha para apps de terceiros.{OFF}")
        print(f"  {RED}[!] Tem de usar o Token do Navegador (F12 > Storage > Local Storage > localuser > token).{OFF}\n")
        
        auth_token = input("  ❯ Cole o Token (user_auth_token) aqui: ")
        if not auth_token: sys.exit(1)

        config["qobuz"]["password"] = ""
        config["qobuz"]["auth_token"] = auth_token.strip()

        print(f"\n{YELLOW}--- 2. Letras & Tradução ---{OFF}")
        print("  Deseja baixar e injetar letras automaticamente?")
        print("    1) Sim, procurar e injetar letras")
        print("    2) Não, saltar as letras")
        fetch_lyrics_opt = input("  ❯ Escolha (1 ou 2): ")
        config["qobuz"]["fetch_lyrics"] = "true" if fetch_lyrics_opt.strip() == "1" else "false"

        target_lang = "PT-BR"
        genius_token = ""
        deepl_api_key = ""

        if config["qobuz"]["fetch_lyrics"] == "true":
            target_lang_input = input("\n  ❯ Idioma alvo para tradução (ex: 'PT-BR', 'EN-US') [padrão: PT-BR]: ")
            if target_lang_input.strip(): target_lang = target_lang_input.strip().upper()

            print(f"\n  {CYAN}[Dica] Deixe as chaves em branco se quiser usar apenas os servidores gratuitos (LRCLIB, etc).{OFF}")
            deepl_api_key = input("  ❯ Chave API do DeepL (para tradução premium): ").strip()
            genius_token = input("  ❯ Token API do Genius (para busca estendida): ").strip()

        config["qobuz"]["target_lang"] = target_lang
        config["qobuz"]["deepl_api_key"] = deepl_api_key
        config["qobuz"]["genius_token"] = genius_token

        print(f"\n{YELLOW}--- 3. Playlists Inteligentes (IA) ---{OFF}")
        print("  Deseja gerar playlists usando Inteligência Artificial?")
        print("    1) OpenAI (ChatGPT)")
        print("    2) Google Gemini")
        print("    3) Saltar (Nenhuma IA)")
        ai_choice = input("  ❯ Escolha (1, 2 ou 3) [padrão: 3]: ").strip()

        config["qobuz"]["ai_provider"] = "openai"
        config["qobuz"]["openai_api_key"] = ""
        config["qobuz"]["gemini_api_key"] = ""

        if ai_choice == "1": 
            config["qobuz"]["openai_api_key"] = input("  ❯ Chave API da OpenAI (sk-...): ").strip()
        elif ai_choice == "2": 
            config["qobuz"]["ai_provider"] = "gemini"
            config["qobuz"]["gemini_api_key"] = input("  ❯ Chave API do Gemini: ").strip()

        print(f"\n{YELLOW}--- 4. Automação & Radares ---{OFF}")
        config["qobuz"]["webhook_url"] = input("  ❯ URL do Webhook (n8n/Make.com) (em branco para saltar): ").strip()
        
        dias_busca = input("  ❯ Radar: Dias a retroceder para procurar lançamentos [padrão: 7]: ").strip()
        config["qobuz"]["dias_de_busca"] = dias_busca if dias_busca else "7"

        print(f"\n{YELLOW}--- 5. Espelho do Telegram ---{OFF}")
        print("  Deseja enviar cópias dos downloads para canais do Telegram?")
        tg_choice = input("  ❯ Ativar Telegram? (s/N): ").strip().lower()

        if tg_choice == "s":
            config["telegram"] = {}
            config["telegram"]["enabled"] = "false"   # Desativado por padrão para proteção
            print(f"\n  {CYAN}[!] O Telegram começará 'desativado'. Altere 'enabled = true' no config.ini quando quiser usar.{OFF}")
            config["telegram"]["api_id"]   = input("  ❯ Telegram api_id (de my.telegram.org): ").strip()
            config["telegram"]["api_hash"] = input("  ❯ Telegram api_hash: ").strip()
            config["telegram"]["session"]  = input("  ❯ Nome da sessão [padrão: qobuz_session]: ").strip() or "qobuz_session"
            
            print(f"\n  {CYAN}[!] Os IDs de canais começam sempre com -100{OFF}")
            config["channels"] = {}
            config["channels"]["musicas"]  = input("  ❯ ID Canal Músicas (ex: -100...): ").strip()
            config["channels"]["albuns"]   = input("  ❯ ID Canal Álbuns (ex: -100...): ").strip()
            config["channels"]["artistas"] = input("  ❯ ID Canal Artistas (ex: -100...): ").strip()
            config["channels"]["geral"]    = input("  ❯ ID Canal Geral/Log (ex: -100...): ").strip()
        else:
            # Preenche vazio para evitar quebras futuras
            config["telegram"] = {"enabled": "false", "api_id": "", "api_hash": "", "session": "qobuz_session"}
            config["channels"] = {"musicas": "", "albuns": "", "artistas": "", "geral": ""}

        print(f"\n{YELLOW}--- 6. Preferências de Download ---{OFF}")
        directory = input(f"  ❯ Pasta principal de downloads [padrão: Qobuz Downloads]: ").strip()
        config["qobuz"]["directory"] = directory if directory else "Qobuz Downloads"

        folder_format = input(f"  ❯ Formato das subpastas [padrão: {DEFAULT_FOLDER}]: ").strip()
        config["qobuz"]["folder_format"] = folder_format if folder_format else DEFAULT_FOLDER

        print("\n  Qualidade Padrão de Download:")
        print("    27) 24-Bit / >96 kHz (Hi-Res Máximo)")
        print("     7) 24-Bit / <96 kHz (Hi-Res Padrão)")
        print("     6) 16-Bit / 44.1 kHz (Qualidade CD / FLAC)")
        print("     5) 320 kbps (MP3 Econômico)")
        quality = input("  ❯ Escolha (27, 7, 6 ou 5) [padrão: 7]: ").strip()
        config["qobuz"]["default_quality"] = quality if quality else "7"

    except KeyboardInterrupt:
        print(f"\n\n{RED}[!] Configuração cancelada pelo utilizador.{OFF}")
        sys.exit(1)

    # Aplica todas as definições base silenciosas
    config["qobuz"].update({
        "default_limit": "500", "enhanced_lrc": "false", "no_m3u": "false", "albums_only": "false", 
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
        "multi_value_tags": "false",
        "embedded_art_size": "org", "saved_art_size": "org",
        "multiple_disc_prefix": "CD", "multiple_disc_one_dir": "false",
        "multiple_disc_track_format": "{disc_number}.{track_number} - {track_title}",
        "max_workers": "3", "user_auth_token": ""
    })

    print()
    logging.info(f"{CYAN}[*] A gerar chaves de segurança da API... Aguarde.{OFF}")
    bundle = Bundle()
    config["qobuz"]["app_id"] = str(bundle.get_app_id())
    config["qobuz"]["secrets"] = ",".join(bundle.get_secrets().values())

    with open(config_file, "w") as configfile:
        config.write(configfile)
        
    logging.info(f"\n{GREEN}[+] Configuração guardada com sucesso em:{OFF} {config_file}\n")
    return 0


def _remove_leftovers(directory):
    """Limpa ficheiros temporários .tmp que possam ter ficado em caso de erro."""
    for tmp_file in Path(directory).rglob(".*.tmp"):
        try:
            tmp_file.unlink(missing_ok=True)
        except Exception:
            pass


async def _handle_commands(maestro, qobuz, arguments):
    def sigint_handler(sig, frame):
        pass
        abort_event.set()
        raise KeyboardInterrupt
        
    signal.signal(signal.SIGINT, sigint_handler)

    try:
        if arguments.command == "dl":
            # --- DELEGAÇÃO PARA O MAESTRO ---
            import os
            urls_finais = []
            
            # Lê URLs simples ou extrai de ficheiros .txt
            for item in arguments.SOURCE:
                if Path(item).is_file():
                    with open(item, "r", encoding="utf-8") as f:
                        urls_finais.extend([linha.strip() for linha in f if linha.strip() and not linha.startswith("#") and "[DONE]" not in linha])
                else:
                    urls_finais.append(item)
            
            # O Cérebro assume o controlo da lista de links!
            await maestro.process_batch(urls_finais)

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


        # --- INÍCIO DA INTEGRAÇÃO DO OST HUNTER ---
    if len(sys.argv) > 1 and sys.argv[1] in ("ost", "ost_hunter"):
        from qobuz_dl.ost_hunter import amain as _async_run_ost
        try:
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            await _async_run_ost()
        except KeyboardInterrupt:
            print(f"\n\n{RED}[!] Caçador de Trilhas interrompido (CTRL+C).{OFF}")
        sys.exit(0)
    # --- FIM DA INTEGRAÇÃO DO OST HUNTER ---

    # --- INÍCIO DA INTEGRAÇÃO DO ANIME HUNTER ---
    if len(sys.argv) > 1 and sys.argv[1] == "anime":
        from qobuz_dl.anime_hunter import amain as _async_run_anime
        try:
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            await _async_run_anime()
        except KeyboardInterrupt:
            print(f"\n\n{RED}[!] Caçador de Animes interrompido (CTRL+C).{OFF}")
        sys.exit(0)
    # --- FIM DA INTEGRAÇÃO DO ANIME HUNTER ---

    # --- INÍCIO DA INTEGRAÇÃO DO TRANSFER ---
    if len(sys.argv) > 1 and sys.argv[1] in ("transfer", "tr"):
        from qobuz_dl.account_transfer import amain as transfer_amain
        try:
            await transfer_amain()
        except KeyboardInterrupt:
            print(f"\n\n{RED}[!] Transferência interrompida pelo utilizador (CTRL+C).{OFF}\n")
        sys.exit(0)
    # --- FIM DA INTEGRAÇÃO DO TRANSFER ---

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

    # Exporta o caminho do config.ini para que o telegram_uploader encontre
    # a seção [telegram] e [channels] independente de onde é chamado
    os.environ.setdefault("QOBUZ_DL_CONFIG", str(CONFIG_FILE))

    try:
        section = "qobuz" if config.has_section("qobuz") else "DEFAULT"
        email = config.get(section, "email")
        token = config.get(section, "auth_token", fallback="")
        password = token if token else config.get(section, "password")
        
        fetch_lyrics = config.getboolean(section, "fetch_lyrics", fallback=False)
        enhanced_lrc = config.getboolean(section, "enhanced_lrc", fallback=False)
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
        


        # [!] Correção Crítica: O sync_database é agora uma função assíncrona!

        await sync_database(sync_dir, str(QOBUZ_DB), sync_client)
        
        sys.exit(f"\n{GREEN}Database synchronization finished successfully.{OFF}")

    if arguments.command == "lyrics":
        from qobuz_dl.retro_tagger import inject_lyrics_retroactively
        try:
            await inject_lyrics_retroactively(ensure_long_path(arguments.DIR), genius_token=genius_token, deepl_api_key=deepl_api_key, overwrite=getattr(arguments, 'overwrite', False), target_lang=target_lang, max_workers=int(config.get(section, "max_workers", fallback=3)),
            )
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
    settings.enhanced_lrc = enhanced_lrc
    
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
    
    # --- INÍCIO DA INTEGRAÇÃO DO MAESTRO ---
    from core.maestro import MaestroEngine
    from core.qobuz_provider import QobuzProvider
    
    # Iniciar o Motor
    maestro = MaestroEngine()
    
    # O Plugin abraça o seu motor clássico
    qobuz_plugin = QobuzProvider(qobuz)
    maestro.register_provider(qobuz_plugin)
    
    # Autenticar via Plugin
    credentials = {
        "email": email,
        "password": password,
        "app_id": app_id,
        "secrets": secrets
    }
    await qobuz_plugin.authenticate(credentials)

    try:
        # Passamos o Maestro e o Qobuz para que os comandos antigos não quebrem!
        await _handle_commands(maestro, qobuz, arguments)
    finally:
        await qobuz_plugin.shutdown()


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