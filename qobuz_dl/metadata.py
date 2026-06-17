import re
import os
import logging
import mimetypes
import shutil
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, TypedDict
from functools import lru_cache

from mutagen.flac import FLAC, Picture
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError

from qobuz_dl.settings import QobuzDLSettings
from qobuz_dl.utils import get_album_artist

logger = logging.getLogger(__name__)

# ─── Estruturas de Dados da API do Qobuz ──────────────────────────────────────
class QobuzAlbum(TypedDict, total=False):
    id: str
    title: str
    version: Optional[str]
    release_date_original: str
    tracks_count: int
    media_count: int
    copyright: str
    label: Dict[str, Any]
    upc: str
    product_type: str
    parental_warning: bool
    genres_list: List[str]
    artists: List[Dict[str, Any]]
    artist: Dict[str, Any]
    url: str

class QobuzItem(TypedDict, total=False):
    id: str
    title: str
    version: Optional[str]
    track_number: int
    media_number: int
    isrc: str
    actual_bit_depth: int
    actual_sampling_rate: float
    maximum_bit_depth: int
    maximum_sampling_rate: float
    duration: int
    performer: Dict[str, Any]
    performers: Union[str, List[Dict[str, Any]]]
    composer: Dict[str, Any]
    audio_info: Dict[str, Any]
    work: Optional[str]
    album: QobuzAlbum

# ─── Constantes Globais ────────────────────────────────────────────────────────
COPYRIGHT, PHON_COPYRIGHT = "\u2117", "\u00a9"
FLAC_MAX_BLOCKSIZE = 16777215

ID3_LEGEND = {
    "albumartist": id3.TPE2,
    "album": id3.TALB,
    "artist": id3.TPE1,
    "title": id3.TIT2,
    "date": id3.TDAT,
    "mediatype": id3.TMED,
    "genre": id3.TCON,
    "composer": id3.TCOM,
    "itunesadvisory": id3.TXXX,
    "copyright": id3.TCOP,
    "label": id3.TPUB,
    "barcode": id3.TXXX,
    "isrc": id3.TSRC,
    "comment": id3.COMM,
    "year": id3.TYER,
    "performer": id3.TOPE,
    "QOBUZTRACKID": id3.TXXX,
    "QOBUZALBUMID": id3.TXXX,
    "replaygain_track_gain": id3.TXXX,
    "replaygain_track_peak": id3.TXXX,
    "conductor": id3.TPE3,
    "ensemble": id3.TXXX,
    "work": id3.TIT1,
    # [FIX] bitdepth/samplerate eram gravados no dict de tags
    # (tags["BITDEPTH"]/tags["SAMPLERATE"] em _get_tags_to_add) mas não
    # existiam aqui. Resultado: no FLAC funcionava normal (lá não passa por
    # esse dict de legendas, qualquer chave vira Vorbis Comment direto), mas
    # em todo arquivo MP3 essas duas tags eram descartadas em silêncio no
    # loop de tag_mp3() -- nenhum erro, nenhum aviso, só desapareciam.
    # Mapeadas pra TXXX (campo customizado), igual outras infos técnicas
    # já existentes aqui (QOBUZTRACKID, barcode, etc).
    "bitdepth": id3.TXXX,
    "samplerate": id3.TXXX,
}

EMB_COVER_NAMES = [
    "embed_cover.jpg",
    "embed_cover.jpeg",
    "embed_cover.png",
    "embed_cover.webp"
]

# ─── Funções Auxiliares ────────────────────────────────────────────────────────
def _find_cover_image(root_dir: Union[str, Path]) -> Optional[Path]:
    root_path = Path(root_dir).resolve()
    search_dirs = [root_path, root_path.parent]
    
    for directory in search_dirs:
        for cover_name in EMB_COVER_NAMES:
            cover_path = directory / cover_name
            if cover_path.is_file():
                return cover_path
    return None

