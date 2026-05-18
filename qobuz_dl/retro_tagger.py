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

import asyncio

def _process_single_file(file_path_str, engine, overwrite=False, current_idx=0, total_files=0):
    try:
        title, artist, album_artist, album = "", "", "", ""
        has_lyrics = False

        file_path_lower = file_path_str.lower()

        # Cores para a UI
        C = "\033[96m"  # Cyan
        G = "\033[92m"  # Green
        Y = "\033[93m"  # Yellow
        O = "\033[0m"   # Off/Reset
        RED_COLOR = "\033[91m"  # Red

        # =========================
        # FLAC
        # =========================
        if file_path_lower.endswith(".flac"):
            audio = FLAC(file_path_str)

            # Verifica se já possui letra
            if audio.get("LYRICS") or audio.get("UNSYNCEDLYRICS") or audio.get("LYRICS_SYNCED"):
                has_lyrics = True

            title = audio.get("TITLE", [""])[0]
            artist = audio.get("ARTIST", [""])[0]
            album_artist = audio.get("ALBUMARTIST", [""])[0]
            album = audio.get("ALBUM", [""])[0]

        # =========================
        # MP3
        # =========================
        elif file_path_lower.endswith(".mp3"):
            try:
                audio = id3.ID3(file_path_str)
            except ID3NoHeaderError:
                return "skipped"

            # Verifica se já possui letra
            if audio.getall("USLT") or audio.getall("SYLT"):
                has_lyrics = True

            title = audio.get("TIT2").text[0] if audio.get("TIT2") else ""
            artist = audio.get("TPE1").text[0] if audio.get("TPE1") else ""
            album_artist = audio.get("TPE2").text[0] if audio.get("TPE2") else ""
            album = audio.get("TALB").text[0] if audio.get("TALB") else ""

        # =========================
        # VALIDATION & LOGIC
        # =========================

        if not title or not artist:
            return "skipped"

        # Prioriza o Álbum Artista para não quebrar na busca (exceto se for Various Artists)
        search_artist = album_artist if album_artist and album_artist.lower() != "various artists" else artist
        progresso = f"[{current_idx}/{total_files}]"

        # Se não for overwrite e já tiver letra, avisa e pula
        if not overwrite and has_lyrics:
            safe_print(f"{Y}{progresso} Ignorado (Já Marcado): {search_artist} - {title}{O}")
            return "skipped"

        # =========================
        # SEARCH & INJECT
        # =========================

        # Instead of printing inside the thread, return the results to print sequentially
        res_tuple = asyncio.run(engine.fetch_and_inject(
            file_path=file_path_str,
            album_artist=search_artist,
            track=title,
            album=album,
            save_lrc=True,
            overwrite=overwrite,
            return_message=True
        ))

        # Unpack, robustly handling old and new returns
        success = res_tuple[0]
        has_translation = res_tuple[1]
        messages = res_tuple[2] if len(res_tuple) > 2 else []

        status_result = "injected" if success else "skipped"
        return {"status": status_result, "artist": search_artist, "title": title, "messages": messages}

    except Exception as e:
        logger.error(f"Error in _process_single_file: {e}", exc_info=True)
        return {"status": "error", "artist": "Unknown", "title": "Unknown", "messages": [f"{RED}[!] Error processing {file_path_str}: {e}{OFF}"]}

    return {"status": "skipped", "artist": search_artist, "title": title, "messages": []}


# =========================
# MAIN RETRO SCAN
# =========================

def inject_lyrics_retroactively(
    directory_path,
    genius_token=None,
    overwrite=False,
    target_lang="pt"
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

    engine = LyricsEngine(genius_token=genius_token, translate=True, target_lang=target_lang)

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

    # Ideal para iSH/iPad: rápido sem bagunçar o terminal
    max_workers = 3

    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        futures = {}
        
        # Mantém a ordem original dos arquivos para impressão sequencial
        for idx, path in enumerate(all_files, 1):
            future = executor.submit(
                _process_single_file,
                str(path),
                engine,
                overwrite,
                idx,
                processed
            )
            # Armazena o index original com o future
            futures[future] = (idx, path)

        # Para imprimir na ordem exata de chegada (ex: [1/20], [2/20]),
        # armazenamos os resultados assim que terminam, e processamos em ordem.
        results_by_idx = {}
        next_to_print = 1

        for future in as_completed(futures):
            idx, path = futures[future]
            try:
                result_data = future.result()
            except Exception as e:
                logger.error(f"[!] Thread execution error: {e}")
                result_data = {"status": "error", "artist": "Unknown", "title": "Unknown", "messages": []}

            # Salva o resultado no dict
            if isinstance(result_data, str):
                 results_by_idx[idx] = {"status": result_data, "messages": []}
            else:
                 results_by_idx[idx] = result_data

            # Imprime tudo que já está pronto e na ordem correta
            while next_to_print in results_by_idx:
                data = results_by_idx[next_to_print]
                status = data.get("status")
                artist = data.get("artist", "Unknown")
                title = data.get("title", "Unknown")
                messages = data.get("messages", [])

                # Imprime o início da busca
                progresso = f"[{next_to_print}/{processed}]"
                safe_print(f"{CYAN}{progresso} Searching: {artist} - {title}{OFF}")

                # Imprime as mensagens retornadas
                for msg in messages:
                    safe_print(msg)

                if status == "injected":
                    injected += 1
                elif status == "skipped":
                    skipped += 1
                elif status == "error":
                    errors += 1

                # Deleta para poupar memória e avança o contador
                del results_by_idx[next_to_print]
                next_to_print += 1

    # =========================
    # FINAL SUMMARY
    # =========================

    safe_print(f"\n{GREEN}[+] Retroactive Scan and Injection Completed!{OFF}")
    safe_print(f"{CYAN}  - TOTAL DE ARQUIVOS ANALISADOS: {processed}{OFF}")
    safe_print(f"{OFF}  - ARQUIVOS EDITADOS/TAGGEADOS: {injected}{OFF}")
    safe_print(f"{YELLOW}  - ARQUIVOS PULADOS (dados já etiquetados ou ausentes): {skipped}{OFF}")

    if errors > 0:
        safe_print(f"{RED}  - Errors encountered: {errors}{OFF}")
    
    safe_print("\n")
