import logging
import os
import sys
import asyncio
import aiohttp
import shutil
from pathlib import Path
from typing import Optional, List

from pathvalidate import sanitize_filename

from qobuz_dl.bundle import Bundle
from qobuz_dl import downloader, qopy
from qobuz_dl.color import CYAN, OFF, RED, YELLOW, DF, RESET, GREEN
from qobuz_dl.exceptions import NonStreamable
from qobuz_dl.db import create_db, handle_download_id
from qobuz_dl.utils import (
    get_url_info,
    make_m3u,
    smart_discography_filter,
    format_duration,
    create_and_return_dir,
    PartialFormatter,
)
from qobuz_dl.settings import QobuzDLSettings

# ---------------------------------------------------------------------------
# UI table formatting helper
# ---------------------------------------------------------------------------

def _align_text(text: str, width: int) -> str:
    """Trunca com '...' se longo, preenche com espaços se curto."""
    text = str(text)
    if len(text) > width:
        return text[:width - 3] + "..."
    return text.ljust(width)


# ---------------------------------------------------------------------------
# Lógica de tipo de lançamento -- fonte única de verdade
# ---------------------------------------------------------------------------

def classificar_tipo_lancamento(
    raw_type: Optional[str],
    title: str = "",
    version: str = "",
    t_count: int = 0,
    duration: int = 0,
) -> str:
    """
    Classifica o tipo de lançamento de forma centralizada.

    Usada tanto pelo core.py quanto pelo radar.py, eliminando a duplicação
    de heurísticas entre os dois módulos.

    Retorna uma string lowercase: "album", "ep", "single", "live", "compilation".
    """
    r_type = (raw_type or "").lower().strip()
    title_l   = (title or "").lower()
    version_l = (version or "").lower()

    # Palavras-chave explícitas no título/versão têm prioridade máxima
    if "live" in version_l or "(live" in title_l or "- live" in title_l:
        return "live"
    if any(kw in title_l or kw in version_l
           for kw in ("best of", "greatest hits", "anthology", "collection", "compilation")):
        return "compilation"
    if " ep" in title_l or version_l == "ep":
        return "ep"

    # Corrige contradições entre o tipo declarado e os metadados reais
    if r_type == "single" and (t_count >= 4 or duration >= 1_740):
        r_type = "ep"
    elif r_type == "ep" and 1 <= t_count <= 3:
        r_type = "single"
    elif r_type == "album" and 1 <= t_count <= 3:
        r_type = "single"

    # Heurística quando a API não informa o tipo
    if r_type not in ("album", "ep", "single", "live", "compilation"):
        if t_count == 1 or (t_count == 0 and 0 < duration < 600):
            r_type = "single"
        elif t_count <= 3 or (0 < duration < 1_740):
            r_type = "ep"
        else:
            r_type = "album"

    return r_type


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

WEB_URL = "https://play.qobuz.com/"
QUALITIES = {
    5:  "5 - MP3",
    6:  "6 - 16 bit, 44.1kHz",
    7:  "7 - 24 bit, <96kHz",
    27: "27 - 24 bit, >96kHz",
}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass de configuração -- substitui os 20+ parâmetros soltos no __init__
# ---------------------------------------------------------------------------