# O PULO DO GATO: Memoriza a resolução da capa para não ler o disco a cada faixa
@lru_cache(maxsize=10)
def _get_cover_info(cover_path: Path) -> str:
    try:
        size_mb = cover_path.stat().st_size / (1024 * 1024)
        try:
            from PIL import Image
            with Image.open(cover_path) as img:
                width, height = img.size
                return f"Cover: {width}x{height}px ({size_mb:.2f} MB)"
        except ImportError:
            return f"Cover: Original ({size_mb:.2f} MB)"
        except Exception:
            return f"Cover: Original ({size_mb:.2f} MB)"
    except Exception:
        return "Cover: Original"

def _get_title_with_version(title: str = "", version: Optional[str] = "") -> str:
    item_title = title
    if version:
        item_title = f"{title} ({version})" if version.lower() not in title.lower() else title
    return item_title

def _format_copyright(s: str) -> str:
    if s:
        s = s.replace("(P)", PHON_COPYRIGHT).replace("(C)", COPYRIGHT)
    return s

def _format_genres(genres: List[str]) -> str:
    genres_flat = re.findall(r"([^\u2192\/]+)", "/".join(genres))
    no_repeats = list(dict.fromkeys(g.strip() for g in genres_flat))
    return ", ".join(no_repeats)

def _embed_flac_img(cover_image: Path, audio: FLAC) -> None:
    try:
        if cover_image.stat().st_size > FLAC_MAX_BLOCKSIZE:
            return
        image = Picture()
        image.type = 3
        mime_type, _ = mimetypes.guess_type(str(cover_image))
        image.mime = mime_type or "image/jpeg"
        image.desc = "cover"
        with open(cover_image, "rb") as img:
            image.data = img.read()
        audio.add_picture(image)
    except Exception:
        pass

def _embed_id3_img(cover_image: Path, audio: id3.ID3) -> None:
    with open(cover_image, "rb") as cover:
        mime_type, _ = mimetypes.guess_type(str(cover_image))
        audio.add(id3.APIC(encoding=3, mime=mime_type or "image/jpeg", type=3, desc="Cover", data=cover.read()))

# ─── Funções Principais de Tagging ───────────────────────────────────────────
def tag_flac(filename: str, root_dir: Union[str, Path], final_name: str, d: QobuzItem, album: QobuzAlbum, istrack: bool = True, em_image: bool = False, settings: Optional[QobuzDLSettings] = None) -> None:
    if settings is None:
        settings = QobuzDLSettings()
        
    audio = FLAC(filename)
    qobuz_item = d
    qobuz_album = d.get("album", album) if istrack else album

    tags = _get_tags_to_add(qobuz_album, qobuz_item, settings=settings)

    if not settings.no_track_number_tag:
        tags["TRACKNUMBER"] = str(qobuz_item.get("track_number", "1"))
    if not settings.no_track_total_tag:
        tags["TRACKTOTAL"] = str(qobuz_album.get("tracks_count", "1"))
    if not settings.no_disc_number_tag:
        tags["DISCNUMBER"] = str(qobuz_item.get("media_number", "1"))
    if not settings.no_disc_total_tag:
        tags["DISCTOTAL"] = str(qobuz_album.get("media_count", "1"))

    tech_comment = tags.get("COMMENT", "")

    if em_image:
        cover_path = _find_cover_image(root_dir)
        if cover_path:
            _embed_flac_img(cover_path, audio)
            cover_info = _get_cover_info(cover_path)
            tags["COMMENT"] = f"{tech_comment}\n{cover_info}" if tech_comment else cover_info

    for k, v in tags.items():
        if v:
            if isinstance(v, list):
                audio[k] = [str(i) for i in v]
            else:
                audio[k] = str(v)

    audio.save()

    # Cofre de tentativas (Micro-pausas para não congelar as outras threads no asyncio)
    for _ in range(15):
        try:
            shutil.move(filename, final_name)
            return
        except Exception:
            time.sleep(0.1) 
    
    try:
        os.rename(filename, final_name)
    except OSError as e:
        # [FIX] Antes essa falha desaparecia 100% em silêncio (except OSError:
        # pass): o download "parecia" concluído com sucesso, mas o arquivo
        # final podia nem existir no destino (disco cheio, permissão, path
        # longo demais, etc). Mantemos o comportamento de não derrubar o
        # loop do downloader, mas agora pelo menos fica registrado no log
        # pra dar pra investigar depois.
        logger.error(f"Falha ao mover/renomear arquivo final '{filename}' -> '{final_name}': {e}")

