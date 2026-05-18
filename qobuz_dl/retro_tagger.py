import os
import logging
import asyncio

from pathlib import Path
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed

from mutagen.flac import FLAC
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError

from qobuz_dl.lyrics_engine import LyricsEngine
from qobuz_dl.color import CYAN, GREEN, YELLOW, RED, OFF

logger = logging.getLogger(__name__)

# =====================================================
# THREAD SAFE PRINT
# =====================================================

print_lock = Lock()

def safe_print(message):
    with print_lock:
        print(message, flush=True)

# =====================================================
# PROCESSAR ARQUIVO ÚNICO
# =====================================================

def _process_single_file(
    file_path_str,
    engine,
    overwrite=False,
    current_idx=0,
    total_files=0
):

    try:

        title = ""
        artist = ""
        album_artist = ""
        album = ""

        has_lyrics = False

        file_path_lower = file_path_str.lower()

        # =====================================================
        # FLAC
        # =====================================================

        if file_path_lower.endswith(".flac"):

            audio = FLAC(file_path_str)

            lyrics_fields = [
                "LYRICS",
                "UNSYNCEDLYRICS",
                "LYRICS_SYNCED"
            ]

            has_lyrics = any(
                audio.get(field)
                for field in lyrics_fields
            )

            title = audio.get("TITLE", [""])[0]
            artist = audio.get("ARTIST", [""])[0]
            album_artist = audio.get("ALBUMARTIST", [""])[0]
            album = audio.get("ALBUM", [""])[0]

        # =====================================================
        # MP3
        # =====================================================

        elif file_path_lower.endswith(".mp3"):

            try:
                audio = id3.ID3(file_path_str)

            except ID3NoHeaderError:
                return {
                    "status": "skipped",
                    "artist": "Unknown",
                    "title": "Unknown",
                    "messages": []
                }

            has_lyrics = bool(
                audio.getall("USLT") or
                audio.getall("SYLT")
            )

            title = (
                audio.get("TIT2").text[0]
                if audio.get("TIT2")
                else ""
            )

            artist = (
                audio.get("TPE1").text[0]
                if audio.get("TPE1")
                else ""
            )

            album_artist = (
                audio.get("TPE2").text[0]
                if audio.get("TPE2")
                else ""
            )

            album = (
                audio.get("TALB").text[0]
                if audio.get("TALB")
                else ""
            )

        else:

            return {
                "status": "skipped",
                "artist": "Unknown",
                "title": "Unknown",
                "messages": []
            }

        # =====================================================
        # VALIDAÇÃO
        # =====================================================

        if not title or not artist:

            return {
                "status": "skipped",
                "artist": artist,
                "title": title,
                "messages": []
            }

        # Prioriza Album Artist
        search_artist = (
            album_artist
            if album_artist and album_artist.lower() != "various artists"
            else artist
        )

        progresso = f"[{current_idx}/{total_files}]"

        # =====================================================
        # JÁ POSSUI LETRA
        # =====================================================

        if not overwrite and has_lyrics:

            return {
                "status": "skipped",
                "artist": search_artist,
                "title": title,
                "messages": [
                    f"{YELLOW}{progresso} Ignorado (Já Marcado): "
                    f"{search_artist} - {title}{OFF}"
                ]
            }

        # =====================================================
        # BUSCAR LETRA
        # =====================================================

        result = asyncio.run(
            engine.fetch_and_inject(
                file_path=file_path_str,
                album_artist=search_artist,
                track=title,
                album=album,
                save_lrc=True,
                overwrite=overwrite,
                return_message=True
            )
        )

        success = result[0]
        has_translation = result[1]
        messages = result[2] if len(result) > 2 else []

        return {
            "status": "injected" if success else "skipped",
            "artist": search_artist,
            "title": title,
            "messages": messages
        }

    except Exception as e:

        logger.error(
            f"Error processing file: {e}",
            exc_info=True
        )

        return {
            "status": "error",
            "artist": "Unknown",
            "title": "Unknown",
            "messages": [
                f"{RED}[!] Error processing "
                f"{file_path_str}: {e}{OFF}"
            ]
        }

