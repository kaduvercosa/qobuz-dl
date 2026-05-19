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
        # Safely create a new event loop for this thread to avoid RuntimeError
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res_tuple = loop.run_until_complete(engine.fetch_and_inject(
                file_path=file_path_str,
                album_artist=search_artist,
                track=title,
                album=album,
                save_lrc=True,
                overwrite=overwrite,
                return_message=True
            ))
        finally:
            loop.close()

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
            f"Existing lyrics will be replaced.{OFF}\n"
        )

    target_dir = Path(directory_path)

    if not target_dir.is_dir():
        safe_print(
            f"{RED}[!] Error: "
            f"The directory '{directory_path}' does not exist.{OFF}\n"
        )
        return

    engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=True, target_lang=target_lang)

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

# =========================
# INTERACTIVE FIX LYRICS
# =========================

async def interactive_fix_lyrics(
    directory_path,
    genius_token=None,
    deepl_api_key=None,
    target_lang="PT-BR"
):
    from pick import pick
    import aiohttp
    import time

    target_dir = Path(directory_path)

    if not target_dir.is_dir():
        print(f"{RED}[!] Error: The directory '{directory_path}' does not exist.{OFF}")
        return

    engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=True, target_lang=target_lang)

    # 1. SCAN DIRECTORY
    all_files = []
    for ext in [".flac", ".mp3"]:
        all_files.extend(list(target_dir.rglob(f"*{ext}")))
        all_files.extend(list(target_dir.rglob(f"*{ext.upper()}")))

    all_files = list(set(all_files))
    all_files.sort()

    if not all_files:
        print(f"{RED}[!] No compatible audio files found in '{directory_path}'.{OFF}")
        return

    # Extract metadata for display
    file_options = []
    file_mapping = {}

    print(f"{CYAN}[*] Scanning {len(all_files)} files to build the interactive menu...{OFF}")

    for path in all_files:
        path_str = str(path)
        path_lower = path_str.lower()
        title, artist = "", ""
        duration = 0

        try:
            if path_lower.endswith(".flac"):
                audio = FLAC(path_str)
                title = audio.get("TITLE", [""])[0]
                artist = audio.get("ARTIST", [""])[0]
                duration = audio.info.length
            elif path_lower.endswith(".mp3"):
                audio = id3.ID3(path_str)
                title = audio.get("TIT2").text[0] if audio.get("TIT2") else ""
                artist = audio.get("TPE1").text[0] if audio.get("TPE1") else ""
                duration = audio.info.length
        except Exception:
            continue

        if title and artist:
            # Sort as Title - Artist.flac
            display_str = f"{title} - {artist}{path.suffix}"
            file_options.append(display_str)
            file_mapping[display_str] = {
                "path": path_str,
                "title": title,
                "artist": artist,
                "duration": duration,
                "album": audio.get("ALBUM", [""])[0] if path_lower.endswith(".flac") else (audio.get("TALB").text[0] if audio.get("TALB") else ""),
                "album_artist": audio.get("ALBUMARTIST", [""])[0] if path_lower.endswith(".flac") else (audio.get("TPE2").text[0] if audio.get("TPE2") else "")
            }

    if not file_options:
        print(f"{RED}[!] Failed to extract metadata from files in '{directory_path}'.{OFF}")
        return

    file_options.sort() # Ensure pure alphabetical order
    file_options.append(">> Exit") # Provide a way to exit the loop

    while True:
        title_text = "Select one or more tracks to fix their lyrics (Press SPACE to select, ENTER to continue):"

        # Enable multiselect
        selected = pick(file_options, title_text, multiselect=True, min_selection_count=1)

        if not selected:
            break

        # Check if user selected the "Exit" option
        if any(item[0] == ">> Exit" for item in selected):
            break

        print(f"\n{CYAN}[*] You selected {len(selected)} tracks to fix.{OFF}")

        for item in selected:
            selected_option = item[0]
            track_info = file_mapping[selected_option]
            await _handle_manual_lyric_search(track_info, engine)

        print(f"\n{GREEN}[+] Batch fix completed! Returning to track list...{OFF}")
        import asyncio
        await asyncio.sleep(1.5)