def tag_mp3(filename: str, root_dir: Union[str, Path], final_name: str, d: QobuzItem, album: QobuzAlbum, istrack: bool = True, em_image: bool = False, settings: Optional[QobuzDLSettings] = None) -> None:
    if settings is None:
        settings = QobuzDLSettings()
        
    try:
        audio = id3.ID3(filename)
    except ID3NoHeaderError:
        audio = id3.ID3()
        
    qobuz_item = d
    qobuz_album = d.get("album", album) if istrack else album

    tags = _get_tags_to_add(qobuz_album, qobuz_item, settings=settings)
    tech_comment = tags.get("COMMENT", "")
    
    if em_image:
        cover_path = _find_cover_image(root_dir)
        if cover_path:
            _embed_id3_img(cover_path, audio)
            cover_info = _get_cover_info(cover_path)
            tags["COMMENT"] = f"{tech_comment}\n{cover_info}" if tech_comment else cover_info

    for k, v in tags.items():
        if v:
            id3tag = ID3_LEGEND.get(k.lower()) or ID3_LEGEND.get(k)
            if id3tag:
                if id3tag == id3.TXXX:
                    audio.add(id3tag(encoding=3, desc=k, text=v))
                elif id3tag == id3.COMM:
                    audio.add(id3tag(encoding=3, lang='eng', desc='', text=[v] if isinstance(v, str) else v))
                elif id3tag == id3.TDAT:
                    # [FIX] TDAT no ID3v2.3 é, por spec, só DDMM (dia+mês,
                    # 4 dígitos) -- não uma data ISO completa. Antes a string
                    # inteira (ex.: "2024-05-01") era jogada direto nesse
                    # frame, fora do spec (a maioria dos players é tolerante
                    # e ignora isso, mas é tecnicamente incorreto).
                    # Continuamos guardando a data completa normalmente em
                    # DATE pro FLAC (Vorbis aceita ISO sem problema) -- esse
                    # reformatação é só pro frame TDAT específico do MP3.
                    # O ano continua coberto separadamente pelo frame TYER.
                    date_str = v if isinstance(v, str) else (v[0] if v else "")
                    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
                    if m:
                        audio["TDAT"] = id3tag(encoding=3, text=[f"{m.group(3)}{m.group(2)}"])
                else:
                    audio[id3tag.__name__] = id3tag(encoding=3, text=[v] if isinstance(v, str) else v)

    audio["TRCK"] = id3.TRCK(encoding=3, text=f'{str(qobuz_item.get("track_number", "1"))}/{str(qobuz_album.get("tracks_count", "1"))}')
    audio["TPOS"] = id3.TPOS(encoding=3, text=f'{str(qobuz_item.get("media_number", "1"))}/{str(qobuz_album.get("media_count", "1"))}')
        
    audio.save(filename, v2_version=3)

    # Cofre de tentativas (Micro-pausas para não congelar as outras threads no asyncio)
    for _ in range(15):
        try:
            shutil.move(filename, final_name)
            return
        except Exception:
            time.sleep(0.1)
            
    try:
        os.rename(filename, final_name)
    except OSError as e:
        # [FIX] Mesmo motivo do tag_flac() acima: agora registra no log em
        # vez de falhar 100% em silêncio.
        logger.error(f"Falha ao mover/renomear arquivo final '{filename}' -> '{final_name}': {e}")

