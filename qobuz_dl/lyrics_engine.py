import os
import re
import logging
import requests
import mutagen

from dataclasses import dataclass
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from mutagen.id3 import ID3, USLT, ID3NoHeaderError
from mutagen.flac import FLAC

from deep_translator import GoogleTranslator
from langdetect import detect

# =========================================================
# CONFIG
# =========================================================

LRCLIB_URL = "https://lrclib.net/api/get"
REQUEST_TIMEOUT = 12

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"
)

logger = logging.getLogger("LyricsEngine")

# =========================================================
# OPTIONAL GENIUS IMPORT
# =========================================================

try:
    import lyricsgenius
except ImportError:
    lyricsgenius = None

# =========================================================
# DATA MODEL
# =========================================================

@dataclass
class LyricsResult:
    synced: bool
    lyrics: str
    source: str

# =========================================================
# TEXT CLEANER
# =========================================================

class TextCleaner:

    @staticmethod
    def clean_search_term(text: str) -> str:

        if not text:
            return ""

        # Remove tudo após " - "
        text = text.split(" - ")[0]

        # Remove feat/remaster/etc
        text = re.sub(
            r'(?i)\s*[\(\[][^\)\]]*(remaster|feat|mix|version|edit|mono|stereo)[\)\]]',
            '',
            text
        )

        return text.strip()

    # -----------------------------------------------------

    @staticmethod
    def clean_genius_lyrics(text: str) -> str:

        if not text:
            return ""

        text = re.sub(r'\d*Embed$', '', text)
        text = re.sub(r'EmbedShare URLCopyEmbedCopy$', '', text)

        return text.strip()

# =========================================================
# LANGUAGE
# =========================================================

class LanguageHelper:

    LANG_MAP = {
        'en': 'EN',
        'es': 'ES',
        'fr': 'FR',
        'it': 'IT',
        'de': 'DE',
        'ja': 'JP',
        'ko': 'KR',
        'pt': 'PT'
    }

    @staticmethod
    def detect_language(text: str, fallback="ORIG") -> str:

        try:

            lang = detect(text)

            return LanguageHelper.LANG_MAP.get(
                lang,
                lang.upper()
            )

        except Exception:

            return fallback

# =========================================================
# TRANSLATOR
# =========================================================

