import logging
import shutil
import sys
import os
import time
import re
import signal
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, Union
import textwrap

import aiohttp
import aiofiles
import asyncio
try:
    from Cryptodome.Cipher import AES
except ImportError:
    from Crypto.Cipher import AES
from pathvalidate import sanitize_filename, sanitize_filepath
from tqdm import tqdm

import qobuz_dl.metadata as metadata
from qobuz_dl.color import OFF, GREEN, RED, YELLOW, CYAN, RESET
from qobuz_dl.exceptions import NonStreamable
from qobuz_dl.settings import QobuzDLSettings
from qobuz_dl.utils import get_album_artist, clean_filename
from qobuz_dl.db import handle_download_id
from qobuz_dl.constants import DEFAULT_FOLDER, DEFAULT_TRACK, DEFAULT_MULTIPLE_DISC_TRACK
from qobuz_dl.lyrics_engine import LyricsEngine

# UI Lock and Event management explicitly designed for Asyncio
print_lock = asyncio.Lock()
abort_event = asyncio.Event()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def safe_print_async(*args, **kwargs) -> None:
    """Imprime de forma assíncrona garantindo que a barra do tqdm não é quebrada."""
    async with print_lock:
        text = " ".join(map(str, args))
        tqdm.write(text, end=kwargs.get('end', '\n'))

def format_release_type(release_type: Optional[str]) -> str:
    """Normaliza o tipo de lançamento retornado pela API."""
    if not release_type:
        return "Unknown"
    release_type = release_type.lower()
    return "EP" if release_type == "ep" else release_type.title()

def process_folder_format_with_subdirs(folder_format: str, attr_dict: dict, path: Optional[str] = None, legacy_charmap: bool = False) -> str:
    """Processa o formato da pasta, limpa carateres inválidos e constrói a árvore."""
    cleaned_parts = []
    for part in folder_format.split('/'):
        if not part: continue
        try:
            formatted_part = part.format(**attr_dict)
            cleaned_part = sanitize_filepath(clean_filename(formatted_part, legacy_charmap=legacy_charmap), replacement_text="_")
            
            # Truncamento inteligente
            if cleaned_part and len(cleaned_part) > 120:
                cleaned_part = cleaned_part[:60].rstrip(' ."-_\'') + "..." + cleaned_part[-50:].lstrip(' ."-_\'')
                
            if cleaned_part: cleaned_parts.append(cleaned_part)
        except KeyError as e:
            logger.warning(f"{YELLOW}Format error ({e}), using original text.{OFF}")
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


