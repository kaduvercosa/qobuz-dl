import sys
import difflib
import string
import re
import configparser
import io
import logging
import os
import signal
import aiohttp
import asyncio
import platform
from pathlib import Path
from typing import Union

from qobuz_dl.bundle import Bundle
from qobuz_dl.color import Tema, GREEN, RED, YELLOW, OFF, CYAN, BLUE
from qobuz_dl.commands import qobuz_dl_args
from qobuz_dl.core import QobuzDL
from qobuz_dl.downloader import DEFAULT_FOLDER, DEFAULT_TRACK, abort_event, close_shared_cover_session
from qobuz_dl.settings import QobuzDLSettings

logging.basicConfig(level=logging.INFO, format="%(message)s")


# ==============================================================================
# 1. CONFIGURAÇÕES DE CAMINHOS E SISTEMA (PATH & OS CONFIG)
# ==============================================================================

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

from qobuz_dl.constants import IS_IOS, CONFIG_PATH, DEFAULT_DOWNLOAD_DIR

if os.name == "nt":
    _win_base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    CONFIG_PATH = _win_base / "qobuz-dl"

CONFIG_FILE = CONFIG_PATH / "config.ini"
QOBUZ_DB    = CONFIG_PATH / "qobuz_dl.db"

# ==============================================================================
# 2. FUNÇÕES UTILITÁRIAS E DE VERIFICAÇÃO (UTILITIES)
# ==============================================================================

def validate_config_formats(formats_to_check: dict) -> None:
    """Verifica a sintaxe das variáveis de formatação para evitar KeyErrors silenciosos."""
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
        if not format_string: continue
        try:
            parsed_vars = [tup[1] for tup in string.Formatter().parse(str(format_string)) if tup[1] is not None]
            for var in parsed_vars:
                base_var = var.split(':')[0].split('!')[0]
                if base_var not in VALID_KEYS:
                    print(f"{YELLOW}[!] Config Warning: Unknown variable '{{{base_var}}}' detected in '{config_name}'.{OFF}")
                    similar_keys = difflib.get_close_matches(base_var, VALID_KEYS, n=1, cutoff=0.6)
                    if similar_keys: print(f"    {GREEN}-> Did you mean '{{{similar_keys[0]}}}'?{OFF}")
                    print(f"    {RED}-> This will cause the entire format string to be discarded during download.{OFF}")
                    has_errors = True
        except ValueError as e:
            print(f"{RED}[!] Config Error: Syntax error in '{config_name}' -> {e}{OFF}")
            has_errors = True

    if has_errors:
        print(f"\n{YELLOW}[*] Tip: Please check your config.ini file or your command line arguments and fix any typos before downloading.{OFF}\n")
        sys.exit(1)

def _remove_leftovers(directory):
    """Limpa ficheiros temporários .tmp que possam ter ficado em caso de erro."""
    for tmp_file in Path(directory).rglob(".*.tmp"):
        try: tmp_file.unlink(missing_ok=True)
        except Exception: pass

async def check_for_updates():
    """Verifica se há atualizações no GitHub uma vez por dia."""
    import datetime
    check_file = CONFIG_PATH / "last_update_check"
    try:
        if check_file.is_file():
            last_check_str = check_file.read_text().strip()
            if datetime.date.fromisoformat(last_check_str) >= datetime.date.today(): return
    except Exception: pass

    try:
        from qobuz_dl import __version__
        url = "https://api.github.com/repos/kaduvercosa/qobuz-dl/releases/latest"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=2) as response:
                response.raise_for_status()
                data = await response.json()
        
        latest_version_str = data.get("tag_name", "").replace("v", "")
        def parse_version(v: str): return tuple(int(p) for p in re.findall(r'\d+', v)[:3])
        
        if parse_version(latest_version_str) > parse_version(__version__):
            print(f"\n{YELLOW}[*] UPDATE AVAILABLE: Master Edition v{latest_version_str} is out!{OFF}")
            print(f"{YELLOW}    - PyPI: run 'pip install -U qobuz-dl-master'{OFF}")
            print(f"{YELLOW}    - Docker: pull the latest image{OFF}")
            print(f"{YELLOW}    - Standalone: download the new release from GitHub{OFF}\n")

        check_file.write_text(str(datetime.date.today()))
    except Exception: pass

