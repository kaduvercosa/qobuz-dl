import re
import os
import logging
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional

from mutagen.flac import FLAC, Picture
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError
from qobuz_dl.settings import QobuzDLSettings
from qobuz_dl.utils import get_album_artist

logger = logging.getLogger(__name__)

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
}

EMB_COVER_NAMES = [
    "embed_cover.jpg",
    "embed_cover.jpeg",
    "embed_cover.png",
    "embed_cover.webp"
]

def _find_cover_image(root_dir: [str, Path]) -> Optional[Path]:
    """Procura a imagem de capa na pasta atual ou na pasta pai."""
    root_path = Path(root_dir).resolve()
    search_dirs = [root_path, root_path.parent]
    
    for directory in search_dirs:
        for cover_name in EMB_COVER_NAMES:
            cover_path = directory / cover_name
            if cover_path.is_file():
                return cover_path
    return None

def _get_cover_info(cover_path: Path) -> str:
    """Extrai as informações de tamanho da capa para os comentários técnicos."""
    try:
        size_mb = cover_path.stat().st_size / (1024 * 1024)
        return f"Cover Quality: _org | Size: {size_mb:.2f} MB"
    except Exception as e:
        logger.warning(f"Não foi possível ler o tamanho da capa: {e}")
        return "Cover Quality: _org"

def _get_title_with_version(title: str = "", version: str = "") -> str:
    item_title = title
    if version:
        item_title = f"{title} ({version})" if version.lower() not in title.lower() else title
    return item_title

def _format_copyright(s: str) -> str:
    if s:
        s = s.replace("(P)", PHON_COPYRIGHT).replace("(C)", COPYRIGHT)
    return s

def _format_genres(genres: list) -> str:
    """Extrai os géneros e remove duplicados mantendo a ordem original."""
    genres_flat = re.findall(r"([^\u2192\/]+)", "/".join(genres))
    no_repeats = list(dict.fromkeys(g.strip() for g in genres_flat))
    return ", ".join(no_repeats)

def _embed_flac_img(cover_image: Path, audio: FLAC) -> None:
    try:
        if cover_image.stat().st_size > FLAC_MAX_BLOCKSIZE:
            size_mb = cover_image.stat().st_size / (1024 * 1024)
            logger.info(f"[!] Capa Original ({size_mb:.2f} MB) excedeu o limite do FLAC. Pulando embed..")
            return

        image = Picture()
        image.type = 3
        mime_type, _ = mimetypes.guess_type(str(cover_image))
        image.mime = mime_type or "image/jpeg"
        image.desc = "cover"
        
        with open(cover_image, "rb") as img:
            image.data = img.read()
            
        audio.add_picture(image)
    except Exception as e:
        logger.error(f"Error embedding image: {e}", exc_info=True)

def _embed_id3_img(cover_image: Path, audio: id3.ID3) -> None:
    with open(cover_image, "rb") as cover:
        mime_type, _ = mimetypes.guess_type(str(cover_image))
        audio.add(id3.APIC(encoding=3, mime=mime_type or "image/jpeg", type=3, desc="Cover", data=cover.read()))

def tag_flac(filename: str, root_dir: str, final_name: str, d: dict, album: dict, istrack: bool = True, em_image: bool = False, settings: QobuzDLSettings = None):
    audio = FLAC(filename)
    qobuz_item = d
    qobuz_album = d.get("album", {}) if istrack else album

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
            
            # Puxa a info primeiro, e SÓ DEPOIS injeta no comentário
            cover_info = _get_cover_info(cover_path)
            tags["COMMENT"] = f"{tech_comment}\n{cover_info}" if tech_comment else cover_info

    for k, v in tags.items():
        if v:
            audio[k] = v

    audio.save()
    Path(filename).rename(final_name)

def tag_mp3(filename: str, root_dir: str, final_name: str, d: dict, album: dict, istrack: bool = True, em_image: bool = False, settings: QobuzDLSettings = None):
    try:
        audio = id3.ID3(filename)
    except ID3NoHeaderError:
        audio = id3.ID3()
        
    qobuz_item = d
    qobuz_album = d.get("album", {}) if istrack else album

    tags = _get_tags_to_add(qobuz_album, qobuz_item, settings=settings)
    tech_comment = tags.get("COMMENT", "")
    
    if em_image:
        cover_path = _find_cover_image(root_dir)
        if cover_path:
            _embed_id3_img(cover_path, audio)
            
            # Puxa a info primeiro, e SÓ DEPOIS injeta no comentário
            cover_info = _get_cover_info(cover_path)
            tags["COMMENT"] = f"{tech_comment}\n{cover_info}" if tech_comment else cover_info

    for k, v in tags.items():
        if v:
            id3tag = ID3_LEGEND.get(k.lower()) or ID3_LEGEND.get(k)
            if id3tag:
                if id3tag == id3.TXXX:
                    audio.add(id3tag(encoding=3, desc=k, text=v))
                elif id3tag == id3.COMM:
                    audio.add(id3tag(encoding=3, lang='eng', desc='', text=[v]))
                else:
                    audio[id3tag.__name__] = id3tag(encoding=3, text=v)

    audio["TRCK"] = id3.TRCK(encoding=3, text=f'{str(qobuz_item.get("track_number", "1"))}/{str(qobuz_album.get("tracks_count", "1"))}')
    audio["TPOS"] = id3.TPOS(encoding=3, text=f'{str(qobuz_item.get("media_number", "1"))}/{str(qobuz_album.get("media_count", "1"))}')
        
    audio.save(filename, v2_version=3)
    Path(filename).rename(final_name)

