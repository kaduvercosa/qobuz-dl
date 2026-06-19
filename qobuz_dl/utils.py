import re
import string
import logging
import time
import unicodedata
import aiohttp
import difflib
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Union

from mutagen.mp3 import EasyMP3
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen import File

from qobuz_dl.color import GREEN, RED, YELLOW, CYAN, OFF

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EXTENSIONS = {".mp3", ".flac"}


# ─── FUNÇÕES DE VALIDAÇÃO DE CAPA (FILTRO DE SANIDADE) ──────────────────────────

def limpar_texto(texto: str) -> str:
    """Remove acentos e deixa tudo minúsculo para uma comparação justa."""
    if not texto: return ""
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    return texto.lower().strip()

def validar_capa_apple(titulo_qobuz: str, titulo_apple: str, artista_qobuz: str, artista_apple: str) -> bool:
    """Verifica se a Apple trouxe o álbum e o artista corretos comparando similaridade."""
    q_titulo = limpar_texto(titulo_qobuz)
    a_titulo = limpar_texto(titulo_apple)
    
    q_artista = limpar_texto(artista_qobuz)
    a_artista = limpar_texto(artista_apple)

    sim_titulo = difflib.SequenceMatcher(None, q_titulo, a_titulo).ratio()
    sim_artista = difflib.SequenceMatcher(None, q_artista, a_artista).ratio()

    # Se o título ou o artista tiverem menos de 75% de similaridade, bloqueia a capa
    if sim_titulo < 0.75 or sim_artista < 0.75:
        logger.debug(f"Capa da Apple rejeitada. Similaridade: Título={sim_titulo:.2f}, Artista={sim_artista:.2f}")
        return False
    return True

# ────────────────────────────────────────────────────────────────────────────────

