import re
import os
import logging
import mimetypes

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

def _find_cover_image(root_dir):
    search_dirs = [root_dir, os.path.abspath(os.path.join(root_dir, os.pardir))]
    for directory in search_dirs:
        for cover_name in EMB_COVER_NAMES:
            cover_path = os.path.join(directory, cover_name)
            if os.path.isfile(cover_path):
                return cover_path
    return None

def _get_title_with_version(title: str = "", version: str = "") -> str:
    item_title = title
    if version:
        item_title = f"{title} ({version})" if version.lower() not in title.lower() else title
    return item_title

def _get_title(track_dict):
    title = track_dict["title"]
    version = track_dict.get("version")
    if version:
        title = f"{title} ({version})"
    if track_dict.get("work"):
        title = f"{track_dict['work']}: {title}"
    return title

def _format_copyright(s: str) -> str:
    if s:
        s = s.replace("(P)", PHON_COPYRIGHT)
        s = s.replace("(C)", COPYRIGHT)
    return s

def _format_genres(genres: list) -> str:
    genres = re.findall(r"([^\u2192\/]+)", "/".join(genres))
    no_repeats = []
    [no_repeats.append(g) for g in genres if g not in no_repeats]
    return ", ".join(no_repeats)

def _embed_flac_img(root_dir, audio: FLAC):
    cover_image = _find_cover_image(root_dir)
    if not cover_image:
        logger.debug("Cover image not found to embed")
        return
    try:
        if os.path.getsize(cover_image) > FLAC_MAX_BLOCKSIZE:
            raise Exception("downloaded cover size too large to embed. turn off `og_cover` to avoid error")
        image = Picture()
        image.type = 3
        mime_type, _ = mimetypes.guess_type(cover_image)
        image.mime = mime_type or "image/jpeg"
        image.desc = "cover"
        with open(cover_image, "rb") as img:
            image.data = img.read()
        audio.add_picture(image)
    except Exception as e:
        logger.error(f"Error embedding image: {e}", exc_info=True)

def _embed_id3_img(root_dir, audio: id3.ID3):
    cover_image = _find_cover_image(root_dir)
    if not cover_image:
        logger.debug("Cover image not found to embed")
        return
    with open(cover_image, "rb") as cover:
        mime_type, _ = mimetypes.guess_type(cover_image)
        audio.add(id3.APIC(encoding=3, mime=mime_type or "image/jpeg", type=3, desc="Cover", data=cover.read()))

def tag_flac(filename, root_dir, final_name, d: dict, album, istrack=True, em_image=False, settings: QobuzDLSettings = None):
    audio = FLAC(filename)
    if istrack:
        qobuz_item = d
        qobuz_album = d.get("album", {})
    else:
        qobuz_item = d
        qobuz_album = album

    tags = _get_tags_to_add(qobuz_album, qobuz_item, settings=settings)

    if not settings.no_track_number_tag:
        tags["TRACKNUMBER"] = str(qobuz_item.get("track_number", "1"))
    if not settings.no_track_total_tag:
        tags["TRACKTOTAL"] = str(qobuz_album.get("tracks_count", "1"))
    if not settings.no_disc_number_tag:
        tags["DISCNUMBER"] = str(qobuz_item.get("media_number", "1"))
    if not settings.no_disc_total_tag:
        tags["DISCTOTAL"] = str(qobuz_album.get("media_count", "1"))

    for k, v in tags.items():
        if v:
            audio[k] = v
            
    if em_image:
        _embed_flac_img(root_dir, audio)
        
        # --- INJEÇÃO DAS INFOS DA CAPA NA TAG DE COMENTÁRIO (SEM PILLOW) ---
        cover_path = _find_cover_image(root_dir)
        if cover_path:
            try:
                size_mb = os.path.getsize(cover_path) / (1024 * 1024)
                cover_info = f"Cover Quality: _org | Size: {size_mb:.2f} MB"
            except Exception as e:
                logger.warning(f"Não foi possível ler o tamanho da capa: {e}")
                cover_info = "Cover Quality: _org"
            
            audio["comment"] = cover_info
        # -------------------------------------------------------------------

    audio.save()
    os.rename(filename, final_name)