def _initial_checks():
    """Verificações básicas de boot."""
    if not CONFIG_PATH.is_dir() or not CONFIG_FILE.is_file():
        CONFIG_PATH.mkdir(parents=True, exist_ok=True)
        _reset_config(CONFIG_FILE)

    if len(sys.argv) < 2:
        sys.exit(qobuz_dl_args().print_help())


# ==============================================================================
# 3. ASSISTENTE DE CONFIGURAÇÃO (WIZARD)
# ==============================================================================

def _reset_config(config_file: Path) -> int:
    logging.info(f"\n{BLUE}╭──────────────────────────────────────────────────╮{OFF}")
    logging.info(f"{BLUE}│       QOBUZ-DL MASTER : CONFIGURAÇÃO INICIAL     │{OFF}")
    logging.info(f"{BLUE}╰──────────────────────────────────────────────────╯{OFF}")
    
    config = configparser.ConfigParser(interpolation=None)
    config["qobuz"] = {}
    
    try:
        print(f"\n{YELLOW}--- 1. CREDENCIAIS DA CONTA QOBUZ ---{OFF}")
        email = input("  ❯ Email do Qobuz: ")
        if not email: sys.exit(1)
        config["qobuz"]["email"] = email.strip()

        print(f"\n  {CYAN} A Qobuz exige o 'User Auth Token' (encontrado via F12 no navegador).{OFF}")
        auth_token = input("  ❯ Cole o Token (user_auth_token) aqui: ")
        if not auth_token: sys.exit(1)

        config["qobuz"]["password"] = ""
        config["qobuz"]["auth_token"] = auth_token.strip()

        print(f"\n{YELLOW}--- 2. LETRAS E TRADUÇÃO HÍBRIDA ---{OFF}")
        fetch_lyrics_opt = input("  ❯ Deseja baixar e injetar letras sincronizadas automaticamente? (S/n): ").strip().lower()
        fetch_lyrics = fetch_lyrics_opt != 'n'
        config["qobuz"]["fetch_lyrics"] = "true" if fetch_lyrics else "false"

        target_lang, genius_token, deepl_api_key, translate_lyrics = "PT-BR", "", "", False
        translation_symbol_input = ""
        
        if fetch_lyrics:
            translate_opt = input("  ❯ Traduzir as letras estrangeiras para o seu idioma? (S/n): ").strip().lower()
            translate_lyrics = translate_opt != 'n'
            if translate_lyrics:
                target_lang_input = input("\n  ❯ Idioma alvo para tradução (ex: 'PT-BR', 'EN-US') [padrão: PT-BR]: ").strip()
                if target_lang_input: target_lang = target_lang_input.upper()

                print(f"\n  {CYAN}[!] Símbolo mostrado antes da linha traduzida no .lrc. Use \\t (tab), \\s (espaço) e \\n (quebra de linha) em vez dos caracteres reais, pois espaços/tabs reais no início ou fim são cortados ao salvar no config.ini.{OFF}")
                translation_symbol_input = input("  ❯ Símbolo da tradução [padrão: 3 espaços + ~ + espaço]: ").strip()

                print(f"\n {CYAN}[HIERARQUIA] 1º Oficial Qobuz -> 2º DeepL API -> 3º Google Translate {OFF}")
                deepl_input = input("  ❯ Token API do DeepL (Opcional - deixe em branco, para utilizar o Google): ").strip()
                if deepl_input: deepl_api_key = deepl_input

            genius_input = input("\n  ❯ Token API do Genius {CYAN}[Opcional]{OFF}: ").strip() 
            if genius_input: genius_token = genius_input

        config["qobuz"]["target_lang"] = target_lang
        config["qobuz"]["translate_lyrics"] = "true" if translate_lyrics else "false"
        config["qobuz"]["deepl_api_key"] = deepl_api_key
        config["qobuz"]["genius_token"] = genius_token
        # Só grava a chave se o usuário escolheu algo. Se deixar em branco, o
        # projeto usa o padrão "   ~ " (com espaços reais) direto no código --
        # se a gente escrevesse esse padrão aqui, na próxima leitura do
        # config.ini os espaços do início/fim seriam cortados sem querer.
        if translation_symbol_input:
            config["qobuz"]["translation_symbol"] = translation_symbol_input

        print(f"\n{YELLOW}--- 3. PLAYLISTS INTELIGENTES (IA) ---{OFF}")
        print("    1) Nenhuma (Saltar)")
        print("    2) OpenAI (ChatGPT)")
        print("    3) Google Gemini")
        ai_choice = input("  ❯ Escolha o motor de IA [padrão: 1]: ").strip()

        config["qobuz"]["ai_provider"] = "openai"
        config["qobuz"]["openai_api_key"] = ""
        config["qobuz"]["gemini_api_key"] = ""

        if ai_choice == "2": 
            config["qobuz"]["openai_api_key"] = input("  ❯ Chave API da OpenAI (sk-...): ").strip()
        elif ai_choice == "3": 
            config["qobuz"]["ai_provider"] = "gemini"
            config["qobuz"]["gemini_api_key"] = input("  ❯ Chave API do Gemini: ").strip()

        print(f"\n{YELLOW}--- 4. AUTOMAÇÃO E RADAR ---{OFF}")
        config["qobuz"]["webhook_url"] = input("  ❯ URL do Webhook (n8n/Make.com) {CYAN}[Opcional](em branco para saltar){OFF}: ").strip()
        dias_busca = input("  ❯ Radar: Dias a retroceder para procurar lançamentos [padrão: 7]: ").strip()
        config["qobuz"]["dias_de_busca"] = dias_busca if dias_busca else "7"

        print(f"\n{YELLOW}--- 5. INTEGRAÇÃO TELEGRAM (ESPELHO) ---{OFF}")
        tg_choice = input("  ❯ Deseja enviar cópias dos downloads para canais do Telegram? (s/N): ").strip().lower()

        if tg_choice == "s":
            config["telegram"] = {"enabled": "false"}
            print(f"\n  {CYAN}[!] O Telegram começará 'desativado'. Altere 'enabled = true' no config.ini quando quiser usar.{OFF}")
            config["telegram"]["api_id"]   = input("  ❯ Telegram api_id (de my.telegram.org): ").strip()
            config["telegram"]["api_hash"] = input("  ❯ Telegram api_hash: ").strip()
            config["telegram"]["session"]  = input("  ❯ Nome da sessão [padrão: qobuz_session]: ").strip() or "qobuz_session"
            
            print(f"\n  {CYAN}[!] Os IDs de canais começam sempre com -100{OFF}")
            config["channels"] = {
                "musicas": input("  ❯ ID Canal Músicas (ex: -100...): ").strip(),
                "albuns": input("  ❯ ID Canal Álbuns (ex: -100...): ").strip(),
                "artistas": input("  ❯ ID Canal Artistas (ex: -100...): ").strip(),
                "geral": input("  ❯ ID Canal Geral/Log (ex: -100...): ").strip()
            }
        else:
            config["telegram"] = {"enabled": "false", "api_id": "", "api_hash": "", "session": "qobuz_session"}
            config["channels"] = {"musicas": "", "albuns": "", "artistas": "", "geral": ""}

        print(f"\n{YELLOW}--- 6. PREFERÊNCIAS DE DOWNLOAD ---{OFF}")
        directory = input(f"  ❯ Pasta principal de downloads {CYAN}[padrão: Qobuz Downloads]{OFF}: ").strip()
        config["qobuz"]["directory"] = directory if directory else DEFAULT_DOWNLOAD_DIR

        folder_format = input(f"  ❯ Formato das subpastas {CYAN}[padrão: {DEFAULT_FOLDER}]{OFF}: ").strip()
        config["qobuz"]["folder_format"] = folder_format if folder_format else DEFAULT_FOLDER

        print(f"\n  {YELLOW}Qualidade Padrão de Download:")
        print("    27) 24-Bit / >96 kHz (Hi-Res Máximo)")
        print("     7) 24-Bit / <96 kHz (Hi-Res Padrão)")
        print("     6) 16-Bit / 44.1 kHz (Qualidade CD / FLAC)")
        print("     5) 320 kbps (MP3 Econômico)")
        quality = input("  ❯ Escolha (27, 7, 6 ou 5) {CYAN}[padrão: 7]{OFF}: ").strip()
        config["qobuz"]["default_quality"] = quality if quality in ["27", "7", "6", "5"] else "7"

    except KeyboardInterrupt:
        print(f"\n\n{RED}[!] Configuração cancelada pelo utilizador.{OFF}")
        sys.exit(1)

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
        # Escreve primeiro em memória pra poder injetar um comentário-lembrete
        # sobre a notação de escape do translation_symbol (o configparser não
        # tem suporte nativo a comentários associados a uma chave específica).
        buffer = io.StringIO()
        config.write(buffer)
        config_text = buffer.getvalue()

        aviso_symbol = (
            "; DICA: pra mudar o símbolo mostrado antes da linha traduzida no .lrc,\n"
            "; adicione (ou edite) a linha 'translation_symbol' abaixo. Use \\t (tab),\n"
            "; \\s (espaço) e \\n (quebra de linha) em vez dos caracteres reais -- espaços\n"
            "; e tabs reais no início/fim do valor são cortados ao ler o arquivo.\n"
            "; Exemplo: translation_symbol = \\t~\\s   (padrão se omitido: 3 espaços + ~ + espaço)\n"
        )
        config_text = config_text.replace("target_lang = ", aviso_symbol + "target_lang = ")

        configfile.write(config_text)
        
    logging.info(f"\n{GREEN}[+] Configuração guardada com sucesso em:{OFF} {config_file}\n")
    return 0


