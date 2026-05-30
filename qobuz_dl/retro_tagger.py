import os
import time
import logging
from pathlib import Path
from threading import Lock
import asyncio
import aiohttp
from typing import Tuple, Dict, Any, List

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError

from qobuz_dl.lyrics_engine import LyricsEngine
from qobuz_dl.color import CYAN, GREEN, YELLOW, RED, OFF

logger = logging.getLogger(__name__)

# =========================
# THREAD-SAFE PRINT & STATE
# =========================

print_lock = Lock()

def safe_print(message: str) -> None:
    """Garante que as mensagens no terminal não se sobrepõem quando usamos concorrência."""
    with print_lock:
        print(message, flush=True)

class ScanState:
    """Classe dedicada para rastrear o progresso e evitar erros de dicionário em concorrência."""
    def __init__(self, total_files: int):
        self.processed = total_files
        self.files_done = 0
        self.injected = 0
        self.skipped = 0
        self.errors = 0
        self.elapsed_times = []
        self.scan_start = time.monotonic()


# =========================
# HELPER: METADATA EXTRACTION
# =========================

def _extract_metadata(file_path: Path) -> Dict[str, Any]:
    """
    Lê as tags do ficheiro de áudio e centraliza a extração de dados.
    Evita repetição de código nas funções principais.
    """
    data = {
        "title": "", 
        "artist": "", 
        "album_artist": "", 
        "album": "", 
        "has_lyrics": False, 
        "duration": 0.0
    }
    
    try:
        if file_path.suffix.lower() == ".flac":
            audio = FLAC(file_path)
            data["title"] = audio.get("TITLE", [""])[0]
            data["artist"] = audio.get("ARTIST", [""])[0]
            data["album_artist"] = audio.get("ALBUMARTIST", [""])[0]
            data["album"] = audio.get("ALBUM", [""])[0]
            data["has_lyrics"] = bool(audio.get("LYRICS") or audio.get("UNSYNCEDLYRICS") or audio.get("LYRICS_SYNCED"))
            data["duration"] = audio.info.length

        elif file_path.suffix.lower() == ".mp3":
            try:
                audio_id3 = id3.ID3(file_path)
            except ID3NoHeaderError:
                audio_id3 = id3.ID3()
                
            mp3_audio = MP3(file_path)
            data["title"] = audio_id3.get("TIT2").text[0] if audio_id3.get("TIT2") else ""
            data["artist"] = audio_id3.get("TPE1").text[0] if audio_id3.get("TPE1") else ""
            data["album_artist"] = audio_id3.get("TPE2").text[0] if audio_id3.get("TPE2") else ""
            data["album"] = audio_id3.get("TALB").text[0] if audio_id3.get("TALB") else ""
            data["has_lyrics"] = bool(audio_id3.getall("USLT") or audio_id3.getall("SYLT"))
            data["duration"] = mp3_audio.info.length

    except Exception as e:
        logger.debug(f"Erro ao ler metadados de {file_path.name}: {e}")

    return data


# =========================
# PROCESS SINGLE FILE
# =========================

