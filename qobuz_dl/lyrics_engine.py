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

# Import deepl e langdetect para traduções automatizadas com IA
DEEPL_AVAILABLE = False
TRANSLATOR_IMPORT_ERROR = None

try:
    import deepl
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0 # Torna a detecção determinística
    DEEPL_AVAILABLE = True
except ImportError as import_error:
    TRANSLATOR_IMPORT_ERROR = str(import_error)
except Exception as unexpected_error:
    TRANSLATOR_IMPORT_ERROR = str(unexpected_error)

logger = logging.getLogger(__name__)

class LyricsEngine:
    def __init__(self, genius_token=None, deepl_api_key=None, translate=True, target_lang='PT-BR', translation_symbol=" ¬ "):
        self.genius_token = genius_token
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        self.deepl_api_key = deepl_api_key
        self.translator = None
        
        if self.translate:
            if not DEEPL_AVAILABLE:
                print(f"\n\033[93m[!] AVISO: Módulo deepl/langdetect ausente. Tradução desabilitada! (Erro: {TRANSLATOR_IMPORT_ERROR})\033[0m")
                self.translate = False
            elif not self.deepl_api_key:
                print(f"\n\033[93m[!] AVISO: Nenhuma API Key do DeepL fornecida no config.ini. Tradução desabilitada!\033[0m")
                self.translate = False
            else:
                try:
                    self.translator = deepl.Translator(self.deepl_api_key)
                except Exception as e:
                    print(f"\n\033[91m[!] Erro ao inicializar o DeepL: {e}. Tradução desabilitada!\033[0m")
                    self.translate = False
        
        if self.genius_token and lyricsgenius:
            self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)

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
        """Traduz a letra usando DeepL (se configurado), pulando músicas/linhas em português para economizar cota."""
        if not self.translate or not DEEPL_AVAILABLE or not self.translator:
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

        # Extrai todas as linhas com texto real
        for line in lines:
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

        # 1. MACRO DETECÇÃO (ECONOMIA GLOBAL):
        # Lê a música inteira. Se o idioma predominante for Português (pt), aborta a tradução e economiza a cota.
        full_text = " ".join(texts_to_translate)
        try:
            dominant_lang = detect(full_text)
            # Se o idioma dominante já é o mesmo idioma alvo, não traduzimos nada.
            # Convertendo target_lang "PT-BR" para "pt" para comparação.
            if dominant_lang.lower() == self.target_lang.split('-')[0].lower():
                return lyrics
        except Exception:
            # Se langdetect falhar em detectar, continua e tenta traduzir
            pass

        # 2. MICRO DETECÇÃO (FILTRA LINHAS MISTAS E GÍRIAS CURTAS):
        lines_to_deepl = []
        indices_to_translate = [] # Mapeia quais índices do 'texts_to_translate' realmente enviamos

        for i, txt in enumerate(texts_to_translate):
            txt_clean = txt.strip()
            # Ignora linhas curtas (< 15 chars) ou de poucas palavras (< 4 palavras). Ex: "Oh yeah"
            if len(txt_clean) < 15 or len(txt_clean.split()) < 4:
                continue

            try:
                line_lang = detect(txt_clean)
                if line_lang.lower() == self.target_lang.split('-')[0].lower():
                    continue # Já está no idioma alvo
            except Exception:
                pass

            lines_to_deepl.append(txt_clean)
            indices_to_translate.append(i)

        if not lines_to_deepl:
            return lyrics

        # 3. TRADUÇÃO EM LOTE COM DEEPL (ECONÔMICO E RÁPIDO):
        try:
            # Envia tudo em um único batch para o DeepL
            results = await asyncio.to_thread(self.translator.translate_text, lines_to_deepl, target_lang=self.target_lang)
            translated_results = [res.text for res in results]
        except Exception as e:
            logger.error(f"[!] Erro na API do DeepL: {e}")
            return lyrics

        # 4. REMONTAR AS LINHAS (MAPEAR TRADUÇÕES DE VOLTA)
        translated_texts = [""] * len(texts_to_translate)
        for original_idx, translated_text in zip(indices_to_translate, translated_results):
            translated_texts[original_idx] = translated_text

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
