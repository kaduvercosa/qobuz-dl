import logging
import shutil
import sys
import os
import io
import time
import re
import signal
import json
import hashlib
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, Union
import textwrap
import unicodedata
import urllib.parse
import difflib

import yarl
import aiohttp
import aiofiles
import asyncio
try:
    from Cryptodome.Cipher import AES
    HAS_NATIVE_CRYPTO = True
except (ImportError, OSError):
    try:
        from Crypto.Cipher import AES
        HAS_NATIVE_CRYPTO = True
    except ImportError:
        import pyaes
        HAS_NATIVE_CRYPTO = False
from pathvalidate import sanitize_filename, sanitize_filepath
from tqdm import tqdm

import qobuz_dl.metadata as metadata
from qobuz_dl.exceptions import NonStreamable
from qobuz_dl.settings import QobuzDLSettings
from qobuz_dl.utils import get_album_artist, clean_filename, get_apple_hq_cover
from qobuz_dl.db import handle_download_id
from qobuz_dl.constants import DEFAULT_FOLDER, DEFAULT_TRACK, DEFAULT_MULTIPLE_DISC_TRACK, CONFIG_PATH
from qobuz_dl.lyrics_engine import LyricsEngine
from qobuz_dl.color import Tema

# =========================================================================
# FUNÇÃO DE RESPONSIVIDADE (NOVO)
# =========================================================================
def get_dynamic_pad():
    """Lê a largura do terminal em tempo real para evitar quebras de linha em ecrãs pequenos (iPhone)."""
    term_width = shutil.get_terminal_size((80, 20)).columns
    # Define um limite máximo de 100 para não ficar feio no iPad em ecrã inteiro
    return min(term_width - 2, 100)
# =========================================================================

class LoopGlobals:
    _state = {}

    @classmethod
    def get(cls, name):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try: loop = asyncio.get_event_loop()
            except: loop = "fallback"
            
        if loop not in cls._state:
            cls._state[loop] = {
                'print_lock': asyncio.Lock() if loop != "fallback" else None,
                'abort_event': asyncio.Event() if loop != "fallback" else None,
                'cover_resize_lock': asyncio.Lock() if loop != "fallback" else None,
                'db_write_lock': asyncio.Lock() if loop != "fallback" else None,
                'lyrics_translation_lock': asyncio.Lock() if loop != "fallback" else None,
                'cover_session_lock': asyncio.Lock() if loop != "fallback" else None,
                'cover_session': None
            }
        return cls._state[loop][name]

    @classmethod
    def set(cls, name, val):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try: loop = asyncio.get_event_loop()
            except: loop = "fallback"
        if loop not in cls._state:
            cls.get(name) 
        cls._state[loop][name] = val


class ProxyAbortEvent:
    def is_set(self):
        ev = LoopGlobals.get('abort_event')
        return ev.is_set() if ev else False
        
    def set(self):
        for state in LoopGlobals._state.values():
            if state.get('abort_event'):
                state['abort_event'].set()
                
    def clear(self):
        for state in LoopGlobals._state.values():
            if state.get('abort_event'):
                state['abort_event'].clear()


abort_event = ProxyAbortEvent()

print_lock = None
cover_resize_lock = None
db_write_lock = None

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def safe_print_async(*args, **kwargs) -> None:
    lck = LoopGlobals.get('print_lock')
    if lck:
        async with lck:
            text = " ".join(map(str, args))
            tqdm.write(text, end=kwargs.get('end', '\n'))
    else:
        text = " ".join(map(str, args))
        tqdm.write(text, end=kwargs.get('end', '\n'))

def format_release_type(album_meta: dict) -> str:
    from qobuz_dl.core import classificar_tipo_lancamento
    raw_type = album_meta.get("release_type") or album_meta.get("product_type")
    title = album_meta.get("title", "")
    version = album_meta.get("version", "")
    
    t_count = album_meta.get("tracks_count", 0)
    if not t_count and "tracks" in album_meta and "items" in album_meta["tracks"]:
        t_count = len(album_meta["tracks"]["items"])

    duration = album_meta.get("duration", 0)

    r = classificar_tipo_lancamento(raw_type, title, version, t_count, duration)
    return "EP" if r == "ep" else r.title()

def process_folder_format_with_subdirs(folder_format: str, attr_dict: dict, path: Optional[str] = None, legacy_charmap: bool = False) -> str:
    cleaned_parts = []
    for part in folder_format.split('/'):
        if not part: continue
        try:
            formatted_part = part.format(**attr_dict)
            cleaned_part = sanitize_filepath(clean_filename(formatted_part, legacy_charmap=legacy_charmap), replacement_text="_")
            if cleaned_part and len(cleaned_part) > 120:
                cleaned_part = cleaned_part[:60].rstrip(' ."-_\'') + "..." + cleaned_part[-50:].lstrip(' ."-_\'')
            if cleaned_part: cleaned_parts.append(cleaned_part)
        except KeyError as e:
            cleaned_part = sanitize_filepath(clean_filename(part, legacy_charmap=legacy_charmap), replacement_text="_")
            if cleaned_part and len(cleaned_part) > 120:
                cleaned_part = cleaned_part[:60].rstrip(' ."-_\'') + "..." + cleaned_part[-50:].lstrip(' ."-_\'')
            if cleaned_part: cleaned_parts.append(cleaned_part)
            
    final_path = Path(*cleaned_parts) if cleaned_parts else Path("")
    return str(Path(path) / final_path) if path else str(final_path)

QL_DOWNGRADE = "FormatRestrictedByFormatAvailability"
DEFAULT_FORMATS = {
    "MP3": ["{album_artist} - {album_title} ({year}) [MP3]", "{track_number} - {track_title}"],
    "Unknown": ["{album_artist} - {album_title}", "{track_number} - {track_title}"],
}

EMB_COVER_NAME = "embed_cover.jpg"
POST_DOWNLOAD_SETTLE_DELAY = 0.4

QUALITY_LABELS = {
    5:  "MP3 320kbps",
    6:  "16bit/44.1kHz (CD)",
    7:  "24bit/<96kHz (Hi-Res)",
    27: "24bit/>96kHz (Hi-Res+)",
}