# ==============================================================================
# 4. INTERCETORES DE COMANDOS ISOLADOS (STANDALONE COMMANDS)
# ==============================================================================

async def _intercept_standalone_commands():
    """
    Processa comandos diretos que não precisam da carga completa do motor QobuzDL.
    Se um destes comandos for acionado, o programa executa-o e encerra-se (sys.exit).
    Adicione novos scripts avulsos nesta secção.
    """
    if len(sys.argv) < 2: return
    cmd = sys.argv[1].lower()

    if cmd == "radar":
        from qobuz_dl.radar import _async_run_radar
        try: await _async_run_radar()
        except KeyboardInterrupt: print(f"\n\n{RED}[!] Radar manualmente interrompido.. (CTRL+C).{OFF}")
        sys.exit(0)

    if cmd in ("ost", "ost_hunter"):
        from qobuz_dl.ost_hunter import amain as _async_run_ost
        try:
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            await _async_run_ost()
        except KeyboardInterrupt: print(f"\n\n{RED}[!] Caçador de Trilhas interrompido (CTRL+C).{OFF}")
        sys.exit(0)

    if cmd == "anime":
        from qobuz_dl.anime_hunter import amain as _async_run_anime
        try:
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            await _async_run_anime()
        except KeyboardInterrupt: print(f"\n\n{RED}[!] Caçador de Animes interrompido (CTRL+C).{OFF}")
        sys.exit(0)

    if cmd in ("transfer", "tr"):
        from qobuz_dl.account_transfer import amain as transfer_amain
        try: await transfer_amain()
        except KeyboardInterrupt: print(f"\n\n{RED}[!] Transferência interrompida pelo utilizador (CTRL+C).{OFF}\n")
        sys.exit(0)

    if cmd == "stats":
        from qobuz_dl.db import create_db, get_library_stats, get_folder_stats
        _cfg = configparser.ConfigParser(interpolation=None)
        _cfg.read(CONFIG_FILE)
        _sec = "qobuz" if _cfg.has_section("qobuz") else "DEFAULT"
        scan_dir = os.path.expanduser(_cfg.get(_sec, "directory", fallback=None) or _cfg.get(_sec, "default_folder", fallback=DEFAULT_DOWNLOAD_DIR))

        print(f"\n{CYAN}--- QOBUZ-DL MASTER -- LIBRARY STATISTICS ---{OFF}")
        force_full_scan = "--full-scan" in sys.argv or "--rescan" in sys.argv
        stats, source_label = None, ""

        if not force_full_scan:
            try:
                create_db(QOBUZ_DB)
                lib_stats = get_library_stats(str(QOBUZ_DB))
                if lib_stats and lib_stats['total_tracks'] > 0:
                    stats, source_label = lib_stats, "banco de dados local (instantâneo)"
            except Exception: pass

        if stats is None:
            print(f"{YELLOW}Scanning: {scan_dir}{OFF}\n")
            if not Path(scan_dir).is_dir():
                print(f"{RED}[!] Directory not found: {scan_dir}{OFF}")
                print(f"{YELLOW}    Make sure your download folder exists and is correctly set in config.ini{OFF}\n")
                sys.exit(1)
            stats, source_label = get_folder_stats(scan_dir), "varredura completa do disco"

        print(f"{YELLOW}Fonte: {source_label}{OFF}\n")
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

    if cmd in ("translate", "tl"):
        from qobuz_dl.retro_tagger import interactive_translate_lyrics
        try:
            _cfg = configparser.ConfigParser(interpolation=None)
            _cfg.read(CONFIG_FILE)
            _sec = "qobuz" if _cfg.has_section("qobuz") else "DEFAULT"
            target_directory = sys.argv[2] if len(sys.argv) > 2 else _cfg.get(_sec, "directory", fallback=DEFAULT_DOWNLOAD_DIR)
            _deepl = _cfg.get(_sec, "deepl_api_key", fallback=None)
            _lang = _cfg.get(_sec, "target_lang", fallback="PT-BR")
            _tsymbol = _cfg.get(_sec, "translation_symbol", fallback="   ~ ")
            await interactive_translate_lyrics(ensure_long_path(target_directory), deepl_api_key=_deepl, target_lang=_lang, translation_symbol=_tsymbol)
        except KeyboardInterrupt: print(f"\n\n{RED}[!] Tradutor interrompido pelo utilizador (CTRL+C).{OFF}\n")
        sys.exit(0)
    
    if cmd == "set-deepl":
        if len(sys.argv) < 3:
            print(f"{RED}[!] Uso correto: qobuz-dl set-deepl <SUA_NOVA_CHAVE_AQUI>{OFF}\n")
            sys.exit(1)
        nova_chave = sys.argv[2].strip()
        from qobuz_dl.retro_tagger import _test_deepl_api
        if not _test_deepl_api(nova_chave):
            print(f"\n{RED}[!] Operação abortada. A chave não foi salva no config.ini por que falhou no teste.{OFF}\n")
            sys.exit(1)
        _cfg = configparser.ConfigParser(interpolation=None)
        _cfg.read(CONFIG_FILE)
        if not _cfg.has_section("qobuz"): _cfg.add_section("qobuz")
        _cfg.set("qobuz", "deepl_api_key", nova_chave)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: _cfg.write(f)
        print(f"\n{GREEN}[+] Chave do Deepl atualizada com sucesso no arquivo config.ini!{OFF}")
        sys.exit(0)