async def _process_single_file(semaphore: asyncio.Semaphore, file_path: Path, engine: Any, 
                               state: ScanState, overwrite: bool = False, current_idx: int = 0, 
                               total_files: int = 0, max_workers: int = 3) -> None:
    async with semaphore:
        status_result = "skipped"
        msg = ""
        elapsed = None

        try:
            meta = _extract_metadata(file_path)
            title = meta["title"]
            artist = meta["artist"]
            album_artist = meta["album_artist"]
            has_lyrics = meta["has_lyrics"]
            
            if not title or not artist:
                return

            search_artist = album_artist if album_artist and album_artist.lower() != "various artists" else artist

            if not overwrite and has_lyrics:
                msg = f"{YELLOW}  [*] Ignorado (Já Marcado): {title} - {search_artist}{OFF}"
                return

            safe_print(f"{CYAN}[{current_idx}/{total_files}] Buscando: {title} - {search_artist}...{OFF}")
            task_start = time.monotonic()

            res_tuple = await engine.fetch_and_inject(
                file_path=str(file_path),
                album_artist=search_artist,
                track=title,
                album=meta["album"],
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
                    msg = f"{CYAN}[*] Letra Já Existente (Local): {title} - {search_artist}{OFF}"
                else:
                    if total_lines > 0 and trans_count > 0:
                        trans_type = "Total" if trans_count >= total_lines else "Parcial"
                        trad_str = f"{trans_count}/{total_lines} - ({trans_type})"
                    else:
                        trad_str = "Não"
                    msg = f"{OFF}  [*] Letra Encontrada: {title} - {search_artist} | Tradução: {trad_str} | Response_Code: {resp_code} | Tempo: {elapsed:.1f}s{OFF}"
            else:
                status_result = "skipped"
                msg = f"{YELLOW}  [!] Falha ao obter letra para: {title} - {search_artist} | Code: {resp_code or 'Não'} | Tempo: {elapsed:.1f}s{OFF}"

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in _process_single_file: {e}", exc_info=True)
            status_result = "error"
            msg = f"{RED}[!] Error processing {file_path.name}: {e}{OFF}"

        finally:
            state.files_done += 1
            if elapsed is not None:
                state.elapsed_times.append(elapsed)

            if status_result == "injected": state.injected += 1
            elif status_result == "error": state.errors += 1
            else: state.skipped += 1

            # Calcula o ETA
            remaining = state.processed - state.files_done
            eta_info = None
            if state.elapsed_times and remaining > 0:
                avg_time = sum(state.elapsed_times) / len(state.elapsed_times)
                eta_sec = (remaining * avg_time) / max_workers
                eta_str = f"{int(eta_sec // 60)}m{int(eta_sec % 60):02d}s" if eta_sec >= 60 else f"{eta_sec:.0f}s"
                eta_info = f"{CYAN}[ETA: ~{eta_str} restantes para {remaining} arquivo(s)]{OFF}"
            elif remaining == 0:
                total_sec = time.monotonic() - state.scan_start
                total_str = f"{int(total_sec // 60)}m{int(total_sec % 60):02d}s" if total_sec >= 60 else f"{total_sec:.0f}s"
                eta_info = f"{GREEN}  [Concluído em {total_str}]{OFF}"

            output_parts = [m for m in (msg, eta_info) if m]
            if output_parts:
                safe_print("\n".join(output_parts))


# =========================
# MAIN RETRO SCAN
# =========================

async def inject_lyrics_retroactively(directory_path: str, genius_token: str = None, 
                                      deepl_api_key: str = None, overwrite: bool = False, 
                                      target_lang: str = "PT-BR") -> None:
    safe_print(f"\n{CYAN}[*] Starting retroactive lyrics scan in: {directory_path}{OFF}\n")

    if overwrite:
        safe_print(f"{RED}[!] OVERWRITE MODE ENABLED: Existing lyrics will be replaced.{OFF}\n")

    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        safe_print(f"{RED}[!] Error: The directory '{directory_path}' does not exist.{OFF}\n")
        return

    engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=True, target_lang=target_lang)

    # Usa rglob para encontrar ficheiros de forma eficiente
    all_files = [p for p in target_dir.rglob('*') if p.is_file() and p.suffix.lower() in {'.flac', '.mp3'}]

    state = ScanState(len(all_files))
    safe_print(f"{CYAN}[*] Found {state.processed} compatible audio files. Processing...{OFF}\n")

    max_workers = 3
    semaphore = asyncio.Semaphore(max_workers)

    tasks = [
        asyncio.create_task(_process_single_file(semaphore, path, engine, state, overwrite, idx, state.processed, max_workers))
        for idx, path in enumerate(all_files, 1)
    ]

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
    safe_print(f"{YELLOW}  - ARQUIVOS PULADOS: {state.skipped}{OFF}")

    if state.errors > 0:
        safe_print(f"{RED}  - Errors encountered: {state.errors}{OFF}")
    safe_print("\n")


