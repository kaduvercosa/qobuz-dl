import os
import logging
from pathlib import Path
from mutagen.flac import FLAC
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError
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

async def _process_single_file(semaphore, file_path_str, engine, overwrite=False, current_idx=0, total_files=0):
    async with semaphore:
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
                    return current_idx, {"status": "skipped", "artist": "Unknown", "title": "Unknown", "messages": []}

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
                return current_idx, {"status": "skipped", "artist": artist or "Unknown", "title": title or "Unknown", "messages": []}

            # Prioriza o Álbum Artista para não quebrar na busca (exceto se for Various Artists)
            search_artist = album_artist if album_artist and album_artist.lower() != "various artists" else artist

            # Se não for overwrite e já tiver letra, avisa e pula
            if not overwrite and has_lyrics:
                return current_idx, {
                    "status": "skipped",
                    "artist": search_artist,
                    "title": title,
                    "messages": [f"{Y}  [*] Ignorado (Já Marcado): {title} - {search_artist}{O}"]
                }

            # =========================
            # SEARCH & INJECT
            # =========================

            # Instead of printing inside the thread, return the results to print sequentially
            res_tuple = await engine.fetch_and_inject(
                file_path=file_path_str,
                album_artist=search_artist,
                track=title,
                album=album,
                save_lrc=True,
                overwrite=overwrite
            )

            # Unpack the new return signature (success, trans_count, total_lines, status_code)
            success = res_tuple[0]
            trans_count = res_tuple[1] if len(res_tuple) > 1 else 0
            total_lines = res_tuple[2] if len(res_tuple) > 2 else 0
            resp_code = res_tuple[3] if len(res_tuple) > 3 else "Unknown"

            messages = []
            if success:
                if resp_code == "Local":
                    messages.append(f"{C}[*] Letra Já Existente (Local): {title} - {search_artist}{O}")
                else:
                    if total_lines > 0 and trans_count > 0:
                        trans_type = "Total" if trans_count >= total_lines else "Parcial"
                        trad_str = f"{trans_count}/{total_lines} - ({trans_type})"
                    elif total_lines > 0:
                        trad_str = "Não"
                    else:
                        trad_str = "Não"
                    messages.append(f"{O}  [*] Letra Encontrada: {title} - {search_artist} | Tradução: {trad_str} | Response_Code: {resp_code}{O}")
            else:
                resp_str = resp_code if resp_code else "Não"
                messages.append(f"{Y}  [!] Falha ao obter letra para: {title} - {search_artist} | Code: {resp_str}{O}")

            status_result = "injected" if success else "skipped"
            return current_idx, {"status": status_result, "artist": search_artist, "title": title, "messages": messages}

        except Exception as e:
            logger.error(f"Error in _process_single_file: {e}", exc_info=True)
            return current_idx, {"status": "error", "artist": "Unknown", "title": "Unknown", "messages": [f"{RED}[!] Error processing {file_path_str}: {e}{OFF}"]}

    return current_idx, {"status": "skipped", "artist": "Unknown", "title": "Unknown", "messages": []}


# =========================
# MAIN RETRO SCAN
# =========================

async def inject_lyrics_retroactively(
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
    semaphore = asyncio.Semaphore(max_workers)

    tasks = []

    # Mantém a ordem original dos arquivos para impressão sequencial
    for idx, path in enumerate(all_files, 1):
        task = asyncio.create_task(
            _process_single_file(
                semaphore,
                str(path),
                engine,
                overwrite,
                idx,
                processed
            )
        )
        tasks.append(task)

    # Processa assim que terminam para feedback imediato no terminal
    files_done = 0

    for future in asyncio.as_completed(tasks):
        try:
            result = await future
            idx, result_data = result
        except Exception as e:
            logger.error(f"[!] Async execution error: {e}")
            files_done += 1
            continue # We can't recover the idx safely here if the task threw without returning it.

        files_done += 1

        if isinstance(result_data, str):
             data = {"status": result_data, "messages": []}
        else:
             data = result_data

        status = data.get("status")
        artist = data.get("artist", "Unknown")
        title = data.get("title", "Unknown")
        messages = data.get("messages", [])

        # Usa o lock nativo do safe_print para evitar mensagens bagunçadas
        progresso = f"[{files_done}/{processed}]"

        # Constrói um único bloco de impressão para não cruzar dados no terminal
        output_block = f"{CYAN}{progresso} Processed: {artist} - {title}{OFF}"
        for msg in messages:
            output_block += f"\n{msg}"

        safe_print(output_block)

        if status == "injected":
            injected += 1
        elif status == "skipped":
            skipped += 1
        elif status == "error":
            errors += 1

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

    while True:
        title_text = "Select one or more tracks to fix their lyrics\n(Press SPACE to select, ENTER to continue, or CTRL+C to Exit):"

        # Enable multiselect
        try:
            selected = pick(file_options, title_text, multiselect=True, min_selection_count=1)
        except KeyboardInterrupt:
            # Captures CTRL+C to act as the Exit/Back button cleanly
            break

        if not selected:
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
            async with session.get(lrclib_url, params=params, headers=headers, timeout=35) as resp:
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

    # 2. Query Musixmatch directly from the engine
    async def fetch_musixmatch():
        text = await engine._fetch_musixmatch_lyrics(search_artist, track_title)
        if text:
            results.append({
                "provider": "Musixmatch",
                "duration": real_duration, # Assume perfect match for sorting purposes
                "syncedLyrics": text,
                "plainLyrics": None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "Musixmatch"
            })

    # 3. Query LyricsPlus directly from the engine
    async def fetch_lyricsplus():
        text = await engine._fetch_lyrics_plus(search_artist, track_title)
        if text:
            results.append({
                "provider": "LyricsPlus",
                "duration": real_duration, # Assume perfect match for sorting purposes
                "syncedLyrics": text,
                "plainLyrics": None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "LyricsPlus"
            })

    # 4. Query Netease directly from the engine
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

    # 5. Query Genius directly from the engine
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
            fetch_musixmatch(),
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

    result = await engine.inject_manual_lyrics(
        file_path=track_info["path"],
        raw_lyrics=chosen_lyric_data.get("syncedLyrics") or chosen_lyric_data.get("plainLyrics"),
        is_synced=bool(chosen_lyric_data.get("syncedLyrics"))
    )

    # inject_manual_lyrics agora retorna (success, trans_count, total_lines)
    # para que possamos exibir o mesmo log que aparece nos downloads e no overwrite.
    if isinstance(result, tuple):
        success, trans_count, total_lines = result
    else:
        success, trans_count, total_lines = result, 0, 0

    if success:
        # Monta o mesmo "Letra Encontrada" do modo normal / overwrite
        provider = chosen_lyric_data.get("provider", "Unknown")
        if total_lines > 0 and trans_count > 0:
            trans_type = "Total" if trans_count >= total_lines else "Parcial"
            trad_str = f"{trans_count}/{total_lines} - ({trans_type})"
        elif total_lines > 0:
            trad_str = "Não"
        else:
            trad_str = "Não"

        C = "\033[96m"
        O = "\033[0m"
        print(f"{O}  [*] Letra Encontrada: {track_title} - {search_artist} | Tradução: {trad_str} | Response_Code: {provider}{O}")
        print(f"{GREEN}[+] Lyrics successfully replaced!{OFF}")
    else:
        print(f"{RED}[!] Failed to inject lyrics.{OFF}")

    await asyncio.sleep(2)