class QobuzDLConfig:
    """
    Centraliza todos os parâmetros de configuração do QobuzDL.

    Antes eram 20+ argumentos diretos no __init__, dificultando manutenção
    e adição de novos parâmetros. Agora basta adicionar um atributo aqui.
    """

    def __init__(
        self,
        directory:             str            = "QobuzDownloads",
        quality:               int            = 6,
        embed_art:             bool           = True,
        lucky_limit:           int            = 1,
        lucky_type:            str            = "album",
        interactive_limit:     int            = 20,
        ignore_singles_eps:    bool           = False,
        no_m3u_for_playlists:  bool           = False,
        quality_fallback:      bool           = True,
        cover_og_quality:      bool           = True,
        no_cover:              bool           = False,
        downloads_db:          Optional[str]  = None,
        folder_format:         str            = "{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]",
        track_format:          str            = "{track_number} - {track_title}",
        smart_discography:     bool           = False,
        fetch_lyrics:          bool           = False,
        no_lrc_files:          bool           = False,
        genius_token:          Optional[str]  = None,
        deepl_api_key:         Optional[str]  = None,
        force_english:         bool           = True,
        no_credits:            bool           = False,
        booklet_only:          bool           = False,
        blacklist:             Optional[str]  = None,
        target_lang:           str            = "PT-BR",
        delay:                 Optional[int]  = None,
        settings:              Optional[QobuzDLSettings] = None,
    ):
        self.directory            = directory
        self.quality              = quality
        self.embed_art            = embed_art
        self.lucky_limit          = lucky_limit
        self.lucky_type           = lucky_type
        self.interactive_limit    = interactive_limit
        self.ignore_singles_eps   = ignore_singles_eps
        self.no_m3u_for_playlists = no_m3u_for_playlists
        self.quality_fallback     = quality_fallback
        self.cover_og_quality     = cover_og_quality
        self.no_cover             = no_cover
        self.downloads_db         = downloads_db
        self.folder_format        = folder_format
        self.track_format         = track_format
        self.smart_discography    = smart_discography
        self.fetch_lyrics         = fetch_lyrics
        self.no_lrc_files         = no_lrc_files
        self.genius_token         = genius_token
        self.deepl_api_key        = deepl_api_key
        self.force_english        = force_english
        self.no_credits           = no_credits
        self.booklet_only         = booklet_only
        self.blacklist            = blacklist
        self.target_lang          = target_lang
        self.delay                = delay
        self.settings             = settings or QobuzDLSettings()


# ---------------------------------------------------------------------------
# Classe principal
# ---------------------------------------------------------------------------