class Download:
    def __init__(
        self, client: Any, item_id: str, path: str, quality: int, embed_art: bool = False,
        albums_only: bool = False, downgrade_quality: bool = False, cover_og_quality: bool = False,
        no_cover: bool = False, folder_format: str = None, track_format: str = None, fetch_lyrics: bool = False,
        no_lrc_files: bool = False, genius_token: str = None, deepl_api_key: str = None, target_lang: str = "PT-BR",
        no_credits: bool = False, settings: QobuzDLSettings = None, download_db: str = None,
        is_playlist: bool = False, playlist_track_number: int = None, booklet_only: bool = False
    ):
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
        
        if self.fetch_lyrics:
            self.lyrics_engine = LyricsEngine(genius_token=genius_token, deepl_api_key=deepl_api_key, translate=True, target_lang=self.target_lang)

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
 
    async def _apply_delay(self):
        """Gerencia o delay de forma centralizada"""
        delay_val = int(self.delay) if self.delay is not None else 0

        if delay_val > 0 and not abort_event.is_set():
            await safe_print_async(f"{YELLOW}[*] Sleeping {delay_val}s...{OFF}")
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
        album_meta = await self.client.get_album_meta(self.item_id)

        if not album_meta.get("streamable"):
            raise NonStreamable("This release is not streamable")

        if self.albums_only and (album_meta.get("release_type") != "album" or album_meta.get("artist").get("name") == "Various Artists"):
            logger.info(f'{OFF}Ignoring Single/EP/VA: {album_meta.get("title", "n/a")}')
            return

        album_title = _get_title(album_meta)
        url = album_meta.get("url", "")
        release_date = album_meta.get("release_date_original", "")
        file_format, quality_met, bit_depth, sampling_rate = await self._get_format(album_meta)

        if not self.downgrade_quality and not quality_met:
            logger.info(f"{OFF}Skipping {album_title} as it doesn't meet quality requirement")
            return

        _track_count = sum(1 for t in album_meta["tracks"]["items"] if "sample" not in t and t.get("streamable", True))
        logger.info(f"\n{YELLOW}Downloading: {album_title}\nQuality: {file_format} ({bit_depth}bit/{sampling_rate}kHz) | [{_track_count} FAIXAS NA FILA..]\n{OFF}")
        
        album_attr = self._build_metadata_dict(album_meta, album_title, bit_depth, sampling_rate, file_format, True)
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
            except OSError as e:
                logger.warning(f"{YELLOW}[!] Could not rename folder to [IN PROGRESS]. ({e}){OFF}")
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
            await safe_print_async(f"{YELLOW}[*] Safety Delay active: Sequential mode enabled.{OFF}")
            active_workers = 1
        elif is_parallel:
            await safe_print_async(f"{YELLOW}[*] Multithreading Enabled ({active_workers} workers).{OFF}")
            
        failed_tracks, aborted_by_user = 0, False
        abort_event.clear()

        try:
            await self._generate_tracklist(album_meta, str(working_dirn), album_title, file_format, bit_depth, sampling_rate)

            if self.settings.no_cover:
                logger.info(f"{OFF}Skipping cover")
            else:
                await _get_extra(album_meta["image"]["large"], str(working_dirn), art_size="org")

            if self.settings.embed_art:
                cover_path, embed_path = working_dirn / "cover.jpg", working_dirn / EMB_COVER_NAME
                if cover_path.exists(): shutil.copy2(cover_path, embed_path)
                else: await _get_extra(album_meta["image"]["large"], str(working_dirn), extra=EMB_COVER_NAME, art_size="org")

            if "goodies" in album_meta:
                await _download_goodies(album_meta, str(working_dirn))
                
            if getattr(self, 'booklet_only', False):
                await safe_print_async(f"{YELLOW}[*] --booklet-only flag active. Skipping tracks.{OFF}")
                if is_standard_album and working_dirn == inprogress_dirn:
                    try: working_dirn.rename(incomplete_dirn)
                    except OSError: pass
                return
             
            # --- CÓDIGO DE CONCORRÊNCIA OTIMIZADO ---
            sem = asyncio.Semaphore(active_workers)
            
            async def bound_process_track(dirn, t_count, track_item, a_meta, is_multi, is_para):
                """Envolve a chamada de API E o download na mesma barreira do semáforo."""
                async with sem:
                    if abort_event.is_set(): return False
                    
                    try:
                        # A API só é chamada quando o worker está liberado para trabalhar (Evita HTTP 429)
                        parse = await self.client.get_track_url(track_item["id"], fmt_id=self.quality)
                    except Exception as e:
                        await safe_print_async(f"{RED}[!] API Error for track {track_item.get('track_number')} (ID: {track_item['id']}): {e}{OFF}")
                        return False

                    if "sample" not in parse and parse.get("sampling_rate"):
                        media_num = track_item.get("media_number") if is_multi else None
                        return await self._download_and_tag(
                            dirn, t_count, parse, track_item, a_meta, False, int(self.quality) == 5, media_num, is_para
                        )
                    return False

            tasks = []
            for continuous_track_index, i in enumerate(album_meta["tracks"]["items"], start=1):
                if abort_event.is_set(): break
                if is_multiple: i["track_number"] = continuous_track_index
                
                tasks.append(bound_process_track(str(working_dirn), count, i, album_meta, is_multiple, is_parallel))
                count += 1

            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        await safe_print_async(f"{RED}[!] Track process failed: {res}{OFF}")
                        failed_tracks += 1
                    elif res is False: failed_tracks += 1
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                abort_event.set()
                aborted_by_user = True
                await safe_print_async(f"\n{RED}[!] CTRL+C Intercepted: Securing files and folders...{OFF}")
                    
            if not aborted_by_user:
                await _clean_embed_art(working_dirn)
                if self.fetch_lyrics and not self.no_credits:
                    await self._append_lyrics_to_booklet(str(working_dirn), album_title)
                    
        except (KeyboardInterrupt, SystemExit):
            abort_event.set()
            aborted_by_user = True
            await safe_print_async(f"\n{RED}[!] CTRL+C Intercepted...{OFF}")
                
        if aborted_by_user: time.sleep(1.5)
            
        if is_standard_album and working_dirn == inprogress_dirn:
            final_dirn = target_dirn if (failed_tracks == 0 and not aborted_by_user) else incomplete_dirn
            try: working_dirn.rename(final_dirn)
            except OSError: final_dirn = working_dirn
            
            if aborted_by_user: await safe_print_async(f"{YELLOW}[!] Download aborted. Marked as [INCOMPLETE].{OFF}")
            elif failed_tracks > 0: await safe_print_async(f"\n{YELLOW}[!] Download partial. Marked as [INCOMPLETE].{OFF}")
        else:
            final_dirn = working_dirn
        
        if aborted_by_user: os._exit(1)
            
        handle_download_id(self.download_db, self.item_id, add_id=True, media_type="album", quality=self.quality, file_format=file_format, quality_met=quality_met, bit_depth=bit_depth, sampling_rate=sampling_rate, saved_path=str(final_dirn), url=url, release_date=release_date, artist=album_attr.get("album_artist", "Unknown"), album=album_attr.get("album_title", "Unknown"))
        await safe_print_async(f"{GREEN}Completed{OFF}")

    async def download_track(self) -> None:
        parse = await self.client.get_track_url(self.item_id, self.quality)
        if "sample" not in parse and parse["sampling_rate"]:
            track_meta = await self.client.get_track_meta(self.item_id)
            if getattr(self, 'is_playlist', False) and self.playlist_track_number:
                track_meta["track_number"] = self.playlist_track_number
            
            track_title, artist = _get_title(track_meta), _safe_get(track_meta, "performer", "name")
            logger.info(f"\n{YELLOW}Downloading: {artist} - {track_title}{OFF}")

            file_format, quality_met, bit_depth, sampling_rate = await self._get_format(track_meta, is_track_id=True, track_url_dict=parse)
            if not self.downgrade_quality and not quality_met:
                logger.info(f"{OFF}Skipping {track_title}: quality requirement not met")
                return
                
            track_attr = self._build_metadata_dict(track_meta, track_title, bit_depth, sampling_rate, file_format, False)
            await self._determine_formats(track_meta.get("album", {}), None, [track_meta], track_attr, True, file_format, self.settings)
            
            dirn = Path(process_folder_format_with_subdirs(self.folder_format, track_attr, self.path, getattr(self.settings, 'legacy_charmap', False)))
            dirn.mkdir(parents=True, exist_ok=True)

            if getattr(self, 'is_playlist', False):
                logger.info(f"{OFF}Skipping standard cover save to keep playlist folder clean")
                if self.settings.embed_art:
                    await _get_extra(track_meta["album"]["image"]["large"], str(dirn), extra=EMB_COVER_NAME, art_size="org")
            elif not self.settings.no_cover:
                await _get_extra(track_meta["album"]["image"]["large"], str(dirn), art_size="org")
                if self.settings.embed_art:
                    cover_path, embed_path = dirn / "cover.jpg", dirn / EMB_COVER_NAME
                    if cover_path.exists(): shutil.copy2(cover_path, embed_path)
            
            download_success = await self._download_and_tag(str(dirn), 1, parse, track_meta, track_meta, True, int(self.quality) == 5, False, False)
            await _clean_embed_art(dirn)
            
            if download_success and not abort_event.is_set():
                handle_download_id(self.download_db, self.item_id, True, "track", self.quality, file_format, quality_met, bit_depth, sampling_rate, str(dirn), track_meta.get("album", {}).get("url", ""), track_meta.get("release_date_original", ""), track_attr.get("artist", "Unknown"), track_attr.get("album", "Unknown"))
            else:
                await safe_print_async(f"{YELLOW}[*] Faixa Incompleta. Ignorando base de dados.{OFF}")
        else:
            logger.info(f"{OFF}Demo. Skipping")
        logger.info(f"{GREEN}Completed{OFF}")

    async def _download_and_tag(self, root_dir: str, tmp_count: int, track_url_dict: dict, track_meta: dict, album_meta: dict, is_track: bool, is_mp3: bool, multiple: Optional[int], is_parallel: bool) -> bool:
        extension = ".mp3" if is_mp3 else ".flac"
        legacy_flag = getattr(self.settings, 'legacy_charmap', False)
        filename_attr = self._get_filename_attr(_safe_get(track_meta, "performer", "name"), track_meta, album_meta.get("album", {}) if is_track else album_meta)

        if getattr(self, 'is_playlist', False):
            formatted_path = sanitize_filename(clean_filename("{artist} - {track_title}".format(**filename_attr), legacy_charmap=legacy_flag), replacement_text="_")
        elif multiple and self.settings.multiple_disc_one_dir:
            formatted_path = sanitize_filename(clean_filename(self.settings.multiple_disc_track_format.format(**filename_attr), legacy_charmap=legacy_flag), replacement_text="_")
        else:
            base_formatted = sanitize_filename(clean_filename(self.track_format.format(**filename_attr), legacy_charmap=legacy_flag), replacement_text="_")
            if multiple and album_meta.get('media_count', 1) > 1:
                try: d_num = int(multiple) if not isinstance(multiple, bool) else 1
                except: d_num = 1
                formatted_path = os.path.join(f"{self.settings.multiple_disc_prefix} {d_num:02}", base_formatted)
            else:
                formatted_path = base_formatted
            
        if len(formatted_path) > 180:
            formatted_path = formatted_path[:110].rstrip(' ."-_\'') + "..." + formatted_path[-60:].lstrip(' ."-_\'')
            
        final_file = Path(root_dir) / f"{formatted_path}{extension}"

        if final_file.exists():
            await safe_print_async(f"{CYAN}[*] Skipping: {final_file.name} (Already exists){OFF}")
            return True

        if abort_event.is_set(): return False
        
        if not is_parallel:
            await self._apply_delay()

        try: url = track_url_dict["url"]
        except KeyError:
            logger.info(f"{OFF}Track not available for download")
            return False

        if multiple and album_meta.get('media_count', 1) > 1 and not self.settings.multiple_disc_one_dir:
            try: d_num = int(multiple) if not isinstance(multiple, bool) else 1
            except: d_num = 1
            root_dir = str(Path(root_dir) / f"{self.settings.multiple_disc_prefix} {d_num:02}")
            Path(root_dir).mkdir(exist_ok=True)

        filename = str(Path(root_dir) / f".{tmp_count:02}.tmp")
        track_no = str(track_meta.get('track_number', 0)).zfill(2)
        desc = f"{track_no}. {track_meta.get('title')}"

        FALLBACK_TIERS, TIER_NAMES = [27, 7, 6, 5], {27: "24-bit/>96kHz", 7: "24-bit/96kHz", 6: "16-bit/44.1kHz (CD)", 5: "MP3 320kbps"}
        try: start_idx = FALLBACK_TIERS.index(int(self.quality))
        except ValueError: start_idx = 0
            
        success, final_fmt = False, int(self.quality)
        for attempt_fmt in FALLBACK_TIERS[start_idx:]:
            if abort_event.is_set(): return False
            if attempt_fmt != int(self.quality):
                await safe_print_async(f"{YELLOW}[!] Downgrade: Attempting {TIER_NAMES[attempt_fmt]}...{OFF}")

            async def get_fresh_url(fmt=attempt_fmt, force_segments=False):
                return await self.client.get_track_url(track_meta["id"], fmt_id=fmt, force_segments=force_segments)

            try:
                fresh_track = await get_fresh_url(force_segments=False)
                if "url" in fresh_track:
                    try:
                        await tqdm_download(fresh_track["url"], filename, desc, is_parallel)
                        success, final_fmt = True, attempt_fmt
                        break
                    except Exception:
                        if abort_event.is_set(): return False
                        await safe_print_async(f"{YELLOW}[!] Akamai block. Activating fallback segmented download...{OFF}")
                        fresh_track = await get_fresh_url(force_segments=True)
                
                if "url_template" in fresh_track:
                    await tqdm_download_segments(fresh_track, filename, desc, is_parallel)
                    success, final_fmt = True, attempt_fmt
                    break
            except Exception: pass

        if abort_event.is_set(): return False
        if not success:
            await safe_print_async(f"\n{RED}[!] TRACK {track_no} DISCARDED AFTER ALL DOWNGRADES.{OFF}")
            return False

        tag_function = metadata.tag_mp3 if final_fmt == 5 else metadata.tag_flac
        try:
            tag_function(filename, root_dir, str(final_file), track_meta, album_meta, is_track, self.embed_art, settings=self.settings)
        except Exception as e:
            await safe_print_async(f"{RED}[!] Error tagging: {e}{OFF}")

        if self.fetch_lyrics and hasattr(self, 'lyrics_engine') and not abort_event.is_set():
            s_artist = _safe_get(track_meta, "performer", "name") or _safe_get(track_meta, "artist", "name", default="Unknown")
            if _safe_get(track_meta, "album", "artist", "name") not in [None, "Various Artists"]:
                s_artist = _safe_get(track_meta, "album", "artist", "name")
                
            letra_ok, trans_count, total_lines, resp_code = await self.lyrics_engine.fetch_and_inject(
                file_path=str(final_file), album_artist=s_artist, track=track_meta.get("title"),
                album=_safe_get(track_meta, "album", "title", default=""), save_lrc=not self.no_lrc_files
            )
            if letra_ok:
                trad_str = f"{trans_count}/{total_lines} - ({'Total' if trans_count >= total_lines else 'Parcial'})" if trans_count else "Não"
                await safe_print_async(f"{OFF if resp_code != 'Local' else CYAN}[*] Letra Encontrada{' (Local)' if resp_code == 'Local' else ''}: {desc} - {s_artist} | Trad: {trad_str} | Code: {resp_code}{OFF}")
            else:
                await safe_print_async(f"{RED}  [-] Letra Não Encontrada: {desc} - {s_artist}{OFF}")

        if not is_parallel:
            await self._apply_delay()
            
        return True

    @staticmethod
    def _get_filename_attr(track_artist: str, track_meta: dict, album_meta: dict) -> dict:     
        a_artist_raw = get_album_artist(album_meta)
        a_artist_str = ", ".join(a_artist_raw) if isinstance(a_artist_raw, list) else (str(a_artist_raw) if a_artist_raw else track_artist)

        performers = track_meta.get("performers", [])
        if isinstance(performers, list) and performers:
            seen = set()
            names = [p.get("name") for p in performers if isinstance(p, dict) and p.get("name") and not (p.get("name") in seen or seen.add(p.get("name")))]
            final_track_artist = ", ".join(names) if names else track_artist
        elif isinstance(performers, str) and performers.strip():
            final_track_artist = performers
        else:
            final_track_artist = track_artist

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
        }

    def _build_metadata_dict(self, meta: dict, title: str, bit_depth: str, sampling_rate: str, file_format: str, is_album: bool) -> dict:
        """Centraliza a extração de dados da API num dicionário amigável de tags, fundindo a lógica de álbum e faixa."""
        album_meta = meta if is_album else meta.get("album", {})
        a_artist_raw = get_album_artist(album_meta)
        a_artist_str = ", ".join(a_artist_raw) if isinstance(a_artist_raw, list) else (str(a_artist_raw) if a_artist_raw else _safe_get(meta, "performer", "name"))

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
            "release_type": format_release_type(album_meta.get("release_type") if not is_album else meta.get("release_type")),
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

    async def _generate_tracklist(self, meta: dict, dirn: str, album_title: str, file_format: str, bit_depth: str, sampling_rate: str) -> None:
        import textwrap
        if self.no_credits or abort_event.is_set(): return
        
        t_path = Path(dirn) / f"{sanitize_filename(album_title)} - Tracklist.txt"
        if t_path.is_file(): return
            
        await safe_print_async(f"{CYAN}[+] Generating Digital Booklet...{OFF}")
        
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

            await safe_print_async(f"{GREEN}  L Completed: Digital Booklet.txt{OFF}")
        except Exception as e:
            await safe_print_async(f"{RED}[!] Error creating booklet: {e}{OFF}")

    async def _append_lyrics_to_booklet(self, dirn: str, album_title: str) -> None:
        if abort_event.is_set(): return
        
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
                await safe_print_async(f"{CYAN}[+] Lyrics appended to Digital Booklet.{OFF}")
            except Exception as e:
                logger.error(f"{RED}[!] Error appending lyrics: {e}{OFF}")