def _get_tags_to_add(qobuz_album: QobuzAlbum, qobuz_item: QobuzItem, settings: Optional[QobuzDLSettings] = None) -> Dict[str, Any]:
    if settings is None:
        settings = QobuzDLSettings()
        
    tags: Dict[str, Any] = {}
    if not qobuz_album or not qobuz_item:
        return tags

    if not settings.no_album_title_tag:
        tags["ALBUM"] = _get_title_with_version(title=qobuz_album.get("title", ""), version=qobuz_album.get("version", ""))
    if not settings.no_track_title_tag:
        tags["TITLE"] = _get_title_with_version(title=qobuz_item.get("title", ""), version=qobuz_item.get("version", ""))

    album_artist_raw = get_album_artist(qobuz_album)
    album_artist_name = album_artist_raw if isinstance(album_artist_raw, list) else str(album_artist_raw)

    artists: List[str] = []
    conductors: List[str] = []
    ensembles: List[str] = []
    composers: List[str] = []

    main_art_raw = qobuz_item.get("performer", {}).get("name") or qobuz_item.get("artist", {}).get("name", "")
    if main_art_raw:
        splits = re.split(r'(?i)\s*,\s*|\s+&\s+|\s+feat\.?\s+|\s+ft\.?\s+|\s*/\s+|\s+with\s+|\s+x\s+', main_art_raw)
        for s in splits:
            if s.strip() and s.strip() not in artists:
                artists.append(s.strip())

    performers_data = qobuz_item.get("performers", "")
    target_roles = ["mainartist", "main artist", "performedartist", "performed artist", "featuredartist", "featured artist", "guestartist", "guest artist", "remixer"]
    
    if isinstance(performers_data, str) and performers_data.strip():
        blocks = re.split(r'\r?\n|\s+-\s+', performers_data.strip())
        for block in blocks:
            if not block.strip(): continue
            
            parts = [p.strip() for p in block.split(",")]
            if not parts: continue
            
            name = parts[0]
            roles_str = "".join(parts[1:]).lower().replace(" ", "")
            
            if any(tr.replace(" ", "") in name.lower().replace(" ", "") for tr in target_roles):
                name = parts[-1]
                roles_str = "".join(parts[:-1]).lower().replace(" ", "")
                
            if roles_str:
                if any(tr.replace(" ", "") in roles_str for tr in target_roles):
                    if name not in artists: artists.append(name)
                if "conductor" in roles_str:
                    if name not in conductors: conductors.append(name)
                if "orchestra" in roles_str or "ensemble" in roles_str or "choir" in roles_str:
                    if name not in ensembles: ensembles.append(name)
                if "composer" in roles_str:
                    if name not in composers: composers.append(name)
            else:
                if name not in artists: artists.append(name)

    elif isinstance(performers_data, list):
        for p in performers_data:
            if not isinstance(p, dict): continue
            name = p.get("name", "").strip()
            roles_str = str(p.get("roles", [])).lower().replace(" ", "")
            if any(tr.replace(" ", "") in roles_str for tr in target_roles):
                if name not in artists: artists.append(name)
            if "conductor" in roles_str:
                if name not in conductors: conductors.append(name)
            if "orchestra" in roles_str or "ensemble" in roles_str:
                if name not in ensembles: ensembles.append(name)
            if "composer" in roles_str:
                if name not in composers: composers.append(name)

    clean_artists: List[str] = []
    seen = set()
    for a in artists:
        if a.lower() not in seen:
            seen.add(a.lower())
            clean_artists.append(a)

    if "Various Artists" in album_artist_name:
        new_aa = clean_artists[0] if clean_artists else qobuz_item.get("artist", {}).get("name", "").strip()
        tags["ALBUMARTIST"] = new_aa if new_aa else album_artist_name
    else:
        tags["ALBUMARTIST"] = album_artist_name

    if not settings.no_track_artist_tag and clean_artists:
        if getattr(settings, 'multi_value_tags', False):
            tags["ARTIST"] = clean_artists 
        else:
            tags["ARTIST"] = ", ".join(clean_artists)

    if conductors:
        tags["CONDUCTOR"] = conductors if getattr(settings, 'multi_value_tags', False) else ", ".join(conductors)
    if ensembles:
        tags["ENSEMBLE"] = ensembles if getattr(settings, 'multi_value_tags', False) else ", ".join(ensembles)

    if not settings.no_composer_tag:
        api_composer = qobuz_item.get("composer", {}).get("name", "")
        if composers:
            if api_composer and api_composer not in composers:
                composers.insert(0, api_composer)
            tags["COMPOSER"] = composers if getattr(settings, 'multi_value_tags', False) else ", ".join(composers)
        elif api_composer:
            if getattr(settings, 'multi_value_tags', False):
                tags["COMPOSER"] = [c.strip() for c in re.split(r'(?i)\s*,\s*|\s+&\s+|\s+and\s+', api_composer) if c.strip()]
            else:
                tags["COMPOSER"] = api_composer

    release_date = qobuz_album.get("release_date_original", "")
    if not settings.no_release_date_tag:
        tags["DATE"] = release_date
        tags["YEAR"] = release_date[:4] if release_date else ""

    if not settings.no_genre_tag:
        genres_list = qobuz_album.get("genres_list", [])
        if getattr(settings, 'multi_value_tags', False):
            genres_flat = re.findall(r"([^\u2192\/]+)", "/".join(genres_list))
            tags["GENRE"] = list(dict.fromkeys(g.strip() for g in genres_flat))
        else:
            tags["GENRE"] = _format_genres(genres_list)

    if not settings.no_copyright_tag:
        tags["COPYRIGHT"] = _format_copyright(qobuz_album.get("copyright", "n/a"))
    if not settings.no_label_tag:
        tags["LABEL"] = re.sub(r'\s+', ' ', qobuz_album.get("label", {}).get("name", ""))
    if not settings.no_isrc_tag:
        tags["ISRC"] = qobuz_item.get("isrc", "")
    if not settings.no_upc_tag:
        tags["BARCODE"] = qobuz_album.get("upc", "")
    if not settings.no_media_type_tag:
        tags["MEDIATYPE"] = qobuz_album.get("product_type", "").upper()
    if not settings.no_explicit_tag:
        tags["ITUNESADVISORY"] = "1" if qobuz_album.get("parental_warning", False) else "0"

    # INJEÇÃO DA QUALIDADE REAL DOWNLOADADA
    actual_bd = qobuz_item.get("actual_bit_depth")
    actual_sr = qobuz_item.get("actual_sampling_rate")
    
    bit_depth = str(actual_bd) if actual_bd else str(qobuz_item.get("maximum_bit_depth", "16"))
    sampling_rate = str(actual_sr) if actual_sr else str(qobuz_item.get("maximum_sampling_rate", "44.1"))

    tags["BITDEPTH"] = bit_depth
    tags["SAMPLERATE"] = sampling_rate

    audio_info = qobuz_item.get("audio_info", {})
    if audio_info:
        rg_gain = audio_info.get("replaygain_track_gain")
        rg_peak = audio_info.get("replaygain_track_peak")
        if rg_gain is not None:
            tags["REPLAYGAIN_TRACK_GAIN"] = f"{rg_gain} dB"
        if rg_peak is not None:
            tags["REPLAYGAIN_TRACK_PEAK"] = str(rg_peak)

    qobuz_id = qobuz_item.get("id", "")
    album_id = qobuz_album.get("id", "")
    album_url = qobuz_album.get("url", "")
    hires_tag = "Hi-Res " if int(float(bit_depth)) >= 24 else "CD-Quality "

    comments = [
        f"Source: Qobuz",
        f"Track ID: {qobuz_id} | Album ID: {album_id}",
        f"Quality: {hires_tag}{bit_depth}-bit / {sampling_rate} kHz",
    ]
    if album_url:
        comments.append(f"URL: {album_url}")

    tags["COMMENT"] = "\n".join(comments)
    tags["WORK"] = qobuz_item.get("work") if qobuz_item.get("work") else ""
    tags["QOBUZTRACKID"] = str(qobuz_item.get("id", ""))
    tags["QOBUZALBUMID"] = str(qobuz_album.get("id", ""))

    return {k: v for k, v in tags.items() if v}