# =========================
# INTERACTIVE FIX LYRICS
# =========================

async def interactive_fix_lyrics(directory_path: str, genius_token: str = None, 
                                 deepl_api_key: str = None, target_lang: str = "PT-BR") -> None:
    from pick import pick

    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        print(f"{RED}[!] Error: The directory '{directory_path}' does not exist.{OFF}")
        return

    engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=True, target_lang=target_lang)

    all_files = sorted([p for p in target_dir.rglob('*') if p.is_file() and p.suffix.lower() in {'.flac', '.mp3'}])

    if not all_files:
        print(f"{RED}[!] No compatible audio files found in '{directory_path}'.{OFF}")
        return

    file_options = []
    file_mapping = {}

    print(f"{CYAN}[*] Scanning {len(all_files)} files to build the interactive menu...{OFF}")

    for path in all_files:
        meta = _extract_metadata(path)

        if meta["title"] and meta["artist"]:
            display_str = f"{meta['title']} - {meta['artist']}{path.suffix}"
            file_options.append(display_str)
            file_mapping[display_str] = {
                "path": str(path),
                "title": meta["title"],
                "artist": meta["artist"],
                "duration": meta["duration"],
                "album": meta["album"],
                "album_artist": meta["album_artist"]
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

async def _handle_manual_lyric_search(track_info: dict, engine: Any) -> None:
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

    async def fetch_lyricsplus():
        text = await engine._fetch_lyrics_plus(search_artist, track_title)
        if text:
            results.append({
                "provider": "Apple",
                "duration": real_duration, 
                "syncedLyrics": text,
                "plainLyrics": None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "Apple Music"
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
            minutes, seconds = int(duration_sec // 60), int(duration_sec % 60)
            duration_str = f"[{minutes:02d}:{seconds:02d}]"
            diff = abs(duration_sec - real_duration)
            diff_str = f"(Match! {diff:.0f}s dif)" if diff <= 2 else f"({diff:.0f}s dif)"
        else:
            duration_str = "[--:--]"
            diff_str = ""

        sync_status = "[Synced]" if res.get("syncedLyrics") else "[Unsynced]"
        display = f"{duration_str} | {res.get('provider')} | {diff_str} {res.get('artistName')} - {res.get('trackName')} {sync_status} (Album: {res.get('albumName')})".replace("  ", " ")
        
        options.append(display)
        option_mapping[display] = res

    options.append(">> Cancel / Back to Track List")

    title_prompt = f"Target Duration: [{real_mins:02d}:{real_secs:02d}] | File: {track_title}\nChoose the alternative lyric:"
    selected_option, _ = pick(options, title_prompt, indicator="* ")

    if selected_option == ">> Cancel / Back to Track List":
        return

    chosen_lyric_data = option_mapping[selected_option]

    print(f"\n{GREEN}[+] Downloading and injecting chosen lyrics...{OFF}")

    result = await engine.inject_manual_lyrics(
        file_path=track_info["path"],
        raw_lyrics=chosen_lyric_data.get("syncedLyrics") or chosen_lyric_data.get("plainLyrics"),
        is_synced=bool(chosen_lyric_data.get("syncedLyrics"))
    )

    success, trans_count, total_lines = result if isinstance(result, tuple) else (result, 0, 0)

    if success:
        provider = chosen_lyric_data.get("provider", "Unknown")
        trad_str = f"{trans_count}/{total_lines} - ({'Total' if trans_count >= total_lines else 'Parcial'})" if (total_lines > 0 and trans_count > 0) else "Não"
        print(f"{OFF}  [*] Letra Encontrada: {track_title} - {search_artist} | Tradução: {trad_str} | Response_Code: {provider}{OFF}")
        print(f"{GREEN}[+] Lyrics successfully replaced!{OFF}")
    else:
        print(f"{RED}[!] Failed to inject lyrics.{OFF}")

    await asyncio.sleep(2)