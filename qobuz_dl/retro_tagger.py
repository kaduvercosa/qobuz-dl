import os
import re
import asyncio
import aiohttp
import logging
from mutagen.flac import FLAC
from mutagen.id3 import ID3, USLT, ID3NoHeaderError

# Import lyricsgenius apenas se o usuário tiver configurado o token
try:
    import lyricsgenius
except ImportError:
    lyricsgenius = None

# Import deepl para traduções automáticas (API Oficial)
try:
    import deepl
    DEEPL_AVAILABLE = True
except ImportError:
    deepl = None
    DEEPL_AVAILABLE = False

# Import fasttext e langdetect para detecção de idioma
try:
    import fasttext
    # Suppress the fasttext load warning
    fasttext.FastText.eprint = lambda x: None
except ImportError:
    fasttext = None

try:
    from langdetect import detect as langdetect_detect
except ImportError:
    langdetect_detect = None

# Configurar logging e silenciar as bibliotecas ruidosas de rede
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("deepl").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class LyricsEngine:
    def __init__(self, genius_token=None, deepl_api_key=None, translate=True, target_lang='PT-BR', translation_symbol=" ¬ "):
        self.genius_token = genius_token
        self.genius = None
        self.deepl_api_key = deepl_api_key
        self.deepl_translator = None
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        
        self.fasttext_model = None
        self._init_fasttext()

        # Dicionário de exclusão rápida (falsos positivos em PT-BR)
        self.pt_false_positives = {"oh", "yeah", "ah", "baby", "na", "la", "uh", "hey"}

        # BUG FIX: Verificar se deepl está disponível e inicializar o translator
        if self.translate and self.deepl_api_key:
            if not DEEPL_AVAILABLE:
                print("\n\033[93m[!] AVISO: O pacote 'deepl' não está instalado!")
                print("    Traduções via DeepL serão desabilitadas.")
                print("    Instale com: pip install deepl\033[0m\n")
                self.translate = False
                self.deepl_api_key = None
            else:
                try:
                    self.deepl_translator = deepl.Translator(deepl_api_key)
                    logger.debug(f"[*] DeepL Translator inicializado para idioma alvo: {target_lang}")
                except Exception as e:
                    logger.error(f"[!] Erro ao inicializar DeepL Translator: {e}")
                    print(f"\n\033[91m[!] Erro ao inicializar DeepL: {e}\033[0m")
                    self.translate = False
                    self.deepl_api_key = None
        
        if self.genius_token and lyricsgenius:
            try:
                self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)
                logger.debug("[*] Genius API inicializado como fallback")
            except Exception as e:
                logger.error(f"[!] Erro ao inicializar Genius: {e}")
                self.genius = None

    def _init_fasttext(self):
        """Inicializa o modelo fasttext se disponível."""
        if not fasttext:
            return

        model_path = os.path.join(os.path.dirname(__file__), "lid.176.ftz")
        try:
            if not os.path.exists(model_path):
                import urllib.request
                print("\n\033[96m[*] Baixando modelo Fasttext (lid.176.ftz) para detecção de idiomas (900KB)...\033[0m")
                urllib.request.urlretrieve("https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz", model_path)

            self.fasttext_model = fasttext.load_model(model_path)
        except Exception as e:
            logger.debug(f"[*] Falha ao inicializar Fasttext: {e}")

    def _detect_lang(self, text):
        """Retorna tuple (lang_code, confidence_score) usando fasttext ou langdetect."""
        if self.fasttext_model:
            try:
                text_clean = text.replace('\n', ' ')
                res = self.fasttext_model.predict(text_clean)
                label = res[0][0] # ex: '__label__en'
                score = float(res[1][0])
                return label.replace('__label__', ''), score
            except Exception:
                pass

        if langdetect_detect:
            try:
                return langdetect_detect(text), 0.5 # langdetect não retorna score fácil, assumimos 0.5
            except Exception:
                pass
        return None, 0.0

    def _has_lyrics(self, file_path, check_lrc=True):
        """Verifica se o arquivo já possui letra."""
        if check_lrc:
            base_name = os.path.splitext(file_path)[0]
            if os.path.exists(f"{base_name}.lrc"):
                return True
        
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == '.flac':
                audio = FLAC(file_path)
                if audio.get('LYRICS') or audio.get('UNSYNCEDLYRICS'):
                    return True
            elif ext == '.mp3':
                try:
                    audio = ID3(file_path)
                    if any(frame.FrameID in ['USLT', 'SYLT'] for frame in audio.values()):
                        return True
                except ID3NoHeaderError:
                    pass
        except Exception:
            pass
        return False

    def _is_valid_translation(self, original, translated):
        """Verifica se a tradução é válida (não é idêntica ou vazia)."""
        if not translated or not translated.strip():
            return False
        return original.strip().lower() != translated.strip().lower()

    async def _process_translation(self, lyrics, is_synced=True):
        """Traduz a letra usando DeepL mantendo o idioma original e duplicando os timestamps."""
        lines = lyrics.split('\n')
        texts_to_translate = []
        line_mapping = []

        for line in lines:
            if not line.strip():
                line_mapping.append(('empty', None, ''))
                continue

            if is_synced:
                match = re.match(r'^((?:\[\d+:\d+(?:\.\d+)?\]\s*)+)(.*)', line)
                if match:
                    ts = match.group(1)
                    txt = match.group(2).strip()
                    if txt:
                        texts_to_translate.append(txt)
                        line_mapping.append(('synced', ts, txt))
                    else:
                        line_mapping.append(('empty_synced', ts, ''))
                else:
                    line_mapping.append(('raw', None, line))
            else:
                txt = line.strip()
                if txt:
                    texts_to_translate.append(txt)
                    line_mapping.append(('text', None, txt))
                else:
                    line_mapping.append(('empty', None, ''))

        total_lines = len(texts_to_translate)

        # Retornar original se tradução desabilitada ou sem API key
        if not self.translate or not self.deepl_api_key or not self.deepl_translator:
            logger.debug("[*] Tradução desabilitada ou DeepL não configurado, retornando lyrics original")
            return lyrics, 0, total_lines

        if not texts_to_translate:
            logger.debug("[*] Sem linhas para traduzir, retornando original")
            return lyrics, 0, total_lines

        # 1. DETECÇÃO GLOBAL DE IDIOMA (economia de quota)
        full_text = " ".join(texts_to_translate)
        target_lang_code = self.target_lang.split('-')[0].lower()

        dominant_lang_code, _ = self._detect_lang(full_text)
        if dominant_lang_code and dominant_lang_code.lower() == target_lang_code:
            logger.debug(f"[*] Texto já está em {self.target_lang}, pulando tradução")
            return lyrics, 0, total_lines

        # Se o idioma global não for o alvo, e for muito diferente (