def _get_title(item: dict) -> str:
    title = item.get("title", "")
    if v := item.get("version"):
        title = f"{title} ({v})" if v.lower() not in title.lower() else title
    return title

async def _get_extra(item: str, dirn: str, extra: str = "cover.jpg", art_size: str = None, og_quality: bool = False) -> None:
    if abort_event.is_set(): return
    e_file = Path(dirn) / extra
    if e_file.is_file(): return
        
    if og_quality: art_size = "org"
    if art_size in ["50", "100", "150", "300", "600", "max", "org"]:
        item = item.replace("_600.", f"_{art_size}.")
    
    try: await tqdm_download(item, str(e_file), extra, is_parallel=False)
    except Exception as e: await safe_print_async(f"  {YELLOW}[!] Skipping '{extra}': {e}{OFF}")

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

async def tqdm_download(url: str, fname: str, track_name: str, is_parallel: bool = False) -> None:
    if abort_event.is_set(): return
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Connection": "keep-alive"}
    d_size, t_size = 0, 0
    delays = [4, 8, 16, 32, 64] 

    for attempt in range(5):
        if abort_event.is_set(): return
        try:
            headers['Range'] = f'bytes={d_size}-'
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=headers, timeout=aiohttp.ClientTimeout(sock_read=30.0, connect=10.0)) as r:
                    if r.status == 416: return
                    if r.status not in [200, 206]: raise Exception(f"HTTP {r.status}")

                    if t_size == 0: t_size = d_size + int(r.headers.get('content-length', 0))
                    if d_size == 0 and attempt == 0:
                        await safe_print_async(f"{CYAN}[+] In progress: {track_name} [{t_size / (1024*1024):.1f} MB]{OFF}")

                    async with aiofiles.open(fname, 'ab' if d_size > 0 else 'wb') as file:
                        with tqdm(total=t_size, unit="iB", unit_scale=True, desc="" if is_parallel else f" {GREEN}Downloading{OFF}", initial=d_size, disable=is_parallel, leave=False) as bar:
                            async for data in r.content.iter_chunked(65536):
                                if abort_event.is_set(): return
                                if data:
                                    await file.write(data)
                                    d_size += len(data)
                                    if not is_parallel: bar.update(len(data))
            
            if d_size >= t_size:
                await safe_print_async(f"{GREEN}  L Completed: {track_name}{OFF}")
                return 

        except asyncio.TimeoutError:
            if attempt < 6:
                await safe_print_async(f"{YELLOW}[*] Timeout '{track_name}'. Resuming in {delays[attempt]}s{OFF}")
                await asyncio.sleep(delays[attempt])
                continue
            if Path(fname).exists(): Path(fname).unlink()
            raise Exception("Timeout definitivo")
        except Exception as e:
            if attempt < 6 and "404" not in str(e):
                await safe_print_async(f"\n{YELLOW}[!] Server block. Retrying in {delays[attempt]}s | Erro: {e}{OFF}")
                await asyncio.sleep(delays[attempt])
                continue
            if Path(fname).exists(): Path(fname).unlink()
            raise Exception(f"Falha definitiva: {e}")

    if d_size < t_size and not abort_event.is_set():
        if Path(fname).exists(): Path(fname).unlink()
        raise Exception("Incomplete download")