def tag_mp3(filename, root_dir, final_name, d, album, istrack=True, em_image=False, settings: QobuzDLSettings = None):
    try:
        audio = id3.ID3(filename)
    except ID3NoHeaderError:
        audio = id3.ID3()
    if istrack:
        qobuz_item = d
        qobuz_album = d.get("album", {})
    else:
        qobuz_item = d
        qobuz_album = album

    tags = _get_tags_to_add(qobuz_album, qobuz_item, settings=settings)

    for k, v in tags.items():
        if v:
            id3tag = ID3_LEGEND.get(k.lower()) or ID3_LEGEND.get(k)
            if id3tag:
                if id3tag == id3.TXXX:
                    audio.add(id3tag(encoding=3, desc=k, text=v))
                else:
                    audio[id3tag.__name__] = id3tag(encoding=3, text=v)

    audio["TRCK"] = id3.TRCK(encoding=3, text=f'{str(qobuz_item.get("track_number", "1"))}/{str(qobuz_album.get("tracks_count", "1"))}')
    audio["TPOS"] = id3.TPOS(encoding=3, text=f'{str(qobuz_item.get("media_number", "1"))}/{str(qobuz_album.get("media_count", "1"))}')
    
    if em_image:
        _embed_id3_img(root_dir, audio)
        
        # --- INJEÇÃO DAS INFOS DA CAPA NA TAG DE COMENTÁRIO (SEM PILLOW) ---
        cover_path = _find_cover_image(root_dir)
        if cover_path:
            try:
                size_mb = os.path.getsize(cover_path) / (1024 * 1024)
                cover_info = f"Cover Quality: _org | Size: {size_mb:.2f} MB"
            except Exception as e:
                logger.warning(f"Não foi possível ler o tamanho da capa: {e}")
                cover_info = "Cover Quality: _org"
            
            # Adiciona o comentário específico para MP3 (ID3v2 COMM tag)
            audio.add(id3.COMM(encoding=3, lang='eng', desc='CoverInfo', text=[cover_info]))
        # -------------------------------------------------------------------
        
    audio.save(filename, v2_version=3)
    os.rename(filename, final_name)

def _get_tags_to_add(qobuz_album: dict, qobuz_item: dict, settings: QobuzDLSettings = None):
    tags = dict()
    if not qobuz_album or not qobuz_item:
        return tags

    if not settings.no_album_title_tag:
        tags["ALBUM"] = _get_title_with_version(title=qobuz_album.get("title", ""), version=qobuz_album.get("version", ""))
    if not settings.no_track_title_tag:
        tags["TITLE"] = _get_title_with_version(title=qobuz_item.get("title", ""), version=qobuz_item.get("version", ""))

    if not settings.no_album_artist_tag:
        tags["ALBUMARTIST"] = get_album_artist(qobuz_album)

    if not settings.no_track_artist_tag:
        artists = []
        performers_str = qobuz_item.get("performers", "")
        if performers_str:
            for i in performers_str.split(" - "):
                if "MainArtist" in i or "FeaturedArtist" in i:
                    name = i.split(",")[0].strip()
                    if name not in artists:
                        artists.append(name)
        if artists:
            artists = [", ".join(artists)]
        else:
            main_artist = qobuz_item.get("performer", {}).get("name", "") or qobuz_album.get("artist", {}).get("name", "")
            artists = [main_artist] if main_artist else []

        if len(artists) == 1:
            tags["ARTIST"] = artists[0]
        elif len(artists) > 1:
            tags["ARTIST"] = artists
        else:
            tags["ARTIST"] = ""

    if not settings.no_composer_tag:
        tags["COMPOSER"] = qobuz_item.get("composer", {}).get("name", "")

    release_date = qobuz_album.get("release_date_original", "")
    if not settings.no_release_date_tag:
        tags["DATE"] = release_date
        tags["YEAR"] = release_date[:4] if release_date else ""

    if not settings.no_genre_tag:
        tags["GENRE"] = _format_genres(qobuz_album.get("genres_list", []))
    if not settings.no_label_tag:
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

    # --- AUDIOPHILE RESOLUTION TAGS ---
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

    work = qobuz_item.get("work")
    if work:
        tags["WORK"] = work

    conductors = []
    ensembles = []
    performers_str = qobuz_item.get("performers", "")
    if performers_str:
        for performer_block in performers_str.split(" - "):
            parts = [p.strip() for p in performer_block.split(", ")]
            if len(parts) > 1:
                name = parts[0]
                roles = parts[1:]
                if "Conductor" in roles:
                    conductors.append(name)
                if any(role in roles for role in ["Orchestra", "Ensemble", "Choir"]):
                    ensembles.append(name)

    if conductors:
        tags["CONDUCTOR"] = conductors if len(conductors) > 1 else conductors[0]
    if ensembles:
        tags["ENSEMBLE"] = ensembles if len(ensembles) > 1 else ensembles[0]

    track_id = qobuz_item.get("id")
    if track_id:
        tags["QOBUZTRACKID"] = str(track_id)
    album_id = qobuz_album.get("id")
    if album_id:
        tags["QOBUZALBUMID"] = str(album_id)

    return tags