class Download:
    def __init__(
        self,
        client: Any,
        item_id: str,
        path: str,
        quality: int,
        embed_art: bool = False,
        albums_only: bool = False,
        downgrade_quality: bool = False,
        cover_og_quality: bool = False,
        no_cover: bool = False,
        folder_format=None,
        track_format=None,
        fetch_lyrics: bool = False,
        no_lrc_files: bool = False,
        genius_token: str = None,
        deepl_api_key: str = None,
        translate_lyrics: bool = True,
        target_lang: str = "PT-BR",
        no_credits: bool = False,
        settings: QobuzDLSettings = None,
        download_db=None,
        is_playlist: bool = False,           
        playlist_track_number: int = None, 
        booklet_only: bool = False,
        is_single_batch: bool = False,
        single_batch_index: int = 1,
        single_batch_total: int = 1):
 
        self.client = client
        self.item_id = item_id
        self.path = path
        self.quality = quality
        self.albums_only = albums_only
        self.embed_art = embed_art
        self.downgrade_quality = downgrade_quality
        self.cover_og_quality = cover_og_quality
        self.no_cover = no_cover
        self.folder_format = folder_format or DEFAULT_FOLDER
        self.track_format = track_format or DEFAULT_TRACK
        self.no_credits = no_credits
        self.booklet_only = booklet_only        
        self.fetch_lyrics = fetch_lyrics
        self.no_lrc_files = no_lrc_files
        self.target_lang = target_lang
        self.translate_lyrics = translate_lyrics
        self.is_single_batch = is_single_batch
        self.single_batch_index = single_batch_index
        self.single_batch_total = single_batch_total
        
        if self.fetch_lyrics:
            self.lyrics_engine = LyricsEngine(
                genius_token=genius_token, 
                deepl_api_key=deepl_api_key, 
                translate=self.translate_lyrics, 
                target_lang=self.target_lang,
                session=self.client.session
            )

        self.settings = settings or QobuzDLSettings()
        self.download_db = download_db
        self.is_playlist = is_playlist                       
        self.playlist_track_number = playlist_track_number
        self._original_folder_format = self.folder_format
        self._original_track_format = self.track_format
        self._original_multiple_disc_track_format = self.settings.multiple_disc_track_format if self.settings else DEFAULT_MULTIPLE_DISC_TRACK

        self.delay = self.settings.delay or 0
        if self.delay == 0 and '--delay' in sys.argv:
            try: self.delay = int(sys.argv[sys.argv.index('--delay') + 1])
            except: pass
 
    async def _apply_delay(self, tag: str = ""):
        delay_val = int(self.delay) if self.delay is not None else 0
        if delay_val > 0 and not LoopGlobals.get('abort_event').is_set():
            prefix = f"{tag} {Tema.AVISO}⏳" if tag else f"{Tema.AVISO}⏳"
            await safe_print_async(f"{prefix} Aguardando {delay_val}s de segurança...{Tema.OFF}")
            await asyncio.sleep(delay_val)

    async def download_id_by_type(self, track: bool = True) -> None:
        self.folder_format = self._original_folder_format
        self.track_format = self._original_track_format
        if self.settings:
            self.settings.multiple_disc_track_format = self._original_multiple_disc_track_format
        
        if track: await self.download_track()
        else: await self.download_release()

    async def download_release(self) -> None:
        count = 0
        try:
            album_meta = await self.client.get_album_meta(self.item_id)
        except Exception as e:
            await safe_print_async(f"\n{Tema.ERRO}[!] Erro ao buscar albúm: {e} (Pode estar bloqueado na sua região).{Tema.OFF}")
            return

        if not album_meta.get("streamable"):
            await safe_print_async(f"\n{Tema.AVISO}[!] Albúm não liberado para streaming (Restrição de Licenciamento).{Tema.OFF}")

        if self.albums_only and (album_meta.get("release_type") != "album" or album_meta.get("artist").get("name") == "Various Artists"):
            return

        album_title = _get_title(album_meta)

        url = album_meta.get("url", "")
        release_date = album_meta.get("release_date_original", "")
        file_format, quality_met, bit_depth, sampling_rate = await self._get_format(album_meta)

        if not self.downgrade_quality and not quality_met:
            return

        _track_count = sum(1 for t in album_meta["tracks"]["items"] if "sample" not in t and t.get("streamable", True))
        
        album_attr = self._build_metadata_dict(album_meta, album_title, bit_depth, sampling_rate, file_format, True)
        
        from qobuz_dl.core import classificar_tipo_lancamento
        r_type_str = classificar_tipo_lancamento(
            raw_type=album_meta.get("release_type") or album_meta.get("product_type"),
            title=album_title,
            version=album_meta.get("version", ""),
            t_count=_track_count,
            duration=album_meta.get("duration", 0)
        )
        display_type = "SINGLE" if r_type_str == "single" else ("EP" if r_type_str == "ep" else "ALBUM")
        icon = "🎵" if display_type == "SINGLE" else ("💽" if display_type == "EP" else "💿")

        t_album = f"  {icon} {display_type} | {album_title}"
        pad_len = get_dynamic_pad()
        if len(t_album) > pad_len: t_album = t_album[:pad_len-3] + "..."
        HEADER_ALBUM = f"{Tema.BG_ALBUM}{Tema.TXT_WHITE}{Tema.BOLD}{t_album} {Tema.OFF}"

        await safe_print_async(" ")
        await safe_print_async(f"{HEADER_ALBUM}")
        await safe_print_async(f"{Tema.TXT_ALBUM}{Tema.BOLD}[INFO ]{Tema.OFF} {Tema.TXT_ALBUM}├──{Tema.OFF} Artista: {album_attr.get('album_artist', 'Unknown')}")
        await safe_print_async(f"{Tema.TXT_ALBUM}{Tema.BOLD}[INFO ]{Tema.OFF} {Tema.TXT_ALBUM}├──{Tema.OFF} Qualidade Max: {file_format} ({bit_depth}b/{sampling_rate}kHz)")
        await safe_print_async(f"{Tema.TXT_ALBUM}{Tema.BOLD}[INFO ]{Tema.OFF} {Tema.TXT_ALBUM}└──{Tema.OFF} Faixas na Fila: {_track_count}")

        await self._determine_formats(album_meta=album_meta, album_attr=album_attr, tracks_meta=album_meta["tracks"]["items"],
                                track_attr=None, is_track=False, file_format=file_format, settings=self.settings)
        
        legacy_flag = getattr(self.settings, 'legacy_charmap', False)
        target_dirn = Path(process_folder_format_with_subdirs(self.folder_format, album_attr, self.path, legacy_charmap=legacy_flag))
        
        incomplete_dirn = target_dirn.parent / f"[INCOMPLETE] {target_dirn.name}"
        inprogress_dirn = target_dirn.parent / f"[IN PROGRESS] {target_dirn.name}"
        
        is_standard_album = not getattr(self, 'is_playlist', False)
        
        if is_standard_album:
            working_dirn = inprogress_dirn
            try:
                if incomplete_dirn.exists(): incomplete_dirn.rename(working_dirn)
                elif target_dirn.exists(): target_dirn.rename(working_dirn)
            except OSError:
                working_dirn = target_dirn
        else:
            working_dirn = target_dirn
            
        working_dirn.mkdir(parents=True, exist_ok=True)

        is_multiple = album_meta.get("media_count", 1) > 1
        delay_time = self.settings.delay
        if delay_time == 0 and '--delay' in sys.argv:
            try: delay_time = int(sys.argv[sys.argv.index('--delay') + 1])
            except: pass
            
        active_workers = int(getattr(self.settings, 'max_workers', 3))
        is_parallel = active_workers > 1 and delay_time == 0
        
        if delay_time > 0:
            active_workers = 1
            
        failed_tracks, aborted_by_user = 0, False
        LoopGlobals.get('abort_event').clear()

        try:
            async def _prepare_artwork_and_extras():
                try:
                    await self._generate_tracklist(album_meta, str(working_dirn), album_title, file_format, bit_depth, sampling_rate, prefix_tag=f"{Tema.TXT_ALBUM}{Tema.BOLD}[PDF  ]{Tema.OFF} ", c_txt=Tema.TXT_ALBUM)

                    album_upc = album_meta.get("upc", "")
                    first_track_isrc = ""
                    try:
                        first_track_isrc = album_meta.get("tracks", {}).get("items", [])[0].get("isrc", "")
                    except Exception:
                        pass

                    apple_cover = await get_apple_hq_cover(
                        upc=album_upc,
                        isrc=first_track_isrc,
                        artist=album_attr.get("album_artist", "Unknown"),
                        album=album_title,
                    )
                    final_cover = apple_cover if apple_cover else album_meta["image"]["large"]

                    if not self.settings.no_cover:
                        await _get_extra(final_cover, str(working_dirn), art_size="org", prefix_tag=f"{Tema.TXT_ALBUM}{Tema.BOLD}[CAPA ]{Tema.OFF} ", c_txt=Tema.TXT_ALBUM)

                    if self.settings.embed_art:
                        cover_path, embed_path = working_dirn / "cover.jpg", working_dirn / EMB_COVER_NAME
                        if cover_path.exists(): shutil.copy2(cover_path, embed_path)
                        else: await _get_extra(final_cover, str(working_dirn), extra=EMB_COVER_NAME, art_size="org", prefix_tag=f"{Tema.TXT_ALBUM}{Tema.BOLD}[CAPA ]{Tema.OFF} ", c_txt=Tema.TXT_ALBUM)

                    if "goodies" in album_meta:
                        await _download_goodies(album_meta, str(working_dirn), prefix_tag=f"{Tema.TXT_ALBUM}{Tema.BOLD}[EXTRA]{Tema.OFF} ", c_txt=Tema.TXT_ALBUM)
                except Exception as e:
                    logger.error(f"Erro ao preparar encartes: {e}")

            await _prepare_artwork_and_extras()

            if getattr(self, 'booklet_only', False):
                await safe_print_async(f"\n{Tema.AVISO}[!] Apenas encartes solicitado. Pulando áudio.{Tema.OFF}")
                if is_standard_album and working_dirn == inprogress_dirn:
                    try: working_dirn.rename(incomplete_dirn)
                    except OSError: pass
                return
             
            sem = asyncio.Semaphore(active_workers)
            
            seq_lock = asyncio.Lock()
            seq_next = 1
            seq_buffer = {}
            completed_tracks = 0
            
            async def print_live_status():
                if is_parallel and completed_tracks < _track_count:
                    msg = f"⏳ Em paralelo... ({completed_tracks}/{_track_count})"
                    sys.stdout.write(f"\r{Tema.AVISO}{msg}{Tema.OFF}\033[K")
                    sys.stdout.flush()
                elif is_parallel and completed_tracks >= _track_count:
                    sys.stdout.write("\r\033[K")
                    sys.stdout.flush()
            
            async def flush_logs():
                nonlocal seq_next
                while seq_next in seq_buffer:
                    if is_parallel:
                        sys.stdout.write("\r\033[K")
                        sys.stdout.flush()
                    logs = seq_buffer.pop(seq_next)
                    for line in logs:
                        await safe_print_async(line)

                    if seq_next < _track_count:
                        await safe_print_async("")

                    seq_next += 1
                await print_live_status()

            async def bound_process_track(dirn, t_count, track_item, a_meta, is_multi, is_para, continuous_track_index):
                nonlocal completed_tracks
                track_logs = []
                try:
                    async with sem:
                        if LoopGlobals.get('abort_event').is_set(): return False
                        
                        t_no = str(track_item.get('track_number', 0)).zfill(2)
                        t_tot = str(_track_count).zfill(2)
                        prefix_str = f"[{t_no}/{t_tot}]"
                        
                        desc_name = _get_title(track_item) or 'Faixa Desconhecida'
                        t_artist = track_item.get('performer', {}).get('name') or a_meta.get('artist', {}).get('name', 'Unknown')
                        
                        c_bg_sec = Tema.BG_ALBUM_SEC
                        c_txt = Tema.TXT_ALBUM
                        
                        root_text = f" ▶ {prefix_str} 🎵 {t_artist} - {desc_name}"
                        p_len = get_dynamic_pad()
                        if len(root_text) > p_len: root_text = root_text[:p_len-3] + "..."
                        root_line = f"{c_bg_sec}{Tema.TXT_WHITE}{Tema.BOLD}{root_text} {Tema.OFF}"
                        
                        try:
                            full_track_meta, parse = await asyncio.gather(
                                self.client.get_track_meta(track_item["id"]),
                                self.client.get_track_url(track_item["id"], fmt_id=self.quality)
                            )
                        except Exception as e:
                            err_prefix = f"{c_txt}{Tema.BOLD}{prefix_str}{Tema.OFF} " if is_para else ""
                            if is_para:
                                track_logs.append(root_line)
                                if "400" in str(e) or "Invalid Request Signature" in str(e):
                                    track_logs.append(f"{err_prefix}{c_txt}{Tema.BOLD}[INFO ]{Tema.OFF} {c_txt}├──{Tema.OFF} ⏭️ Pulando (Restrição Regional)")
                                else:
                                    track_logs.append(f"{err_prefix}{c_txt}{Tema.BOLD}[INFO ]{Tema.OFF} {c_txt}├──{Tema.OFF} ❌ {Tema.ERRO}Erro na API: {e}{Tema.OFF}")
                            else:
                                await safe_print_async(" ")
                                await safe_print_async(root_line)
                                if "400" in str(e) or "Invalid Request Signature" in str(e):
                                    await safe_print_async(f"{err_prefix}{c_txt}{Tema.BOLD}[INFO ]{Tema.OFF} {c_txt}├──{Tema.OFF} ⏭️ Pulando (Restrição Regional)")
                                else:
                                    await safe_print_async(f"{err_prefix}{c_txt}{Tema.BOLD}[INFO ]{Tema.OFF} {c_txt}├──{Tema.OFF} ❌ {Tema.ERRO}Erro na API: {e}{Tema.OFF}")
                            return False

                        if is_para:
                            track_logs.append(root_line)
                        else:
                            await safe_print_async(" ")
                            await safe_print_async(root_line)

                        if "sample" not in parse and parse.get("sampling_rate"):
                            media_num = track_item.get("media_number") if is_multi else None
                            t_tag_prefix = f"{c_txt}{Tema.BOLD}{prefix_str}{Tema.OFF} " if is_para else ""
                            
                            return await self._download_and_tag(
                                dirn, t_count, parse, full_track_meta, a_meta, False, int(self.quality) == 5, media_num, is_para, t_tag=t_tag_prefix, use_siglas=True, c_txt=c_txt, log_buffer=track_logs if is_para else None
                            )
                        return False
                finally:
                    if is_para:
                        async with seq_lock:
                            completed_tracks += 1
                            seq_buffer[continuous_track_index] = track_logs
                            await flush_logs()

            if is_parallel:
                await safe_print_async("")
                await print_live_status()

            tasks = []
            for continuous_track_index, i in enumerate(album_meta["tracks"]["items"], start=1):
                if LoopGlobals.get('abort_event').is_set(): break
                if is_multiple: i["track_number"] = continuous_track_index
                tasks.append(bound_process_track(str(working_dirn), count, i, album_meta, is_multiple, is_parallel, continuous_track_index))
                count += 1

            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        failed_tracks += 1
                        logger.error(f"Erro na track: {res}")
                    elif res is False:
                        failed_tracks += 1
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                LoopGlobals.get('abort_event').set()
                aborted_by_user = True
                if is_parallel:
                    sys.stdout.write("\r\033[K")
                    sys.stdout.flush()
                await safe_print_async(f"\n{Tema.ERRO}[!] CTRL+C Interceptado: Fechando arquivos em segurança...{Tema.OFF}")
                    
            if not aborted_by_user:
                await _clean_embed_art(working_dirn)
                if self.fetch_lyrics and not self.no_credits:
                    await self._append_lyrics_to_booklet(str(working_dirn), album_title)
                    
        except (KeyboardInterrupt, SystemExit):
            LoopGlobals.get('abort_event').set()
            aborted_by_user = True
            if is_parallel:
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
            await safe_print_async(f"\n{Tema.ERRO}[!] Operação Abortada...{Tema.OFF}")
                
        if aborted_by_user:
            await asyncio.sleep(1.5)
            
        if is_standard_album and working_dirn == inprogress_dirn:
            final_dirn = target_dirn if (failed_tracks == 0 and not aborted_by_user) else incomplete_dirn
            try: 
                working_dirn.rename(final_dirn)
                from qobuz_dl.db import rename_library_path_prefix
                rename_library_path_prefix(self.download_db, working_dirn, final_dirn)
            except OSError: 
                final_dirn = working_dirn
            
            if aborted_by_user: await safe_print_async(f"\n{Tema.AVISO}[!] Download abortado. Marcado como [INCOMPLETE].{Tema.OFF}")
            elif failed_tracks > 0: await safe_print_async(f"\n{Tema.AVISO}[!] Download parcial. Marcado como [INCOMPLETE].{Tema.OFF}")
        else:
            final_dirn = working_dirn
        
        if aborted_by_user: 
            await safe_print_async("\n")
            os._exit(1)
        
        if failed_tracks == 0:
            lck = LoopGlobals.get('db_write_lock')
            async with lck:
                await asyncio.to_thread(
                    handle_download_id,
                    self.download_db, 
                    self.item_id, 
                    True, 
                    "album", 
                    self.quality, 
                    file_format, 
                    quality_met, 
                    bit_depth, 
                    sampling_rate, 
                    str(final_dirn), 
                    url, 
                    release_date, 
                    album_attr.get("album_artist", "Unknown"), 
                    album_attr.get("album_title", "Unknown")
                )
        
        if failed_tracks == 0 and not aborted_by_user:
            try:
                from qobuz_dl.telegram_uploader import upload_album_completo
                from qobuz_dl.core import classificar_tipo_lancamento

                t_faixa        = album_attr.get("artist", "Unknown")
                t_album_artist = album_attr.get("album_artist", "Unknown")
                t_album        = album_attr.get("album_title", "Unknown")
                t_year         = album_attr.get("year", "2026")

                t_tipo = classificar_tipo_lancamento(
                    raw_type  = album_meta.get("release_type") or album_meta.get("product_type"),
                    title     = album_meta.get("title", ""),
                    version   = album_meta.get("version", ""),
                    t_count   = sum(1 for t in album_meta.get("tracks", {}).get("items", [])
                                    if "sample" not in t and t.get("streamable", True)),
                    duration  = album_meta.get("duration", 0),
                )
                await upload_album_completo(str(final_dirn), t_album, t_faixa, t_album_artist, t_year, tipo=t_tipo)
            except Exception:
                try:
                    with open(CONFIG_PATH / "telegram_queue.txt", "a", encoding="utf-8") as fq:
                        fq.write(f"{final_dirn}|{t_album}|{t_faixa}|{t_album_artist}|{t_year}|{t_tipo}\n")
                except:
                    pass

        await safe_print_async(f"\n{Tema.SUCESSO}[✔] Lançamento Concluído: {Tema.TITULO}{album_title}{Tema.OFF}")
        
        if getattr(self, 'fetch_lyrics', False) and hasattr(self, 'lyrics_engine'):
            await self.lyrics_engine.close()

    async def download_track(self) -> None:
        aborted_by_user = False
        try:
            try:
                parse = await self.client.get_track_url(self.item_id, self.quality)
            except Exception as e:
                if "400"in str(e) or "Invalid Request Signature" in str(e):
                    await safe_print_async(f"\n{Tema.BLUE} ▶ 🎵 {Tema.AVISO}Faixa Indisponível: (Restrição Regional/Licenciamento){Tema.OFF}")
                else:
                    await safe_print_async(f"\n{Tema.BLUE} ▶ 🎵 {Tema.ERRO}Erro da API: {e}{Tema.OFF}")
                return

            if "sample" not in parse and parse["sampling_rate"]:
                try:
                    track_meta = await self.client.get_track_meta(self.item_id)
                except Exception as e:
                    await safe_print_async(f"\n{Tema.BLUE} ▶ 🎵 {Tema.ERRO}Erro ao obter metadados: {e}{Tema.OFF}")
                    return
                
                if track_meta.get("album", {}).get("media_count", 1) > 1 and not getattr(self, 'is_playlist', False):
                    try:
                        master_album = await self.client.get_album_meta(track_meta["album"]["id"])
                        c_idx = 1
                        for t_item in master_album.get("tracks", {}).get("items", []):
                            if str(t_item.get("id")) == str(self.item_id):
                                track_meta["track_number"] = c_idx
                                break
                            c_idx += 1
                    except Exception:
                        pass

                if getattr(self, 'is_playlist', False) and self.playlist_track_number:
                    track_meta["track_number"] = self.playlist_track_number
            
                track_title, artist = _get_title(track_meta), _safe_get(track_meta, "performer", "name")
            
                file_format, quality_met, bit_depth, sampling_rate = await self._get_format(track_meta, is_track_id=True, track_url_dict=parse)
                if not self.downgrade_quality and not quality_met:
                    return
            
                c_bg = Tema.BG_SINGLE
                c_bg_sec = Tema.BG_SINGLE_SEC
                c_txt = Tema.TXT_SINGLE
                #l_icon = "🎵 SINGLE"

                p_len = get_dynamic_pad()
                prefix_str = ""

                if getattr(self, 'is_playlist', False):
                    l_icon = "🎶 PLAYLIST"
                    pl_name = getattr(self.settings, 'playlist_name', 'PLAYLIST')
                    pl_badge_key = f"_badge_pl_printed_{pl_name}"
                    if not getattr(self.settings, pl_badge_key, False):
                        t_pl = f"  {l_icon} | {pl_name.upper()}"
                        if len(t_pl) > p_len: t_pl = t_pl[:p_len-3] + "..."
                        BADGE_PL = f"{c_bg}{Tema.TXT_WHITE}{Tema.BOLD}{t_pl} {Tema.OFF}"
                        await safe_print_async(" ")
                        await safe_print_async(BADGE_PL)
                        setattr(self.settings, pl_badge_key, True)
                    
                    t_no = str(self.playlist_track_number).zfill(2)
                    total_tracks = getattr(self.settings, 'playlist_total_count', '??')
                    prefix_str = f"[{t_no}/{str(total_tracks).zfill(2)}]"

                elif getattr(self,'is_single_batch', False):
                    l_icon = "🎼 LOTE DE SINGLES"
                    if not getattr(self.settings, '_badge_batch_printed', False):
                        t_lote = f"  {l_icon}"
                        if len(t_lote) > p_len: t_lote = t_lote[:p_len-3] + "..."
                        BADGE_B = f"{c_bg}{Tema.TXT_WHITE}{Tema.BOLD}{t_lote} {Tema.OFF}"
                        await safe_print_async(" ")
                        await safe_print_async(BADGE_B)
                        setattr(self.settings, '_badge_batch_printed', True)

                    t_no = str(self.single_batch_index).zfill(2)
                    t_tot = str(self.single_batch_total).zfill(2)
                    prefix_str = f"[{t_no}/{t_tot}]"
                
                else:
                    t_icon = "🎵 SINGLE"
                    t_single = f"  {l_icon}"
                    if len(t_single) > p_len: t_single = t_single[:p_len-3] + "..."
                    BADGE_S = f"{c_bg}{Tema.TXT_WHITE}{Tema.BOLD}{t_single} {Tema.OFF}"
                    await safe_print_async(" ")
                    await safe_print_async(BADGE_S)
                    prefix_str = "[01/01]"

                root_text = f" ▶ {prefix_str} 🎵 {artist} - {track_title}"
                if len(root_text) > p_len: root_text = root_text[:p_len-3] + "..."
                
                root_line = f"{c_bg_sec}{Tema.TXT_WHITE}{Tema.BOLD}{root_text} {Tema.OFF}"
                
                await safe_print_async(" ")
                await safe_print_async(root_line)
            
                sigla_info       = f"{c_txt}{Tema.BOLD}[INFO ]{Tema.OFF}"
                sigla_capa       = f"{c_txt}{Tema.BOLD}[CAPA ]{Tema.OFF}"
                sigla_qualidade  = f"{c_txt}{Tema.BOLD}[QUAL ]{Tema.OFF}"

                await safe_print_async(f"{sigla_qualidade} {c_txt}├──{Tema.OFF} Qualidade Max: {file_format} ({bit_depth}b/{sampling_rate}kHz)")

                track_attr = self._build_metadata_dict(track_meta, track_title, bit_depth, sampling_rate, file_format, False)

                await self._determine_formats(track_meta.get("album", {}), None, [track_meta], track_attr, True, file_format, self.settings)
            
                dirn = Path(process_folder_format_with_subdirs(self.folder_format, track_attr, self.path, getattr(self.settings, 'legacy_charmap', False)))
                dirn.mkdir(parents=True, exist_ok=True)
                
                extension = ".mp3" if int(self.quality) == 5 else ".flac"
                legacy_flag = getattr(self.settings, 'legacy_charmap', False)
                filename_attr = self._get_filename_attr(artist, track_meta, track_meta.get("album", {}))
                
                if getattr(self, 'is_playlist', False):
                    formatted_path = sanitize_filename(clean_filename(self.track_format.format(**filename_attr), legacy_charmap=legacy_flag), replacement_text="_")
                else:
                    is_multiple_disc = track_meta.get("album", {}).get("media_count", 1) > 1
                    media_num = track_meta.get("media_number") if is_multiple_disc else None
                    base_formatted = sanitize_filename(clean_filename(self.track_format.format(**filename_attr), legacy_charmap=legacy_flag), replacement_text="_")
                    if media_num and track_meta.get("album", {}).get("media_count", 1) > 1:
                        try: d_num = int(media_num)
                        except: d_num = 1
                        formatted_path = os.path.join(f"{self.settings.multiple_disc_prefix} {d_num:02}", base_formatted)
                    else:
                        formatted_path = base_formatted

                if len(formatted_path) > 180:
                    formatted_path = formatted_path[:110].rstrip(' ."-_\'') + "..." + formatted_path[-60:].lstrip(' ."-_\'')
                    
                final_file_check = dirn / f"{formatted_path}{extension}"

                if final_file_check.exists():
                    q_str = f"[{bit_depth}b/{sampling_rate}kHz]" if int(self.quality) != 5 else "[MP3 320kbps]"
                    await safe_print_async(f"{sigla_capa} {c_txt}├──{Tema.OFF} 🖼️ {EMB_COVER_NAME} {Tema.AVISO}[⏭️ Pulando (Já existe)]{Tema.OFF}")
                    await safe_print_async(f"{c_txt}{Tema.BOLD}[ÁUDIO]{Tema.OFF} {c_txt}├──{Tema.OFF} 🎧 {Tema.BOLD}{track_title}{Tema.OFF} {Tema.GREEN}{q_str}{Tema.OFF}")
                    await safe_print_async(f"{c_txt}{Tema.BOLD}[FINAL]{Tema.OFF} {c_txt}└──{Tema.OFF} ⏭️ {Tema.AVISO}Pulando (Já existe){Tema.OFF}")
                    return

                track_upc = track_meta.get("album", {}).get("upc", "")
                track_isrc = track_meta.get("isrc", "")
                
                track_album_title = track_meta.get("album", {}).get("title", "")
                if track_meta.get("album", {}).get("version"):
                    track_album_title = f"{track_album_title} ({track_meta['album']['version']})"

                apple_cover = await get_apple_hq_cover(track_upc, track_isrc, artist, track_album_title)

                final_cover = apple_cover if apple_cover else track_meta["album"]["image"]["large"]

                cover_dir_to_pass = None

                if getattr(self, 'is_playlist', False):
                    fake_cover_dir = dirn / f".cover_{track_meta['id']}"
                    fake_cover_dir.mkdir(exist_ok=True)
                    cover_dir_to_pass = str(fake_cover_dir)

                    if self.settings.embed_art:
                        await _get_extra(final_cover, str(fake_cover_dir), extra=EMB_COVER_NAME, art_size="org", is_playlist=True, prefix_tag=f"{sigla_capa} ", c_txt=c_txt)
                elif not self.settings.no_cover:
                    await _get_extra(final_cover, str(dirn), art_size="org", prefix_tag=f"{sigla_capa} ", c_txt=c_txt)
                    if self.settings.embed_art:
                        cover_path, embed_path = dirn / "cover.jpg", dirn / EMB_COVER_NAME
                        if cover_path.exists(): shutil.copy2(cover_path, embed_path)

                is_multiple_disc = track_meta.get("album", {}).get("media_count", 1) > 1
                media_num = track_meta.get("media_number") if is_multiple_disc else None
            
                download_success = await self._download_and_tag(
                    str(dirn), 1, parse, track_meta, track_meta, True, int(self.quality) == 5, media_num, False, t_tag="", use_siglas=True, c_txt=c_txt, cover_dir=cover_dir_to_pass
                )

                await _clean_embed_art(dirn)
             
                if cover_dir_to_pass and Path(cover_dir_to_pass).exists():
                    shutil.rmtree(cover_dir_to_pass, ignore_errors=True)
            
                if download_success and not LoopGlobals.get('abort_event').is_set():
                    lck_db = LoopGlobals.get('db_write_lock')
                    async with lck_db:
                        await asyncio.to_thread(
                            handle_download_id,
                            self.download_db,
                            self.item_id,
                            True,
                            "track",
                            self.quality,
                            file_format,
                            quality_met,
                            bit_depth,
                            sampling_rate,
                            str(dirn),
                            track_meta.get("album", {}).get("url", ""),
                            track_meta.get("release_date_original", ""),
                            track_attr.get("artist", "Unknown"),
                            track_attr.get("album", "Unknown")
                        )
                
                    if not getattr(self, 'is_playlist', False):
                        try:
                            from qobuz_dl.telegram_uploader import upload_album_completo
                            t_faixa        = track_attr.get("artist", "Unknown")
                            t_album_artist = track_attr.get("album_artist", t_faixa)
                            t_album        = track_attr.get("album", "Unknown")
                            t_date         = track_meta.get("release_date_original", "2026")
                            t_year         = str(t_date).split("-")[0] if t_date else "2026"

                            await upload_album_completo(str(dirn), t_album, t_faixa, t_album_artist, t_year, tipo="single")
                        except Exception:
                            pass
                        
                if not getattr(self, 'is_playlist', False):
                    await safe_print_async(f"\n{Tema.SUCESSO}[✔] Faixa Concluída: {Tema.TITULO}{track_title}{Tema.OFF}")

            if getattr(self, 'fetch_lyrics', False) and hasattr(self, 'lyrics_engine'):
                await self.lyrics_engine.close()

        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            LoopGlobals.get('abort_event').set()
            aborted_by_user = True
            await safe_print_async(f"\n{Tema.ERRO}[!] CTRL+C Interceptado: Cancelando processo com segurança...{Tema.OFF}\n\n")
            await asyncio.sleep(1.5)
            os._exit(1)

    async def _download_and_tag(self, root_dir: str, tmp_count: int, track_url_dict: dict, track_meta: dict, album_meta: dict, is_track: bool, is_mp3: bool, multiple: Optional[int], is_parallel: bool, t_tag: str, cover_dir: str = None, use_siglas: bool = False, c_txt: str = Tema.OFF, log_buffer: list = None) -> bool:

        async def _log(*args, **kwargs):
            text = " ".join(map(str, args))
            if log_buffer is not None:
                log_buffer.append(text)
            else:
                await safe_print_async(text, **kwargs)

        a_meta_for_type = track_meta.get("album", {})
        if not a_meta_for_type:
            a_meta_for_type = album_meta

        extension = ".mp3" if is_mp3 else ".flac"
        legacy_flag = getattr(self.settings, 'legacy_charmap', False)
        filename_attr = self._get_filename_attr(_safe_get(track_meta, "performer", "name"), track_meta, album_meta.get("album", {}) if is_track else album_meta)

        if getattr(self, 'is_playlist', False):
            formatted_path = sanitize_filename(clean_filename(self.track_format.format(**filename_attr), legacy_charmap=legacy_flag), replacement_text="_")
        elif multiple and self.settings.multiple_disc_one_dir:
            formatted_path = sanitize_filename(clean_filename(self.settings.multiple_disc_track_format.format(**filename_attr), legacy_charmap=legacy_flag), replacement_text="_")
        else:
            base_formatted = sanitize_filename(clean_filename(self.track_format.format(**filename_attr), legacy_charmap=legacy_flag), replacement_text="_")

            if multiple and a_meta_for_type.get('media_count', 1) > 1:
                try: d_num = int(multiple) if not isinstance(multiple, bool) else 1
                except: d_num = 1
                formatted_path = os.path.join(f"{self.settings.multiple_disc_prefix} {d_num:02}", base_formatted)
            else:
                formatted_path = base_formatted
            
        if len(formatted_path) > 180:
            formatted_path = formatted_path[:110].rstrip(' ."-_\'') + "..." + formatted_path[-60:].lstrip(' ."-_\'')
            
        final_file = Path(root_dir) / f"{formatted_path}{extension}"

        desc_name = _get_title(track_meta) or  'Unknown'
        if len(desc_name) > 30: desc_name = desc_name[:27] + "..."

        if use_siglas:
            t_tag_arq    = f"{t_tag}{c_txt}{Tema.BOLD}[ÁUDIO]{Tema.OFF} {c_txt}├──{Tema.OFF}"
            t_tag_aviso  = f"{t_tag}{c_txt}{Tema.BOLD}[AVISO]{Tema.OFF} {c_txt}├──{Tema.OFF}"
            t_tag_letra  = f"{t_tag}{c_txt}{Tema.BOLD}[LETRA]{Tema.OFF} {c_txt}├──{Tema.OFF}"
            t_tag_status = f"{t_tag}{c_txt}{Tema.BOLD}[FINAL]{Tema.OFF} {c_txt}├──{Tema.OFF}"
            t_tag_bar    = f"{t_tag}{c_txt}{Tema.BOLD}       {Tema.OFF} {c_txt}└──{Tema.OFF}"
        else:
            t_tag_arq    = f"{t_tag}{c_txt}├──{Tema.OFF}"
            t_tag_aviso  = f"{t_tag}{c_txt}├──{Tema.OFF}"
            t_tag_letra  = f"{t_tag}{c_txt}├──{Tema.OFF}"
            t_tag_status = f"{t_tag}{c_txt}├──{Tema.OFF}"
            t_tag_bar    = f"{t_tag}{c_txt}└──{Tema.OFF}"

        if final_file.exists():
            await _log(f"{t_tag_arq} 🎧 {Tema.BOLD}{desc_name}{Tema.OFF}")
            await _log(f"{t_tag_status} ⏭️ {Tema.AVISO}Pulando (Já existe){Tema.OFF}")
            return True

        if LoopGlobals.get('abort_event').is_set(): return False
        
        if not is_parallel:
            await self._apply_delay(t_tag_arq)

        try: url = track_url_dict["url"]
        except KeyError:
            return False

        if multiple and a_meta_for_type.get('media_count', 1) > 1 and not self.settings.multiple_disc_one_dir:
            try: d_num = int(multiple) if not isinstance(multiple, bool) else 1
            except: d_num = 1
            root_dir = str(Path(root_dir) / f"{self.settings.multiple_disc_prefix} {d_num:02}")
        
        Path(root_dir).mkdir(parents=True, exist_ok=True)

        filename = str(Path(root_dir) / f".{tmp_count:02}.tmp")

        FALLBACK_TIERS = [27, 7, 6, 5]
        requested_fmt = int(self.quality)
        try: start_idx = FALLBACK_TIERS.index(requested_fmt)
        except ValueError: start_idx = 0
            
        success, final_fmt = False, requested_fmt
        actual_bd, actual_sr = None, None

        can_reuse_first_fetch = self.delay == 0

        for tier_idx, attempt_fmt in enumerate(FALLBACK_TIERS[start_idx:]):
            if LoopGlobals.get('abort_event').is_set(): return False

            async def get_fresh_url(fmt=attempt_fmt, force_segments=False):
                return await self.client.get_track_url(track_meta["id"], fmt_id=fmt, force_segments=force_segments)

            try:
                if tier_idx == 0 and can_reuse_first_fetch and attempt_fmt == int(self.quality):
                    fresh_track = track_url_dict
                else:
                    fresh_track = await get_fresh_url(force_segments=False)
                if "url" in fresh_track:
                    try:
                        actual_bd = fresh_track.get("bit_depth")
                        actual_sr = fresh_track.get("sampling_rate")
                        final_fmt = fresh_track.get("format_id", attempt_fmt)

                        await tqdm_download(self.client.session, fresh_track["url"], filename, log_prefix=t_tag_bar, is_parallel=is_parallel, track_name=desc_name)
                        success = True
                        break
                    except Exception:
                        if LoopGlobals.get('abort_event').is_set(): return False
                        fresh_track = await get_fresh_url(force_segments=True)
                
                if "url_template" in fresh_track:
                    actual_bd = fresh_track.get("bit_depth")
                    actual_sr = fresh_track.get("sampling_rate")
                    final_fmt = fresh_track.get("format_id", attempt_fmt)

                    await tqdm_download_segments(self.client.session, fresh_track, filename, log_prefix=t_tag_bar, is_parallel=is_parallel, track_name=desc_name)
                    success = True
                    break
            except Exception: pass

        if LoopGlobals.get('abort_event').is_set(): return False
        
        if not success:
            await _log(f"{t_tag_arq} 🎧 {Tema.BOLD}{desc_name}{Tema.OFF}")
            await _log(f"{t_tag_status} ❌ {Tema.ERRO}Descartada (Sem formato){Tema.OFF}")
            return False

        q_str = f"[{actual_bd}b/{actual_sr}kHz]" if actual_bd and actual_sr else ""
        if int(final_fmt) == 5: q_str = "[MP3 320kbps]"
        await _log(f"{t_tag_arq} 🎧 {Tema.BOLD}{desc_name}{Tema.OFF} {Tema.GREEN}{q_str}{Tema.OFF}")
        
        try:
            t_depth_int = int(track_meta.get("maximum_bit_depth") or 16)
            t_rate_float = float(track_meta.get("maximum_sampling_rate") or 44.1)
        except ValueError:
            t_depth_int, t_rate_float = 16, 44.1

        if t_depth_int >= 24:
            t_max_fmt = 27 if t_rate_float > 96.0 else 7
        elif t_depth_int == 16:
            t_max_fmt = 6
        else:
            t_max_fmt = 5

        is_downgrade = False
        if int(final_fmt) < requested_fmt and int(final_fmt) < t_max_fmt:
            is_downgrade = True
        elif tier_idx > 0 and int(final_fmt) < requested_fmt:
            is_downgrade = True

        if is_downgrade:
            pedido_label = QUALITY_LABELS.get(requested_fmt, str(requested_fmt))
            obtido_label = QUALITY_LABELS.get(int(final_fmt), str(final_fmt))
            await _log(
                f"{t_tag_aviso} ⚠️ {Tema.AVISO}Downgrade automático: {pedido_label} indisponível para esta faixa "
                f"→ baixado em {obtido_label}{Tema.OFF}"
            )

        track_meta["actual_bit_depth"] = actual_bd
        track_meta["actual_sampling_rate"] = actual_sr
        track_meta["actual_format_id"] = final_fmt

        await asyncio.sleep(POST_DOWNLOAD_SETTLE_DELAY)

        tag_dir = cover_dir if cover_dir else root_dir
        
        cover_path_to_check = Path(tag_dir) / "embed_cover.jpg"
        
        lck_cov = LoopGlobals.get('cover_resize_lock')
        async with lck_cov:
            if cover_path_to_check.exists() and os.path.getsize(cover_path_to_check) >= 16500000:

                def _process_heavy_image():
                    import math
                    from PIL import Image

                    orig_size_bytes = os.path.getsize(cover_path_to_check)
                    orig_mb = orig_size_bytes / (1024 * 1024)
                    target_bytes = 16000000
                    
                    ratio = math.sqrt(target_bytes / orig_size_bytes)
                    resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                
                    with Image.open(cover_path_to_check) as img:
                        orig_format = img.format or "JPEG"
                        orig_w, orig_h = img.width, img.height
                        new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)

                        img_resized = img.resize((new_w, new_h), resample_filter)
                        buffer = io.BytesIO()
                        img_resized.save(buffer, format=orig_format, quality=90)

                    new_mb = buffer.tell() / (1024 * 1024)
                    
                    with open(cover_path_to_check, "wb") as f:
                        f.write(buffer.getvalue())

                    return orig_mb, orig_w, orig_h, new_mb, new_w, new_h
                    
                try:
                    o_mb, o_w, o_h, n_mb, n_w, n_h = await asyncio.to_thread(_process_heavy_image)
                    str_orig_mb = f"{o_mb:.1f}".replace(".", ",")
                    str_new_mb = f"{n_mb:.1f}".replace(".", ",")
                    await _log(f"{t_tag_arq} {Tema.AVISO} Capa > 16,5MB! Redimensionando de {str_orig_mb}MB ({o_w}x{o_h}) para {str_new_mb}MB ({n_w}x{n_h}){Tema.OFF}")
                except Exception as e:
                    await _log(f"{t_tag_arq} {Tema.ERRO}Falha ao processar capa: {e}{Tema.OFF}")

        correct_performer = _safe_get(track_meta, "performer", "name")
        raw_performers = track_meta.get("performers")
        
        if correct_performer and raw_performers:

            def remove_accents(input_str):
                return ''.join(c for c in unicodedata.normalize('NFD', input_str) if unicodedata.category(c) != 'Mn')

            persons = raw_performers.split(" - ")
            cleaned_persons = []
            
            for person in persons:
                parts = person.split(", ")
                person_name = parts[0]
                
                if remove_accents(person_name).lower() == remove_accents(correct_performer).lower():
                    parts[0] = correct_performer 
                    
                cleaned_persons.append(", ".join(parts))
                
            track_meta["performers"] = " - ".join(cleaned_persons)

        tag_function = metadata.tag_mp3 if final_fmt == 5 else metadata.tag_flac
        try:
            await asyncio.to_thread(
                tag_function,
                filename,
                tag_dir,
                str(final_file),
                track_meta,
                album_meta,
                is_track,
                self.embed_art,
                settings=self.settings
            )
        except Exception as e:
            await _log(f"{t_tag_status} ❌ {Tema.ERRO}Erro ao injetar metadados: {e}{Tema.OFF}")
            return False

        try:
            from qobuz_dl.db import upsert_library_file
            f_stat = final_file.stat()
            lck_db = LoopGlobals.get('db_write_lock')
            async with lck_db:
                await asyncio.to_thread(
                    upsert_library_file,
                    self.download_db,
                    path=final_file,
                    artist=filename_attr.get("track_artist", ""),
                    album_artist=filename_attr.get("albumartist", ""),
                    album=filename_attr.get("album_title", ""),
                    title=filename_attr.get("track_title", ""),
                    file_format=("MP3" if final_fmt == 5 else "FLAC"),
                    bit_depth=actual_bd,
                    sampling_rate=actual_sr,
                    file_size=f_stat.st_size,
                    mtime=f_stat.st_mtime,
                )
        except Exception:
            pass

        msg_tree = []
        
        if getattr(self, 'fetch_lyrics', False) and not LoopGlobals.get('abort_event').is_set():
            letra_nativa_ok = False
            track_id_str = str(track_meta["id"])
            
            try:
                req_ts = int(time.time())
                base_str = f"tracklyricsUrltrack_id{track_id_str}{req_ts}{self.client.sec}"
                req_sig = hashlib.md5(base_str.encode("utf-8")).hexdigest()
                endpoint_orig = f"{self.client.base}track/lyricsUrl?track_id={track_id_str}&request_ts={req_ts}&request_sig={req_sig}"
                
                async with self.client.session.get(endpoint_orig, headers=self.client.headers) as resp_orig:
                    if resp_orig.status == 200:
                        json_orig = await resp_orig.json()
                        
                        if json_orig and "lyrics_url" in json_orig:
                            async with self.client.session.get(yarl.URL(json_orig["lyrics_url"], encoded=True)) as l_resp:
                                if l_resp.status == 200:
                                    q_data = json.loads(await l_resp.text())
                                    
                                    lang_code = getattr(self, 'target_lang', 'PT-BR')[:2].lower()
                                    if lang_code in q_data.get("translation_langs", []):
                                        req_ts2 = int(time.time())
                                        base_str2 = f"tracklyricsUrllanguage{lang_code}track_id{track_id_str}{req_ts2}{self.client.sec}"
                                        req_sig2 = hashlib.md5(base_str2.encode("utf-8")).hexdigest()
                                        endpoint_trad = f"{self.client.base}track/lyricsUrl?track_id={track_id_str}&language={lang_code}&request_ts={req_ts2}&request_sig={req_sig2}"
                                        
                                        async with self.client.session.get(endpoint_trad, headers=self.client.headers) as resp_trad:
                                            if resp_trad.status == 200:
                                                json_trad = await resp_trad.json()
                                                if json_trad and "lyrics_url" in json_trad:
                                                    async with self.client.session.get(yarl.URL(json_trad["lyrics_url"], encoded=True)) as t_resp:
                                                        if t_resp.status == 200:
                                                            pt_data = json.loads(await t_resp.text())
                                                            if "translation" in pt_data:
                                                                q_data["translation"] = pt_data["translation"]
                                    
                                    use_enhanced = getattr(self.settings, 'enhanced_lrc', False)
                                    if hasattr(self, 'lyrics_engine'):
                                        lck_lyr = LoopGlobals.get('lyrics_translation_lock')
                                        async with lck_lyr:
                                            final_lrc, trans_count, total_lines, fonte = await self.lyrics_engine.process_qobuz_native_json(q_data, use_enhanced)
                                        
                                        if final_lrc:
                                            self.lyrics_engine._inject_metadata(str(final_file), final_lrc)
                                            if not getattr(self, 'no_lrc_files', False):
                                                lrc_path = final_file.with_suffix(".lrc")
                                                lrc_path.write_text(final_lrc, encoding="utf-8")
                                            
                                            if trans_count > 0:
                                                fonte_nome = "Oficial Qobuz" if "Nativa" in fonte else fonte
                                                msg_tree.append(f"{t_tag_letra} 📝 Letra: Qobuz (Sync) | Trad: {fonte_nome} ({trans_count}/{total_lines})")
                                            else:
                                                msg_tree.append(f"{t_tag_letra} 📝 Letra: Qobuz (Sync) | Trad: Nenhuma")
                                            letra_nativa_ok = True
            except Exception:
                pass

            if not letra_nativa_ok and hasattr(self, 'lyrics_engine'):
                s_artist = _safe_get(track_meta, "performer", "name") or _safe_get(track_meta, "artist", "name", default="Unknown")
                if _safe_get(track_meta, "album", "artist", "name") not in [None, "Various Artists"]:
                    s_artist = _safe_get(track_meta, "album", "artist", "name")
                    
                lck_lyr = LoopGlobals.get('lyrics_translation_lock')
                async with lck_lyr:
                    letra_ok, trans_count, total_lines, provider, fonte = await self.lyrics_engine.fetch_and_inject(
                        file_path=str(final_file),
                        album_artist=s_artist,
                        track=track_meta.get("title"),
                        album=_safe_get(track_meta, "album", "title", default=""),
                        duration=track_meta.get("duration", 0),
                        save_lrc=not self.no_lrc_files
                    )
                if letra_ok:
                    if trans_count > 0:
                        msg_tree.append(f"{t_tag_letra} 📝 Letra: 200 [{provider}] | Trad: {fonte} ({trans_count}/{total_lines})")
                    else:
                        msg_tree.append(f"{t_tag_letra} 📝 Letra: 200 [{provider}] | Trad: Nenhuma")
                else:
                    msg_tree.append(f"{t_tag_letra} 📝 Letra: Não encontrada")

        msg_tree.append(f"{t_tag_status} ✔️ {Tema.GREEN}Finalizado{Tema.OFF}")

        await _log("\n".join(msg_tree))

        if not is_parallel:
            await self._apply_delay(t_tag_arq)
            
        return True

    @staticmethod
    def _get_filename_attr(track_artist: str, track_meta: dict, album_meta: dict) -> dict:
        a_artist_str = str(album_meta.get("artist", {}).get("name") or album_meta.get("performer", {}).get("name") or track_artist)

        if "Various Artists" in a_artist_str:
            a_artist_str = track_artist

        final_track_artist = track_meta.get("performer", {}).get("name") or track_artist

        return {
            "artist": final_track_artist, "albumartist": a_artist_str, "tracktitle": _get_title(track_meta),
            "album_title": _get_title(album_meta), "album_title_base": album_meta.get("title"),
            "album_artist": a_artist_str, "track_id": track_meta.get("id"), "track_artist": final_track_artist,
            "track_composer": _safe_get(track_meta,"composer", "name"), "track_number": f'{track_meta.get("track_number", 0):02}',
            "isrc": track_meta.get("isrc"), "bit_depth": track_meta.get("maximum_bit_depth"),
            "sampling_rate": track_meta.get("maximum_sampling_rate"), "track_title": _get_title(track_meta),
            "track_title_base": track_meta.get("title"), "version": track_meta.get("version"),
            "year": track_meta.get("release_date_original", "").split("-")[0],
            "disc_number": f'{track_meta.get("media_number", 1):02}', "release_date": track_meta.get("release_date_original"),
            "ExplicitFlag": "[E]" if track_meta.get("parental_warning") else "",
            "explicit": "[E]" if track_meta.get("parental_warning") else "",
            "release_type": format_release_type(album_meta),
        }

    def _build_metadata_dict(self, meta: dict, title: str, bit_depth: str, sampling_rate: str, file_format: str, is_album: bool) -> dict:
        album_meta = meta if is_album else meta.get("album", {})

        a_artist_str = str(album_meta.get("artist", {}).get("name") or album_meta.get("performer", {}).get("name") or _safe_get(meta, "performer", "name", default="Unknown"))

        if "Various Artists" in a_artist_str:
            if is_album and "tracks" in meta and meta.get("tracks", {}).get("items"):
                first_track = meta["tracks"]["items"][0]
                a_artist_str = _safe_get(first_track, "performer", "name") or _safe_get(first_track, "artist", "name", default="Unknown")
            else:
                a_artist_str = _safe_get(meta, "performer", "name") or _safe_get(meta, "artist", "name", default="Unknown")

        res = {
            "album": _get_title(album_meta) if not is_album else title,
            "artist": a_artist_str if is_album else _safe_get(meta, "artist", "name", default=a_artist_str),
            "album_id": meta.get("id", ""), "album_url": meta.get("url", ""),
            "album_title": _get_title(album_meta) if not is_album else title,
            "album_title_base": album_meta.get("title", ""), "album_artist": a_artist_str,
            "album_genre": meta.get("genre", {}).get("name", ""), "album_composer": meta.get("composer", {}).get("name", ""),
            "label": re.sub(r'\s*[\;\/]\s*|\s+\-\s+', ' ／ ', ' '.join(meta.get("label",{}).get("name", "").split())).strip(),
            "copyright": meta.get("copyright", ""), "upc": meta.get("upc", ""), "barcode": meta.get("upc", ""),
            "release_date": meta.get("release_date_original", ""), "year": meta.get("release_date_original", "").split("-")[0],
            "media_type": meta.get("product_type", "").capitalize(), "format": file_format,
            "bit_depth": bit_depth, "sampling_rate": sampling_rate, "album_version": meta.get("version", ""),
            "version_tag": f" - {meta.get('version')}" if meta.get("version") else "",
            "disc_count": meta.get("media_count", 1), "track_count": meta.get("track_count", 1),
            "ExplicitFlag": "[E]" if (album_meta if not is_album else meta).get("parental_warning") else "",
            "explicit": "[E]" if (album_meta if not is_album else meta).get("parental_warning") else "",
            "release_type": format_release_type(album_meta),
        }
        if not is_album:
            res.update({"tracktitle": title, "track_title": title, "track_title_base": meta.get("title", "")})
        return res

    async def _get_format(self, item_dict: dict, is_track_id: bool = False, track_url_dict: dict = None) -> Tuple[str, bool, str, str]:
        if not is_track_id and ("tracks" not in item_dict or not item_dict["tracks"].get("items")):
            raise NonStreamable("This release has no tracks available (possibly region-locked)")

        track_dict = item_dict if is_track_id else item_dict["tracks"]["items"][0]
        quality_met = True
        try:
            new_track = await self.client.get_track_url(track_dict["id"], fmt_id=self.quality) if not track_url_dict else track_url_dict
            if not new_track: raise KeyError("No URL dict returned")

            restrictions = new_track.get("restrictions")
            if isinstance(restrictions, list) and any(r.get("code") == QL_DOWNGRADE for r in restrictions):
                quality_met = False
            return ("FLAC", quality_met, new_track.get("bit_depth"), new_track.get("sampling_rate"))
        except Exception:
            return ("Unknown", quality_met, None, None)

    async def _determine_formats(self, album_meta: dict, album_attr: dict, tracks_meta: list, track_attr: dict, is_track: bool, file_format: str, settings: QobuzDLSettings) -> None:
        combinations = [
            (self._original_folder_format, self._original_track_format, self._original_multiple_disc_track_format),
            (settings.fallback_folder_format, self._original_track_format, self._original_multiple_disc_track_format),
            (settings.fallback_folder_format, DEFAULT_TRACK, DEFAULT_MULTIPLE_DISC_TRACK),
            (DEFAULT_FOLDER, DEFAULT_TRACK, DEFAULT_MULTIPLE_DISC_TRACK)
        ]

        is_multiple = album_meta.get("media_count", 1) > 1
        legacy_flag = getattr(settings, 'legacy_charmap', False)

        for f_fmt, t_fmt, m_fmt in combinations:
            f_fmt, t_fmt = _clean_format_str(f_fmt, t_fmt, file_format)
            valid = True
            
            try:
                root_dir = process_folder_format_with_subdirs(f_fmt, track_attr if is_track else album_attr, legacy_charmap=legacy_flag)
                for t_meta in tracks_meta:
                    f_attr = self._get_filename_attr(_safe_get(t_meta, "performer", "name"), t_meta, album_meta)
                    if is_multiple and settings.multiple_disc_one_dir:
                        sanitize_filename(clean_filename(m_fmt.format(**f_attr), legacy_charmap=legacy_flag), replacement_text="_")
                    else:
                        sanitize_filename(clean_filename(t_fmt.format(**f_attr), legacy_charmap=legacy_flag), replacement_text="_")
            except (KeyError, ValueError):
                valid = False
                continue

            if valid:
                self.folder_format, self.track_format = f_fmt, t_fmt
                if self.settings: self.settings.multiple_disc_track_format = m_fmt
                return

        self.folder_format, self.track_format = DEFAULT_FOLDER, DEFAULT_TRACK

    async def _generate_tracklist(self, meta: dict, dirn: str, album_title: str, file_format: str, bit_depth: str, sampling_rate: str, prefix_tag: str = "", c_txt: str = Tema.OFF) -> None:
        import textwrap
        if self.no_credits or LoopGlobals.get('abort_event').is_set(): return
        
        t_path = Path(dirn) / f"{sanitize_filename(album_title)} - Tracklist.txt"
        if t_path.is_file(): return
            
        try:
            with open(t_path, "w", encoding="utf-8") as f:
                f.write("=" * 70 + "\n")
                f.write(f"ALBUM      : {album_title}\n")
                c = _safe_get(meta, "composer", "name", default="N/A")
                if c != "N/A": f.write(f"COMPOSER   : {c}\n")
                f.write(f"MAIN ART.  : {_safe_get(meta, 'artist', 'name', default='Unknown')}\n")
                f.write(f"LABEL      : {_safe_get(meta, 'label', 'name', default='Independent')}\n")
                f.write(f"GENRE      : {_safe_get(meta, 'genre', 'name', default='Unknown')}\n")
                f.write(f"RELEASE    : {meta.get('release_date_original', 'Unknown')}\n")
                f.write(f"QUALITY    : {file_format} ({bit_depth}-Bit / {sampling_rate} kHz)\n")
                f.write("=" * 70 + "\n\n")
                
                tracks = meta.get("tracks", {}).get("items", [])
                t_discs, curr_disc = max((t.get("media_number", 1) for t in tracks), default=1), None 
                
                for t in tracks:
                    if t_discs > 1 and (d_num := t.get("media_number", 1)) != curr_disc:
                        if curr_disc is not None: f.write("\n")
                        f.write(f"--- DISC {d_num} ---\n\n")
                        curr_disc = d_num

                    dur = int(t.get("duration", 0))
                    t_num = str(t.get("track_number", 0)).zfill(2)
                    t_title = t.get("title", "Unknown")
                    track_display = f"{t_num}. {t_title}"[:60]
                    f.write(f"{track_display:<60} [{dur//60:02}:{dur%60:02}]\n")

                    p_raw = t.get("performers", "")
                    if p_raw:
                        for line in re.split(r'\r?\n|\s+-\s+', str(p_raw)):
                            if line.strip(): f.write(f"    * {line.strip()}\n")
                    else:
                        f.write(f"    {_safe_get(t, 'performer', 'name', default=_safe_get(meta, 'artist', 'name', default='Unknown'))}\n")
                    f.write("\n")
                desc = meta.get("description")
                if desc:
                    f.write("\n" + "=" * 70 + "\nALBUM REVIEW / NOTES\n" + "=" * 70 + "\n\n")
                    for p in re.sub(r'<[^<]+>', '', re.sub(r'<br\s*/?>', '\n', str(desc))).split('\n'):
                        if p.strip(): f.write(textwrap.fill(p.strip(), width=70) + "\n\n")

            await safe_print_async(f"{prefix_tag}{c_txt}├──{Tema.OFF} 📄 {Tema.SUCESSO}Booklet criado com sucesso{Tema.OFF}")
        except Exception:
            pass

    async def _append_lyrics_to_booklet(self, dirn: str, album_title: str) -> None:
        if LoopGlobals.get('abort_event').is_set(): return
        
        t_path = Path(dirn) / f"{sanitize_filename(album_title)} - Tracklist.txt"
        if not t_path.is_file(): return
            
        a_files = sorted(f for f in Path(dirn).rglob("*") if f.suffix.lower() in {'.flac', '.mp3'})
        to_append = []
        
        for a_path in a_files:
            lrc_path, txt_path = a_path.with_suffix(".lrc"), a_path.with_suffix(".txt")
            l_text = ""
            
            if lrc_path.exists():
                clean = re.sub(r'\[[a-zA-Z]+:.*?\]\n?|\[\d{2,}:\d{2}\.\d{2,3}\]', '', lrc_path.read_text(encoding="utf-8"))
                l_text = "\n".join(line.strip() for line in clean.splitlines() if line.strip() or (l_text and l_text[-1] != "")).strip()
            elif txt_path.exists() and "Tracklist" not in txt_path.name:
                l_text = txt_path.read_text(encoding="utf-8").strip()
                    
            if l_text: to_append.append(f"--- {a_path.stem} ---\n\n{l_text}\n\n")
                
        if to_append:
            try:
                with open(t_path, "a", encoding="utf-8") as f:
                    f.write("\n" + "=" * 70 + "\nALBUM LYRICS\n" + "=" * 70 + "\n\n")
                    f.writelines(to_append)
            except Exception:
                pass

