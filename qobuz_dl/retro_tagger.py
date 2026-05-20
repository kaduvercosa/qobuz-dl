import os
import time
import logging
from pathlib import Path
from mutagen.flac import FLAC
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError
from threading import Lock
import asyncio
import aiohttp

from qobuz_dl.lyrics_engine import LyricsEngine
from qobuz_dl.color import CYAN, GREEN, YELLOW, RED, OFF

logger = logging.getLogger(__name__)

# =========================
# THREAD-SAFE PRINT & STATE
# =========================

print_lock = Lock()

def safe_print(message):
    with print_lock:
        print(message, flush=True)

class ScanState:
    """Classe dedicada para evitar qualquer possibilidade de KeyError em dicionários assíncronos."""
    def __init__(self, total_files):
        self.processed = total_files
        self.files_done = 0
        self.injected = 0
        self.skipped = 0
        self.errors = 0
        self.elapsed_times = []
        self.scan_start = time.monotonic()

# =========================
# PROCESS SINGLE FILE
# =========================

async def _process_single_file(semaphore, file_path_str, engine, state, overwrite=False, current_idx=0, total_files=0):
    async with semaphore:
        status_result = "skipped"
        msg = ""
        elapsed = None
        search_artist = "Unknown"
        title = "Unknown"

        try:
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
                if audio.get("LYRICS") or audio.get("UNSYNCEDLYRICS") or audio.get("LYRICS_SYNCED"):
                    has_lyrics = True
                else:
                    has_lyrics = False

                title = audio.get("TITLE", [""])[0]
                artist = audio.get("ARTIST", [""])[0]
                album_artist = audio.get("ALBUMARTIST", [""])[0]
                album = audio.get("ALBUM", [""])[0]

            # =========================
            # MP3
            # =========================
            elif file_path_lower.endswith(".mp3"):
                try:
                    audio_id3 = id3.ID3(file_path_str)
                except ID3NoHeaderError:
                    return

                if audio_id3.getall("USLT") or audio_id3.getall("SYLT"):
                    has_lyrics = True
                else:
                    has_lyrics = False

                title = audio_id3.get("TIT2").text[0] if audio_id3.get("TIT2") else ""
                artist = audio_id3.get("TPE1").text[0] if audio_id3.get("TPE1") else ""
                album_artist = audio_id3.get("TPE2").text[0] if audio_id3.get("TPE2") else ""
                album = audio_id3.get("TALB").text[0] if audio_id3.get("TALB") else ""

            # =========================
            # VALIDATION & LOGIC
            # =========================

            if not title or not artist:
                return

            search_artist = album_artist if album_artist and album_artist.lower() != "various artists" else artist

            if not overwrite and has_lyrics:
                msg = f"{Y}  [*] Ignorado (Já Marcado): {title} - {search_artist}{O}"
                return

            # =========================
            # SEARCH & INJECT
            # =========================
            safe_print(f"{C}[{current_idx}/{total_files}] Buscando: {title} - {search_artist}...{O}")
            task_start = time.monotonic()

            res_tuple = await engine.fetch_and_inject(
                file_path=file_path_str,
                album_artist=search_artist,
                track=title,
                album=album,
                save_lrc=True,
                overwrite=overwrite
            )

            elapsed = time.monotonic() - task_start

            success = res_tuple[0]
            trans_count = res_tuple[1] if len(res_tuple) > 1 else 0
            total_lines = res_tuple[2] if len(res_tuple) > 2 else 0
            resp_code = res_tuple[3] if len(res_tuple) > 3 else "Unknown"

            if success:
                status_result = "injected"
                if resp_code == "Local":
                    msg = f"{C}[*] Letra Já Existente (Local): {title} - {search_artist}{O}"
                else:
                    if total_lines > 0 and trans_count > 0:
                        trans_type = "Total" if trans_count >= total_lines else "Parcial"
                        trad_str = f"{trans_count}/{total_lines} - ({trans_type})"
                    elif total_lines > 0:
                        trad_str = "Não"
                    else:
                        trad_str = "Não"
                    msg = f"{O}  [*] Letra Encontrada: {title} - {search_artist} | Tradução: {trad_str} | Response_Code: {resp_code} | Tempo: {elapsed:.1f}s{O}"
            else:
                status_result = "skipped"
                resp_str = resp_code if resp_code else "Não"
                msg = f"{Y}  [!] Falha ao obter letra para: {title} - {search_artist} | Code: {resp_str} | Tempo: {elapsed:.1f}s{O}"

        except asyncio.CancelledError:
            # Captura cancelamentos (Ctrl+C ou timeout) silenciosamente
            raise
        except Exception as e:
            logger.error(f"Error in _process_single_file: {e}", exc_info=True)
            status_result = "error"
            msg = f"{RED_COLOR}[!] Error processing {file_path_str}: {e}{O}"

        finally:
            # Atualiza o estado global imediatamente antes de sair do semáforo
            # Usando atributos da classe, KeyError não existe mais.
            state.files_done += 1
            
            if elapsed is not None:
                state.elapsed_times.append(elapsed)

            if status_result == "injected":
                state.injected += 1
            elif status_result == "error":
                state.errors += 1
            else:
                state.skipped += 1

            # Calcula o ETA
            remaining = state.processed - state.files_done
            eta_info = None
            if state.elapsed_times and remaining > 0:
                avg_time = sum(state.elapsed_times) / len(state.elapsed_times)
                eta_sec = (remaining * avg_time) / 3  # max_workers = 3
                if eta_sec >= 60:
                    eta_str = f"{int(eta_sec // 60)}m{int(eta_sec % 60):02d}s"
                else:
                    eta_str = f"{eta_sec:.0f}s"
                eta_info = f"{CYAN}[ETA: ~{eta_str} restantes para {remaining} arquivo(s)]{O}"
            elif remaining == 0:
                total_sec = time.monotonic() - state.scan_start
                if total_sec >= 60:
                    total_str = f"{int(total_sec // 60)}m{int(total_sec % 60):02d}s"
                else:
                    total_str = f"{total_sec:.0f}s"
                eta_info = f"{G}  [Concluído em {total_str}]{O}"

            # Exibe o bloco visual (garante ordem cronológica)
            output_parts = []
            if msg:
                output_parts.append(msg)
            if eta_info:
                output_parts.append(eta_info)

            if output_parts:
                safe_print("\n".join(output_parts))


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
    safe_print(f"\n{CYAN}[*] Starting retroactive lyrics scan in: {directory_path}{OFF}\n")

    if overwrite:
        safe_print(f"{RED}[!] OVERWRITE MODE ENABLED: Existing lyrics will be replaced.{OFF}\n")

    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        safe_print(f"{RED}[!] Error: The directory '{directory_path}' does not exist.{OFF}\n")
        return

    engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=True, target_lang=target_lang)

    all_files = []
    for ext in [".flac", ".mp3"]:
        all_files.extend(list(target_dir.rglob(f"*{ext}")))
        all_files.extend(list(target_dir.rglob(f"*{ext.upper()}")))

    all_files = list(set(all_files))

    # Objeto de estado seguro (evita KeyError)
    state = ScanState(len(all_files))

    safe_print(f"{CYAN}[*] Found {state.processed} compatible audio files. Processing...{OFF}\n")

    max_workers = 3
    semaphore = asyncio.Semaphore(max_workers)

    tasks = []
    for idx, path in enumerate(all_files, 1):
        task = asyncio.create_task(
            _process_single_file(
                semaphore,
                str(path),
                engine,
                state,
                overwrite,
                idx,
                state.processed
            )
        )
        tasks.append(task)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        safe_print(f"\n{RED}[!] Processo interrompido pelo usuário.{OFF}\n")

    # =========================
    # FINAL SUMMARY
    # =========================
    safe_print(f"\n{GREEN}[+] Retroactive Scan and Injection Completed!{OFF}")
    safe_print(f"{CYAN}  - TOTAL DE ARQUIVOS ANALISADOS: {state.processed}{OFF}")
    safe_print(f"{OFF}  - ARQUIVOS EDITADOS/TAGGEADOS: {state.injected}{OFF}")
    safe_print(f"{YELLOW}  - ARQUIVOS PULADOS (dados já etiquetados ou ausentes): {state.skipped}{OFF}")

    if state.errors > 0:
        safe_print(f"{RED}  - Errors encountered: {state.errors}{OFF}")
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

    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        print(f"{RED}[!] Error: The directory '{directory_path}' does not exist.{OFF}")
        return

    engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=True, target_lang=target_lang)

    all_files = []
    for ext in [".flac", ".mp3"]:
        all_files.extend(list(target_dir.rglob(f"*{ext}")))
        all_files.extend(list(target_dir.rglob(f"*{ext.upper()}")))

    all_files = list(set(all_files))
    all_files.sort()

    if not all_files:
        print(f"{RED}[!] No compatible audio files found in '{directory_path}'.{OFF}")
        return

    file_options = []
    file_mapping = {}

    print(f"{CYAN}[*] Scanning {len(all_files)} files to build the interactive menu...{OFF}")

    for path in all_files:
        path_str = str(path)
        path_lower = path_str.lower()
        title, artist, album, album_artist = "", "", "", ""
        duration = 0

        try:
            if path_lower.endswith(".flac"):
                audio = FLAC(path_str)
                title = audio.get("TITLE", [""])[0]
                artist = audio.get("ARTIST", [""])[0]
                duration = audio.info.length
                album = audio.get("ALBUM", [""])[0]
                album_artist = audio.get("ALBUMARTIST", [""])[0]
            elif path_lower.endswith(".mp3"):
                from mutagen.mp3 import MP3
                mp3_audio = MP3(path_str)
                tags = mp3_audio.tags or id3.ID3()
                title = tags.get("TIT2").text[0] if tags.get("TIT2") else ""
                artist = tags.get("TPE1").text[0] if tags.get("TPE1") else ""
                duration = mp3_audio.info.length
                album = tags.get("TALB").text[0] if tags.get("TALB") else ""
                album_artist = tags.get("TPE2").text[0] if tags.get("TPE2") else ""
        except Exception:
            continue

        if title and artist:
            display_str = f"{title} - {artist}{path.suffix}"
            file_options.append(display_str)
            file_mapping[display_str] = {
                "path": path_str,
                "title": title,
                "artist": artist,
                "duration": duration,
                "album": album,
                "album_artist": album_artist
            }

    if not file_options:
        print(f"{RED}[!] Failed to extract metadata from files in '{directory_path}'.{OFF}")
        return

    file_options.sort()

    while True:
        title_text = "Select one or more tracks to fix their lyrics\n(Press SPACE to select, ENTER to continue, or CTRL+C to Exit):"

        try:
            selected = pick(file_options, title_text, multiselect=True, min_selection_count=1)
        except KeyboardInterrupt:
            break

        if not selected:
            break

        print(f"\n{CYAN}[*] You selected {len(selected)} tracks to fix.{OFF}")

        for item in selected:
            selected_option = item[0]
            track_info = file_mapping[selected_option]
            await _handle_manual_lyric_search(track_info, engine)

        print(f"\n{GREEN}[+] Batch fix completed! Returning to track list...{OFF}")
        await asyncio.sleep(1.5)