class LyricsTranslator:

    LRC_REGEX = re.compile(
        r'^((?:\[\d{1,2}:\d{2}(?:\.\d{1,3})?\])+)(.*)'
    )

    def __init__(self, target_lang='pt'):

        self.target_lang = target_lang.upper()

        self.translator = GoogleTranslator(
            source='auto',
            target=target_lang
        )

        self.translation_cache = {}

    # =====================================================
    # TRANSLATE SINGLE
    # =====================================================

    def translate_text(self, text):

        if not text:
            return text

        if text in self.translation_cache:
            return self.translation_cache[text]

        try:

            translated = self.translator.translate(text)

            if translated is None:
                translated = text

        except Exception:

            translated = text

        self.translation_cache[text] = translated

        return translated

    # =====================================================
    # TRANSLATE BATCH
    # =====================================================

    def translate_batch(self, texts):

        if not texts:
            return []

        uncached = []
        uncached_map = {}

        results = [None] * len(texts)

        for i, text in enumerate(texts):

            if text in self.translation_cache:

                results[i] = self.translation_cache[text]

            else:

                uncached_map[len(uncached)] = i
                uncached.append(text)

        if uncached:

            try:

                translated = self.translator.translate_batch(
                    uncached
                )

                for uncached_index, translated_text in enumerate(translated):

                    original_index = uncached_map[uncached_index]

                    original_text = texts[original_index]

                    if translated_text is None:
                        translated_text = original_text

                    self.translation_cache[
                        original_text
                    ] = translated_text

                    results[original_index] = translated_text

            except Exception as e:

                logger.warning(
                    f"    ⚠️ Falha na tradução em lote: {e}"
                )

                return texts

        return results

    # =====================================================
    # BUILD BILINGUAL LRC
    # =====================================================

    def build_bilingual_lrc(self, synced_lyrics):

        logger.info(
            "    🌍 Traduzindo letra sincronizada..."
        )

        bilingual_lrc = []

        parsed_lines = []
        texts_to_translate = []

        # -------------------------------------------------
        # PARSE
        # -------------------------------------------------

        for line in synced_lyrics.splitlines():

            match = self.LRC_REGEX.match(line)

            if match:

                timestamps = match.group(1)
                text = match.group(2).strip()

                parsed_lines.append({
                    "type": "lyric",
                    "timestamps": timestamps,
                    "text": text
                })

                if text:
                    texts_to_translate.append(text)

            else:

                parsed_lines.append({
                    "type": "raw",
                    "line": line
                })

        # -------------------------------------------------
        # MAIN LANGUAGE
        # -------------------------------------------------

        main_prefix = "ORIG"

        if texts_to_translate:

            sample_text = " ".join(
                texts_to_translate[:5]
            )

            try:

                main_lang = detect(sample_text)

                main_prefix = (
                    LanguageHelper.LANG_MAP.get(
                        main_lang,
                        main_lang.upper()
                    )
                )

            except Exception:
                pass

        # -------------------------------------------------
        # TRANSLATE BATCH
        # -------------------------------------------------

        translated_texts = self.translate_batch(
            texts_to_translate
        )

        # -------------------------------------------------
        # BUILD FINAL
        # -------------------------------------------------

        trans_index = 0

        for item in parsed_lines:

            # ---------------------------------------------
            # RAW
            # ---------------------------------------------

            if item["type"] == "raw":

                bilingual_lrc.append(
                    item["line"]
                )

                continue

            timestamps = item["timestamps"]
            text = item["text"]

            # ---------------------------------------------
            # EMPTY
            # ---------------------------------------------

            if not text:

                bilingual_lrc.append(
                    f"{timestamps}"
                )

                continue

            translated_text = translated_texts[
                trans_index
            ]

            trans_index += 1

            if translated_text is None:
                translated_text = text

            # ---------------------------------------------
            # LANGUAGE DETECTION
            # ---------------------------------------------

            line_prefix = main_prefix

            if len(text.split()) >= 2:

                try:

                    line_lang = detect(text)

                    line_prefix = (
                        LanguageHelper.LANG_MAP.get(
                            line_lang,
                            line_lang.upper()
                        )
                    )

                except Exception:
                    pass

            # ---------------------------------------------
            # ORIGINAL
            # ---------------------------------------------

            bilingual_lrc.append(
                f"{timestamps}[{line_prefix}] {text}"
            )

            # ---------------------------------------------
            # TRANSLATION
            # ---------------------------------------------

            if (
                line_prefix != self.target_lang
                and translated_text.lower()
                != text.lower()
            ):

                bilingual_lrc.append(
                    f"{timestamps}[{self.target_lang}] {translated_text}"
                )

            bilingual_lrc.append("")

        return "\n".join(bilingual_lrc)

    # =====================================================
    # BUILD BILINGUAL PLAIN
    # =====================================================

    def build_bilingual_plain_lyrics(
        self,
        lyrics
    ):

        logger.info(
            "    🌍 Traduzindo letra simples..."
        )

        final_lines = []

        original_lines = [
            line.strip()
            for line in lyrics.splitlines()
        ]

        non_empty_lines = [
            line
            for line in original_lines
            if line
        ]

        main_prefix = "ORIG"

        if non_empty_lines:

            sample_text = " ".join(
                non_empty_lines[:5]
            )

            try:

                main_lang = detect(sample_text)

                main_prefix = (
                    LanguageHelper.LANG_MAP.get(
                        main_lang,
                        main_lang.upper()
                    )
                )

            except Exception:
                pass

        translated = self.translate_batch(
            non_empty_lines
        )

        trans_index = 0

        for line in original_lines:

            if not line:

                final_lines.append("")
                continue

            translated_text = translated[
                trans_index
            ]

            trans_index += 1

            if translated_text is None:
                translated_text = line

            line_prefix = main_prefix

            if len(line.split()) >= 2:

                try:

                    line_lang = detect(line)

                    line_prefix = (
                        LanguageHelper.LANG_MAP.get(
                            line_lang,
                            line_lang.upper()
                        )
                    )

                except Exception:
                    pass

            final_lines.append(
                f"[{line_prefix}] {line}"
            )

            if (
                line_prefix != self.target_lang
                and translated_text.lower()
                != line.lower()
            ):

                final_lines.append(
                    f"[{self.target_lang}] {translated_text}"
                )

            final_lines.append("")

        return "\n".join(final_lines)