def _get_title(item: dict) -> str:
    title = item.get("title", "")
    if v := item.get("version"):
        title = f"{title} ({v})" if v.lower() not in title.lower() else title
    return title

async def _get_shared_cover_session() -> aiohttp.ClientSession:
    lck = LoopGlobals.get('cover_session_lock')
    async with lck:
        sess = LoopGlobals.get('cover_session')
        if sess is None or sess.closed:
            from qobuz_dl.core import FastTCPConnector
            sess = aiohttp.ClientSession(connector=FastTCPConnector())
            LoopGlobals.set('cover_session', sess)
    return sess

async def close_shared_cover_session() -> None:
    sess = LoopGlobals.get('cover_session')
    if sess is not None and not sess.closed:
        await sess.close()
    LoopGlobals.set('cover_session', None)

async def _get_extra(item: str, dirn: str, extra: str = "cover.jpg", art_size: str = None, og_quality: bool = False, is_playlist: bool = False, prefix_tag: str = "", c_txt: str = Tema.OFF) -> None:
    if LoopGlobals.get('abort_event').is_set(): return
    e_file = Path(dirn) / extra
    
    tag_capa = f"{prefix_tag}{c_txt}├──{Tema.OFF}"
    
    if e_file.is_file():
        q_file = Path(dirn) / ".cover_quality"
        q_tag = ""
        if q_file.exists():
            saved_q = q_file.read_text(encoding="utf-8").strip()
            if saved_q == "Apple":
                q_tag = f" {Tema.PURPLE}[Apple]{Tema.OFF}"
            else:
                q_tag = f" {Tema.CYAN}[Qobuz _{saved_q}]{Tema.OFF}" if saved_q and saved_q != "org" else f" {Tema.CYAN}[Qobuz]{Tema.OFF}"
                
        await safe_print_async(f"{tag_capa} 🖼️ {extra}{q_tag} ⏭️  {Tema.AVISO}Pulando (Já existe){Tema.OFF}")
        return
        
    if og_quality: art_size = "org"
    
    is_apple = "mzstatic.com" in item
    qualities_to_try = [art_size, "600"] if art_size else ["600"]
    
    for q in qualities_to_try:
        if LoopGlobals.get('abort_event').is_set(): break
        
        try_url = item.replace("_600.", f"_{q}.") if (q and not is_apple) else item
        
        try:
            sess = await _get_shared_cover_session()
            
            bar_prefix = prefix_tag.replace("[CAPA ]", "       ").replace("[EXTRA]", "       ")
            log_bar = f"{bar_prefix}{c_txt}│  {Tema.OFF}"
            
            await tqdm_download(sess, try_url, str(e_file), log_prefix=log_bar, is_parallel=False)
            
            if is_apple:
                q_tag = f" {Tema.PURPLE}[Apple]{Tema.OFF}"
                saved_q = "Apple"
            else:
                q_tag = f" {Tema.CYAN}[Qobuz _{q}]{Tema.OFF}" if q else f" {Tema.CYAN}[Qobuz]{Tema.OFF}"
                saved_q = q
                
            await safe_print_async(f"{tag_capa} 🖼️ {extra}{q_tag}")
            
            if extra in ["cover.jpg", EMB_COVER_NAME] and saved_q:
                (Path(dirn) / ".cover_quality").write_text(saved_q, encoding="utf-8")
            return
            
        except Exception:
            if is_apple: break
            continue