def _get_tags_to_add(qobuz_album: dict, qobuz_item: dict, settings: QobuzDLSettings = None) -> Dict[str, Any]:
    tags = {}
    if not qobuz_album or not qobuz_item:
        return tags

    if not settings.no_album_title_tag:
        tags["ALBUM"] = _get_title_with_version(title=qobuz_album.get("title", ""), version=qobuz_album.get("version", ""))
    if not settings.no_track_title_tag:
        tags["TITLE"] = _get_title_with_version(title=qobuz_item.get("title", ""), version=qobuz_item.get("version", ""))

    if not settings.no_album_artist_tag:
        album_artist_name = get_album_artist(qobuz_album)
        nome_generico = ["Various Artists"]

        if album_artist_name in nome_generico:
            performer_singular = qobuz_item.get("performer")

            if performer_singular and isinstance(performer_singular, dict):
                tags["ALBUMARTIST"] = performer_singular.get("name", "").strip()
            elif performer_singular and isinstance(performer_singular, str):
                tags["ALBUMARTIST"] = performer_singular.strip()
            else:
                tags["ALBUMARTIST"] = album_artist_name
        else:
            tags["ALBUMARTIST"] = album_artist_name


    # --- EXTRATOR ABSOLUTAMENTE ESTRITO DE PERFORMERS ---
    artists = []
    conductors = []
    ensembles = []

    performers_data = qobuz_item.get("performers", [])
    
    target_roles = ["mainartist", "main artist", "performedartist", "performed artist"]
    
    if isinstance(performers_data, list) and performers_data:
        for p in performers_data:
            if not isinstance(p, dict): continue
            name = p.get("name", "").strip()
            if not name: continue
            
            roles_str = str(p.get("roles", [])).lower()
            
            if any(role in roles_str for role in target_roles):
                if name not in artists: artists.append(name)
                
            if "conductor" in roles_str:
                if name not in conductors: conductors.append(name)
            if any(role in roles_str for role in ["orchestra", "ensemble", "choir"]):
                if name not in ensembles: ensembles.append(name)

    elif isinstance(performers_data, str) and performers_data.strip():
        for performer_block in performers_data.split(" - "):
            parts = [p.strip() for p in performer_block.split(",")]
            if not parts: continue
            
            name = parts[0]
            roles_str = "".join(parts[1:]).lower()

            if roles_str:
                if any(role in roles_str for role in target_roles):
                    if name not in artists: artists.append(name)
                if "conductor" in roles_str:
                    if name not in conductors: conductors.append(name)
                if any(role in roles_str for role in ["orchestra", "ensemble", "choir"]):
                    if name not in ensembles: ensembles.append(name)

    artists = list(dict.fromkeys(artists))
    conductors = list(dict.fromkeys(conductors))
    ensembles = list(dict.fromkeys(ensembles))

    if not settings.no_track_artist_tag and artists:
        tags["ARTIST"] = ", ".join(artists)
 

    if conductors:
        tags["CONDUCTOR"] = ", ".join(conductors)
    if ensembles:
        tags["ENSEMBLE"] = ", ".join(ensembles)

    if not settings.no_composer_tag:
        tags["COMPOSER"] = qobuz_item.get("composer", {}).get("name", "")

    release_date = qobuz_album.get("release_date_original", "")
    if not settings.no_release_date_tag:
        tags["DATE"] = release_date
        tags["YEAR"] = release_date[:4] if release_date else ""

    if not settings.no_genre_tag:
        tags["GENRE"] = _format_genres(qobuz_album.get("genres_list", []))
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

    tags["BITDEPTH"] = str(qobuz_item.get("maximum_bit_depth", "16"))
    tags["SAMPLERATE"] = str(qobuz_item.get("maximum_sampling_rate", "44.1"))

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
    bit_depth = qobuz_item.get("maximum_bit_depth", "16")
    sampling_rate = qobuz_item.get("maximum_sampling_rate", "44.1")
    hires_tag = "Hi-Res " if int(bit_depth) >= 24 else "CD-Quality "

    comments = [
        f"Source: Qobuz",
        f"Track ID: {qobuz_id} | Album ID: {album_id}",
        f"Quality: {hires_tag}{bit_depth}-bit / {sampling_rate} kHz",
    ]
    if album_url:
        comments.append(f"URL: {album_url}")

    tags["COMMENT"] = "\n".join(comments)

    work = qobuz_item.get("work")
    if work:
        tags["WORK"] = work

    track_id = qobuz_item.get("id")
    if track_id:
        tags["QOBUZTRACKID"] = str(track_id)
    album_id = qobuz_album.get("id")
    if album_id:
        tags["QOBUZALBUMID"] = str(album_id)

    return tags