# =========================================================
# LRCLIB PROVIDER
# =========================================================

class LRCLibProvider:

    def __init__(self, session):

        self.session = session

    def fetch(
        self,
        artist,
        track,
        album
    ):

        clean_artist = (
            TextCleaner.clean_search_term(
                artist
            )
        )

        clean_track = (
            TextCleaner.clean_search_term(
                track
            )
        )

        headers = {
            "User-Agent": "qobuz-dl-ultimate/5.0"
        }

        # -------------------------------------------------
        # WITH ALBUM
        # -------------------------------------------------

        params = {
            "artist_name": clean_artist,
            "track_name": clean_track,
            "album_name": album
        }

        response = self.session.get(
            LRCLIB_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        # -------------------------------------------------
        # WITHOUT ALBUM
        # -------------------------------------------------

        if response.status_code != 200:

            params = {
                "artist_name": clean_artist,
                "track_name": clean_track
            }

            response = self.session.get(
                LRCLIB_URL,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )

        if response.status_code != 200:
            return None

        data = response.json()

        synced = data.get("syncedLyrics")
        plain = data.get("plainLyrics")

        if synced:

            return LyricsResult(
                synced=True,
                lyrics=synced,
                source="LRCLIB"
            )

        if plain:

            return LyricsResult(
                synced=False,
                lyrics=plain,
                source="LRCLIB"
            )

        return None

# =========================================================
# GENIUS PROVIDER
# =========================================================

class GeniusProvider:

    def __init__(self, genius_token=None):

        self.genius = None

        if genius_token and lyricsgenius:

            self.genius = lyricsgenius.Genius(
                genius_token,
                verbose=False,
                remove_section_headers=True
            )

    def fetch(
        self,
        artist,
        track
    ):

        if not self.genius:
            return None

        clean_artist = (
            TextCleaner.clean_search_term(
                artist
            )
        )

        clean_track = (
            TextCleaner.clean_search_term(
                track
            )
        )

        song = self.genius.search_song(
            clean_track,
            clean_artist
        )

        if not song or not song.lyrics:
            return None

        lyrics = (
            TextCleaner.clean_genius_lyrics(
                song.lyrics
            )
        )

        return LyricsResult(
            synced=False,
            lyrics=lyrics,
            source="GENIUS"
        )

# =========================================================
# METADATA
# =========================================================

class MetadataManager:

    @staticmethod
    def has_embedded_lyrics(file_path):

        ext = os.path.splitext(
            file_path
        )[1].lower()

        try:

            if ext == ".flac":

                audio = FLAC(file_path)

                if "LYRICS" in audio:

                    return bool(
                        audio["LYRICS"][0].strip()
                    )

            elif ext == ".mp3":

                audio = ID3(file_path)

                return len(
                    audio.getall("USLT")
                ) > 0

        except Exception:
            pass

        return False

    # -----------------------------------------------------

    @staticmethod
    def inject(
        file_path,
        lyrics
    ):

        if not lyrics:
            return

        ext = os.path.splitext(
            file_path
        )[1].lower()

        try:

            # -------------------------------------------------
            # FLAC
            # -------------------------------------------------

            if ext == ".flac":

                audio = FLAC(file_path)

                audio["LYRICS"] = lyrics

                audio.save()

            # -------------------------------------------------
            # MP3
            # -------------------------------------------------

            elif ext == ".mp3":

                try:

                    audio = ID3(file_path)

                except ID3NoHeaderError:

                    audio = ID3()

                audio.delall("USLT")

                audio.add(
                    USLT(
                        encoding=3,
                        lang='eng',
                        desc='',
                        text=lyrics
                    )
                )

                audio.save(file_path)

        except mutagen.MutagenError as e:

            logger.warning(
                f"    ⚠️ Falha metadata: {e}"
            )

# =========================================================
# LRC FILE
# =========================================================

class LRCFileManager:

    @staticmethod
    def has_lrc_file(file_path):

        base_name = os.path.splitext(
            file_path
        )[0]

        lrc_path = f"{base_name}.lrc"

        return os.path.exists(
            lrc_path
        )

    # -----------------------------------------------------

    @staticmethod
    def save(
        audio_file_path,
        lyrics
    ):

        base_name = os.path.splitext(
            audio_file_path
        )[0]

        lrc_path = f"{base_name}.lrc"

        try:

            with open(
                lrc_path,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(lyrics)

        except OSError as e:

            logger.warning(
                f"    ⚠️ Falha ao salvar LRC: {e}"
            )

# =========================================================
# ENGINE
# =========================================================

class LyricsEngine:

    def __init__(
        self,
        genius_token=None,
        target_lang='pt'
    ):

        self.session = requests.Session()

        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[
                429,
                500,
                502,
                503,
                504
            ]
        )

        adapter = HTTPAdapter(
            max_retries=retries
        )

        self.session.mount(
            "https://",
            adapter
        )

        self.session.mount(
            "http://",
            adapter
        )

        self.lrclib = LRCLibProvider(
            self.session
        )

        self.genius = GeniusProvider(
            genius_token
        )

        self.translator = LyricsTranslator(
            target_lang
        )

    # =====================================================
    # SKIP CHECK
    # =====================================================

    def should_skip_file(
        self,
        file_path,
        overwrite_all=False
    ):

        if overwrite_all:
            return False

        has_embedded = (
            MetadataManager.has_embedded_lyrics(
                file_path
            )
        )

        has_lrc = (
            LRCFileManager.has_lrc_file(
                file_path
            )
        )

        return has_embedded or has_lrc

    # =====================================================
    # MAIN
    # =====================================================

    def fetch_and_process(
        self,
        file_path,
        artist,
        track,
        album,
        overwrite_all=False
    ):

        logger.info(
            f"    🔍 Buscando letras para: {track}"
        )

        # -------------------------------------------------
        # SKIP
        # -------------------------------------------------

        if self.should_skip_file(
            file_path,
            overwrite_all
        ):

            logger.info(
                "    ⏭️ Arquivo já possui lyrics. Pulando..."
            )

            return False

        try:

            # -------------------------------------------------
            # LRCLIB
            # -------------------------------------------------

            result = self.lrclib.fetch(
                artist,
                track,
                album
            )

            # -------------------------------------------------
            # GENIUS FALLBACK
            # -------------------------------------------------

            if not result:

                result = self.genius.fetch(
                    artist,
                    track
                )

            # -------------------------------------------------

            if not result:

                logger.warning(
                    "    ❌ Nenhuma letra encontrada."
                )

                return False

            # =================================================
            # SYNCED
            # =================================================

            if result.synced:

                bilingual_lrc = (
                    self.translator
                    .build_bilingual_lrc(
                        result.lyrics
                    )
                )

                # Apenas .lrc
                LRCFileManager.save(
                    file_path,
                    bilingual_lrc
                )

                logger.info(
                    f"    ✅ LRC salvo ({result.source})"
                )

            # =================================================
            # PLAIN
            # =================================================

            else:

                bilingual_plain = (
                    self.translator
                    .build_bilingual_plain_lyrics(
                        result.lyrics
                    )
                )

                # Apenas metadata
                MetadataManager.inject(
                    file_path,
                    bilingual_plain
                )

                logger.info(
                    f"    ✅ Letra embutida ({result.source})"
                )

            return True

        # -------------------------------------------------
        # ERRORS
        # -------------------------------------------------

        except requests.Timeout:

            logger.warning(
                "    ⚠️ Timeout ao buscar letras."
            )

        except requests.RequestException as e:

            logger.warning(
                f"    ⚠️ Erro de rede: {e}"
            )

        except Exception as e:

            logger.warning(
                f"    ⚠️ Erro inesperado: {e}"
            )

        return False

    # =====================================================
    # BACKWARD COMPATIBILITY
    # =====================================================

    def fetch_and_inject(
        self,
        file_path,
        artist,
        track,
        album,
        overwrite_all=False
    ):
        """
        Compatibilidade com versões antigas.
        """

        return self.fetch_and_process(
            file_path=file_path,
            artist=artist,
            track=track,
            album=album,
            overwrite_all=overwrite_all
        )