def _clean_format_str(folder: str, track: str, file_format: str) -> Tuple[str, str]:
    final = []
    for i, fs in enumerate((folder, track)):
        fs = fs[:-4].strip() if fs.endswith(".mp3") else (fs[:-5].strip() if fs.endswith(".flac") else fs.strip())
        if file_format in ("MP3", "Unknown") and ("bit_depth" in fs or "sampling_rate" in fs):
            fs = DEFAULT_FORMATS[file_format][i]
        final.append(fs)
    return tuple(final)

def _safe_get(d: dict, *keys, default=None):
    res = default
    for key in keys:
        res = d.get(key, default)
        if res == default or not hasattr(res, "__getitem__"): return res
        d = res
    return res

async def tqdm_download(session, url: str, fname: str, log_prefix: str = "", is_parallel: bool = False, track_name: str = "") -> None:
    if LoopGlobals.get('abort_event').is_set(): return
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Connection": "keep-alive"}
    d_size, t_size = 0, 0
    delays = [4, 8, 16, 32, 64] 

    for attempt in range(5):
        if LoopGlobals.get('abort_event').is_set(): break
        try:
            headers['Range'] = f'bytes={d_size}-'
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(sock_read=30.0, connect=10.0)) as r:
                if r.status == 416: return
                if r.status not in [200, 206]: raise Exception(f"HTTP {r.status}")
                
                if r.status == 200 and d_size > 0:
                    d_size = 0
                    t_size = 0

                if t_size == 0: t_size = d_size + int(r.headers.get('content-length', 0))

                async with aiofiles.open(fname, 'ab' if d_size > 0 else 'wb') as file:
                    # =========================================================
                    # BARRA DE PROGRESSO DINÂMICA
                    # =========================================================
                    term_width = shutil.get_terminal_size((80, 20)).columns
                    display_name = track_name
                    bar_fmt = "{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]"
                    
                    if term_width < 65: # Modo iPhone / Ecrã apertado
                        display_name = track_name[:12] + ".." if track_name and len(track_name) > 12 else track_name
                        bar_fmt = "{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}"
                        
                    bar_desc = f"{log_prefix}⬇️ {display_name}" if display_name else f"{log_prefix}⬇️ "
                    
                    with tqdm(total=t_size, unit="B", unit_scale=True, desc=bar_desc, initial=d_size, disable=is_parallel, leave=False, dynamic_ncols=True, bar_format=bar_fmt) as bar:
                        async for data in r.content.iter_chunked(262144):
                            if LoopGlobals.get('abort_event').is_set(): break
                            if data:
                                await file.write(data)
                                d_size += len(data)
                                if not is_parallel: bar.update(len(data))
            
            if LoopGlobals.get('abort_event').is_set():
                if Path(fname).exists(): Path(fname).unlink()
                return

            if d_size >= t_size: return 

        except asyncio.TimeoutError:
            if attempt < 4:
                await asyncio.sleep(delays[attempt])
                continue
            Path(fname).unlink(missing_ok=True)
            raise Exception("Timeout definitivo")
        except Exception as e:
            if attempt < 4 and "404" not in str(e):
                await asyncio.sleep(delays[attempt])
                continue
            Path(fname).unlink(missing_ok=True)
            raise Exception(f"Falha definitiva: {e}")

    if LoopGlobals.get('abort_event').is_set():
        Path(fname).unlink(missing_ok=True)
        return

    if d_size < t_size and not LoopGlobals.get('abort_event').is_set():
        Path(fname).unlink(missing_ok=True)
        raise Exception("Incomplete download")

