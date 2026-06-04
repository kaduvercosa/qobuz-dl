import logging
import os
import sys
import asyncio
import aiohttp
import shutil
from pathlib import Path
from typing import Optional, List, Tuple

from pathvalidate import sanitize_filename

from qobuz_dl.bundle import Bundle
from qobuz_dl import downloader, qopy
from qobuz_dl.exceptions import NonStreamable
from qobuz_dl.db import create_db, handle_download_id
from qobuz_dl.utils import (
    get_url_info,
    make_m3u,
    smart_discography_filter,
    create_and_return_dir,
)
from qobuz_dl.settings import QobuzDLSettings

# ---------------------------------------------------------------------------
# 🎨 SISTEMA DE CORES E DESIGN LIMPO (SEM SETAS)
# ---------------------------------------------------------------------------
class Tema:
    CYAN    = "\033[36m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    BLUE    = "\033[34m"   
    PURPLE  = "\033[35m"   
    BOLD    = "\033[1m"
    OFF     = "\033[0m"

    TITULO    = BOLD           
    SUCESSO   = GREEN          
    AVISO     = YELLOW         
    ERRO      = RED            

    SYS    = f"{BLUE}[SISTEMA]{OFF}  ❯ "
    URL    = f"{BLUE}[URL]{OFF}      ❯ "
    BUSCA  = f"{BLUE}[BUSCA]{OFF}    ❯ "
    FILA   = f"{BLUE}[FILA]{OFF}     ❯ "
    ALERTA = f"{BLUE}[AVISO]{OFF}    ❯ "

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper de Alinhamento
# ---------------------------------------------------------------------------
def _align_text(text: str, width: int) -> str:
    text = str(text)
    if len(text) > width:
        return text[:width - 3] + "..."
    return text.ljust(width)

# ---------------------------------------------------------------------------
# Lógica de tipo de lançamento
# ---------------------------------------------------------------------------
def classificar_tipo_lancamento(raw_type: Optional[str], title: str = "", version: str = "", t_count: int = 0, duration: int = 0) -> str:
    r_type = (raw_type or "").lower().strip()
    title_l   = (title or "").lower()
    version_l = (version or "").lower()

    if "live" in version_l or "(live" in title_l or "- live" in title_l: return "live"
    if any(kw in title_l or kw in version_l for kw in ("best of", "greatest hits", "anthology", "collection", "compilation")): return "compilation"
    if " ep" in title_l or version_l == "ep": return "ep"

    if r_type == "single" and (t_count >= 4 or duration >= 1_740): r_type = "ep"
    elif r_type == "ep" and 1 <= t_count <= 3: r_type = "single"
    elif r_type == "album" and 1 <= t_count <= 3: r_type = "single"

    if r_type not in ("album", "ep", "single", "live", "compilation"):
        if t_count == 1 or (t_count == 0 and 0 < duration < 600): r_type = "single"
        elif t_count <= 3 or (0 < duration < 1_740): r_type = "ep"
        else: r_type = "album"

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

# O pick renderiza "* [ ] " ou "  [ ] " antes de cada linha = 6 chars.
# O cabeçalho precisa de 7 espaços para alinhar com o "│" das linhas de dados,
# porque o pick usa um espaço extra antes do "│" do primeiro campo.
_PICK_HEADER_OFFSET = "       "  # 7 espaços

# ---------------------------------------------------------------------------
# Dataclass de configuração
# ---------------------------------------------------------------------------
class QobuzDLConfig:
    def __init__(self, directory: str = "QobuzDownloads", quality: int = 6, embed_art: bool = True, lucky_limit: int = 1, lucky_type: str = "album", interactive_limit: int = 20, ignore_singles_eps: bool = False, no_m3u_for_playlists: bool = False, quality_fallback: bool = True, cover_og_quality: bool = True, no_cover: bool = False, downloads_db: Optional[str] = None, folder_format: str = "{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]", track_format: str = "{track_number} - {track_title}", smart_discography: bool = False, fetch_lyrics: bool = False, no_lrc_files: bool = False, genius_token: Optional[str] = None, deepl_api_key: Optional[str] = None, force_english: bool = True, no_credits: bool = False, booklet_only: bool = False, blacklist: Optional[str] = None, target_lang: str = "PT-BR", delay: Optional[int] = None, settings: Optional[QobuzDLSettings] = None):
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
    def __init__(self, directory: str = "QobuzDownloads", quality: int = 7, embed_art: bool = True, lucky_limit: int = 1, lucky_type: str = "album", interactive_limit: int = 20, ignore_singles_eps: bool = False, no_m3u_for_playlists: bool = False, quality_fallback: bool = True, cover_og_quality: bool = True, no_cover: bool = False, downloads_db: Optional[str] = None, folder_format: str = "{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]", track_format: str = "{track_number} - {track_title}", smart_discography: bool = False, fetch_lyrics: bool = False, no_lrc_files: bool = False, genius_token: Optional[str] = None, deepl_api_key: Optional[str] = None, force_english: bool = True, no_credits: bool = False, settings: Optional[QobuzDLSettings] = None, booklet_only: bool = False, blacklist: Optional[str] = None, target_lang: str = "PT-BR", delay: Optional[int] = None):
        self.deepl_api_key        = deepl_api_key
        self.delay                = delay
        self.directory            = create_and_return_dir(directory)
        self.quality              = quality
        self.embed_art            = True  
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

        self._file_lock:              Optional[asyncio.Lock] = None
        self._is_interactive_session: bool                   = False
        self.allowed_release_types:   Optional[List[str]]   = None

        if self.delay is not None:
            self.settings.delay = int(self.delay)

        self.blacklist_patterns: List[str] = []
        if blacklist and Path(blacklist).is_file():
            try:
                with open(blacklist, "r", encoding="utf-8") as f:
                    self.blacklist_patterns = [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]
                print(f"{Tema.SYS}{Tema.SUCESSO}Blacklist carregada: {len(self.blacklist_patterns)} regras ativas.{Tema.OFF}")
            except Exception as exc:
                print(f"{Tema.SYS}{Tema.ERRO}Falha na Blacklist: {exc}{Tema.OFF}")

    async def initialize_client(self, email: str, pwd: str, app_id: str, secrets: list):
        self.client = qopy.Client(email, pwd, app_id, secrets, self.settings.user_auth_token, force_english=self.force_english)
        await self.client.start()
        print(f"{Tema.SYS}{Tema.AVISO}Sessão Ativa | Qualidade: {QUALITIES[int(self.quality)]}{Tema.OFF}\n")

    def get_tokens(self):
        bundle = Bundle()
        self.app_id  = bundle.get_app_id()
        self.secrets = [s for s in bundle.get_secrets().values() if s]

    async def download_from_id(self, item_id: str, album: bool = True, alt_path: Optional[str] = None, is_playlist: bool = False, playlist_index: Optional[int] = None, is_single_batch: bool = False, single_batch_index: int = 1, single_batch_total: int = 1):
        if handle_download_id(self.downloads_db, item_id, add_id=False, quality=self.quality):
            print(f"{Tema.ALERTA}{Tema.AVISO}ID ({item_id}) ignorado (já existe no banco local).{Tema.OFF}")
            return

        try:
            dloader = downloader.Download(
                client=self.client, item_id=item_id, path=alt_path or self.directory, quality=int(self.quality),
                embed_art=self.embed_art, albums_only=self.ignore_singles_eps, downgrade_quality=self.quality_fallback,
                cover_og_quality=self.cover_og_quality, no_cover=self.no_cover, folder_format=self.folder_format,
                track_format=self.track_format, fetch_lyrics=self.fetch_lyrics, no_lrc_files=self.no_lrc_files,
                genius_token=self.genius_token, deepl_api_key=self.deepl_api_key, target_lang=self.target_lang,
                no_credits=self.no_credits, settings=self.settings, download_db=self.downloads_db,
                is_playlist=is_playlist, playlist_track_number=playlist_index, booklet_only=self.booklet_only,
                is_single_batch=is_single_batch, single_batch_index=single_batch_index, single_batch_total=single_batch_total
            )
            await dloader.download_id_by_type(not album)
        except (aiohttp.ClientError, asyncio.TimeoutError, NonStreamable) as exc:
            print(f"{Tema.ALERTA}{Tema.ERRO}Erro ao obter lançamento: {exc}{Tema.OFF}")
        finally:
            if self.settings.delay and self.settings.delay > 0:
                await asyncio.sleep(self.settings.delay)

    async def _resolve_release_type(self, item: dict) -> str:
        raw_type: Optional[str] = None
        try:
            full_meta = None
            if hasattr(self.client, "get_album_meta"):
                full_meta = await self.client.get_album_meta(item["id"])
            elif hasattr(self.client, "get_album"):
                full_meta = await self.client.get_album(item["id"])
            if full_meta: raw_type = full_meta.get("release_type") or full_meta.get("product_type")
        except Exception:
            pass

        return classificar_tipo_lancamento(raw_type=raw_type, title=str(item.get("title", "")), version=str(item.get("version", "")), t_count=item.get("tracks_count", 0), duration=item.get("duration", 0))

    async def handle_url(self, url: str, is_single_batch: bool = False, single_batch_index: int = 1, single_batch_total: int = 1):
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
            print(f"{Tema.URL}{Tema.ERRO}URL Inválida: {url}{Tema.OFF}")
            return

        if type_dict["func"]:
            content = [item async for item in type_dict["func"](item_id)]
            content_name = content[0]["name"]
            
            print(f"\n{Tema.URL}{Tema.TITULO}{content_name}{Tema.OFF} ({url_type})")

            new_path = create_and_return_dir(str(Path(self.directory) / sanitize_filename(content_name)))

            if self.smart_discography and url_type == "artist":
                items = smart_discography_filter(content, save_space=True, skip_extras=True)
            else:
                items = [item for chunk in content for item in chunk.get(type_dict["iterable_key"], {}).get("items", [])]

            if self._is_interactive_session and url_type == "artist":
                import pick
                options = ["Album", "EP", "Single", "Live", "Compilation"]
                title_text = f"Encontrados {len(items)} lançamentos para {content_name}.\nFiltre por tipo de lançamento (Espaço para selecionar):"
                selected_raw = pick.pick(options, title_text, multiselect=True, min_selection_count=1)
                self.allowed_release_types = [opt[0].lower() for opt in selected_raw] if selected_raw else []
                if not self.allowed_release_types: items = []
            else:
                self.allowed_release_types = None

            print(f"{Tema.FILA}{Tema.SUCESSO}{len(items)} itens agendados para processamento.{Tema.OFF}\n")

            is_playlist = (url_type == "playlist")
            if is_playlist:
                original_folder_format = self.folder_format
                original_multi_disc_setting = self.settings.multiple_disc_one_dir
                self.folder_format = "."
                self.settings.multiple_disc_one_dir = True

            self.settings.playlist_total_count = len(items)

            for idx, item in enumerate(items, start=1):
                if self.allowed_release_types and url_type == "artist":
                    r_type = await self._resolve_release_type(item)
                    if r_type not in self.allowed_release_types: continue

                if self.blacklist_patterns:
                    display_name = f"{item.get('title') or item.get('name')} ({item.get('version', '')})".strip(" ()")
                    if any(p in display_name.lower() for p in self.blacklist_patterns):
                        continue

                await self.download_from_id(item["id"], type_dict["iterable_key"] == "albums", new_path, is_playlist=is_playlist, playlist_index=idx)

            if is_playlist:
                self.folder_format = original_folder_format
                self.settings.multiple_disc_one_dir = original_multi_disc_setting
                try:
                    from qobuz_dl.telegram_uploader import upload_album_completo
                    await upload_album_completo(new_path, content_name, "Vários Artistas", "Various Artists", "Vários Artistas (Playlist)", "Playlist")
                except Exception as e:
                    print(f"{Tema.ALERTA}{Tema.ERRO}Falha no Telegram (Playlist): {e}{Tema.OFF}")

            if url_type == "playlist" and not self.no_m3u_for_playlists:
                make_m3u(new_path)
        else:
            await self.download_from_id(item_id, type_dict["album"], is_single_batch=is_single_batch, single_batch_index=single_batch_index, single_batch_total=single_batch_total)

    async def mark_url_done_in_file(self, txt_file: str, url_to_mark: str):
        if not txt_file or not Path(txt_file).is_file(): return
        if self._file_lock is None: self._file_lock = asyncio.Lock()
        try:
            async with self._file_lock:
                with open(txt_file, "r", encoding="utf-8") as f: lines = f.readlines()
                with open(txt_file, "w", encoding="utf-8") as f:
                    for line in lines:
                        stripped = line.strip()
                        f.write(f"{stripped} [DONE]\n" if stripped == url_to_mark.strip() else line)
        except Exception: pass

    async def _process_single_url(self, url: str, txt_file: Optional[str] = None, is_single_batch: bool = False, single_batch_index: int = 1, single_batch_total: int = 1):
        original_url = url
        url = url.replace("open.qobuz.com", "play.qobuz.com")
        try:
            if "last.fm" in url: await self.download_lastfm_pl(url)
            elif Path(url).is_file(): await self.download_from_txt_file(url)
            else: await self.handle_url(url, is_single_batch, single_batch_index, single_batch_total)
            if txt_file: await self.mark_url_done_in_file(txt_file, original_url)
        except Exception as exc:
            print(f"{Tema.ALERTA}{Tema.ERRO}Erro ao baixar {original_url}: {exc}{Tema.OFF}")

    async def download_list_of_urls(self, urls: List[str], txt_file: Optional[str] = None):
        if not urls or not isinstance(urls, list): return
        
        try: max_batch_workers = int(getattr(self.settings, "max_workers", 3))
        except (ValueError, TypeError): max_batch_workers = 3
        
        is_batch = len(urls) > 1
        total_urls = len(urls)

        if is_batch and max_batch_workers > 1 and txt_file is not None:
            print(f"{Tema.SYS}{Tema.AVISO}Modo Batch Ativo: Processando {max_batch_workers} links simultâneos.{Tema.OFF}")
            original_workers = max_batch_workers
            self.settings.max_workers = 1
            sem = asyncio.Semaphore(max_batch_workers)

            async def sem_process(url: str):
                async with sem: await self._process_single_url(url, txt_file, is_batch, idx, total_urls)

            try: await asyncio.gather(*[sem_process(idx, u) for idx, u in enumerate(urls, start=1)])
            finally: self.settings.max_workers = original_workers
        else:
            for idx, url in enumerate(urls, start=1):
                await self._process_single_url(url, txt_file, is_batch, idx, total_urls)

    async def download_from_txt_file(self, txt_file: str):
        try:
            valid_urls: List[str] = []
            with open(txt_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "[DONE]" in line: continue
                    if "last.fm" in line:
                        valid_urls.append(line)
                        continue
                    try:
                        get_url_info(line)
                        valid_urls.append(line)
                    except (KeyError, IndexError, AttributeError): pass
        except Exception as exc:
            print(f"{Tema.SYS}{Tema.ERRO}Erro ao ler arquivo .txt: {exc}{Tema.OFF}")
            return

        if not valid_urls: return
        print(f"\n{Tema.SYS}{Tema.TITULO}Leitura de TXT concluída{Tema.OFF}")
        print(f"{Tema.FILA}{Tema.SUCESSO}{len(valid_urls)} links encontrados.{Tema.OFF}\n")
        await self.download_list_of_urls(valid_urls, txt_file=txt_file)

    def _setup_terminal_widths(self):
        """Calcula os limites máximos permitidos com base no ecrã atual do iPad."""
        term_cols = shutil.get_terminal_size((120, 20)).columns
        available = max(30, term_cols - 65) # Margem para as divisórias e espaços do Pick
        self.max_w_art = int(available * 0.25)
        self.max_w_tit = int(available * 0.45)
        self.max_w_alb = int(available * 0.30)

    # ---------------------------------------------------------------------------
    # Tabela Elástica Inteligente
    # ---------------------------------------------------------------------------
    async def search_by_type(self, query: Optional[str], item_type: str, limit: int = 10, lucky: bool = False, fav_subtype: Optional[str] = None):
        if item_type != "favorites" and (not query or len(query) < 3): return []
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
                results = await mode_dict["func"](fav_type=fav_subtype, limit=limit)
                iterable = results.get("favorites", {}).get(fav_subtype, {}).get("items", []) or results.get(fav_subtype, {}).get("items", [])
                mode_dict["requires_extra"] = fav_subtype not in ("artists", "playlists")
            else:
                results = await mode_dict["func"](query, limit)
                if not results or mode_dict["key"] not in results or "items" not in results[mode_dict["key"]]: return []
                iterable = results[mode_dict["key"]]["items"]

            item_list = []
            if mode_dict["requires_extra"]:
                self._setup_terminal_widths()
                raw_data = []
                
                # Passo 1: Descobrir o comprimento máximo dos textos
                max_art = len("ARTISTA")
                max_tit = len("TÍTULO")
                col3_head = "GRAVADORA" if (item_type == "album" or fav_subtype == "albums") else "ÁLBUM"
                max_alb = len(col3_head)

                for i in iterable:
                    artist = i.get("artist", {}).get("name") or i.get("performer", {}).get("name") or "Unknown"
                    title = i.get("title") or i.get("name") or "Unknown"
                    if i.get("version"): title = f"{title} ({i['version']})"
                    if i.get("parental_warning"): title = f"{title} [E]"
                    year = str(i.get("release_date_original") or i.get("release_date") or "    ")[:4]
                    
                    r_type_str = classificar_tipo_lancamento(raw_type=i.get("release_type") or i.get("product_type"), title=str(i.get("title", "")), version=str(i.get("version", "")), t_count=i.get("tracks_count", 0), duration=i.get("duration", 0))
                    rel_type = "EP" if r_type_str == "ep" else r_type_str.title()
                    quality = f"[HI-RES] {i.get('maximum_bit_depth', 24)}b/{i.get('maximum_sampling_rate', 96.0)}kHz" if i.get("hires_streamable") else "[ CD ] 16b/44.1kHz"
                    
                    # Gravadora para álbuns, álbum para tracks
                    if item_type == "album" or fav_subtype == "albums":
                        col3_val = i.get("label", {}).get("name", "Independente")
                    elif item_type == "track" or fav_subtype == "tracks":
                        col3_val = i.get("album", {}).get("title", "Unknown")
                    else:
                        col3_val = "-"

                    max_art = min(self.max_w_art, max(max_art, len(artist)))
                    max_tit = min(self.max_w_tit, max(max_tit, len(title)))
                    max_alb = min(self.max_w_alb, max(max_alb, len(col3_val)))
                    
                    raw_data.append((artist, title, col3_val, rel_type, year, quality, i))

                # Gravando as larguras exatas para a grelha
                self.w_art, self.w_tit, self.w_alb = max_art, max_tit, max_alb
                self.w_typ, self.w_yea, self.w_qua = 11, 4, 20

                # Passo 2: Renderizar a Tabela Elástica
                for artist, title, col3_val, rel_type, year, quality, i in raw_data:
                    text = f"│ {_align_text(artist, self.w_art)} │ {_align_text(title, self.w_tit)} │ {_align_text(col3_val, self.w_alb)} │ {_align_text(rel_type, self.w_typ)} │ {_align_text(year, self.w_yea)} │ {_align_text(quality, self.w_qua)} │"
                    url_category = fav_subtype[:-1] if item_type == "favorites" and fav_subtype else item_type
                    url = f"{WEB_URL}{url_category}/{i.get('id', '')}"
                    item_list.append({"text": text, "url": url} if not lucky else url)
            else:
                raw_data = []
                max_name = len("NOME")
                for i in iterable:
                    name = i.get('name', 'Unknown')
                    count_str = f"{i.get('albums_count', i.get('tracks_count', 0))} itens"
                    max_name = min(50, max(max_name, len(name)))
                    raw_data.append((name, count_str, i))

                self.w_name = max_name
                for name, count_str, i in raw_data:
                    text = f"│ {_align_text(name, self.w_name)} │ {_align_text(count_str, 13)} │"
                    url_category = fav_subtype[:-1] if item_type == "favorites" and fav_subtype else item_type
                    url = f"{WEB_URL}{url_category}/{i.get('id', '')}"
                    item_list.append({"text": text, "url": url} if not lucky else url)
            return item_list
        except (KeyError, IndexError): return []

    async def _interactive_search_loop(self, selected_type: str, fav_subtype: str) -> List[str]:
        import pick
        final_url_list = []
        while True:
            if selected_type == "favorites":
                print(f"\n{Tema.BUSCA}Procurando nos favoritos: {fav_subtype}...")
                options = await self.search_by_type(None, selected_type, limit=self.interactive_limit, fav_subtype=fav_subtype)
                query_title = f"My Favorite {fav_subtype.title()}"
            else:
                query = input(f"\n{Tema.BUSCA}Termo de pesquisa (ou Ctrl+C para sair):\n{Tema.BUSCA}{Tema.TITULO}> {Tema.OFF}").strip()
                if not query: continue
                print(f"{Tema.BUSCA}Procurando por '{query}'...")
                options = await self.search_by_type(query, selected_type, self.interactive_limit)
                query_title = query.title()

            if not options:
                print(f"{Tema.ALERTA}{Tema.AVISO}Nenhum resultado encontrado.{Tema.OFF}")
                if selected_type == "favorites": break
                continue

            # ---------------------------------------------------------------
            # Cabeçalho da tabela -- offset de 7 espaços para alinhar com o
            # prefixo "* [ ] " / "  [ ] " que o pick injeta em cada linha.
            # ---------------------------------------------------------------
            O = _PICK_HEADER_OFFSET  # 7 espaços

            if selected_type in ("album", "track") or (selected_type == "favorites" and fav_subtype in ("albums", "tracks")):
                col3_head = "GRAVADORA" if (selected_type == "album" or fav_subtype == "albums") else "ÁLBUM"
                b_top = f"{O}┌{'─' * (self.w_art+2)}┬{'─' * (self.w_tit+2)}┬{'─' * (self.w_alb+2)}┬{'─' * (self.w_typ+2)}┬{'─' * (self.w_yea+2)}┬{'─' * (self.w_qua+2)}┐"
                h_row = f"{O}│ {'ARTISTA'.ljust(self.w_art)} │ {'TÍTULO'.ljust(self.w_tit)} │ {col3_head.ljust(self.w_alb)} │ {'TIPO'.ljust(self.w_typ)} │ {'ANO'.ljust(self.w_yea)} │ {'QUALIDADE'.ljust(self.w_qua)} │"
                b_mid = f"{O}├{'─' * (self.w_art+2)}┼{'─' * (self.w_tit+2)}┼{'─' * (self.w_alb+2)}┼{'─' * (self.w_typ+2)}┼{'─' * (self.w_yea+2)}┼{'─' * (self.w_qua+2)}┤"
                t_head = f"{b_top}\n{h_row}\n{b_mid}"
            else:
                w_name = getattr(self, "w_name", 50)
                b_top = f"{O}┌{'─' * (w_name+2)}┬{'─' * 15}┐"
                h_row = f"{O}│ {'NOME'.ljust(w_name)} │ {'LANÇAMENTOS'.ljust(13)} │"
                b_mid = f"{O}├{'─' * (w_name+2)}┼{'─' * 15}┤"
                t_head = f"{b_top}\n{h_row}\n{b_mid}"

            title = f'*** RESULTADOS PARA "{query_title}" ***\n\n[Use setas para mover | Espaço para marcar/desmarcar | Enter para confirmar]\n\n{t_head}'
            options_texts = [opt.get("text") for opt in options]
            selected_items = pick.pick(options_texts, title, multiselect=True, min_selection_count=0)

            if selected_items:
                print(f"\n{Tema.SYS}{Tema.SUCESSO}{len(selected_items)} item(ns) selecionado(s) com sucesso!{Tema.OFF}")
                await asyncio.sleep(0.8) 

                for item, original_index in selected_items:
                    if original_index >= 0: final_url_list.append(options[original_index]["url"])

                os.system('clear')
                
                if pick.pick(["⬇️ Iniciar Download", "🔍 Pesquisar Mais"], "O que deseja fazer agora?")[0] == "⬇️ Iniciar Download": 
                    break
            else:
                print(f"{Tema.ALERTA}{Tema.AVISO}Nenhum item selecionado.{Tema.OFF}")
                await asyncio.sleep(0.8)
                if selected_type == "favorites": break
                continue

        return final_url_list

    async def interactive(self, download: bool = True):
        self._is_interactive_session = True
        
        try:
            import pick
            if hasattr(pick, "SYMBOL_CIRCLE_EMPTY"): pick.SYMBOL_CIRCLE_EMPTY, pick.SYMBOL_CIRCLE_FILLED = "[ ]", "[X]"
        except ImportError:
            sys.exit("Please install pick library.")

        try:
            item_types = ["Albums", "Tracks", "Artists", "Playlists", "Favorites"]
            selected_type = pick.pick(item_types, "O que deseja pesquisar?")[0].lower()
            fav_subtype = ""
            
            if selected_type == "favorites":
                fav_subtype = pick.pick(["Albums", "Tracks", "Artists", "Playlists"], "Navegar em qual categoria de favoritos?")[0].lower()
            else:
                selected_type = selected_type[:-1]

            final_url_list = await self._interactive_search_loop(selected_type, fav_subtype)

            if final_url_list:
                qualities = [{"q_string": "320kbps MP3", "q": 5}, {"q_string": "Lossless 16-bit", "q": 6}, {"q_string": "Hi-Res =< 96kHz", "q": 7}, {"q_string": "Hi-Res > 96kHz", "q": 27}]
                self.quality = qualities[pick.pick([q.get("q_string") for q in qualities], "Defina a qualidade (downgrade automático se não existir):", default_index=1)[1]]["q"]
                
                if download: await self.download_list_of_urls(final_url_list)
                return final_url_list

        except KeyboardInterrupt:
            print(f"\n{Tema.SYS}{Tema.ERRO}Operação abortada pelo utilizador.{Tema.OFF}")
            return

    async def download_lastfm_pl(self, playlist_url: str):
        from qobuz_dl.lastfm_parser import fetch_lastfm_playlist
        print(f"\n{Tema.URL}{Tema.AVISO}Integração Last.fm detetada{Tema.OFF}")
        
        tracks_list = await fetch_lastfm_playlist(playlist_url)
        if not tracks_list:
            print(f"{Tema.ALERTA}{Tema.ERRO}Abortado: Nenhuma faixa encontrada na playlist.{Tema.OFF}")
            return

        pl_id = playlist_url.rstrip("/").split("/")[-1]
        pl_title = sanitize_filename(f"LastFM_Playlist_{pl_id}")
        pl_directory = str(Path(self.directory) / pl_title)

        print(f"{Tema.FILA}Baixando Playlist: {Tema.TITULO}{pl_title}{Tema.OFF}")
        print(f"{Tema.FILA}Cruzando {len(tracks_list)} faixas com a API Qobuz...")
        
        track_ids = await self.client.get_track_ids_from_list(tracks_list)
        if not track_ids:
            print(f"{Tema.ALERTA}{Tema.ERRO}Falha: Nenhuma faixa coincidiu no catálogo da Qobuz.{Tema.OFF}")
            return

        original_folder_format = self.folder_format
        original_multi_disc_setting = self.settings.multiple_disc_one_dir
        self.folder_format = "."
        self.settings.multiple_disc_one_dir = True

        for idx, t_id in enumerate(track_ids, start=1):
            try: await self.download_from_id(t_id, False, pl_directory, is_playlist=True, playlist_index=idx)
            except Exception as exc: print(f"{Tema.ALERTA}{Tema.ERRO}ID {t_id} falhou: {exc}{Tema.OFF}")

        self.folder_format = original_folder_format
        self.settings.multiple_disc_one_dir = original_multi_disc_setting

        if not self.no_m3u_for_playlists: make_m3u(pl_directory)