async def tqdm_download_segments(track_url: dict, fname: str, track_name: str, is_parallel: bool = False) -> None:
    if abort_event.is_set(): return
    
    tmp_fname = f"{fname}.mp4"
    n_seg = track_url["n_segments"]
    tmpl = track_url["url_template"]
    key = track_url["raw_key"]

    async def get_seg_size(session, i):
        if abort_event.is_set(): return 0
        try:
            async with session.head(tmpl.replace("$SEGMENT$", str(i)), timeout=5) as r:
                return int(r.headers.get("content-length", 0))
        except: return 0

    async with aiohttp.ClientSession() as session:
        t_size = sum(await asyncio.gather(*(get_seg_size(session, i) for i in range(n_seg + 1))))

    if is_parallel:
        await safe_print_async(f"{CYAN}[+] In progress: {track_name} [{t_size / (1024*1024):.1f} MB]{OFF}")

    async def fetch_seg(session, i, bar):
        if abort_event.is_set(): return bytearray()
        
        # --- CÓDIGO DE RETRY ADICIONADO PARA RESILIÊNCIA EM SEGMENTOS ---
        for attempt in range(4):
            try:
                async with session.get(tmpl.replace("$SEGMENT$", str(i)), timeout=15) as r:
                    r.raise_for_status()
                    data = bytearray()
                    async for chunk in r.content.iter_chunked(65536):
                        if abort_event.is_set(): return bytearray()
                        data.extend(chunk)
                        if not is_parallel: bar.update(len(chunk))
                    return data
            except Exception as e:
                if attempt == 3: raise
                await asyncio.sleep(2 ** attempt)

    try:
        async with aiohttp.ClientSession() as s:
            async with aiofiles.open(tmp_fname, "wb") as f:
                with tqdm(total=t_size, unit="iB", unit_scale=True, desc="" if is_parallel else f" {GREEN}Segmented Download{OFF}", disable=is_parallel, leave=False) as bar:
                    seg_uuid = None
                    for i in range(2):
                        data = await fetch_seg(s, i, bar)
                        if abort_event.is_set(): return
                        if i == 1:
                            seg_uuid = _get_qobuz_segment_uuid(data)
                        await f.write(_decrypt_qobuz_segment(data, key, seg_uuid))

                    if n_seg >= 2:
                        sem = asyncio.Semaphore(8)
                        async def bounded_fetch(i):
                            async with sem: return await fetch_seg(s, i, bar)
                        for data in await asyncio.gather(*(bounded_fetch(i) for i in range(2, n_seg + 1))):
                            if not abort_event.is_set(): await f.write(_decrypt_qobuz_segment(data, key, seg_uuid))

        if abort_event.is_set(): return
        if not is_parallel: await safe_print_async(f" {GREEN}  > Assembling FLAC...{OFF}")
            
        # --- CÓDIGO DO FFMPEG OTIMIZADO PARA FINALIZAR COM CTRL+C ---
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", tmp_fname, 
            "-c:a", "copy", "-f", "flac", fname, 
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        
        try:
            _, stderr = await proc.communicate()
            if proc.returncode != 0: raise ConnectionError(f"FFmpeg failed: {stderr.decode()}")
        except asyncio.CancelledError:
            proc.terminate()
            raise
        
        await safe_print_async(f"{GREEN}  L Completed: {track_name}{OFF}")

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
                    cipher = AES.new(raw_key, AES.MODE_CTR, initial_value=c, nonce=b'')
                    buf[f_start:data_end] = cipher.decrypt(bytes(buf[f_start:data_end]))
                ptr += c_len
        pos += size
    return bytes(buf)

async def _download_goodies(album_meta: dict, dirn: str) -> None:
    if abort_event.is_set(): return
    try:
        for goody in album_meta.get("goodies", []):
            if abort_event.is_set(): break
            if not goody.get("url"): continue
            g_name = sanitize_filename(clean_filename(f'{album_meta.get("title")} ({goody.get("id")}).pdf'))
            await _get_extra(goody.get("url"), dirn, extra=g_name)
    except Exception as e:
        logger.error(f"{RED}Error downloading goodies: {e}{OFF}", exc_info=True)

async def _clean_embed_art(dirn: Union[str, Path], settings=None) -> None:
    e_file = Path(dirn) / EMB_COVER_NAME
    if e_file.exists():
        try:
            await asyncio.sleep(0.5) 
            e_file.unlink()
        except OSError: pass