async def tqdm_download_segments(session, track_url: dict, fname: str, log_prefix: str = "", is_parallel: bool = False, track_name: str = "") -> None:
    if LoopGlobals.get('abort_event').is_set(): return
    
    tmp_fname = f"{fname}.mp4"
    n_seg = track_url["n_segments"]
    tmpl = track_url["url_template"]
    key = track_url["raw_key"]

    async def fetch_seg(sess, i, bar):
        if LoopGlobals.get('abort_event').is_set(): return bytearray()
        for attempt in range(4):
            try:
                async with sess.get(tmpl.replace("$SEGMENT$", str(i)), timeout=15) as r:
                    r.raise_for_status()
                    data = bytearray()
                    async for chunk in r.content.iter_chunked(262144):
                        if LoopGlobals.get('abort_event').is_set(): return bytearray()
                        data.extend(chunk)
                        if not is_parallel: bar.update(1)
                    return data
            except Exception:
                if attempt == 3: raise
                await asyncio.sleep(2 ** attempt)

    try:
        async with aiofiles.open(tmp_fname, "wb") as f:
            # =========================================================
            # BARRA DE PROGRESSO DINÂMICA (Segmentos)
            # =========================================================
            term_width = shutil.get_terminal_size((80, 20)).columns
            display_name = track_name
            bar_fmt = "{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]"
            
            if term_width < 65:
                display_name = track_name[:12] + ".." if track_name and len(track_name) > 12 else track_name
                bar_fmt = "{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}"
                
            bar_desc = f"{log_prefix}✂️ {display_name}" if display_name else f"{log_prefix}✂️ "
            
            with tqdm(total=n_seg, unit="seg", desc=bar_desc, disable=is_parallel, leave=False, dynamic_ncols=True, bar_format=bar_fmt) as bar:
                seg_uuid = None
                for i in range(2):
                    data = await fetch_seg(session, i, bar)
                    if LoopGlobals.get('abort_event').is_set(): return
                    if i == 1:
                        seg_uuid = _get_qobuz_segment_uuid(data)

                    decrypted_data = await asyncio.to_thread(_decrypt_qobuz_segment, data, key, seg_uuid)
                    await f.write(decrypted_data)

                if n_seg >= 2:
                    sem = asyncio.Semaphore(8)
                    async def bounded_fetch(i):
                        async with sem: return await fetch_seg(session, i, bar)
                    tasks = [asyncio.create_task(bounded_fetch(i)) for i in range(2, n_seg + 1)]
                    
                    for task in tasks:
                        data = await task
                        if not LoopGlobals.get('abort_event').is_set() and data:
                            decrypted_data = await asyncio.to_thread(_decrypt_qobuz_segment,data, key, seg_uuid)
                            await f.write(decrypted_data)
                            del data 
                            del decrypted_data 

    finally:
        if LoopGlobals.get('abort_event').is_set() and Path(tmp_fname).exists():
            try: Path(tmp_fname).unlink()
            except OSError: pass
            return

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", tmp_fname, 
            "-c:a", "copy", fname, 
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        
        try:
            _, stderr = await proc.communicate()
            if proc.returncode != 0: raise ConnectionError(f"FFmpeg failed: {stderr.decode()}")
        except asyncio.CancelledError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
            raise 
        finally:
            if Path(tmp_fname).exists():
                try: Path(tmp_fname).unlink()
                except OSError: pass