class QobuzDL:
    def __init__(
        self,
        directory:             str            = "QobuzDownloads",
        quality:               int            = 7,
        embed_art:             bool           = True,
        lucky_limit:           int            = 1,
        lucky_type:            str            = "album",
        interactive_limit:     int            = 20,
        ignore_singles_eps:    bool           = False,
        no_m3u_for_playlists:  bool           = False,
        quality_fallback:      bool           = True,
        cover_og_quality:      bool           = True,
        no_cover:              bool           = False,
        downloads_db:          Optional[str]  = None,
        folder_format:         str            = "{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]",
        track_format:          str            = "{track_number} - {track_title}",
        smart_discography:     bool           = False,
        fetch_lyrics:          bool           = False,
        no_lrc_files:          bool           = False,
        genius_token:          Optional[str]  = None,
        deepl_api_key:         Optional[str]  = None,
        force_english:         bool           = True,
        no_credits:            bool           = False,
        settings:              Optional[QobuzDLSettings] = None,
        booklet_only:          bool           = False,
        blacklist:             Optional[str]  = None,
        target_lang:           str            = "PT-BR",
        delay:                 Optional[int]  = None,
    ):
        # ── Configuração ────────────────────────────────────────────────────
        self.deepl_api_key        = deepl_api_key
        self.delay                = delay
        self.directory            = create_and_return_dir(directory)
        self.quality              = quality
        self.embed_art            = True  # forçado como padrão
        self.lucky_limit          = lucky_limit
        self.lucky_type           = lucky_type
        self.interactive_limit    = interactive_limit
        self.ignore_singles_eps   = ignore_singles_eps
        self.no_m3u_for_playlists = no_m3u_for_playlists
        self.quality_fallback     = quality_fallback
        self.cover_og_quality     = cover_og_quality
        self.no_cover             = no_cover
        self.downloads_db         = create_db(downloads_db) if downloads_db else None
        self.folder_format        = folder_format
        self.track_format         = track_format
        self.smart_discography    = smart_discography
        self.fetch_lyrics         = fetch_lyrics
        self.no_lrc_files         = no_lrc_files
        self.genius_token         = genius_token
        self.target_lang          = target_lang
        self.force_english        = force_english
        self.no_credits           = no_credits
        self.settings             = settings or QobuzDLSettings()
        self.booklet_only         = booklet_only

        # ── Estado interno ───────────────────────────────────────────────────
        self._file_lock:              Optional[asyncio.Lock] = None
        self._is_interactive_session: bool                   = False
        self.allowed_release_types:   Optional[List[str]]   = None

        # Atributos de largura de coluna (definidos em interactive())
        self.w_art = self.w_tit = self.w_alb = self.w_typ = self.w_yea = self.w_qua = 20

        # Delay de rate-limiting
        if self.delay is not None:
            self.settings.delay = int(self.delay)

        # ── Blacklist ────────────────────────────────────────────────────────
        self.blacklist_patterns: List[str] = []
        if blacklist and Path(blacklist).is_file():
            try:
                with open(blacklist, "r", encoding="utf-8") as f:
                    self.blacklist_patterns = [
                        line.strip().lower()
                        for line in f
                        if line.strip() and not line.startswith("#")
                    ]
                logger.info(
                    f"{YELLOW}[*] Blacklist loaded: "
                    f"{len(self.blacklist_patterns)} patterns active.{OFF}"
                )
            except Exception as exc:
                logger.error(f"{RED}[!] Failed to load blacklist: {exc}{OFF}")

    # ── Inicialização do cliente ─────────────────────────────────────────────

    async def initialize_client(self, email: str, pwd: str, app_id: str, secrets: list):
        self.client = qopy.Client(
            email, pwd, app_id, secrets,
            self.settings.user_auth_token,
            force_english=self.force_english,
        )
        await self.client.start()
        logger.info(f"{YELLOW}Defina a qualidade maxima: {QUALITIES[int(self.quality)]}\n")

    def get_tokens(self):
        bundle = Bundle()
        self.app_id  = bundle.get_app_id()
        self.secrets = [s for s in bundle.get_secrets().values() if s]

    # ── Download individual ──────────────────────────────────────────────────

    async def download_from_id(
        self,
        item_id:        str,
        album:          bool           = True,
        alt_path:       Optional[str]  = None,
        is_playlist:    bool           = False,
        playlist_index: Optional[int]  = None,
    ):
        if handle_download_id(self.downloads_db, item_id, add_id=False, quality=self.quality):
            logger.info(
                f"{OFF}Este ID de lancamento: ({item_id}) ja foi baixado "
                "de acordo com o banco de dados local.\nUse a flag '--no-db' flag para contornar isto.."
            )
            return

        try:
            dloader = downloader.Download(
                client=self.client,
                item_id=item_id,
                path=alt_path or self.directory,
                quality=int(self.quality),
                embed_art=self.embed_art,
                albums_only=self.ignore_singles_eps,
                downgrade_quality=self.quality_fallback,
                cover_og_quality=self.cover_og_quality,
                no_cover=self.no_cover,
                folder_format=self.folder_format,
                track_format=self.track_format,
                fetch_lyrics=self.fetch_lyrics,
                no_lrc_files=self.no_lrc_files,
                genius_token=self.genius_token,
                deepl_api_key=self.deepl_api_key,
                target_lang=self.target_lang,
                no_credits=self.no_credits,
                settings=self.settings,
                download_db=self.downloads_db,
                is_playlist=is_playlist,
                playlist_track_number=playlist_index,
                booklet_only=self.booklet_only,
            )
            await dloader.download_id_by_type(not album)

        except (aiohttp.ClientError, asyncio.TimeoutError, NonStreamable) as exc:
            logger.error(f"{RED}Error getting release: {exc}. Skipping...")

        finally:
            # Rate-limiting configurável via config.ini (delay = N segundos)
            if self.settings.delay and self.settings.delay > 0:
                logger.debug(
                    f"[*] Sleeping {self.settings.delay}s to prevent rate limiting..."
                )
                await asyncio.sleep(self.settings.delay)

    # ── Resolução de tipo de lançamento ─────────────────────────────────────

    async def _resolve_release_type(self, item: dict) -> str:
        """
        Resolve o tipo de lançamento buscando metadados completos na API.

        Usa classificar_tipo_lancamento() como fonte única de heurística,
        eliminando a duplicação com o radar.py.

        ATENÇÃO: faz uma chamada extra à API por item -- use apenas quando
        necessário (ex.: filtro interativo de tipo na sessão interativa).
        """
        raw_type: Optional[str] = None

        try:
            full_meta = None
            if hasattr(self.client, "get_album_meta"):
                full_meta = await self.client.get_album_meta(item["id"])
            elif hasattr(self.client, "get_album"):
                full_meta = await self.client.get_album(item["id"])

            if full_meta:
                raw_type = full_meta.get("release_type") or full_meta.get("product_type")

        except Exception as exc:
            logger.debug(f"Erro ao buscar metadados completos para {item.get('id')}: {exc}")

        return classificar_tipo_lancamento(
            raw_type=raw_type,
            title=str(item.get("title", "")),
            version=str(item.get("version", "")),
            t_count=item.get("tracks_count", 0),
            duration=item.get("duration", 0),
        )

    # ── Handler de URL ───────────────────────────────────────────────────────

    async def handle_url(self, url: str):
        possibles = {
            "playlist": {"func": self.client.get_plist_meta,  "iterable_key": "tracks"},
            "artist":   {"func": self.client.get_artist_meta, "iterable_key": "albums"},
            "label":    {"func": self.client.get_label_meta,  "iterable_key": "albums"},
            "album":    {"album": True,  "func": None, "iterable_key": None},
            "track":    {"album": False, "func": None, "iterable_key": None},
        }

        try:
            url_type, item_id = get_url_info(url)
            type_dict = possibles[url_type]
        except (KeyError, IndexError):
            logger.info(f'{RED}Invalid url: "{url}". Use urls from https://play.qobuz.com!{OFF}')
            return

        if type_dict["func"]:
            content      = [item async for item in type_dict["func"](item_id)]
            content_name = content[0]["name"]
            logger.info(f"{YELLOW}Downloading all the music from {content_name} ({url_type})!{OFF}")

            new_path = create_and_return_dir(
                str(Path(self.directory) / sanitize_filename(content_name))
            )

            if self.smart_discography and url_type == "artist":
                items = smart_discography_filter(content, save_space=True, skip_extras=True)
            else:
                items = [
                    item
                    for chunk in content
                    for item in chunk.get(type_dict["iterable_key"], {}).get("items", [])
                ]

            # Filtro interativo de tipo (só em sessões interativas)
            if self._is_interactive_session and url_type == "artist":
                import pick
                options = ["Album", "EP", "Single", "Live", "Compilation"]
                title_text = (
                    f"Found {len(items)} total releases for {content_name}.\n"
                    "Filter by release type:\n"
                    "(Use arrows to move, Space to select, Enter to confirm)"
                )
                selected_raw = pick.pick(options, title_text, multiselect=True, min_selection_count=1)
                self.allowed_release_types = (
                    [opt[0].lower() for opt in selected_raw] if selected_raw else []
                )
                if not self.allowed_release_types:
                    items = []
            else:
                self.allowed_release_types = None

            if self.allowed_release_types is not None:
                logger.info(
                    f"{YELLOW}[*] Evaluating {len(items)} releases "
                    f"(unwanted types skipped silently)...{OFF}"
                )
            else:
                logger.info(f"{YELLOW}[{len(items)} downloads na fila]{OFF}")

            is_playlist = (url_type == "playlist")
            if is_playlist:
                original_folder_format       = self.folder_format
                original_multi_disc_setting  = self.settings.multiple_disc_one_dir
                self.folder_format           = "."
                self.settings.multiple_disc_one_dir = True

            for idx, item in enumerate(items, start=1):
                # Filtro de tipo (só quando allowed_release_types está definido)
                if self.allowed_release_types and url_type == "artist":
                    r_type = await self._resolve_release_type(item)
                    if r_type not in self.allowed_release_types:
                        continue

                # Filtro de blacklist
                if self.blacklist_patterns:
                    display_name = (
                        f"{item.get('title') or item.get('name')} "
                        f"({item.get('version', '')})"
                    ).strip(" ()")
                    if any(p in display_name.lower() for p in self.blacklist_patterns):
                        logger.info(f"{YELLOW}[!] Skipped (Blacklisted): {display_name}{OFF}")
                        continue

                await self.download_from_id(
                    item["id"],
                    type_dict["iterable_key"] == "albums",
                    new_path,
                    is_playlist=is_playlist,
                    playlist_index=idx,
                )

            if is_playlist:
                self.folder_format                  = original_folder_format
                self.settings.multiple_disc_one_dir = original_multi_disc_setting
                
                # --- GATILHO DO TELEGRAM PARA PLAYLISTS INTEIRAS ---
                try:
                    from qobuz_dl.telegram_uploader import upload_album_completo
                    logger.info(f"\n{CYAN}[*] Playlist Concluída! Subindo pacote completo para o Telegram...{OFF}")
                    await upload_album_completo(new_path, content_name, "Vários Artistas", "Vários Artistas (Playlist)", "Playlist")
                except Exception as e:
                    logger.error(f"{RED}[!] Erro ao enviar Playlist para o Telegram: {e}{OFF}")
                # ---------------------------------------------------

            if url_type == "playlist" and not self.no_m3u_for_playlists:
                make_m3u(new_path)

        else:
            await self.download_from_id(item_id, type_dict["album"])

    # ── Marcação de URLs concluídas ──────────────────────────────────────────

    async def mark_url_done_in_file(self, txt_file: str, url_to_mark: str):
        if not txt_file or not Path(txt_file).is_file():
            return

        if self._file_lock is None:
            self._file_lock = asyncio.Lock()

        try:
            async with self._file_lock:
                with open(txt_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(txt_file, "w", encoding="utf-8") as f:
                    for line in lines:
                        stripped = line.strip()
                        f.write(
                            f"{stripped} [DONE]\n"
                            if stripped == url_to_mark.strip()
                            else line
                        )
        except Exception as exc:
            logger.error(f"{RED}Failed to update text file status: {exc}{OFF}")

    # ── Processamento de URL individual ─────────────────────────────────────

    async def _process_single_url(self, url: str, txt_file: Optional[str] = None):
        original_url = url
        url = url.replace("open.qobuz.com", "play.qobuz.com")

        try:
            if "last.fm" in url:
                await self.download_lastfm_pl(url)
            elif Path(url).is_file():
                await self.download_from_txt_file(url)
            else:
                await self.handle_url(url)

            if txt_file:
                await self.mark_url_done_in_file(txt_file, original_url)

        except Exception as exc:
            logger.error(f"{RED}[!] Error downloading {original_url}: {exc}{OFF}")

    # ── Download em lote ────────────────────────────────────────────────────

    async def download_list_of_urls(self, urls: List[str], txt_file: Optional[str] = None):
        if not urls or not isinstance(urls, list):
            logger.info(f"{OFF}Nothing to download")
            return

        # [!] CORREÇÃO AQUI: Forçando a conversão de max_workers para inteiro para evitar o TypeError
        try:
            max_batch_workers = int(getattr(self.settings, "max_workers", 3))
        except (ValueError, TypeError):
            max_batch_workers = 3

        if len(urls) > 1 and max_batch_workers > 1 and txt_file is not None:
            logger.info(
                f"{YELLOW}[*] Batch download detected. "
                f"Processing up to {max_batch_workers} items in parallel.{OFF}"
            )
            original_workers        = max_batch_workers
            self.settings.max_workers = 1
            sem                     = asyncio.Semaphore(max_batch_workers)

            async def sem_process(url: str):
                async with sem:
                    await self._process_single_url(url, txt_file)

            try:
                await asyncio.gather(*[sem_process(u) for u in urls])
            finally:
                self.settings.max_workers = original_workers
        else:
            for url in urls:
                await self._process_single_url(url, txt_file)

    # ── Download de arquivo de texto ─────────────────────────────────────────

    async def download_from_txt_file(self, txt_file: str):
        try:
            valid_urls: List[str] = []
            with open(txt_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "[DONE]" in line:
                        continue
                    if "last.fm" in line:
                        valid_urls.append(line)
                        continue
                    try:
                        get_url_info(line)
                        valid_urls.append(line)
                    except (KeyError, IndexError, AttributeError):
                        logger.debug(f"Skipping invalid URL line: {line}")

        except Exception as exc:
            logger.error(f"{RED}Invalid text file: {exc}{OFF}")
            return

        if not valid_urls:
            logger.info(f"{OFF}No new valid URLs found in file: {txt_file}")
            return

        logger.info(f"{YELLOW}qobuz-dl will download {len(valid_urls)} urls from file: {txt_file}{OFF}")
        await self.download_list_of_urls(valid_urls, txt_file=txt_file)

    # ── Modo sorte ───────────────────────────────────────────────────────────

    async def lucky_mode(self, query: str, download: bool = True):
        if len(query) < 3:
            logger.info(f"{RED}Your search query is too short or invalid")
            return
        logger.info(
            f'{YELLOW}Searching {self.lucky_type}s for "{query}".\n'
            f"qobuz-dl will attempt to download the first {self.lucky_limit} results."
        )
        results = await self.search_by_type(query, self.lucky_type, self.lucky_limit, True)
        if download and results:
            await self.download_list_of_urls(results)
        return results

    # ── Busca por tipo ───────────────────────────────────────────────────────

    async def search_by_type(
        self,
        query:       Optional[str],
        item_type:   str,
        limit:       int  = 10,
        lucky:       bool = False,
        fav_subtype: Optional[str] = None,
    ):
        if item_type != "favorites" and (not query or len(query) < 3):
            logger.info(f"{RED}Your search query is too short or invalid")
            return []

        possibles = {
            "album":     {"func": self.client.search_albums,    "key": "albums",    "requires_extra": True},
            "artist":    {"func": self.client.search_artists,   "key": "artists",   "requires_extra": False},
            "track":     {"func": self.client.search_tracks,    "key": "tracks",    "requires_extra": True},
            "playlist":  {"func": self.client.search_playlists, "key": "playlists", "requires_extra": False},
            "favorites": {"func": self.client.get_favorites,    "key": "favorites", "requires_extra": True},
        }

        try:
            mode_dict = possibles[item_type]

            if item_type == "favorites":
                results  = await mode_dict["func"](fav_type=fav_subtype, limit=limit)
                iterable = (
                    results.get("favorites", {}).get(fav_subtype, {}).get("items", [])
                    or results.get(fav_subtype, {}).get("items", [])
                )
                mode_dict["requires_extra"] = fav_subtype not in ("artists", "playlists")
            else:
                results = await mode_dict["func"](query, limit)
                if not results or mode_dict["key"] not in results or "items" not in results[mode_dict["key"]]:
                    return []
                iterable = results[mode_dict["key"]]["items"]

            item_list = []
            for i in iterable:
                if mode_dict["requires_extra"]:
                    artist = (
                        i.get("artist", {}).get("name")
                        or i.get("performer", {}).get("name")
                        or "Unknown"
                    )
                    title = i.get("title") or i.get("name") or "Unknown"
                    if i.get("version"):          title = f"{title} ({i['version']})"
                    if i.get("parental_warning"): title = f"{title} [E]"

                    year      = str(i.get("release_date_original") or i.get("release_date") or "    ")[:4]
                    t_count   = i.get("tracks_count", 0)
                    duration  = i.get("duration", 0)
                    raw_type  = i.get("release_type") or i.get("product_type")

                    # Usa a função centralizada de classificação
                    r_type_str = classificar_tipo_lancamento(
                        raw_type=raw_type,
                        title=str(i.get("title", "")),
                        version=str(i.get("version", "")),
                        t_count=t_count,
                        duration=duration,
                    )
                    rel_type = "EP" if r_type_str == "ep" else r_type_str.title()

                    if i.get("hires_streamable"):
                        bit_depth     = i.get("maximum_bit_depth", 24)
                        sampling_rate = i.get("maximum_sampling_rate", 96.0)
                        quality       = f"[HI-RES] {bit_depth}b/{sampling_rate}kHz"
                    else:
                        quality = "[ CD ] 16b/44.1kHz"

                    album_name = (
                        ""        if item_type == "album"
                        else i.get("album", {}).get("title", "Unknown") if item_type == "track"
                        else "-"
                    )

                    text = (
                        f"{_align_text(artist, self.w_art)}   "
                        f"{_align_text(title, self.w_tit)}   "
                        f"{_align_text(album_name, self.w_alb)}   "
                        f"{_align_text(rel_type, self.w_typ)}   "
                        f"{_align_text(year, self.w_yea)}   "
                        f"{_align_text(quality, self.w_qua)}"
                    )
                else:
                    name  = i.get("name", "Unknown")
                    count = i.get("albums_count", i.get("tracks_count", 0))
                    desc  = "albums" if "albums_count" in i else "tracks"
                    text  = f"{_align_text(name, 50)}   {count} {desc}"

                url_category = (
                    fav_subtype[:-1]
                    if item_type == "favorites" and fav_subtype
                    else item_type
                )
                url = f"{WEB_URL}{url_category}/{i.get('id', '')}"
                item_list.append({"text": text, "url": url} if not lucky else url)

            return item_list

        except (KeyError, IndexError):
            logger.info(f"{RED}Invalid type: {item_type}")
            return []

    # ── Modo interativo ──────────────────────────────────────────────────────

    async def interactive(self, download: bool = True):
        self._is_interactive_session = True
        terminal_width = shutil.get_terminal_size((120, 20)).columns

        if terminal_width < 100:
            self.w_art, self.w_tit, self.w_alb, self.w_typ, self.w_yea, self.w_qua = 15, 25, 10, 5, 5, 20
        else:
            self.w_art, self.w_tit, self.w_alb, self.w_typ, self.w_yea, self.w_qua = 20, 35, 30, 8, 5, 25

        try:
            import pick
            if hasattr(pick, "SYMBOL_CIRCLE_EMPTY"):
                pick.SYMBOL_CIRCLE_EMPTY, pick.SYMBOL_CIRCLE_FILLED = "[ ]", "[X]"
        except (ImportError, ModuleNotFoundError):
            if os.name == "nt":
                sys.exit("Please install curses with 'pip3 install windows-curses' to continue")
            raise

        qualities = [
            {"q_string": "320",            "q": 5},
            {"q_string": "Lossless",        "q": 6},
            {"q_string": "Hi-res =< 96kHz", "q": 7},
            {"q_string": "Hi-Res > 96 kHz", "q": 27},
        ]

        try:
            item_types  = ["Albums", "Tracks", "Artists", "Playlists", "Favorites"]
            scelta_raw  = pick.pick(item_types, "Vou procurar por:\n[press Intro]")[0]
            selected_type = "favorites" if scelta_raw == "Favorites" else scelta_raw[:-1].lower()

            logger.info(f"{GREEN}Ok, Vamos pesquisar por {selected_type}{RESET}")
            final_url_list: List[str] = []

            while True:
                if selected_type == "favorites":
                    fav_types    = ["Albums", "Tracks", "Artists", "Playlists"]
                    selected_fav = pick.pick(
                        fav_types,
                        "Sobre quais favoritos voce quer navegar?\n[press Intro]",
                    )[0].lower()
                    logger.info(f"{YELLOW}A buscar o seu favorito: {selected_fav}...{RESET}")
                    options     = await self.search_by_type(None, selected_type, limit=self.interactive_limit, fav_subtype=selected_fav)
                    query_title = f"My Favorite {selected_fav.title()}"
                else:
                    query = input(f"{CYAN}INSIRA PARA PESQUISAR: [Ctrl + c para sair]\n-{DF} ").strip()
                    if not query:
                        continue
                    logger.info(f"\n{GREEN}p e s q u i s a n d o ...{RESET}")
                    options     = await self.search_by_type(query, selected_type, self.interactive_limit)
                    query_title = query.title()

                if not options:
                    logger.info(f"{OFF}Nothing found{RESET}")
                    if selected_type == "favorites":
                        break
                    continue

                if selected_type in ("album", "track") or (
                    selected_type == "favorites" and selected_fav in ("albums", "tracks")
                ):
                    table_header = (
                        f"       {'ARTIST'.ljust(self.w_art)}   {'TITLE'.ljust(self.w_tit)}   "
                        f"{'ALBUM'.ljust(self.w_alb)}   {'TYPE'.ljust(self.w_typ)}   "
                        f"{'YEAR'.ljust(self.w_yea)}   {'QUALITY'.ljust(self.w_qua)}\n"
                        f"       {'-' * (self.w_art + self.w_tit + self.w_alb + self.w_typ + self.w_yea + self.w_qua + 15)}"
                    )
                else:
                    table_header = f"       {'NAME'.ljust(50)}   RELEASES\n       {'-' * 63}"

                title = (
                    f'*** RESULTS FOR "{query_title}" ***\n\n'
                    "[Use setas para mover, <Space> para selecionar, <Enter> para confirmar]\n"
                    "Pressione Ctrl + C para sair. Don't select anything to try another search.\n\n"
                    f"{table_header}"
                )

                options_texts  = [opt.get("text") for opt in options]
                selected_items = pick.pick(options_texts, title, multiselect=True, min_selection_count=0)

                if selected_items:
                    selected_strings = [item[0] for item in selected_items]
                    if "[ Sair do programa ]" in selected_strings:
                        logger.info(f"\n{YELLOW}Saindo da busca...{RESET}")
                        return final_url_list
                    if "[ Fazer nova busca ]" in selected_strings:
                        continue

                    for item, original_index in selected_items:
                        if original_index >= 0:
                            final_url_list.append(options[original_index]["url"])

                    if pick.pick(
                        ["Yes", "No"],
                        "Os itens foram adicionados à fila. Continuar pesquisando?",
                    )[0] == "No":
                        break
                else:
                    logger.info(f"{YELLOW}Ok, tentando novamente...{RESET}")
                    if selected_type == "favorites":
                        break
                    continue

            if final_url_list:
                desc = (
                    "Select [intro] the quality "
                    "(the quality will be automatically downgraded if not found)"
                )
                selected_quality = pick.pick(
                    [q.get("q_string") for q in qualities], desc, default_index=1
                )
                self.quality = qualities[selected_quality[1]]["q"]

                if download:
                    await self.download_list_of_urls(final_url_list)

                return final_url_list

        except KeyboardInterrupt:
            logger.info(f"\n{YELLOW}Ctrl+C Used - ABORTED")
            return

    # ── Last.fm ──────────────────────────────────────────────────────────────

    async def download_lastfm_pl(self, playlist_url: str):
        from qobuz_dl.lastfm_parser import fetch_lastfm_playlist

        logger.info(f"{CYAN}[*] Last.fm URL detected! Initiating Last.fm integration...{OFF}")
        tracks_list = await fetch_lastfm_playlist(playlist_url)

        if not tracks_list:
            logger.info(f"{YELLOW}[!] Last.fm processing aborted (no tracks).{OFF}")
            return

        pl_id        = playlist_url.rstrip("/").split("/")[-1]
        pl_title     = sanitize_filename(f"LastFM_Playlist_{pl_id}")
        pl_directory = str(Path(self.directory) / pl_title)

        logger.info(f"{YELLOW}Downloading playlist: {pl_title} ({len(tracks_list)} tracks){RESET}")
        track_ids = await self.client.get_track_ids_from_list(tracks_list)

        if not track_ids:
            logger.info(f"{RED}[!] No matching tracks found on Qobuz. Aborting.{OFF}")
            return

        original_folder_format      = self.folder_format
        original_multi_disc_setting = self.settings.multiple_disc_one_dir
        self.folder_format          = "."
        self.settings.multiple_disc_one_dir = True

        for idx, t_id in enumerate(track_ids, start=1):
            try:
                await self.download_from_id(
                    t_id, False, pl_directory,
                    is_playlist=True, playlist_index=idx,
                )
            except Exception as exc:
                logger.error(f"{RED}[!] Failed to queue track ID {t_id}: {exc}{OFF}")

        self.folder_format                  = original_folder_format
        self.settings.multiple_disc_one_dir = original_multi_disc_setting

        if not self.no_m3u_for_playlists:
            make_m3u(pl_directory)