# ==============================================================================
# 5. ORQUESTRAÇÃO DE DOWNLOADS (CORE ENGINE)
# ==============================================================================

async def _handle_commands(maestro, qobuz, arguments):
    """Encaminha os comandos clássicos após os motores estarem devidamente inicializados."""
    def sigint_handler(sig, frame):
        abort_event.set()
        raise KeyboardInterrupt
        
    signal.signal(signal.SIGINT, sigint_handler)

    try:
        if arguments.command == "dl":
            import os
            urls_finais = []
            for item in arguments.SOURCE:
                if Path(item).is_file():
                    with open(item, "r", encoding="utf-8") as f:
                        urls_finais.extend([linha.strip() for linha in f if linha.strip() and not linha.startswith("#") and "[DONE]" not in linha])
                else:
                    urls_finais.append(item)
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


async def amain():
    """Função principal que carrega a configuração e inicializa os motores da aplicação."""
    await check_for_updates()
    
    # Executa comandos isolados primeiro, saindo caso algum seja acionado.
    await _intercept_standalone_commands()

    # --- INÍCIO DO CARREGAMENTO DO CONFIG.INI ---
    config = configparser.ConfigParser(interpolation=None)
    config.read(CONFIG_FILE)
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
        translate_lyrics = config.getboolean(section, "translate_lyrics", fallback=True)
        target_lang = config.get(section, "target_lang", fallback="PT-BR")
        # Símbolo que marca o início da linha traduzida no .lrc. Aceita escapes:
        # \t (tab/recuo), \s (espaço, útil no fim já que o configparser corta
        # espaços reais ali) e \n. Ex no config.ini: translation_symbol = \t~\s
        translation_symbol = config.get(section, "translation_symbol", fallback="   ~ ")
        
        directory_val = config.get(section, "directory", fallback=None)
        if directory_val is not None:
            default_folder = directory_val
        else:
            legacy_val = config.get(section, "default_folder", fallback=None)
            if legacy_val is not None:
                print(f"{YELLOW}[!] Notice: 'default_folder' is deprecated. Rename it to 'directory'.{OFF}")
                default_folder = legacy_val
            else:
                default_folder = DEFAULT_DOWNLOAD_DIR

        default_limit = config.get(section, "default_limit")
        default_quality = config.get(section, "default_quality")
        no_lrc_files_config = config.getboolean(section, "no_lrc_files", fallback=False)
        no_credits_config = config.getboolean(section, "no_credits", fallback=False)
        blacklist_config = config.get(section, "blacklist", fallback="blacklist.txt")
        app_id = config.get(section, "app_id")
        secrets = [s.strip() for s in config.get(section, "secrets", fallback="").split(",") if s.strip()]
        
        arguments = qobuz_dl_args(default_quality, default_limit, default_folder).parse_args()
        
        if getattr(arguments, 'no_lyrics', False): fetch_lyrics = False
        if getattr(arguments, 'no_translate', False): translate_lyrics = False
            
        force_english = not getattr(arguments, 'native_lang', False)
        no_credits_flag = getattr(arguments, 'no_credits', False) or no_credits_config 
        
    except (configparser.Error, KeyError) as error:
        arguments = qobuz_dl_args().parse_args()
        if not arguments.reset:
            sys.exit(f"{RED}Invalid or corrupted configuration ({error}).\n{OFF}{YELLOW}Run 'python -m qobuz_dl -r' to fix this.{OFF}")

    if arguments.show_config:
        print(f"Configuration: {CONFIG_FILE}\nDatabase: {QOBUZ_DB}\n---")
        with open(CONFIG_FILE, "r") as f: print(f.read())
        sys.exit()

    # --- COMANDOS QUE DEPENDEM DOS ARGUMENTOS MAS NÃO DO MOTOR DE DOWNLOAD ---
    if getattr(arguments, 'sync_db', None):
        from qobuz_dl.sync import sync_database
        from qobuz_dl.qopy import Client
        sync_client = Client(email, password, app_id, secrets, user_auth_token=token, force_english=force_english)
        sync_dir = ensure_long_path(default_folder if arguments.sync_db == "DEFAULT" else arguments.sync_db)
        await sync_database(sync_dir, str(QOBUZ_DB), sync_client)
        sys.exit(f"\n{GREEN}Database synchronization finished successfully.{OFF}")

    if arguments.command == "lyrics":
        from qobuz_dl.retro_tagger import inject_lyrics_retroactively
        try:
            await inject_lyrics_retroactively(ensure_long_path(arguments.DIR), genius_token=genius_token, deepl_api_key=deepl_api_key, overwrite=getattr(arguments, 'overwrite', False), target_lang=target_lang, translation_symbol=translation_symbol, translate_lyrics=translate_lyrics, max_workers=int(config.get(section, "max_workers", fallback=3)))
        except KeyboardInterrupt: print(f"\n\n{RED}[!] Operation manually interrupted by the user (CTRL+C).{OFF}\n{YELLOW}Already processed files are safe. Exiting...{OFF}")
        sys.exit(0)

    elif arguments.command in ("fix-lyrics", "fl"):
        from qobuz_dl.retro_tagger import interactive_fix_lyrics
        try: await interactive_fix_lyrics(ensure_long_path(arguments.DIR), genius_token=genius_token, deepl_api_key=deepl_api_key, target_lang=target_lang, translation_symbol=translation_symbol, translate_lyrics=translate_lyrics)
        except KeyboardInterrupt: print(f"\n\n{RED}[!] Operation manually interrupted (CTRL+C).{OFF}")
        sys.exit(0)

    # --- INICIALIZAÇÃO DO QOBUZ-DL & MAESTRO ENGINE ---
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
        directory_to_use, getattr(arguments, 'quality', None) or default_quality,
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
        fetch_lyrics=fetch_lyrics, no_lrc_files=("--no-lrc-files" in sys.argv) or no_lrc_files_config,
        genius_token=genius_token, deepl_api_key=deepl_api_key, translate_lyrics=translate_lyrics,
        target_lang=target_lang, translation_symbol=translation_symbol, force_english=force_english, no_credits=no_credits_flag,
        settings=settings, booklet_only=getattr(arguments, 'booklet_only', False),
        blacklist=getattr(arguments, 'blacklist', None) or blacklist_config,
    )

    from core.maestro import MaestroEngine
    from core.qobuz_provider import QobuzProvider
    
    maestro = MaestroEngine()
    qobuz_plugin = QobuzProvider(qobuz)
    maestro.register_provider(qobuz_plugin)
    
    def fetch_fresh_keys():
        b = Bundle()
        return str(b.get_app_id()), list(b.get_secrets().values())

    print(f"\n\r\033[K{Tema.SYS}{GREEN}Verificando Chaves de Segurança...{OFF}", end="", flush=True)
    try:
        fresh_app_id, fresh_secrets = await asyncio.wait_for(asyncio.to_thread(fetch_fresh_keys), timeout=10.0)
        if fresh_app_id:
            app_id, secrets = fresh_app_id, fresh_secrets
            print(f"\r\033[K{Tema.SYS}{GREEN}Chaves atualizadas com sucesso!{OFF}", end="", flush=True)
    except asyncio.TimeoutError:
        print(f"\r\033[K{Tema.SYS}{YELLOW}Aviso: Tempo esgotado (Usando chaves offline..){OFF}", end="", flush=True)
    except Exception as e:
        print(f"\r\033[K{Tema.SYS}{RED}Aviso: Erro ao buscar chaves novas ({e}){OFF}", end="", flush=True)

    credentials = {"email": email, "password": password, "app_id": app_id, "secrets": secrets}
    await qobuz_plugin.authenticate(credentials)

    try:
        await asyncio.to_thread(_remove_leftovers, qobuz.directory)
        await _handle_commands(maestro, qobuz, arguments)
    finally:
        await qobuz_plugin.shutdown()
        await close_shared_cover_session()


# ==============================================================================
# 6. PONTO DE ENTRADA DO SCRIPT (MAIN)
# ==============================================================================

def main():
    import asyncio
    
    # Super Interceptador: Purge Imediato
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("-p", "--purge"):
        try:
            QOBUZ_DB.unlink()
            print(f"{Tema.SUCESSO}[✅] Banco de Dados de Histórico apagado com sucesso!{Tema.OFF}\n")
        except FileNotFoundError:
            print(f"{Tema.AVISO}[⚠️] O banco de dados já estava vazio ou não existia.{Tema.OFF}\n")
        except Exception as e:
            print(f"{Tema.ERRO}[❌] Erro ao apagar banco de dados: {e}{Tema.OFF}\n")
        sys.exit(0)

    # Interceptador do Reset
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("-r", "--reset"):
        sys.exit(_reset_config(CONFIG_FILE))

    _initial_checks()

    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()