def _get_qobuz_segment_uuid(segment_data):
    pos = 0
    while pos + 24 <= len(segment_data):
        size = int.from_bytes(segment_data[pos : pos + 4], "big")
        if size <= 0 or pos + size > len(segment_data): break
        if bytes(segment_data[pos + 4 : pos + 8]) == b"uuid": return bytes(segment_data[pos + 8 : pos + 24])
        pos += size
    return None

def _decrypt_qobuz_segment(segment_data, raw_key, segment_uuid):
    if segment_uuid is None: return bytes(segment_data)
    buf = bytearray(segment_data)
    pos = 0
    while pos + 8 <= len(buf):
        size = int.from_bytes(buf[pos : pos + 4], "big")
        if size <= 0 or pos + size > len(buf): break

        if bytes(buf[pos + 4 : pos + 8]) == b"uuid" and bytes(buf[pos + 8 : pos + 24]) == segment_uuid:
            ptr = pos + 28
            data_end = pos + int.from_bytes(buf[ptr : ptr + 4], "big")
            ptr += 4
            c_len = buf[ptr]
            ptr += 1
            f_count = int.from_bytes(buf[ptr : ptr + 3], "big")
            ptr += 3

            for _ in range(f_count):
                f_len = int.from_bytes(buf[ptr : ptr + 4], "big")
                ptr += 6
                flags = int.from_bytes(buf[ptr : ptr + 2], "big")
                ptr += 2
                f_start, data_end = data_end, data_end + f_len

                if flags:
                    c = bytes(buf[ptr : ptr + c_len]) + (b"\x00" * (16 - c_len))
                    
                    if HAS_NATIVE_CRYPTO: 
                        cipher = AES.new(raw_key, AES.MODE_CTR, initial_value=c, nonce=b'')
                        buf[f_start:data_end] = cipher.decrypt(bytes(buf[f_start:data_end]))
                    else:
                        counter_int = int.from_bytes(c, byteorder='big')
                        counter = pyaes.Counter(initial_value=counter_int)
                        cipher = pyaes.AESModeOfOperationCTR(raw_key, counter=counter)
                        buf[f_start:data_end] = cipher.decrypt(bytes(buf[f_start:data_end]))

                ptr += c_len
        pos += size
    return bytes(buf)

async def _download_goodies(album_meta: dict, dirn: str, prefix_tag: str = "", c_txt: str = Tema.OFF) -> None:
    if LoopGlobals.get('abort_event').is_set(): return
    try:
        for goody in album_meta.get("goodies", []):
            if LoopGlobals.get('abort_event').is_set(): break
            if not goody.get("url"): continue
            g_name = sanitize_filename(clean_filename(f'{album_meta.get("title")} ({goody.get("id")}).pdf'))
            await _get_extra(goody.get("url"), dirn, extra=g_name, prefix_tag=prefix_tag, c_txt=c_txt)
    except Exception:
        pass

async def _clean_embed_art(dirn: Union[str, Path]) -> None:
    e_file = Path(dirn) / EMB_COVER_NAME
    q_file = Path(dirn) / ".cover_quality"
    
    if e_file.exists():
        try:
            await asyncio.sleep(0.5) 
            e_file.unlink()
        except OSError: pass

    if q_file.exists():
        try:
            q_file.unlink()
        except OSError: pass