async def _handle_manual_lyric_search(track_info, engine):
    from pick import pick

    search_artist = track_info["album_artist"] if track_info["album_artist"] and track_info["album_artist"].lower() != "various artists" else track_info["artist"]
    track_title = track_info["title"]
    real_duration = track_info.get("duration", 0)
    real_mins = int(real_duration // 60)
    real_secs = int(real_duration % 60)

    print(f"\n{CYAN}[*] Searching alternatives for: {search_artist} - {track_title}...{OFF}")

    results = []

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

    async def fetch_musixmatch():
        text = await engine._fetch_musixmatch_lyrics(search_artist, track_title)
        if text:
            results.append({
                "provider": "Musixmatch",
                "duration": real_duration,
                "syncedLyrics": text,
                "plainLyrics": None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "Musixmatch"
            })

    async def fetch_lyricsplus():
        text = await engine._fetch_lyrics_plus(search_artist, track_title)
        if text:
            results.append({
                "provider": "LyricsPlus",
                "duration": real_duration,
                "syncedLyrics": text,
                "plainLyrics": None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "LyricsPlus"
            })

    async def fetch_netease():
        text = await engine._fetch_netease_lyrics(search_artist, track_title)
        if text:
            results.append({
                "provider": "Netease",
                "duration": real_duration,
                "syncedLyrics": text,
                "plainLyrics": None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "Netease"
            })

    async def fetch_genius():
        if engine.genius:
            song = await asyncio.to_thread(engine.genius.search_song, track_title, search_artist)
            if song and song.lyrics:
                results.append({
                    "provider": "Genius",
                    "duration": 0,
                    "syncedLyrics": None,
                    "plainLyrics": song.lyrics,
                    "artistName": search_artist,
                    "trackName": track_title,
                    "albumName": "Genius"
                })

    try:
        await asyncio.gather(fetch_lrclib(), fetch_musixmatch(), fetch_lyricsplus(), fetch_netease(), fetch_genius())
    except Exception as e:
        print(f"{RED}[!] Search failed: {e}{OFF}")
        return

    if not results:
        print(f"{YELLOW}[!] No alternative lyrics found for this track across all providers.{OFF}")
        await asyncio.sleep(2)
        return

    options = []
    option_mapping = {}

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
        display = display.replace("  ", " ")
        options.append(display)
        option_mapping[display] = res

    options.append(">> Cancel / Back to Track List")

    title_prompt = f"Target Duration: [{real_mins:02d}:{real_secs:02d}] | File: {track_title}\nChoose the alternative lyric:"
    selected_option, index = pick(options, title_prompt, indicator="* ")

    if selected_option == ">> Cancel / Back to Track List":
        return

    chosen_lyric_data = option_mapping[selected_option]
    print(f"\n{GREEN}[+] Downloading and injecting chosen lyrics...{OFF}")

    result = await engine.inject_manual_lyrics(
        file_path=track_info["path"],
        raw_lyrics=chosen_lyric_data.get("syncedLyrics") or chosen_lyric_data.get("plainLyrics"),
        is_synced=bool(chosen_lyric_data.get("syncedLyrics"))
    )

    if isinstance(result, tuple):
        success, trans_count, total_lines = result
    else:
        success, trans_count, total_lines = result, 0, 0

    if success:
        provider = chosen_lyric_data.get("provider", "Unknown")
        if total_lines > 0 and trans_count > 0:
            trans_type = "Total" if trans_count >= total_lines else "Parcial"
            trad_str = f"{trans_count}/{total_lines} - ({trans_type})"
        elif total_lines > 0:
            trad_str = "Não"
        else:
            trad_str = "Não"

        O = "\033[0m"
        print(f"{O}  [*] Letra Encontrada: {track_title} - {search_artist} | Tradução: {trad_str} | Response_Code: {provider}{O}")
        print(f"{GREEN}[+] Lyrics successfully replaced!{OFF}")
    else:
        print(f"{RED}[!] Failed to inject lyrics.{OFF}")

    await asyncio.sleep(2)