import os
import re
import asyncio
import aiohttp
import logging
import string

from mutagen.flac import FLAC
from mutagen.id3 import ID3, USLT, ID3NoHeaderError

from langdetect import detect, LangDetectException

try:
    import lyricsgenius
except ImportError:
    lyricsgenius = None

GoogleTranslator = None
DEEP_TRANSLATOR_AVAILABLE = False

try:
    from deep_translator import GoogleTranslator
    DEEP_TRANSLATOR_AVAILABLE = True
except Exception:
    pass

logger = logging.getLogger(__name__)

class LyricsEngine:

    def __init__(
        self,
        genius_token=None,
        translate=True,
        target_lang='pt',
        translation_symbol=" ¬ "
    ):

        self.genius_token = genius_token
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol

        self.translation_cache = {}

        self.genius = None

        if genius_token and lyricsgenius:
            self.genius = lyricsgenius.Genius(
                genius_token,
                verbose=False,
                remove_section_headers=True
            )

    # =====================================================
    # DETECTAR SE PRECISA TRADUZIR
    # =====================================================

    def _should_translate(self, text):

        text = text.strip()

        if not text:
            return False

        # Muito curto
        if len(text) < 10:
            return False

        # Poucas palavras
        if len(text.split()) < 3:
            return False

        # Poucas letras
        alpha_chars = sum(c.isalpha() for c in text)

        if alpha_chars < 3:
            return False

        try:
            lang = detect(text)

            # NÃO traduz português
            if lang == "pt":
                return False

            return True

        except LangDetectException:
            return False

        except Exception:
            return False

    # =====================================================
    # VERIFICAR LETRA EXISTENTE
    # =====================================================

    def _has_lyrics(self, file_path, check_lrc=True):

        if check_lrc:

            base_name = os.path.splitext(file_path)[0]

            if os.path.exists(f"{base_name}.lrc"):
                return True

        ext = os.path.splitext(file_path)[1].lower()

        try:

            if ext == '.flac':

                audio = FLAC(file_path)

                fields = [
                    "LYRICS",
                    "UNSYNCEDLYRICS",
                    "LYRICS_SYNCED"
                ]

                return any(audio.get(field) for field in fields)

            elif ext == '.mp3':

                try:

                    audio = ID3(file_path)

                    return bool(
                        audio.getall("USLT") or
                        audio.getall("SYLT")
                    )

                except ID3NoHeaderError:
                    return False

        except Exception:
            return False

        return False

    # =====================================================
    # LIMPAR SYLLABLE SYNC
    # =====================================================

    def _clean_syllable_sync(self, lrc_text):

        if not lrc_text:
            return lrc_text

        cleaned_lines = []

        for line in lrc_text.splitlines():

            match = re.match(
                r'^(\[\d{2}:\d{2}\.\d{2,3}\])(.*)',
                line
            )

            if match:

                timestamp = match.group(1)
                content = match.group(2)

                content = re.sub(
                    r'<\d{2}:\d{2}\.\d{2,3}>',
                    '',
                    content
                )

                content = re.sub(
                    r'\[\d{2}:\d{2}\.\d{2,3}\]',
                    '',
                    content
                )

                content = ' '.join(content.split())

                cleaned_lines.append(
                    f"{timestamp} {content}".strip()
                )

            else:
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    # =====================================================
    # TRADUZIR BLOCO
    # =====================================================

    async def _translate_chunk(self, translator, chunk):

        joined = "\n".join(chunk)

        try:

            translated = await asyncio.to_thread(
                translator.translate,
                joined
            )

            if not translated:
                return chunk

            split_lines = translated.split("\n")

            if len(split_lines) != len(chunk):
                return chunk

            return split_lines

        except Exception:
            return chunk

    # =====================================================
    # PROCESSAR TRADUÇÃO
    # =====================================================

    async def _process_translation(self, lyrics, is_synced=True):

        if not self.translate:
            return lyrics

        if not DEEP_TRANSLATOR_AVAILABLE:
            return lyrics

        try:

            translator = GoogleTranslator(
                source='auto',
                target=self.target_lang
            )

        except Exception:
            return lyrics

        result_lines = []

        pending_lines = []
        pending_meta = []

        async def flush_chunk():

            nonlocal pending_lines
            nonlocal pending_meta
            nonlocal result_lines

            if not pending_lines:
                return

            translated = await self._translate_chunk(
                translator,
                pending_lines
            )

            for meta, trad in zip(pending_meta, translated):

                timestamp, original = meta

                # Original
                if timestamp:
                    result_lines.append(
                        f"{timestamp}{original}"
                    )
                else:
                    result_lines.append(original)

                trad = trad.strip()

                # Tradução
                if trad and trad.lower() != original.lower():

                    if timestamp:
                        result_lines.append(
                            f"{timestamp}{self.translation_symbol}{trad}"
                        )
                    else:
                        result_lines.append(
                            f"{self.translation_symbol}{trad}"
                        )

                    self.translation_cache[original] = trad

            pending_lines.clear()
            pending_meta.clear()

        for line in lyrics.split("\n"):

            if not line.strip():
                result_lines.append("")
                continue

            timestamp = ""
            text = line.strip()

            if is_synced:

                match = re.match(
                    r'^((?:\[\d+:\d+(?:\.\d+)?\]\s*)+)(.*)',
                    line
                )

                if match:

                    timestamp = match.group(1)
                    text = match.group(2).strip()

                else:
                    result_lines.append(line)
                    continue

            if not text:
                result_lines.append(line)
                continue

            # NÃO traduz PT
            if not self._should_translate(text):

                if timestamp:
                    result_lines.append(
                        f"{timestamp}{text}"
                    )
                else:
                    result_lines.append(text)

                continue

            # CACHE
            if text in self.translation_cache:

                trad = self.translation_cache[text]

                if timestamp:
                    result_lines.append(
                        f"{timestamp}{text}"
                    )

                    result_lines.append(
                        f"{timestamp}{self.translation_symbol}{trad}"
                    )

                else:
                    result_lines.append(text)

                    result_lines.append(
                        f"{self.translation_symbol}{trad}"
                    )

                continue

            pending_lines.append(text)
            pending_meta.append((timestamp, text))

            # BLOCO DE 20
            if len(pending_lines) >= 20:
                await flush_chunk()

        await flush_chunk()

        return "\n".join(result_lines)

    # =====================================================
    # SAVE LRC
    # =====================================================

    def _save_lrc_file(self, audio_file_path, synced_lyrics):

        try:

            base_name = os.path.splitext(audio_file_path)[0]

            lrc_path = f"{base_name}.lrc"

            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)

        except Exception:
            pass

    # =====================================================
    # INJECT
    # =====================================================

    def _inject_metadata(self, file_path, lyrics):

        if not lyrics:
            return

        ext = os.path.splitext(file_path)[1].lower()

        try:

            if ext == '.flac':

                audio = FLAC(file_path)

                audio['LYRICS'] = lyrics

                audio.save()

            elif ext == '.mp3':

                try:
                    audio = ID3(file_path)

                except ID3NoHeaderError:
                    audio = ID3()

                audio.add(
                    USLT(
                        encoding=3,
                        lang='eng',
                        desc='',
                        text=lyrics
                    )
                )

                audio.save(file_path)

        except Exception:
            pass