class PartialFormatter(string.Formatter):
    """
    Formatador de strings que lida com chaves (keys) ausentes de forma elegante,
    em vez de causar um KeyError.
    """
    def __init__(self, missing: str = "n/a", bad_fmt: str = "n/a"):
        self.missing = missing
        self.bad_fmt = bad_fmt

    def get_field(self, field_name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Tuple[Any, str]:
        try:
            val = super().get_field(field_name, args, kwargs)
        except (KeyError, AttributeError):
            val = None, field_name
        return val

    def format_field(self, value: Any, spec: str) -> str:
        if not value:
            return self.missing
        try:
            return super().format_field(value, spec)
        except ValueError:
            if self.bad_fmt:
                return self.bad_fmt
            raise


def make_m3u(pl_directory: Union[str, Path], remote_items: Optional[List[Dict[str, Any]]] = None) -> None:
    """
    Gera um ficheiro de playlist .m3u.
    Se a ordem remota da API (remote_items) for fornecida, usa um algoritmo de
    4 passos (ID -> ISRC -> Título -> Nome de Ficheiro) para preservar a ordem online exata.
    """
    pl_path = Path(pl_directory).resolve()
    track_list = ["#EXTM3U"]
    pl_full_path = pl_path / f"{pl_path.name}.m3u"

    # 1. Analisa a pasta local e extrai as tags de áudio (Pathlib rglob em vez de os.walk)
    local_files_info: List[Dict[str, Any]] = []
    
    for audio_path in pl_path.rglob('*'):
        if not audio_path.is_file() or audio_path.suffix.lower() not in EXTENSIONS:
            continue

        info: Dict[str, Any] = {
            'path': audio_path, 
            'title': '', 
            'artist': '', 
            'isrc': '', 
            'qobuz_id': '',
            'duration': 0
        }
        
        try:
            audio_gen = File(audio_path)
            if audio_gen and audio_gen.info:
                info['duration'] = int(audio_gen.info.length)

            if audio_path.suffix.lower() == '.flac':
                audio = FLAC(audio_path)
                info['qobuz_id'] = audio.get("QOBUZTRACKID", [None])[0]
                info['isrc'] = audio.get("ISRC", [None])[0]
                info['title'] = audio.get("TITLE", [""])[0]
                info['artist'] = audio.get("ARTIST", [""])[0]
            else:
                audio = ID3(audio_path)
                for frame in audio.getall("TXXX"):
                    if frame.desc.upper() == "QOBUZTRACKID":
                        info['qobuz_id'] = frame.text[0]
                        break
                isrc_frame = audio.get("TSRC")
                info['isrc'] = isrc_frame.text[0] if isrc_frame else None
                tit2 = audio.get("TIT2")
                info['title'] = tit2.text[0] if tit2 else ""
                tpe1 = audio.get("TPE1")
                info['artist'] = tpe1.text[0] if tpe1 else ""
                
        except Exception as e:
            logger.debug(f"Error reading tags for {audio_path.name}: {e}")
            info['title'] = audio_path.stem 
        
        local_files_info.append(info)

    ordered_files: List[Dict[str, Any]] = []

    # 2. Corresponde com a ordem da API do Qobuz (Algoritmo de 4 Passos)
    if remote_items:
        by_tid = {str(f['qobuz_id']): f for f in local_files_info if f.get('qobuz_id')}
        by_isrc = {str(f['isrc']): f for f in local_files_info if f.get('isrc')}
        by_title = {str(f['title']).strip().lower(): f for f in local_files_info if f.get('title')}
        
        missing_count = 0
        table_header = (
            f"\n{RED}{'━'*80}\n"
            f"{YELLOW}{'MISSING LOCAL TRACKS':^80}\n"
            f"{RED}{'━'*80}{OFF}\n"
            f"{CYAN}{'TITLE':<35} │ {'ARTIST':<25} │ {'ID':<12}{OFF}\n"
            f"{'─'*80}"
        )
        
        for item in remote_items:
            tid = str(item.get("id", ""))
            isrc = str(item.get("isrc", ""))
            track_title = item.get("title", "Unknown Title")
            album_artist = item.get("album", {}).get("artist", {}).get("name")
            performer_name = item.get("performer", {}).get("name", "Unknown Artist")
            final_artist = performer_name if album_artist in [None, "Various Artists"] else album_artist
            
            best_match = by_tid.get(tid) or by_isrc.get(isrc) or by_title.get(track_title.strip().lower())
            
            if not best_match and track_title != "Unknown Title":
                for f_info in local_files_info:
                    if track_title.lower() in f_info['path'].name.lower():
                        best_match = f_info
                        break
            
            if best_match:
                ordered_files.append(best_match)
            else:
                if missing_count == 0:
                    logger.warning(table_header)
                row = f"{track_title[:35]:<35} │ {final_artist[:25]:<25} │ {tid:<12}"
                logger.warning(f"{YELLOW}{row}{OFF}")
                missing_count += 1
                
        if missing_count > 0:
            logger.warning(f"{RED}{'━'*80}{OFF}\n")

    # 3. Fallback: Ordenação Natural
    if not remote_items or len(ordered_files) == 0:
        def natural_sort_key(s: str) -> List[Any]:
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
        
        ordered_files = sorted(local_files_info, key=lambda x: natural_sort_key(x['path'].name))

    # 4. Gera o ficheiro M3U
    for f_info in ordered_files:
        audio_rel_path = f_info['path'].relative_to(pl_path).as_posix()
        disp_title = f_info['title'] or "Unknown Title"
        disp_artist = f_info['artist'] or "Unknown Artist"
        length = f_info['duration']

        index = f"#EXTINF:{length}, {disp_artist} - {disp_title}\n{audio_rel_path}"
        track_list.append(index)

    if len(track_list) > 1:
        pl_full_path.write_text("\n".join(track_list), encoding="utf-8")


def smart_discography_filter(contents: List[Dict[str, Any]], save_space: bool = False, skip_extras: bool = False) -> List[Dict[str, Any]]:
    """
    Filtra discografias grandes, removendo duplicados de qualidade inferior
    ou versões extra (Deluxe, Live) consoante as configurações.
    """
    TYPE_REGEXES = {
        "remaster": r"(?i)(re)?master(ed)?",
        "extra": r"(?i)(anniversary|deluxe|live|collector|demo|expanded)",
    }

    def is_type(album_t: str, album: Dict[str, Any]) -> bool:
        version = album.get("version", "")
        title = album.get("title", "")
        regex = TYPE_REGEXES[album_t]
        return re.search(regex, f"{title} {version}") is not None

    def essence(album_title: str) -> str:
        r = re.match(r"([^\(]+)(?:\s*[\(\[][^\)][\)\]])*", album_title)
        return r.group(1).strip().lower() if r else album_title.strip().lower()

    requested_artist = contents[0]["name"]
    items = [item["albums"]["items"] for item in contents][0]

    title_grouped: Dict[str, List[Dict[str, Any]]] = dict()
    for item in items:
        title_ = essence(item["title"])
        if title_ not in title_grouped:
            title_grouped[title_] = []
        title_grouped[title_].append(item)

    filtered_items: List[Dict[str, Any]] = []
    for albums in title_grouped.values():
        best_bit_depth = max(a["maximum_bit_depth"] for a in albums)
        get_best = min if save_space else max
        best_sampling_rate = get_best(
            a["maximum_sampling_rate"] for a in albums if a["maximum_bit_depth"] == best_bit_depth
        )
        remaster_exists = any(is_type("remaster", a) for a in albums)

        def is_valid(album: Dict[str, Any]) -> bool:
            return (
                album["maximum_bit_depth"] == best_bit_depth
                and album["maximum_sampling_rate"] == best_sampling_rate
                and album["artist"]["name"] == requested_artist
                and not (
                    (remaster_exists and not is_type("remaster", album))
                    or (skip_extras and is_type("extra", album))
                )
            )

        valid_albums = list(filter(is_valid, albums))
        if valid_albums:
            filtered_items.append(valid_albums[0])

    return filtered_items


def format_duration(duration: int) -> str:
    """Formata segundos num formato legível HH:MM:SS."""
    return time.strftime("%H:%M:%S", time.gmtime(duration))


def create_and_return_dir(directory: Union[str, Path]) -> str:
    """Cria uma pasta absoluta, se não existir, e devolve o seu caminho."""
    fix = Path(directory).expanduser().resolve()
    fix.mkdir(parents=True, exist_ok=True)
    return str(fix)


def get_url_info(url: str) -> Tuple[str, str]:
    """Retorna o tipo de URL do Qobuz e o respetivo ID."""
    r = re.search(
        r"(?:https:\/\/(?:w{3}|open|play)\.qobuz\.com)?(?:\/[a-z]{2}-[a-z]{2})"
        r"?\/(album|artist|track|playlist|label)(?:\/[-\w\d]+)?\/([\w\d]+)",
        url,
    )
    if not r:
        raise ValueError("Invalid Qobuz URL")
    return r.group(1), r.group(2)


def get_album_artist(qobuz_album: Dict[str, Any]) -> List[str]:
    """
    Extrai os artistas principais do álbum. Retorna uma lista de strings para
    garantir o suporte nativo a 'Multi-Artist Tagging'.
    """
    try:
        if not qobuz_album.get("artists"):
            single_artist = qobuz_album.get("artist", {}).get("name", "")
            return [single_artist] if single_artist else []

        main_artists = [a["name"] for a in qobuz_album.get("artists", []) if "main-artist" in a.get("roles", [])]
        
        if main_artists:
            return main_artists
            
        single_artist = qobuz_album.get("artist", {}).get("name", "")
        return [single_artist] if single_artist else []
            
    except Exception as e:
        logger.error(f"Error getting album artist: {str(e)}")
        single_artist = qobuz_album.get("artist", {}).get("name", "")
        return [single_artist] if single_artist else []


def apply_legacy_charmap(filename: str) -> str:
    """
    Aplica substituições ASCII clássicas para contornar limitações do Windows,
    em vez de utilizar carateres Unicode 'full-width'.
    """
    replacements = {
        ':': '-', '?': '', '/': '-', '\\': '-', '*': '-',
        '"': "'", '<': '[', '>': ']', '|': '-'
    }
    
    for old, new in replacements.items():
        filename = filename.replace(old, new)
        
    # Limpa duplos traços criados acidentalmente (ex: "A / B" -> "A - B")
    return re.sub(r'\s*-\s*-+', ' -', filename)


def clean_filename(filename: str, legacy_charmap: bool = False) -> str:
    """
    Limpa carateres especiais redundantes e normaliza o Unicode (NFC).
    """
    filename = unicodedata.normalize('NFC', filename)
    
    # Funde múltiplos separadores num só
    filename = re.sub(r'(?:\s*([,\.\:\;\|/\\_])\s*){2,}', r'\1 ', filename)

    patterns = [
        (r'\(\s*\W*\s*\)', ''), (r'\[\s*\W*\s*\]', ''), (r'\{\s*\W*\s*\}', ''),
        (r'<\s*\W*\s*>', ''), (r'《\s*\W*\s*》', ''), (r'〈\s*\W*\s*〉', ''),
        (r'「\s*\W*\s*」', ''), (r'『\s*\W*\s*』', ''), (r'（\s*\W*\s*）', ''),
        (r'［\s*\W*\s*］', ''), (r'【\s*\W*\s*】', ''),
        (r'(?<=[\(\[\{<《〈「『（［【])(\s*[,\.\:\;\|/\\_]\s*)\b', ''),
        (r'\b(\s*[,\.\:\;\|/\\_]\s*)(?=[】］）』」〉》>\}\]\)])', ''),
    ]

    for pattern, replacement in patterns:
        filename = re.sub(pattern, replacement, filename)

    filename = re.sub(r'\s+', ' ', filename).strip().strip(".").strip()
    
    if legacy_charmap:
        return apply_legacy_charmap(filename)
    return invalid_chars_to_fullwidth(filename)


def invalid_chars_to_fullwidth(filename: str) -> str:
    """Substitui carateres inválidos nos ficheiros pelos seus equivalentes Unicode (Full-width)."""
    invalid_to_fullwidth = {
        '/': '／', '\\': '＼', ':': '：', '*': '＊',
        '?': '？', '"': '＂', '<': '＜', '>': '＞', '|': '｜',
    }

    for invalid_char, fullwidth_char in invalid_to_fullwidth.items():
        filename = filename.replace(invalid_char, fullwidth_char)
    return filename

def normalizar_titulo(text0: str) -> str:
    if not texto: return ""
    # Remove acentos para uma comparação perfeita
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    t = re.sub(r'[^\w\s]', ' ', texto)
    return " ".join(t.split()).lower()

async def get_apple_hq_cover(upc: Optional[str] = None, isrc: Optional[str] = None, artist: Optional[str] = None, album: Optional[str] = None) -> Optional[str]:
    import urllib.parse
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
    }

    async with aiohttp.ClientSession(headers=headers) as session:

        # 1. tentativa Exata: UPC (Código de Barras)
        if upc and upc.lower() != "n/a":
            try:
                async with session.get(f"https://itunes.apple.com/lookup?upc={upc}&entity=album", timeout=5) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        if data.get("resultCount", 0) > 0:
                            return data["results"][0]["artworkUrl100"].replace("100x100bb", "10000x10000bb")
            except Exception: pass

        # 2. Tentativa Exata: ISRC (Impressão Digital da Faixa)
        if isrc and isrc.lower() != "n/a":
            try:
                async with session.get(f"https://itunes.apple.com/lookup?isrc={isrc}", timeout=5) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        if data.get("resultCount", 0) > 0:
                            return data["results"][0]["artworkUrl100"].replace("100x100bb", "10000x10000bb")
            except Exception: pass

        # 3. Sistema de Pontuação de Texto (O Cerebro da Comparação)
        if artist and album:
            clean_artist = urllib.parse.quote(artist)
            clean_title = urllib.parse.quote(album)
            query = f"{clean_artist}+{clean_title}"
            
            try:
                # Pedimos 10 resultados para a Apple para termos opções para avaliar
                async with session.get(f"https://itunes.apple.com/search?term={query}&entity=album&limit=10", timeout=5) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        if data.get("resultCount", 0) > 0:
                            qobuz_norm = normalizar_titulo(album)
                            
                            melhor_capa = None
                            maior_score = 0.0
                            
                            for result in data["results"]:
                                apple_title = result.get("collectionName", "")
                                apple_norm = normalizar_titulo(apple_title)
                                
                                # Dá uma nota de compatibilidade entre o que pedimos e o que a Apple ofereceu
                                score = difflib.SequenceMatcher(None, qobuz_norm, apple_norm).ratio()
                                
                                if score > maior_score:
                                    maior_score = score
                                    url_arte = result.get("artworkUrl100", "")
                                    if url_arte:
                                        melhor_capa = url_arte.replace("100x100bb", "10000x10000bb")

                            if maior_score >= 0.80 and melhor_capa:
                                logger.debug(f"Capa aprovada com nota de {(maior_score * 100):.1f}%")
                                return melhor_capa
                            else:
                                logger.debug(f"Capa rejeitada. Maior nota foi de {(maior_score * 100):.1f}%")
            except Exception: pass

        return None