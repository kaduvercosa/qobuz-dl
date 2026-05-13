import os
import logging
from pathlib import Path
from mutagen.flac import FLAC
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from qobuz_dl.lyrics_engine import LyricsEngine
from qobuz_dl.color import CYAN, GREEN, YELLOW, RED, OFF

logger = logging.getLogger(__name__)

# =========================
# THREAD-SAFE PRINT
# =========================

print_lock = Lock()

def safe_print(message):
    with print_lock:
        print(message, flush=True)

# =========================
# PROCESS SINGLE FILE
# =========================

def _process_single_file(file_path_str, engine, overwrite=False, current_idx=0, total_files=0):
    try:
        title, artist, album = "", "", ""
        needs_lyrics = False

        file_path_lower = file_path_str.lower()

        # =========================
        # FLAC
        # =========================

        if file_path_lower.endswith(".flac"):
            audio = FLAC(file_path_str)

            # Se não for overwrite, verifica se já possui letra
            if not overwrite:
                if (
                    audio.get("LYRICS")
                    or audio.get("UNSYNCEDLYRICS")
                    or audio.get("LYRICS_SYNCED")
                ):
                    return "skipped"

            title = audio.get("TITLE", [""])[0]

            album_artist = audio.get("ALBUMARTIST", [""])[0]
            performer_name = audio.get("ARTIST", ["Unknown Artist"])[0]

            artist = (
                performer_name
                if album_artist in ["", "Various Artists"]
                else album_artist
            )

            album = audio.get("ALBUM", [""])[0]

            needs_lyrics = True

        # =========================
        # MP3
        # =========================

        elif file_path_lower.endswith(".mp3"):

            try:
                audio = id3.ID3(file_path_str)

            except ID3NoHeaderError:
                return "skipped"

            # Se não for overwrite, verifica se já possui letra
            if not overwrite:
                if audio.getall("USLT") or audio.getall("SYLT"):
                    return "skipped"

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

            album = (
                audio.get("TALB").text[0]
                if audio.get("TALB")
                else ""
            )

            needs_lyrics = True

        # =========================
        # VALIDATION
        # =========================

        if not title or not artist:
            return "skipped"

        # =========================
        # SEARCH & INJECT
        # =========================

        if needs_lyrics:
            # Using specific ANSI codes to exactly match the downloader UI
            C = "\033[96m"
            G = "\033[92m"
            O = "\033[0m"
            
            progresso = f"[{current_idx} / {total_files}]"
            safe_print(f"{C}[+{progresso}]: {artist} - {title}{O}")

            # Engine
            success = engine.fetch_and_inject(
                file_path=file_path_str,
                artist=artist,
                track=title,
                album=album,
                overwrite=overwrite
            )

            if success:
                safe_print(f"{G}  L Completed: {artist} - {title}{O}")
                return "injected"
            else:
                return "skipped"

    except Exception as e:
        safe_print(f"{RED}[!] Error processing {file_path_str}: {e}{OFF}")
        return "error"

    return "skipped"

# =========================
# MAIN RETRO SCAN
# =========================

def inject_lyrics_retroactively(
    directory_path,
    genius_token=None,
    overwrite=False
):

    safe_print(
        f"\n{CYAN}[*] Starting retroactive lyrics scan in: "
        f"{directory_path}{OFF}\n"
    )

    if overwrite:
        safe_print(
            f"{RED}[!] OVERWRITE MODE ENABLED: "
            f"Existing lyrics will be replaced.{OFF}\n"
        )

    target_dir = Path(directory_path)

    if not target_dir.is_dir():

        safe_print(
            f"{RED}[!] Error: "
            f"The directory '{directory_path}' does not exist.{OFF}\n"
        )

        return

    engine = LyricsEngine(genius_token)

    # =========================
    # FILE DISCOVERY
    # =========================

    all_files = []

    for ext in [".flac", ".mp3"]:

        all_files.extend(list(target_dir.rglob(f"*{ext}")))
        all_files.extend(list(target_dir.rglob(f"*{ext.upper()}")))

    # Remove duplicados
    all_files = list(set(all_files))

    processed = len(all_files)

    injected = 0
    skipped = 0
    errors = 0

    safe_print(
        f"{CYAN}[*] Found {processed} compatible audio files. "
        f"Processing...{OFF}\n"
    )

    # =========================
    # PARALLEL PROCESSING
    # =========================

    # Ideal para iSH/iPad:
    # rápido sem bagunçar o terminal

    max_workers = 3

    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        futures = {}
        
        for idx, path in enumerate(all_files, 1):
            future = executor.submit(
                _process_single_file,
                str(path),
                engine,
                overwrite,
                idx,
                processed
            )
            futures[future] = path

        for future in as_completed(futures):

            try:
                result = future.result()

                if result == "injected":
                    injected += 1

                elif result == "skipped":
                    skipped += 1

                elif result == "error":
                    errors += 1

            except Exception as e:

                logger.error(
                    f"{RED}[!] Thread execution error: {e}{OFF}"
                )

                errors += 1

    # =========================
    # FINAL SUMMARY
    # =========================

    safe_print(
        f"\n{GREEN}[+] Retroactive Scan and Injection Completed!{OFF}"
    )

    safe_print(
        f"{CYAN}  - Total files analyzed: {processed}{OFF}"
    )

    safe_print(
        f"{GREEN}  - Injection attempts: {injected}{OFF}"
    )

    safe_print(
        f"{YELLOW}  - Skipped files "
        f"(already tagged or missing data): {skipped}{OFF}"
    )

    if errors > 0:

        safe_print(
            f"{RED}  - Errors encountered: {errors}{OFF}"
        )

    safe_print("\n")
