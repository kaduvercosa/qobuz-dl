import logging
import os
import sys
import asyncio
import aiohttp
import shutil
import re
from pathlib import Path
from typing import Optional, List, Tuple, Any
import unicodedata

# ---------------------------------------------------------------------------
# Bibliotecas nativas para captura de hardware no iOS
# ---------------------------------------------------------------------------
import tty
import termios
import select

# ---------------------------------------------------------------------------
# Motor de Interface Avançado (Rich)
# ---------------------------------------------------------------------------
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich import box

from qobuz_dl.color import Tema, GREEN, YELLOW, RED, OFF, CYAN, RESET

# ===========================================================================
# 🚀 MOTOR DE INTERFACE (STUDIO MASTER RESPONSIVO)
# ===========================================================================

def is_mobile_screen() -> bool:
    """Verifica se o terminal é estreito (ex: iPhone na vertical)"""
    return shutil.get_terminal_size((120, 20)).columns < 95

def _read_key():
    """Captura silenciosa das teclas (Virtual e Magic Keyboard)."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            if select.select([sys.stdin], [], [], 0.05)[0]:
                ch += sys.stdin.read(2)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

def _gerar_tabela_rich(titulo: str, col_headers: list, opcoes: list, current_idx: int, selected_indices: set, multiselect: bool, is_mobile: bool):
    """Constrói a grelha visual adaptando automaticamente para iPhone ou iPad."""
    instrucoes = "↑/↓: Mover | Espaço: Marcar | Enter: Confirmar | Q: Sair" if multiselect else "↑/↓: Mover | Enter: Confirmar | Q: Sair"
    titulo_formatado = f"[bold]{titulo}[/bold]\n[dim]{instrucoes}[/dim]"

    tabela = Table(
        title=titulo_formatado,
        box=box.ROUNDED,
        show_lines=True,
        border_style="grey50",
        header_style="bold white"
    )

    tabela.add_column("SEL", justify="center", width=5)

    if not is_mobile:
        for header in col_headers:
            tabela.add_column(header)
    else:
        tabela.add_column("DETALHES DO LANÇAMENTO")

    for i, opt in enumerate(opcoes):
        is_hover = (i == current_idx)
        is_checked = (i in selected_indices)

        cursor = "[bold cyan]❯[/bold cyan]" if is_hover else " "
        
        if multiselect:
            caixa = "[bold][X][/bold]" if is_checked else "[ ]"
        else:
            caixa = ""

        coluna_sel = f"{cursor} {caixa}".strip()
        estilo_linha = "on grey37" if is_hover else None

        if not is_mobile:
            # RENDERIZAÇÃO IPAD/PC (TABELA LARGA)
            col_render = [coluna_sel]
            for col_text in opt["colunas"]:
                text_str = str(col_text)
                if "HI-RES" in text_str.upper():
                    col_render.append(f"[yellow]{text_str}[/yellow]")
                elif "16B" in text_str.upper() or "MP3" in text_str.upper() or "CD" in text_str.upper():
                    col_render.append(f"[grey62]{text_str}[/grey62]")
                else:
                    col_render.append(f"[bold]{text_str}[/bold]")
            tabela.add_row(*col_render, style=estilo_linha)

        else:
            # RENDERIZAÇÃO IPHONE (MODO CARTÃO)
            cols = opt["colunas"]
            if len(cols) >= 6:
                artista, titulo_album, gravadora, tipo, ano, qual = cols[0], cols[1], cols[2], cols[3], cols[4], cols[5]
                q_style = "yellow" if "HI-RES" in str(qual).upper() else "grey62"
                
                card_text = (
                    f"[bold white]🎵 {titulo_album} - {artista} ({ano})[/bold white]\n"
                    f" ├─ 🏷️ [bold]{tipo}[/bold] | 🏢 {gravadora}\n"
                    f" └─ 🎧 [{q_style}]{qual}[/{q_style}]"
                )
            elif len(cols) == 2:
                nome, contagem = cols[0], cols[1]
                card_text = f"[bold white]📂 {nome}[/bold white]\n └─ [grey62]{contagem}[/grey62]"
            else:
                # Fallback para menus simples (Categorias, Qualidades, Ações)
                card_text = "[bold white]" + " - ".join(str(c) for c in cols) + "[/bold white]"
            
            tabela.add_row(coluna_sel, card_text, style=estilo_linha)

    return tabela

async def abrir_interface(titulo: str, col_headers: list, opcoes: list, multiselect: bool = False):
    """Lida com o Live Update da Tabela em resposta ao teclado."""
    console = Console()
    current_idx = 0
    selected_indices = set()
    is_mobile = is_mobile_screen()

    os.system('clear')

    with Live(_gerar_tabela_rich(titulo, col_headers, opcoes, current_idx, selected_indices, multiselect, is_mobile), console=console, refresh_per_second=12, transient=True) as live:
        while True:
            key = await asyncio.to_thread(_read_key)
            
            if key in ('q', 'Q', '\x03'): 
                return []
            elif key == '\x1b[A': 
                current_idx = max(0, current_idx - 1)
            elif key == '\x1b[B': 
                current_idx = min(len(opcoes) - 1, current_idx + 1)
            elif key == ' ' and multiselect: 
                if current_idx in selected_indices:
                    selected_indices.remove(current_idx)
                else:
                    selected_indices.add(current_idx)
            elif key in ('\r', '\n'): 
                if multiselect:
                    if not selected_indices:
                        selected_indices.add(current_idx) 
                    return [opcoes[i]["data"] for i in sorted(selected_indices)]
                else:
                    return [opcoes[current_idx]["data"]]

            live.update(_gerar_tabela_rich(titulo, col_headers, opcoes, current_idx, selected_indices, multiselect, is_mobile))

# ===========================================================================
# 🚀 OTIMIZAÇÃO GLOBAL DE REDE (INJEÇÃO)
# ===========================================================================
try:
    import aiodns
    _fast_resolver = aiohttp.AsyncResolver()
except ImportError:
    _fast_resolver = None

_original_tcp_connector = aiohttp.TCPConnector

class FastTCPConnector(_original_tcp_connector):
    def __init__(self, *args, **kwargs):
        kwargs['ssl'] = False
        kwargs['limit'] = 100  
        if _fast_resolver and 'resolver' not in kwargs:
            kwargs['resolver'] = _fast_resolver
        super().__init__(*args, **kwargs)

aiohttp.TCPConnector = FastTCPConnector
# ===========================================================================

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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper de Alinhamento e Detetores
# ---------------------------------------------------------------------------
def get_display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in str(text))

def _align_text(text: str, width: int) -> str:
    text = str(text)
    current_w = get_display_width(text)
    if current_w <= width: return text + " " * (width - current_w)
    truncated = ""
    current_w = 0
    target_w = width - 3 
    for char in text:
        char_w = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
        if current_w + char_w > target_w: break
        truncated += char
        current_w += char_w
    return truncated + "..." + " " * (width - current_w - 3)

# ---------------------------------------------------------------------------
# Lógica de tipo de lançamento
# ---------------------------------------------------------------------------
def classificar_tipo_lancamento(raw_type: Optional[str], title: str = "", version: str = "", t_count: int = 0, duration: int = 0) -> str:
    r_type = (raw_type or "").lower().strip()
    title_l   = (title or "").lower()
    version_l = (version or "").lower()

    if re.search(r'\blive\b', version_l) or "(live" in title_l or "- live" in title_l or title_l.endswith(" live"):
        return "live"
    if any(kw in title_l or kw in version_l for kw in ("best of", "greatest hits", "anthology", "collection", "compilation")):
        return "compilation"
    if re.search(r'\bep\b', title_l) or re.search(r'\bep\b', version_l):
        return "ep"

    if r_type == "single":
        if t_count >= 7 or duration >= 1800: r_type = "album"
        elif t_count >= 4: r_type = "ep"
    elif r_type == "ep":
        if t_count >= 7 or duration >= 1800: r_type = "album"
    elif r_type == "album":
        if 1 <= t_count <= 3 and duration < 1800: r_type = "single"
        elif 4 <= t_count <= 6 and duration < 1800: r_type = "ep"

    if r_type not in ("album", "ep", "single", "live", "compilation"):
        if t_count >= 7 or duration >= 1800: r_type = "album"
        elif 4 <= t_count <= 6: r_type = "ep"
        else: r_type = "single"

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

# ---------------------------------------------------------------------------
# Dataclass de configuração
# ---------------------------------------------------------------------------
class QobuzDLConfig:
    def __init__(self, directory: str = "QobuzDownloads", quality: int = 6, embed_art: bool = True, lucky_limit: int = 1, lucky_type: str = "album", interactive_limit: int = 20, ignore_singles_eps: bool = False, no_m3u_for_playlists: bool = False, quality_fallback: bool = True, cover_og_quality: bool = True, no_cover: bool = False, downloads_db: Optional[str] = None, folder_format: str = "{release_type}/{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]", track_format: str = "{track_number} - {track_title}", smart_discography: bool = False, fetch_lyrics: bool = False, no_lrc_files: bool = False, genius_token: Optional[str] = None, deepl_api_key: Optional[str] = None, translate_lyrics: bool = True, force_english: bool = True, no_credits: bool = False, booklet_only: bool = False, blacklist: Optional[str] = None, target_lang: str = "PT-BR", delay: Optional[int] = None, settings: Optional[QobuzDLSettings] = None):
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
        self.translate_lyrics     = translate_lyrics
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
    def __init__(self, directory: str = "QobuzDownloads", quality: int = 7, embed_art: bool = True, lucky_limit: int = 1, lucky_type: str = "album", interactive_limit: int = 20, ignore_singles_eps: bool = False, no_m3u_for_playlists: bool = False, quality_fallback: bool = True, cover_og_quality: bool = True, no_cover: bool = False, downloads_db: Optional[str] = None, folder_format: str = "{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]", track_format: str = "{track_number} - {track_title}", smart_discography: bool = False, fetch_lyrics: bool = False, no_lrc_files: bool = False, genius_token: Optional[str] = None, deepl_api_key: Optional[str] = None, translate_lyrics: bool = True, force_english: bool = True, no_credits: bool = False, settings: Optional[QobuzDLSettings] = None, booklet_only: bool = False, blacklist: Optional[str] = None, target_lang: str = "PT-BR", delay: Optional[int] = None):
        self.deepl_api_key        = deepl_api_key
        self.translate_lyrics     = translate_lyrics
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
            except Exception:
                pass

    async def initialize_client(self, email: str, pwd: str, app_id: str, secrets: list):
        self.client = qopy.Client(email, pwd, app_id, secrets, self.settings.user_auth_token, force_english=self.force_english)
        await self.client.start()
        print(f"{Tema.SYS}{Tema.AVISO}Sessão Ativa | Qualidade: {QUALITIES[int(self.quality)]}{Tema.OFF}")

    def get_tokens(self):
        bundle = Bundle()
        self.app_id  = bundle.get_app_id()
        self.secrets = [s for s in bundle.get_secrets().values() if s]

    async def download_from_id(self, item_id: str, album: bool = True, alt_path: Optional[str] = None, is_playlist: bool = False, playlist_index: Optional[int] = None, is_single_batch: bool = False, single_batch_index: int = 1, single_batch_total: int = 1):
        try:
            dloader = downloader.Download(
                client=self.client, item_id=item_id, path=alt_path or self.directory, quality=int(self.quality),
                embed_art=self.embed_art, albums_only=self.ignore_singles_eps, downgrade_quality=self.quality_fallback,
                cover_og_quality=self.cover_og_quality, no_cover=self.no_cover, folder_format=self.folder_format,
                track_format=self.track_format, fetch_lyrics=self.fetch_lyrics, no_lrc_files=self.no_lrc_files,
                genius_token=self.genius_token, deepl_api_key=self.deepl_api_key, translate_lyrics=self.translate_lyrics, target_lang=self.target_lang,
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
            is_playlist = (url_type == "playlist")
            
            if not is_playlist:
                print(f"\n{Tema.URL}{Tema.TITULO}{content_name}{Tema.OFF} ({url_type})")

            if is_playlist:
                new_path = create_and_return_dir(str(Path(self.directory) / "Playlist" / sanitize_filename(content_name)))
            else:
                new_path = create_and_return_dir(str(Path(self.directory) / sanitize_filename(content_name)))

            if self.smart_discography and url_type == "artist":
                items = smart_discography_filter(content, save_space=True, skip_extras=True)
            else:
                items = [item for chunk in content for item in chunk.get(type_dict["iterable_key"], {}).get("items", [])]

            if self._is_interactive_session and url_type == "artist":
                tipos = ["Album", "EP", "Single", "Live", "Compilation"]
                opcoes_ui = [{"colunas": [opt], "data": opt} for opt in tipos]
                titulo = f"*** FILTRO PARA {content_name.upper()} - TIPO DE LANÇAMENTO ***"
                
                selected_raw = await abrir_interface(titulo, ["OPÇÕES"], opcoes_ui, multiselect=True)
                
                self.allowed_release_types = [opt.lower() for opt in selected_raw] if selected_raw else []
                if not self.allowed_release_types: items = []
            else:
                self.allowed_release_types = None

            if not is_playlist:
                print(f"{Tema.FILA}{Tema.SUCESSO}{len(items)} itens agendados para processamento.{Tema.OFF}\n")

            if is_playlist:
                original_folder_format = self.folder_format
                original_multi_disc_setting = self.settings.multiple_disc_one_dir
                self.folder_format = "."
                self.settings.multiple_disc_one_dir = True
                self.settings.playlist_name = content_name

            self.settings.playlist_total_count = len(items)

            try:
                for idx, item in enumerate(items, start=1):
                    if self.allowed_release_types and url_type == "artist":
                        r_type = await self._resolve_release_type(item)
                        if r_type not in self.allowed_release_types: continue

                    if self.blacklist_patterns:
                        display_name = f"{item.get('title') or item.get('name')} ({item.get('version', '')})".strip(" ()")
                        if any(p in display_name.lower() for p in self.blacklist_patterns):
                            continue

                    await self.download_from_id(item["id"], type_dict["iterable_key"] == "albums", new_path, is_playlist=is_playlist, playlist_index=idx)
            finally:
                if is_playlist:
                    self.folder_format = original_folder_format
                    self.settings.multiple_disc_one_dir = original_multi_disc_setting
                    
            if is_playlist:
                try:
                    from qobuz_dl.telegram_uploader import upload_album_completo
                    await upload_album_completo(new_path, content_name, "Vários Artistas", "Various Artists", "Vários Artistas (Playlist)", "Playlist")
                except Exception:
                    pass

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
        
        try: max_batch_workers = int(getattr(self.settings, "max_workers", 1))
        except (ValueError, TypeError): max_batch_workers = 1
        
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
        await self.download_list_of_urls(valid_urls, txt_file=txt_file)

    # ---------------------------------------------------------------------------
    # Motor de Análise e Busca Qobuz API
    # ---------------------------------------------------------------------------
    async def search_by_type(self, query: Optional[str], item_type: str, limit: int = 10, lucky: bool = False, fav_subtype: Optional[str] = None):
        limit = int(limit)
        if item_type != "favorites" and (not query or len(query) < 3): return [], []
        
        api_type = item_type
        if item_type == "album_ep": api_type = "album"
        elif item_type == "single": api_type = "track"
        
        actual_fav_subtype = fav_subtype
        if fav_subtype == "albums": actual_fav_subtype = "albums"
        elif fav_subtype == "singles": actual_fav_subtype = "tracks"

        possibles = {
            "album":     {"func": self.client.search_albums,    "key": "albums",    "requires_extra": True},
            "artist":    {"func": self.client.search_artists,   "key": "artists",   "requires_extra": False},
            "track":     {"func": self.client.search_tracks,    "key": "tracks",    "requires_extra": True},
            "playlist":  {"func": self.client.search_playlists, "key": "playlists", "requires_extra": False},
            "favorites": {"func": self.client.get_favorites,    "key": "favorites", "requires_extra": True},
        }
        
        try:
            mode_dict = possibles[api_type]
            if item_type == "favorites":
                fetch_limit = limit if actual_fav_subtype not in ("albums", "tracks") else 100
                results = await mode_dict["func"](fav_type=actual_fav_subtype, limit=fetch_limit)
                iterable = results.get("favorites", {}).get(actual_fav_subtype, {}).get("items", []) or results.get(actual_fav_subtype, {}).get("items", [])
                mode_dict["requires_extra"] = actual_fav_subtype not in ("artists", "playlists")
            else:
                fetch_limit = limit if item_type not in ("album_ep", "single") else 50
                results = await mode_dict["func"](query, fetch_limit)
                if not results or mode_dict["key"] not in results or "items" not in results[mode_dict["key"]]: return [], []
                iterable = results[mode_dict["key"]]["items"]

            item_list = []
            
            if mode_dict["requires_extra"]:
                is_track_search = (api_type == "track" or actual_fav_subtype == "tracks")
                col_headers = ["ARTISTA", "TÍTULO", "ÁLBUM" if is_track_search else "GRAVADORA", "TIPO", "ANO", "QUALIDADE"]
                
                valid_count = 0
                for i in iterable:
                    if is_track_search:
                        rel_type = "Faixa"
                        col3_val = i.get("album", {}).get("title", "Unknown")
                    else:
                        r_type_str = classificar_tipo_lancamento(
                            raw_type=i.get("release_type") or i.get("product_type"), 
                            title=str(i.get("title", "")), 
                            version=str(i.get("version", "")), 
                            t_count=i.get("tracks_count", 0), 
                            duration=i.get("duration", 0)
                        )
                        if r_type_str not in ("album", "ep"): continue
                        rel_type = "EP" if r_type_str == "ep" else r_type_str.title()
                        col3_val = i.get("label", {}).get("name", "Independente")
                    
                    artist = i.get("artist", {}).get("name") or i.get("performer", {}).get("name") or "Unknown"
                    title = i.get("title") or i.get("name") or "Unknown"
                    if i.get("version"): title = f"{title} ({i['version']})"
                    if i.get("parental_warning"): title = f"{title} [E]"
                    year = str(i.get("release_date_original") or i.get("release_date") or "    ")[:4]
                    
                    quality = f"[HI-RES] {i.get('maximum_bit_depth', 24)}b/{i.get('maximum_sampling_rate', 96.0)}kHz" if i.get("hires_streamable") else "[ CD ] 16b/44.1kHz"
                    
                    url_category = actual_fav_subtype[:-1] if item_type == "favorites" and actual_fav_subtype else api_type
                    url = f"{WEB_URL}{url_category}/{i.get('id', '')}"
                    
                    item_list.append({
                        "colunas": [artist, title, col3_val, rel_type, year, quality],
                        "data": url
                    })
                    
                    valid_count += 1
                    if valid_count >= limit: break

            else:
                col_headers = ["NOME", "LANÇAMENTOS"]
                for i in iterable:
                    name = i.get('name', 'Unknown')
                    count_str = f"{i.get('albums_count', i.get('tracks_count', 0))} itens"
                    
                    url_category = actual_fav_subtype[:-1] if item_type == "favorites" and actual_fav_subtype else api_type
                    url = f"{WEB_URL}{url_category}/{i.get('id', '')}"
                    
                    item_list.append({
                        "colunas": [name, count_str],
                        "data": url
                    })

            return col_headers, item_list
        except (KeyError, IndexError): return [], []

    # ---------------------------------------------------------------------------
    # O LOOP INTERATIVO DEFINITIVO
    # ---------------------------------------------------------------------------
    async def _interactive_search_loop(self, selected_type: str, fav_subtype: str) -> List[str]:
        final_url_list = []
        
        tipo_map = {
            "album_ep": "ÁLBUNS E EPs",
            "single": "SINGLES",
            "artist": "ARTISTAS",
            "playlist": "PLAYLISTS",
            "favorites": f"FAVORITOS ({fav_subtype.upper()})"
        }
        
        while True:
            os.system('clear') 
            tipo_str = tipo_map.get(selected_type, "RESULTADOS")
            
            if selected_type == "favorites":
                print(f"\n{Tema.BUSCA}A carregar {fav_subtype} dos favoritos...")
                col_headers, options = await self.search_by_type(None, selected_type, limit=self.interactive_limit, fav_subtype=fav_subtype)
                query_display = "MEUS FAVORITOS"
            else:
                query = await asyncio.to_thread(input, f"\n{Tema.TERMO}Termo de pesquisa (ou Ctrl+C para sair):\n{Tema.TEXTO}{Tema.TITULO} {Tema.OFF}")
                query = query.strip()
                if not query: continue
                
                os.system('clear') 
                print(f"\n{Tema.BUSCA}A procurar por '{query}' nos servidores da Qobuz...")
                col_headers, options = await self.search_by_type(query, selected_type, self.interactive_limit)
                query_display = query.upper()

            if not options:
                print(f"{Tema.ALERTA}{Tema.AVISO}Nenhum resultado encontrado.{Tema.OFF}")
                await asyncio.sleep(2)
                if selected_type == "favorites": break
                continue

            title_text = f"*** RESULTADOS PARA {query_display} - {tipo_str} ***"
            
            selected_urls = await abrir_interface(title_text, col_headers, options, multiselect=True)

            if selected_urls:
                await asyncio.sleep(0.5) 
                intercept_artist = False
                
                for url in selected_urls:
                    if selected_type == "artist" or (selected_type == "favorites" and fav_subtype == "artists"):
                        intercept_artist = True
                        artist_id = url.rstrip("/").split("/")[-1]
                        
                        artist_name = "ARTISTA"
                        for opt in options:
                            if opt["data"] == url:
                                artist_name = opt["colunas"][0]
                                break
                                
                        albums_urls = await self._fetch_and_pick_artist_albums(artist_id, artist_name)
                        final_url_list.extend(albums_urls)
                    else:
                        final_url_list.append(url)

                if intercept_artist and not final_url_list:
                    continue
                
                action_ui = [
                    {"colunas": ["⬇️ Iniciar Download"], "data": "download"}, 
                    {"colunas": ["🔍 Pesquisar Mais"], "data": "search"}
                ]
                action_sel = await abrir_interface("*** O QUE DESEJA FAZER AGORA? ***", ["AÇÃO"], action_ui, multiselect=False)
                if action_sel and action_sel[0] == "download": 
                    break
            else:
                await asyncio.sleep(1)
                if selected_type == "favorites": break
                continue

        return final_url_list

    async def _fetch_and_pick_artist_albums(self, artist_id: str, artist_name: str) -> List[str]:
        os.system('clear') 
        print(f"\n{Tema.BUSCA}A analisar discografia completa de {Tema.TITULO}{artist_name}{Tema.OFF}...")
        
        all_albums = []
        try:
            async for page in self.client.get_artist_meta(artist_id):
                items = page.get("albums", {}).get("items", [])
                all_albums.extend(items)
        except Exception as e:
            print(f"{Tema.ALERTA}{Tema.ERRO}Erro ao buscar discografia: {e}{Tema.OFF}")
            
        if not all_albums:
            os.system('clear')
            print(f"{Tema.ALERTA}{Tema.AVISO}Nenhum lançamento encontrado para este artista.{Tema.OFF}")
            await asyncio.sleep(1.5)
            return []
            
        raw_data = []
        for i in all_albums:
            title = i.get("title") or i.get("name") or "Unknown"
            if i.get("version"): title = f"{title} ({i['version']})"
            if i.get("parental_warning"): title = f"{title} [E]"
            year = str(i.get("release_date_original") or i.get("release_date") or "    ")[:4]
            r_type_str = classificar_tipo_lancamento(raw_type=i.get("release_type") or i.get("product_type"), title=str(i.get("title", "")), version=str(i.get("version", "")), t_count=i.get("tracks_count", 0), duration=i.get("duration", 0))
            rel_type = "EP" if r_type_str == "ep" else r_type_str.title()
            quality = f"[HI-RES] {i.get('maximum_bit_depth', 24)}b/{i.get('maximum_sampling_rate', 96.0)}kHz" if i.get("hires_streamable") else "[ CD ] 16b/44.1kHz"
            
            raw_data.append((title, rel_type, year, quality, i, r_type_str))
            
        type_order = {"album": 1, "ep": 2, "single": 3, "live": 4, "compilation": 5}
        raw_data.sort(key=lambda x: (type_order.get(x[5], 9), -int(x[2] if x[2].isdigit() else 0)))
        
        col_headers = ["TÍTULO", "TIPO", "ANO", "QUALIDADE"]
        options_ui = []
        
        for title, rel_type, year, quality, i, _ in raw_data:
            url = f"{WEB_URL}album/{i.get('id', '')}"
            options_ui.append({
                "colunas": [title, rel_type, year, quality],
                "data": url
            })
            
        title_text = f"*** DISCOGRAFIA DE {artist_name.upper()} ***"
        selected = await abrir_interface(title_text, col_headers, options_ui, multiselect=True)
        
        return selected if selected else []

    async def interactive(self, download: bool = True):
        self._is_interactive_session = True
        
        try:
            os.system('clear') 
            item_types = ["Álbuns e EPs", "Singles", "Artistas", "Playlists", "Favoritos"]
            options_types = [{"colunas": [opt], "data": opt} for opt in item_types]
            
            selected_type_list = await abrir_interface("*** O QUE DESEJA PESQUISAR? ***", ["CATEGORIA"], options_types, multiselect=False)
            if not selected_type_list: return
            selected_type_raw = selected_type_list[0]
            
            fav_subtype = ""
            
            if selected_type_raw == "Favoritos":
                selected_type = "favorites"
                fav_subtypes = ["Álbuns e EPs", "Singles", "Artistas", "Playlists"]
                options_fav = [{"colunas": [opt], "data": opt} for opt in fav_subtypes]
                
                fav_subtype_list = await abrir_interface("*** NAVEGAR NOS FAVORITOS ***", ["CATEGORIA"], options_fav, multiselect=False)
                if not fav_subtype_list: return
                fav_subtype_raw = fav_subtype_list[0]
                
                if fav_subtype_raw == "Álbuns e EPs": fav_subtype = "albums"
                elif fav_subtype_raw == "Singles": fav_subtype = "singles"
                elif fav_subtype_raw == "Artistas": fav_subtype = "artists"
                else: fav_subtype = "playlists"
            else:
                if selected_type_raw == "Álbuns e EPs": selected_type = "album_ep"
                elif selected_type_raw == "Singles": selected_type = "single"
                elif selected_type_raw == "Artistas": selected_type = "artist"
                else: selected_type = "playlist"

            final_url_list = await self._interactive_search_loop(selected_type, fav_subtype)

            if final_url_list:
                qualities = [{"q_string": "320kbps MP3", "q": 5}, {"q_string": "Lossless 16-bit", "q": 6}, {"q_string": "Hi-Res =< 96kHz", "q": 7}, {"q_string": "Hi-Res > 96kHz", "q": 27}]
                options_q = [{"colunas": [q["q_string"]], "data": q["q"]} for q in qualities]
                
                selected_q = await abrir_interface("*** DEFINA A QUALIDADE MÁXIMA ***", ["QUALIDADE"], options_q, multiselect=False)
                
                if selected_q:
                    self.quality = selected_q[0]
                    if download: await self.download_list_of_urls(final_url_list)
                return final_url_list

        except KeyboardInterrupt:
            os.system('clear')
            print(f"\n{Tema.SYS}{Tema.ERRO}Operação abortada pelo utilizador.{Tema.OFF}\n")
            return

    async def download_lastfm_pl(self, playlist_url: str):
        from qobuz_dl.lastfm_parser import fetch_lastfm_playlist
        print(f"\n{Tema.URL}{Tema.AVISO}Integração Last.fm detetada{Tema.OFF}")
        
        tracks_list = await fetch_lastfm_playlist(playlist_url)
        if not tracks_list:
            print(f"{Tema.ALERTA}{Tema.ERRO}Abortado: Nenhuma faixa encontrada na playlist.{Tema.OFF}")
            return

        pl_id = playlist_url.rstrip("/").split("/")[-1]
        pl_title = sanitize_filename(f"Playlist_LastFM: {pl_id}")
        pl_directory = str(Path(self.directory) / "Playlist - LASTFM" / pl_title)

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

        try:
            for idx, t_id in enumerate(track_ids, start=1):
                try:
                    await self.download_from_id(t_id, False, pl_directory, is_playlist=True, playlist_index=idx)
                except Exception as exc:
                    print(f"{Tema.ALERTA}{Tema.ERRO}ID {t_id} falhou: {exc}{Tema.OFF}")

        finally:
            self.folder_format = original_folder_format
            self.settings.multiple_disc_one_dir = original_multi_disc_setting

        if not self.no_m3u_for_playlists:
            make_m3u(pl_directory)