# =====================================================
# RETRO SCAN PRINCIPAL
# =====================================================

def inject_lyrics_retroactively(
    directory_path,
    genius_token=None,
    deepl_api_key=None,
    overwrite=False,
    target_lang="PT-BR"
):

    safe_print(
        f"\n{CYAN}[*] Starting retroactive lyrics scan in: "
        f"{directory_path}{OFF}\n"
    )

    if overwrite:

        safe_print(
            f"{RED}[!] OVERWRITE MODE ENABLED: "
            f"ARQUIVOS .LRC SERÃO REESCRITOS..{OFF}\n"
        )

    target_dir = Path(directory_path)

    if not target_dir.is_dir():

        safe_print(
            f"{RED}[!] Error: "
            f"Directory does not exist: "
            f"{directory_path}{OFF}\n"
        )

        return

    engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=True, target_lang=target_lang)

    # =====================================================
    # ENCONTRAR ARQUIVOS
    # =====================================================

    all_files = []

    for ext in [".flac", ".mp3"]:

        all_files.extend(
            list(target_dir.rglob(f"*{ext}"))
        )

        all_files.extend(
            list(target_dir.rglob(f"*{ext.upper()}"))
        )

    # Remove duplicados + ordena
    all_files = sorted(set(all_files))

    total_files = len(all_files)

    injected = 0
    skipped = 0
    errors = 0

    safe_print(
        f"{CYAN}[*] Found "
        f"{total_files} compatible audio files."
        f"{OFF}\n"
    )

    # =====================================================
    # OTIMIZAÇÃO iSH/iOS
    # =====================================================

    # iSH sofre MUITO com muitas threads
    max_workers = 1

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {}

        for idx, path in enumerate(all_files, 1):

            future = executor.submit(
                _process_single_file,
                str(path),
                engine,
                overwrite,
                idx,
                total_files
            )

            futures[future] = idx

        results_by_idx = {}

        next_to_print = 1

        for future in as_completed(futures):

            idx = futures[future]

            try:
                result_data = future.result()

            except Exception as e:

                logger.error(
                    f"Thread execution error: {e}",
                    exc_info=True
                )

                result_data = {
                    "status": "error",
                    "artist": "Unknown",
                    "title": "Unknown",
                    "messages": [
                        f"{RED}[!] Thread error: {e}{OFF}"
                    ]
                }

            results_by_idx[idx] = result_data

            while next_to_print in results_by_idx:

                data = results_by_idx[next_to_print]

                status = data.get("status")
                artist = data.get("artist", "Unknown")
                title = data.get("title", "Unknown")
                messages = data.get("messages", [])

                progresso = (
                    f"[{next_to_print}/{total_files}]"
                )

                safe_print(
                    f"{CYAN}{progresso} "
                    f"Searching: "
                    f"{artist} - {title}{OFF}"
                )

                for msg in messages:
                    safe_print(msg)

                if status == "injected":
                    injected += 1

                elif status == "skipped":
                    skipped += 1

                elif status == "error":
                    errors += 1

                del results_by_idx[next_to_print]

                next_to_print += 1

    # =====================================================
    # RESUMO FINAL
    # =====================================================

    safe_print(
        f"\n{GREEN}[+] Retroactive Scan Completed!{OFF}"
    )

    safe_print(
        f"{CYAN}  - TOTAL FILES: "
        f"{total_files}{OFF}"
    )

    safe_print(
        f"{GREEN}  - TAGGED FILES: "
        f"{injected}{OFF}"
    )

    safe_print(
        f"{YELLOW}  - SKIPPED FILES: "
        f"{skipped}{OFF}"
    )

    if errors > 0:

        safe_print(
            f"{RED}  - ERRORS: "
            f"{errors}{OFF}"
        )

    safe_print("\n")
