import os
import re
import time
import logging
from pathlib import Path
from threading import Lock
import asyncio
import aiohttp
from typing import Tuple, Dict, Any, List
from pick import pick

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
    """Garante que as mensagens no terminal nao se sobrepoem quando usamos concorrencia."""
    with print_lock:
        print(message, flush=True)

class ScanState:
    """Classe dedicada para rastrear o progresso e evitar erros de dicionario em concorrencia."""
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
    Le as tags do ficheiro de audio e centraliza a extracao de dados.
    Evita repeticao de codigo nas funcoes principais.
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
                               total_files: int = 0, max_workers: int = 1) -> None:
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
                status_result = "skipped"
                msg = f"{YELLOW} [SEM METADADOS] {file_path.name}{OFF}"
                return

            raw_artist = album_artist if album_artist and album_artist.lower() != "various artists" else artist
            search_artist = re.split(r'(?i)\s*(?:,|\&| feat\.| ft\.|;|\/)\s*',raw_artist)[0].strip()

            if not overwrite and has_lyrics:
                msg = f"{YELLOW}  [*] Ignorado (Ja Marcado): {title} - {search_artist}{OFF}"
                return

            safe_print(f"{GREEN}[{current_idx}/{total_files}] Buscando: {title} - {search_artist}...{OFF}")
            task_start = time.monotonic()

            res_tuple = await engine.fetch_and_inject(
                file_path=str(file_path),
                album_artist=search_artist,
                track=title,
                album=meta["album"],
                duration=meta["duration"],
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
                    msg = f"{CYAN}[*] Letra Ja Existente (Local): {title} - {search_artist}{OFF}"
                else:
                    if total_lines > 0 and trans_count > 0:
                        trans_type = "Total" if trans_count >= total_lines else "Parcial"
                        trad_str = f"{trans_count}/{total_lines} - ({trans_type})"
                    else:
                        trad_str = "Nao"
                    msg = f"{OFF}  [*] Letra Encontrada: {title} - {search_artist} | Traducao: {trad_str} | Response_Code: {resp_code} | Tempo: {elapsed:.1f}s{OFF}"
            else:
                status_result = "skipped"
                msg = f"{YELLOW}  [!] Falha ao obter letra para: {title} - {search_artist} | Code: {resp_code or 'Nao'} | Tempo: {elapsed:.1f}s{OFF}"

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
                eta_info = f"{GREEN}  [Concluido em {total_str}]{OFF}"

            output_parts = [m for m in (msg, eta_info) if m]
            if output_parts:
                safe_print("\n".join(output_parts))


# =========================
# MAIN RETRO SCAN
# =========================

async def inject_lyrics_retroactively(directory_path: str, genius_token: str = None, 
                                      deepl_api_key: str = None, overwrite: bool = False, 
                                      target_lang: str = "PT-BR", translate_lyrics: bool = True, max_workers: int = 1) -> None:
    safe_print(f"\n{CYAN}[*] Starting retroactive lyrics scan in: {directory_path}{OFF}\n")

    if overwrite:
        safe_print(f"{YELLOW}[!] OVERWRITE MODE ENABLED: Existing lyrics will be replaced.{OFF}\n")

    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        safe_print(f"{RED}[!] Erro: O diretorio '{directory_path}' nao existe.{OFF}\n")
        return

    engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=translate_lyrics, target_lang=target_lang)

    all_files = [p for p in target_dir.rglob('*') if p.is_file() and p.suffix.lower() in {'.flac', '.mp3'}]

    state = ScanState(len(all_files))
    safe_print(f"{CYAN}[*] Found {state.processed} compatible audio files. Processing...{OFF}\n")

    max_workers = 1
    semaphore = asyncio.Semaphore(max_workers)

    tasks = [
        asyncio.create_task(_process_single_file(semaphore, path, engine, state, overwrite, idx, state.processed, max_workers))
        for idx, path in enumerate(all_files, 1)
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        safe_print(f"\n{RED}[!] Processo interrompido pelo usuario.{OFF}\n")

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
                                 deepl_api_key: str = None, target_lang: str = "PT-BR", translate_lyrics: bool = True) -> None:
    from pick import pick

    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        print(f"{RED}[!] Erro: O diretorio '{directory_path}' nao existe.{OFF}")
        return

    engine = LyricsEngine(deepl_api_key=deepl_api_key, translate=True, target_lang=target_lang)

    all_files = sorted([p for p in target_dir.rglob('*') if p.is_file() and p.suffix.lower() in {'.flac', '.mp3'}])

    if not all_files:
        print(f"{RED}[!] No compatible audio files found in '{directory_path}'.{OFF}")
        return

    file_options = []
    file_mapping = {}

    print(f"{CYAN}[*] Escaneando {len(all_files)} arquivos para o menu interativo...{OFF}")

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

    raw_artist = track_info["album_artist"] if track_info["album_artist"] and track_info["album_artist"].lower() != "various artists" else track_info["artist"]
    search_artist = re.split(r'(?i)\s*(?:,|\&| feat\.| ft\.|;|\/)\s*',raw_artist)[0].strip()
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

    async def fetch_musixmatch():
        text = await engine._fetch_musixmatch_lyrics(search_artist, track_title)
        if text:
            is_sync = engine._is_strictly_synced(text)
            results.append({
                "provider": "Musixmatch",
                "duration": real_duration, 
                "syncedLyrics": text if is_sync else None,
                "plainLyrics": text if not is_sync else None,
                "artistName": search_artist,
                "trackName": track_title,
                "albumName": "Musixmatch"
            })

    try:
        await asyncio.gather(
            fetch_lrclib(),
            fetch_lyricsplus(),
            fetch_netease(),
            fetch_genius(),
            fetch_musixmatch()
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
        dur_diff = abs(dur - real_duration) if dur > 0 else float('inf')
        provider_weight = 0 if r.get("provider") == "Musixmatch" else 1
        return (provider_weight, dur_diff)

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
        trad_str = f"{trans_count}/{total_lines} - ({'Total' if trans_count >= total_lines else 'Parcial'})" if (total_lines > 0 and trans_count > 0) else "Nao"
        print(f"{OFF}  [*] Letra Encontrada: {track_title} - {search_artist} | Traducao: {trad_str} | Response_Code: {provider}{OFF}")
        print(f"{GREEN}[+] Lyrics successfully replaced!{OFF}")
    else:
        print(f"{RED}[!] Failed to inject lyrics.{OFF}")

    await asyncio.sleep(2)
    
    # ====================================================
    # MODO TRADUTOR INTERATIVO (Apenas traduz letras locais)
    # ====================================================

def _get_existing_lyrics_text(file_path: Path) -> str:
    """Tenta extrair a letra ja existente do arquivo .lrc ou da tag do audio."""
    lrc_path = file_path.with_suffix(".lrc")
    if lrc_path.exists():
        try:
            return lrc_path.read_text(encoding="utf-8")
        except: pass
        
    try:
        if file_path.suffix.lower() == ".flac":
            audio = FLAC(file_path)
            return audio.get("LYRICS", [""])[0] or audio.get("UNSYNCEDLYRICS", [""])[0]
        elif file_path.suffix.lower() == ".mp3":
            audio = id3.ID3(file_path)
            uslt_tags = audio.getall("USLT")
            if uslt_tags:
                return uslt_tags[0].text
    except: pass
    return ""

def _test_deepl_api(api_key: str) -> bool:
    """
    Testa se a chave fornecida do Deepl é válida via requests
    """
    import requests
    url = "https://api-free.deepl.com/v2/translate" if api_key.endswith(":fx") else "https://api.deepl.com/v2/translate" 
    try:
        r = requests.post(url, data={"auth_key": api_key, "text": "Hello", "target_lang": "PT-BR"})
        if r.status_code == 200:
            safe_print(f"{GREEN}[*] Deepl API conectada com sucesso!{OFF}")
            return True
        elif r.status_code == 456:
            safe_print(f"{RED}[!] A chave é válida, porém a cota gratuita de 500.000 caracteres já foi excedida.{OFF}")
            return False
        elif r.status_code == 403:
            safe_print(f"{RED}[!] Chave da API do DeepL inválida ou incorreta.{OFF}")
            return False
        else:
            safe_print(f"{RED}[!] Erro na chave do Deepl: {r.status_code} - {r.text}{OFF}")
            return False
    except Exception as e:
    safe_print(f"\n{RED}[!] Falha ao contatar DeepL: {e}{OFF}")
    return False

async def interactive_translate_lyrics(directory_path: str, deepl_api_key: str = None, target_lang: str = "PT-BR") -> None:

    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        print(f"{RED}[!] Erro: O diretorio '{directory_path}' nao existe.{OFF}")
        return
        
    print(f"{CYAN}[*] Inicializando Tradutor Gratuito (Google Translate)...{OFF}")
        
    engine = LyricsEngine(translate=True, target_lang=target_lang)
    all_files = sorted([p for p in target_dir.rglob('*') if p.is_file() and p.suffix.lower() in {'.flac', '.mp3'}])
    
    if not all_files:
        print(f"{RED}[!] Nenhum arquivo de audio compativel encontrado.{OFF}")
        return

    file_options = []
    file_mapping = {}

    print(f"{CYAN}[*] Escaneando {len(all_files)} arquivos para encontrar letras nativas...{OFF}")

    for path in all_files:
        meta = _extract_metadata(path)
        raw_lyrics = _get_existing_lyrics_text(path)
        
        if meta["title"] and meta["artist"] and raw_lyrics:
            
            # 1. VERIFICA TRADUCAO EXISTENTE (Suporta o til novo e o simbolo antigo)
            is_translated = ("~" in raw_lyrics) or ("¬" in raw_lyrics) or ("\xac" in raw_lyrics)
            
            if is_translated:
                status_tag = "[TRADUZIDA]"
                status_type = "translated"
            else:
                # Limpa o texto para analise do idioma
                clean_text = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', raw_lyrics)
                clean_text = re.sub(r'<\d+:\d+(?:\.\d+)?>', '', clean_text)
                clean_text = re.sub(r'\[.*?\]', '', clean_text)

                sample_text = clean_text[:500].strip()
                lang, conf = engine._detect_lang(sample_text)
                
                pt_words = {"nao", "voce", "que", "de", "amor", "eu", "para", "com", "uma", "um", "meu", "minha", "se", "na", "no"}
                sample_words = set(re.findall(r'\b\w+\b', sample_text.lower()))
                is_pt_fallback = len(pt_words.intersection(sample_words)) >= 3
                
                # 2. VERIFICA SE JA E NATIVA DO BRASIL
                if (lang and lang.startswith('pt') and conf >= 0.5) or is_pt_fallback:
                    status_tag = "[NATIVA PT-BR]"
                    status_type = "native"
                # 3. MARCA COMO PENDENTE (Gringa)
                else:
                    status_tag = "[PENDENTE]"
                    status_type = "pending"
            
            display_str = f"{status_tag} {meta['title']} - {meta['artist']}{path.suffix}"
            file_options.append(display_str)
            
            file_mapping[display_str] = {
                "path": str(path),
                "title": meta["title"],
                "artist": meta["artist"],
                "raw_lyrics": raw_lyrics,
                "status_type": status_type
            }

    if not file_options:
        print(f"{YELLOW}[!] Nenhum arquivo com letra nativa foi encontrado para traduzir.{OFF}")
        return

    file_options.sort()
    file_options.append(">> Cancelar / Sair")

    title_text = "Selecione as faixas que deseja TRADUZIR (Espaco para marcar, ENTER para confirmar):\nLegenda: [PENDENTE] = Gringa | [TRADUZIDA] = Ignorada | [NATIVA] = BR (Pode forcar traducao)"

    try:
        selected = pick(file_options, title_text, multiselect=True, min_selection_count=1)
    except KeyboardInterrupt:
        return

    if not selected:
        return
        
    selected_displays = [s[0] for s in selected]
    if ">> Cancelar / Sair" in selected_displays:
        if len(selected_displays) == 1: return
        selected_displays.remove(">> Cancelar / Sair")

    print(f"\n{CYAN}[*] Voce selecionou {len(selected_displays)} faixas no menu.{OFF}")

    count_translated = 0
    count_skipped = 0

    for display in selected_displays:
        track_info = file_mapping[display]
        title = track_info["title"]
        artist = track_info["artist"]
        raw_lyrics = track_info["raw_lyrics"]
        path = track_info["path"]
        status_type = track_info["status_type"]

        if status_type == "translated":
            safe_print(f"{YELLOW}  [*] Ignorado (Ja Traduzido Anteriormente): {title} - {artist}{OFF}")
            count_skipped += 1
            continue
            
        if status_type == "native":
            safe_print(f"{YELLOW}  [*] Atencao: Forcando traducao de faixa Nativa (PT-BR): {title}{OFF}")

        safe_print(f"{GREEN}[*] Traduzindo: {title} - {artist}...{OFF}")
        
        is_synced = engine._is_strictly_synced(raw_lyrics)
        
        try:
            final_lyrics, trans_count, total_lines = await engine._process_translation(raw_lyrics, is_synced=is_synced)
            
            if trans_count > 0:
                engine._inject_metadata(str(path), final_lyrics)
                engine._save_lrc_file(str(path), final_lyrics)
                safe_print(f"{CYAN}  └── Sucesso! Linhas traduzidas: {trans_count}/{total_lines}{OFF}")
                count_translated += 1
            else:
                safe_print(f"{RED}  └── Falha na API ou texto nao precisava de traducao.{OFF}")
                count_skipped += 1
        except Exception as e:
            safe_print(f"{RED}  └── Erro ao traduzir: {e}{OFF}")
            count_skipped += 1
            
    safe_print(f"\n{GREEN}[+] Modo Tradutor Concluido!{OFF}")
    safe_print(f"{CYAN}  - Arquivos Traduzidos: {count_translated}{OFF}")
    safe_print(f"{YELLOW}  - Arquivos Ignorados/Falhos: {count_skipped}{OFF}\n")