async def _handle_manual_lyric_search(track_info, engine):
    from pick import pick
    import aiohttp
    import asyncio

    search_artist = track_info["album_artist"] if track_info["album_artist"] and track_info["album_artist"].lower() != "various artists" else track_info["artist"]
    track_title = track_info["title"]
    real_duration = track_info.get("duration", 0)
    real_mins = int(real_duration // 60)
    real_secs = int(real_duration % 60)

    print(f"\n{CYAN}[*] Searching alternatives for: {search_artist} - {track_title}...{OFF}")

    results = []

    # 1. Query LRCLIB search endpoint
    lrclib_url = "https://lrclib.net/api/search"
    headers = {"User-Agent": "qobuz-dl-master/2.5 (https://github.com/kaduvercosa/qobuz-dl)"}
    params = {"track_name": track_title, "artist_name": search_artist}

    async def fetch_lrclib():
        async with aiohttp.ClientSession() as session:
            async with session.get(lrclib_url, params=params, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data:
                        results.append({
                            "provider": "LRCLIB",
                            "duration": item.get("duration", 0),
                            "syncedLyrics": item.get("syncedLyrics"),
                            "plainLyrics": item.get("plainLyrics"),
                            "artistName": item.get("artistName"),
                            "trackName": item.get("trackName"),
                            "albumName": item.get("albumName", "Unknown")
                        })

    # 2. Query LyricsPlus (Apple Music) directly from the engine
    async def fetch_lyricsplus():
        text = await engine._fetch_lyrics_plus(search_artist, track_title)
        if text:
            results.append({
                "provider": "Apple",
                "duration": real_duration, # Apple doesn't return duration, assume perfect match for sorting purposes
                "syncedLyrics": text,
                "plainLyrics": None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "Apple Music"
            })

    # 3. Query Netease directly from the engine
    async def fetch_netease():
        text = await engine._fetch_netease_lyrics(search_artist, track_title)
        if text:
            results.append({
                "provider": "Netease",
                "duration": real_duration, # Assume perfect match for sorting purposes
                "syncedLyrics": text,
                "plainLyrics": None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "Netease"
            })

    # 4. Query Genius directly from the engine
    async def fetch_genius():
        if engine.genius:
            song = await asyncio.to_thread(engine.genius.search_song, track_title, search_artist)
            if song and song.lyrics:
                results.append({
                    "provider": "Genius",
                    "duration": 0, # Genius has no duration
                    "syncedLyrics": None,
                    "plainLyrics": song.lyrics,
                    "artistName": search_artist,
                    "trackName": track_title,
                    "albumName": "Genius"
                })

    try:
        await asyncio.gather(
            fetch_lrclib(),
            fetch_lyricsplus(),
            fetch_netease(),
            fetch_genius()
        )
    except Exception as e:
        print(f"{RED}[!] Search failed: {e}{OFF}")
        return

    if not results:
        print(f"{YELLOW}[!] No alternative lyrics found for this track across all providers.{OFF}")
        await asyncio.sleep(2)
        return

    # Format options for pick
    options = []
    option_mapping = {}

    # Sort results by how close they are to the real duration (providers with duration=0 like Genius go last)
    def sort_key(r):
        dur = r.get("duration", 0)
        if dur == 0: return float('inf')
        return abs(dur - real_duration)

    results.sort(key=sort_key)

    for res in results:
        duration_sec = res.get("duration", 0)
        if duration_sec > 0:
            minutes = int(duration_sec // 60)
            seconds = int(duration_sec % 60)
            duration_str = f"[{minutes:02d}:{seconds:02d}]"

            diff = abs(duration_sec - real_duration)
            diff_str = f"(Match! {diff:.0f}s dif)" if diff <= 2 else f"({diff:.0f}s dif)"
        else:
            duration_str = "[--:--]"
            diff_str = ""

        sync_status = "[Synced]" if res.get("syncedLyrics") else "[Unsynced]"
        provider = res.get("provider")

        display = f"{duration_str} | {provider} | {diff_str} {res.get('artistName')} - {res.get('trackName')} {sync_status} (Album: {res.get('albumName')})"
        # Clean up double spaces if diff_str is empty
        display = display.replace("  ", " ")
        options.append(display)
        option_mapping[display] = res

    options.append(">> Cancel / Back to Track List")

    title_prompt = f"Target Duration: [{real_mins:02d}:{real_secs:02d}] | File: {track_title}\nChoose the alternative lyric:"
    selected_option, index = pick(options, title_prompt, indicator="* ")

    if selected_option == ">> Cancel / Back to Track List":
        return

    chosen_lyric_data = option_mapping[selected_option]

    # Proceed to inject manually
    print(f"\n{GREEN}[+] Downloading and injecting chosen lyrics...{OFF}")

    success = await engine.inject_manual_lyrics(
        file_path=track_info["path"],
        raw_lyrics=chosen_lyric_data.get("syncedLyrics") or chosen_lyric_data.get("plainLyrics"),
        is_synced=bool(chosen_lyric_data.get("syncedLyrics"))
    )

    if success:
        print(f"{GREEN}[+] Lyrics successfully replaced!{OFF}")
    else:
        print(f"{RED}[!] Failed to inject lyrics.{OFF}")

    await asyncio.sleep(2)
