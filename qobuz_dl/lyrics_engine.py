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

<<<<<<< HEAD
# Import deepl e langdetect para traduções automatizadas com IA
DEEPL_AVAILABLE = False
TRANSLATOR_IMPORT_ERROR = None

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0 # Torna a detecção determinística
    DEEPL_AVAILABLE = True
except ImportError as import_error:
    TRANSLATOR_IMPORT_ERROR = str(import_error)
except Exception as unexpected_error:
    TRANSLATOR_IMPORT_ERROR = str(unexpected_error)

# Configurar logging (Mantido no modo debug para não poluir a tela)
logger = logging.getLogger(__name__)

class LyricsEngine:
    def __init__(self, genius_token=None, deepl_api_key=None, translate=True, target_lang='PT-BR', translation_symbol=" ¬ "):
=======
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
    def __init__(self, genius_token=None, deepl_api_key=None, translate=True, target_lang='PT-BR', translation_symbol=" ¬ ", synced_only=True):
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
        self.genius_token = genius_token
        self.genius = None
        self.deepl_api_key = deepl_api_key
        self.deepl_translator = None
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        self.deepl_api_key = deepl_api_key
        self.translator = None
        
<<<<<<< HEAD
        if self.translate:
            if not DEEPL_AVAILABLE:
                print(f"\n\033[93m[!] AVISO: Módulo langdetect ausente. Tradução desabilitada! (Erro: {TRANSLATOR_IMPORT_ERROR})\033[0m")
                self.translate = False
            elif not self.deepl_api_key:
                print(f"\n\033[93m[!] AVISO: Nenhuma API Key do DeepL fornecida no config.ini. Tradução desabilitada!\033[0m")
                self.translate = False
            # O Translator oficial foi retirado para fazermos requisições nativas limpas (aiohttp)
=======
        # NOVO: Parâmetro para forçar apenas letras sincronizadas
        self.synced_only = synced_only 
        
        self.fasttext_model = None
        self._init_fasttext()

        self.pt_false_positives = {"oh", "yeah", "ah", "baby", "na", "la", "uh", "hey"}

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
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
        
        if self.genius_token and lyricsgenius:
            try:
                self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)
                logger.debug("[*] Genius API inicializado como fallback")
            except Exception as e:
                logger.error(f"[!] Erro ao inicializar Genius: {e}")
                self.genius = None

    def _init_fasttext(self):
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
        if self.fasttext_model:
            try:
                text_clean = text.replace('\n', ' ')
                res = self.fasttext_model.predict(text_clean)
                label = res[0][0]
                score = float(res[1][0])
                return label.replace('__label__', ''), score
            except Exception:
                pass
        if langdetect_detect:
            try:
                return langdetect_detect(text), 0.5
            except Exception:
                pass
        return None, 0.0

    def _has_lyrics(self, file_path, check_lrc=True):
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
        if not translated or not translated.strip():
            return False
        return original.strip().lower() != translated.strip().lower()

    def _is_strictly_synced(self, text):
        """Verifica se o texto contém as tags de tempo [mm:ss.xx]"""
        if not text:
            return False
<<<<<<< HEAD
            
        # Filtro 3: Detecta paráfase em português (quando o original já está em pt mas a API reescreveu)
        # Por exemplo: "eu te amo" virou "eu amo você", ou "cê tá bem" virou "você está bem"
        # Nós verificamos se ambas as strings usam um vocabulário quase idêntico de palavras.
        orig_words = set(o_no_punct.split())
        trad_words = set(t_no_punct.split())
        if orig_words and trad_words:
            # Intersection of words
            common_words = orig_words.intersection(trad_words)
            # If the translation didn't change the meaning / is essentially the same words reordered
            # or if it only added standard connector words to the original string.
            if len(common_words) / max(len(orig_words), len(trad_words)) >= 0.5:
                return False

        # Filtro 4: Regras gramaticais explícitas (português re-escrito no Google Translate)
        if "eu te amo" in o_no_punct and "eu amo você" in t_no_punct:
            return False

        return True


    def _clean_syllable_sync(self, lrc_text):
        """
        Cleans Syllable-Sync (Word-by-Word) LRC lines to standard Line-by-Line.
        Example: [00:15.30] <00:15.50> pa <00:15.80> la -> [00:15.30] pa la
        """
        if not lrc_text:
            return lrc_text

        cleaned_lines = []
        for line in lrc_text.splitlines():
            match = re.match(r'^(\[\d{2}:\d{2}\.\d{2,3}\])(.*)', line)
            if match:
                timestamp = match.group(1)
                content = match.group(2)

                # Remove <mm:ss.xx> tags (Apple Music / Spotify Syllable sync)
                content = re.sub(r'<\d{2}:\d{2}\.\d{2,3}>', '', content)

                # Remove extra [mm:ss.xx] tags inside the line
                content = re.sub(r'\[\d{2}:\d{2}\.\d{2,3}\]', '', content)

                content = ' '.join(content.split())
                cleaned_lines.append(f"{timestamp} {content}".strip())
            else:
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    async def _process_translation(self, lyrics, is_synced=True):
        """Traduz a letra usando a API do DeepL via aiohttp nativo para esconder logs barulhentos."""
        if not self.translate or not DEEPL_AVAILABLE or not self.deepl_api_key:
            return lyrics, None

=======
        return bool(re.search(r'\[\d+:\d+(?:\.\d+)?\]', text))

    async def _process_translation(self, lyrics, is_synced=True):
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
        lines = lyrics.split('\n')
        texts_to_translate = []
        line_mapping = []

        # Extrai todas as linhas com texto real
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

        if not self.translate or not self.deepl_api_key or not self.deepl_translator:
            return lyrics, 0, total_lines

        if not texts_to_translate:
<<<<<<< HEAD
            return lyrics, None

        # 1. MACRO DETECÇÃO (ECONOMIA GLOBAL):
        full_text = " ".join(texts_to_translate)
        try:
            dominant_lang = detect(full_text)
            if dominant_lang.lower() == self.target_lang.split('-')[0].lower():
                return lyrics, None
        except Exception:
            pass

        # 2. MICRO DETECÇÃO: Envia tudo, menos as linhas que o langdetect tiver CERTEZA ABSOLUTA de que já estão em PT-BR
        # Removemos o filtro de tamanho (len) para traduzir qualquer palavra isolada (Ex: "Yes", "Hello").
        # No entanto, adicionamos uma checagem leve para evitar que frases muito curtas gerem falsos positivos no langdetect
        # que pulariam a tradução erroneamente.
        lines_to_deepl = []
        indices_to_translate = [] # Mapeia quais índices do 'texts_to_translate' realmente enviamos

        for i, txt in enumerate(texts_to_translate):
            txt_clean = txt.strip()
            if not txt_clean:
                continue

            # Se a linha for mais longa, deixamos o langdetect verificar se devemos pular (já está no idioma)
            if len(txt_clean.split()) >= 3:
                try:
                    line_lang = detect(txt_clean)
                    if line_lang.lower() == self.target_lang.split('-')[0].lower():
                        continue # Já está no idioma alvo
                except Exception:
                    pass

            lines_to_deepl.append(txt_clean)
            indices_to_translate.append(i)

        if not lines_to_deepl:
            return lyrics, None

        # 3. TRADUÇÃO EM LOTE COM DEEPL (REQUISIÇÃO AIOHTTP LIMPA E SILENCIOSA)
        translated_results = []
        deepl_status_code = None
        try:
            import json
            # Determina se é a API Free ou Pro baseado na chave
            domain = "api-free.deepl.com" if self.deepl_api_key.endswith(":fx") else "api.deepl.com"
            url = f"https://{domain}/v2/translate"

            headers = {
                "Authorization": f"DeepL-Auth-Key {self.deepl_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "text": lines_to_deepl,
                "target_lang": self.target_lang
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    deepl_status_code = resp.status
                    if resp.status == 200:
                        data = await resp.json()
                        translated_results = [item['text'] for item in data.get('translations', [])]
                    else:
                        logger.error(f"[!] DeepL retornou erro HTTP {resp.status}")
                        return lyrics, deepl_status_code
        except Exception as e:
            logger.error(f"[!] Erro na conexão do DeepL: {e}")
            return lyrics, deepl_status_code

        if not translated_results or len(translated_results) != len(lines_to_deepl):
            return lyrics, deepl_status_code

        # 4. REMONTAR AS LINHAS (MAPEAR TRADUÇÕES DE VOLTA)
        translated_texts = [""] * len(texts_to_translate)
        for original_idx, translated_text in zip(indices_to_translate, translated_results):
            translated_texts[original_idx] = translated_text
=======
            return lyrics, 0, total_lines

        full_text = " ".join(texts_to_translate)
        target_lang_code = self.target_lang.split('-')[0].lower()

        dominant_lang_code, _ = self._detect_lang(full_text)
        if dominant_lang_code and dominant_lang_code.lower() == target_lang_code:
            return lyrics, 0, total_lines

        is_foreign_song = dominant_lang_code and dominant_lang_code.lower() not in (target_lang_code, "en")

        lines_to_translate = []
        indices_to_translate = []
        
        for i, txt in enumerate(texts_to_translate):
            txt_clean = txt.strip()
            if not txt_clean:
                continue

            words = txt_clean.lower().split()
            if len(words) >= 1:
                is_false_positive = all(w in self.pt_false_positives for w in words)
                if not is_false_positive:
                    line_lang, score = self._detect_lang(txt_clean)
                    if line_lang and line_lang.lower() == target_lang_code:
                        threshold = 0.98 if is_foreign_song else 0.85
                        if score >= threshold:
                            continue

            lines_to_translate.append(txt_clean)
            indices_to_translate.append(i)

        if not lines_to_translate:
            return lyrics, 0, total_lines

        translated_texts = [""] * len(texts_to_translate)
        try:
            translated_results = await asyncio.to_thread(
                self.deepl_translator.translate_text,
                lines_to_translate,
                target_lang=self.target_lang
            )

            if not isinstance(translated_results, list):
                translated_results = [translated_results]

            for original_idx, translated_text in zip(indices_to_translate, translated_results):
                translated_texts[original_idx] = translated_text.text if hasattr(translated_text, 'text') else str(translated_text)

        except Exception as e:
            logger.error(f"[!] Erro fatal na tradução DeepL: {e}")
            return lyrics, 0, total_lines
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2

        result_lines = []
        trans_idx = 0
        translation_count = 0

        for item in line_mapping:
            l_type, ts, txt = item
            
            if l_type == 'synced':
                result_lines.append(f"{ts}{txt}")
                if trans_idx < len(translated_texts):
                    traducao = translated_texts[trans_idx]
                    if self._is_valid_translation(txt, traducao):
                        result_lines.append(f"{ts}{self.translation_symbol}{traducao}")
                        translation_count += 1
                trans_idx += 1
                
            elif l_type == 'text':
                result_lines.append(txt)
                if trans_idx < len(translated_texts):
                    traducao = translated_texts[trans_idx]
                    if self._is_valid_translation(txt, traducao):
                        result_lines.append(f"{self.translation_symbol}{traducao}")
                        translation_count += 1
                trans_idx += 1
                
            elif l_type == 'empty_synced':
                result_lines.append(f"{ts}")
                
            elif l_type in ('raw', 'empty'):
                result_lines.append(txt)

<<<<<<< HEAD
        # Só retorna o texto final com tradução se pelo menos UMA linha passou no filtro de inteligência
        if not has_valid_translations:
            return lyrics, deepl_status_code

        return '\n'.join(result_lines), deepl_status_code



    async def _fetch_lyrics_plus(self, artist, track):
        # Fetch highly synchronized lyrics directly from the LyricsPlus (Apple Music/Spotify backend)
        import json
        from urllib import parse

        # We try multiple mirrors since some may be down
        endpoints = [
            "https://lyricsplus.binimum.org",
            "https://lyricsplus-seven.vercel.app",
            "https://lyricsplus.prjktla.workers.dev"
        ]

        try:
            async with aiohttp.ClientSession() as session:
                for base_url in endpoints:
                    url = f"{base_url}/v2/lyrics/get?title={parse.quote(track)}&artist={parse.quote(artist)}"
                    try:
                        async with session.get(url, timeout=10) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if 'lyrics' in data and data['lyrics']:
                                    lines = []
                                    for lyric in data['lyrics']:
                                        time_ms = lyric.get('time', 0)
                                        minutes = int(time_ms / 60000)
                                        seconds = (time_ms % 60000) / 1000
                                        timestamp = f"[{minutes:02d}:{seconds:05.2f}]"
                                        lines.append(f"{timestamp} {lyric.get('text', '')}")
                                    return '\n'.join(lines)
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    async def _fetch_netease_lyrics(self, artist, track):
        import json
        url = "https://music.163.com/api/search/get/web?csrf_token="
        params = {"s": f"{artist} {track}", "type": 1, "offset": 0, "total": "true", "limit": 1}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://music.163.com/",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=params, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        data = json.loads(text)
                        if data.get('code') == 200 and 'result' in data and 'songs' in data['result']:
                            song_id = data['result']['songs'][0]['id']
                            lyr_url = "https://music.163.com/api/song/lyric"
                            lyr_params = {"id": song_id, "lv": 1, "kv": 1, "tv": -1}
                            async with session.get(lyr_url, params=lyr_params, headers=headers, timeout=15) as lyr_resp:
                                if lyr_resp.status == 200:
                                    text_lyr = await lyr_resp.text()
                                    lyr_data = json.loads(text_lyr)
                                    if 'lrc' in lyr_data and 'lyric' in lyr_data['lrc']:
                                        return lyr_data['lrc']['lyric']
        except Exception:
            pass
        return None

    async def fetch_and_inject(self, file_path, album_artist, track, album, save_lrc=True, overwrite=False, return_message=False):
        messages = []
        def _log(msg):
            if return_message:
                messages.append(msg)
            else:
                print(msg)
=======
        return '\n'.join(result_lines), translation_count, total_lines

    async def _fetch_lyrics_plus(self, artist, title):
        import urllib.parse
        try:
            query = urllib.parse.quote(f"{title} {artist}")
            search_url = f"https://lyricsplus.binimum.org/api/search?q={query}"

            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, timeout=40) as resp:
                    data = await resp.json(content_type=None)
                    items = data.get("data", [])
                    if not items:
                        return None
                    song_id = items[0]["id"]

                lyric_url = f"https://lyricsplus.binimum.org/api/lyrics?id={song_id}"
                async with session.get(lyric_url, timeout=40) as resp:
                    lyric_data = await resp.json(content_type=None)
                    lrc = lyric_data.get("data", {}).get("syncedLyrics", "")
                    
                    # Ignorar fallback de plainLyrics se synced_only
                    if not lrc and not self.synced_only:
                        lrc = lyric_data.get("data", {}).get("plainLyrics", "")
                    return lrc if lrc else None
        except Exception as e:
            logger.debug(f"[*] Erro ao buscar no LyricsPlus: {e}")
        return None

    async def _fetch_musixmatch_lyrics(self, artist, title):
        import urllib.parse
        headers = {
            "Host": "apic-appmobile.musixmatch.com",
            "authority": "apic-appmobile.musixmatch.com",
            "X-Cookie": "x-mxm-token-guid=",
            "x-mxm-app-version": "10.1.1",
            "X-User-Agent": "Musixmatch/2025120901 CFNetwork/3860.300.31 Darwin/25.2.0",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json",
        }

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                url = "https://apic-appmobile.musixmatch.com/ws/1.1/token.get?app_id=mac-ios-v2.0"
                async with session.get(url, timeout=50) as resp:
                    data = await resp.json(content_type=None)
                    if data.get("message", {}).get("header", {}).get("status_code") == 200:
                        token = data["message"]["body"]["user_token"]
                    else:
                        token = "21051986b9886beabe1ce01c3ce94c96319411f8f2c12267636fa7"

                params = {
                    "q_artist": artist,
                    "q_track": title,
                    "format": "json",
                    "namespace": "lyrics_richsynched",
                    "usertoken": token,
                    "app_id": "mac-ios-v2.0"
                }

                url = "https://apic-appmobile.musixmatch.com/ws/1.1/macro.subtitles.get?" + urllib.parse.urlencode(params)
                async with session.get(url, timeout=50) as resp:
                    data = await resp.json(content_type=None)
                    if data.get("message", {}).get("header", {}).get("status_code") == 200:
                        macro_calls = data["message"]["body"]["macro_calls"]
                        subtitles = macro_calls.get("track.subtitles.get", {}).get("message", {}).get("body", {})
                        
                        # Retorna a versão Sincronizada
                        if subtitles and "subtitle_list" in subtitles and len(subtitles["subtitle_list"]) > 0:
                            return subtitles["subtitle_list"][0]["subtitle"]["subtitle_body"]

                        # Ignora a versão Plain se synced_only estiver ativo
                        if not self.synced_only:
                            lyrics = macro_calls.get("track.lyrics.get", {}).get("message", {}).get("body", {})
                            if lyrics and "lyrics" in lyrics:
                                return lyrics["lyrics"]["lyrics_body"]
        except Exception as e:
            logger.debug(f"[*] Erro ao buscar no Musixmatch: {e}")
        return None

    async def _fetch_netease_lyrics(self, artist, title):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        search_url = "https://music.163.com/api/search/get/"
        params = {"s": f"{title} {artist}", "type": "1", "offset": "0", "limit": "5"}

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(search_url, data=params, timeout=35) as resp:
                    data = await resp.json(content_type=None)
                    items = data.get("result", {}).get("songs", [])
                    if not items:
                        return None
                    song_id = items[0]["id"]

                lyric_url = f"https://music.163.com/api/song/lyric?os=pc&id={song_id}&lv=-1&kv=-1&tv=-1"
                async with session.get(lyric_url, timeout=40) as resp:
                    lyric_data = await resp.json(content_type=None)
                    lrc = lyric_data.get("lrc", {}).get("lyric", "")
                    return lrc if lrc else None
        except Exception as e:
            logger.debug(f"[*] Erro ao buscar no Netease: {e}")
        return None

    async def inject_manual_lyrics(self, file_path, raw_lyrics, is_synced=True):
        if not raw_lyrics:
            return False, 0, 0
        try:
            final_lyrics, trans_count, total_lines = await self._process_translation(raw_lyrics, is_synced=is_synced)
            self._inject_metadata(file_path, final_lyrics)
            if is_synced:
                self._save_lrc_file(file_path, final_lyrics)
            return True, trans_count, total_lines
        except Exception as e:
            logger.error(f"[!] Erro em inject_manual_lyrics: {e}")
            return False, 0, 0
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2

        if not overwrite and self._has_lyrics(file_path, check_lrc=True):
<<<<<<< HEAD
            return (False, False, messages) if return_message else (False, False)
=======
            return (True, 0, 0, "Local")
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2

        status = None
        try:
            # 1. Musixmatch
            mxm_lyrics = await self._fetch_musixmatch_lyrics(album_artist, track)
            if mxm_lyrics and (not self.synced_only or self._is_strictly_synced(mxm_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(mxm_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [Musixmatch]")

            # 2. LyricsPlus
            lyricsplus_lyrics = await self._fetch_lyrics_plus(album_artist, track)
            if lyricsplus_lyrics and (not self.synced_only or self._is_strictly_synced(lyricsplus_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(lyricsplus_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [LyricsPlus]")

            # 3. LRCLIB
            lrclib_url = "https://lrclib.net/api/get"
            headers = {"User-Agent": "qobuz-dl-master/2.5 (https://github.com/kaduvercosa/qobuz-dl)"}
            params = {"artist_name": album_artist, "track_name": track, "album_name": album}
            
<<<<<<< HEAD
            # Primário: LyricsPlus (Apple Music/Spotify backend via am-lyrics)
            lyrics_plus = await self._fetch_lyrics_plus(album_artist, track)
            if lyrics_plus:
                lyrics_plus = self._clean_syllable_sync(lyrics_plus)
                final_lyrics, deepl_status = await self._process_translation(lyrics_plus, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc:
                    self._save_lrc_file(file_path, final_lyrics)
                has_translation = (self.translation_symbol in final_lyrics)

                # Check for completely vs partially translated
                trad_status = self._get_translation_status(final_lyrics, has_translation)

                status_msg = f" | Status Code: {deepl_status}" if deepl_status else ""
                _log(f"  [*] Letra Encontrada: {album_artist} - {track} (via Apple/Spotify) | Sincronizada: Sim | Tradução: {trad_status}{status_msg}")
                return (True, has_translation, messages) if return_message else (True, has_translation)

            # Fallback 1: LRCLIB
            async with aiohttp.ClientSession() as session:
                async with session.get(lrclib_url, params=params, headers=headers, timeout=45) as response:
                    status = response.status
                    if status == 200:
                        data = await response.json()

                if status != 200:
                    params = {"artist_name": album_artist, "track_name": track}
                    async with session.get(lrclib_url, params=params, headers=headers, timeout=45) as response:
=======
            data = {}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(lrclib_url, params=params, headers=headers, timeout=35) as response:
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
                        status = response.status
                        if status == 200: data = await response.json()

                    if status != 200:
                        params = {"artist_name": album_artist, "track_name": track}
                        async with session.get(lrclib_url, params=params, headers=headers, timeout=35) as response:
                            status = response.status
                            if status == 200: data = await response.json()
            except Exception:
                status = "Erro_Rede"

            if status == 200:
                synced_lyrics = data.get("syncedLyrics")
                plain_lyrics = data.get("plainLyrics")
                
<<<<<<< HEAD
                if synced_lyrics:
                    # Clean the Apple Music/Spotify Syllable-sync tags for Neutron Player compatibility
                    synced_lyrics = self._clean_syllable_sync(synced_lyrics)
                    final_lyrics, deepl_status = await self._process_translation(synced_lyrics, is_synced=True)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    
                    trad_status = self._get_translation_status(final_lyrics, has_translation)
                    status_msg = f" | Status Code: {deepl_status}" if deepl_status else ""
                    _log(f"  [*] Letra Encontrada: {album_artist} - {track} (via LRCLIB) | Sincronizada: Sim | Tradução: {trad_status}{status_msg}")
                    return (True, has_translation, messages) if return_message else (True, has_translation)
                    
                elif plain_lyrics:
                    final_lyrics, deepl_status = await self._process_translation(plain_lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    
                    trad_status = self._get_translation_status(final_lyrics, has_translation)
                    status_msg = f" | Status Code: {deepl_status}" if deepl_status else ""
                    _log(f"  [*] Letra Encontrada: {album_artist} - {track} (via LRCLIB) | Sincronizada: Não | Tradução: {trad_status}{status_msg}")
                    return (True, has_translation, messages) if return_message else (True, has_translation)


            # Fallback 2: Netease (often has synced lyrics when LRCLIB fails)
            netease_lyric = await self._fetch_netease_lyrics(album_artist, track)
            if netease_lyric:
                netease_lyric = self._clean_syllable_sync(netease_lyric)
                final_lyrics, deepl_status = await self._process_translation(netease_lyric, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc:
                    self._save_lrc_file(file_path, final_lyrics)
                has_translation = (self.translation_symbol in final_lyrics)
                trad_status = self._get_translation_status(final_lyrics, has_translation)
                status_msg = f" | Status Code: {deepl_status}" if deepl_status else ""
                _log(f"  [*] Letra Encontrada: {album_artist} - {track} (via Netease) | Sincronizada: Sim | Tradução: {trad_status}{status_msg}")
                return (True, has_translation, messages) if return_message else (True, has_translation)

            # Fallback 2: Genius (Unsynced)
            if self.genius:
                song = await asyncio.to_thread(self.genius.search_song, track, album_artist)
                if song and song.lyrics:
                    final_lyrics, deepl_status = await self._process_translation(song.lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    
                    trad_status = self._get_translation_status(final_lyrics, has_translation)
                    status_msg = f" | Status Code: {deepl_status}" if deepl_status else ""
                    _log(f"  [*] Letra Encontrada: {album_artist} - {track} (via Genius) | Sincronizada: Não | Tradução: {trad_status}{status_msg}")
                    return (True, has_translation, messages) if return_message else (True, has_translation)

            _log(f"  [-] Letra não encontrada: {track}")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            _log(f"  [!] Falha ao buscar letra de {track} ({error_msg})")

        return (False, False, messages) if return_message else (False, False)

    def _get_translation_status(self, final_lyrics, has_translation):
        if not has_translation:
            return "Não"

        # Count lines with translations vs total valid text lines
        total_text_lines = 0
        translated_lines = 0

        for line in final_lyrics.split('\n'):
            line = line.strip()
            # Remove timestamp if present
            line_no_ts = re.sub(r'^(\[\d+:\d+(?:\.\d+)?\]\s*)+', '', line).strip()

            if line_no_ts:
                # Need to strip spaces from translation_symbol as `line_no_ts` is stripped
                if self.translation_symbol.strip() in line_no_ts:
                    translated_lines += 1
                else:
                    # If this line doesn't have the translation symbol, count it as an original text line
                    total_text_lines += 1

        # In our line-by-line format:
        # A fully translated song will have roughly equal translated_lines and total_text_lines
        # A partially translated song will have total_text_lines significantly larger than translated_lines
        # (Since total_text_lines counts every single line without a translation symbol)

        from qobuz_dl.color import GREEN, YELLOW, OFF

        if translated_lines == 0:
            return "Não"

        if total_text_lines > translated_lines * 1.5:
            return f"{YELLOW}Parcial{OFF}"

        return f"{GREEN}Completa{OFF}"
=======
                if synced_lyrics and self._is_strictly_synced(synced_lyrics):
                    final_lyrics, trans_count, total_lines = await self._process_translation(synced_lyrics, is_synced=True)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                    return (True, trans_count, total_lines, f"{status} [LRCLIB]")
                    
                # Apenas tenta PlainLyrics se synced_only estiver desligado
                elif plain_lyrics and not self.synced_only:
                    final_lyrics, trans_count, total_lines = await self._process_translation(plain_lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    return (True, trans_count, total_lines, f"{status} [LRCLIB]")

            # 4. Netease
            netease_lyrics = await self._fetch_netease_lyrics(album_artist, track)
            if netease_lyrics and (not self.synced_only or self._is_strictly_synced(netease_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(netease_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [Netease]")

            # 5. Genius (Ignorado se synced_only estiver ligado)
            if self.genius and not self.synced_only:
                song = await asyncio.to_thread(self.genius.search_song, track, album_artist)
                if song and song.lyrics:
                    final_lyrics, trans_count, total_lines = await self._process_translation(song.lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    return (True, trans_count, total_lines, "200 [Genius]")

        except Exception as e:
            logger.error(f"[!] Erro interno no fetch_and_inject: {e}", exc_info=True)

        return (False, 0, 0, status if status else "Não (Sem Sync)")
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        try:
            base_name = os.path.splitext(audio_file_path)[0]
            lrc_path = f"{base_name}.lrc"
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
        except Exception as e:
            logger.error(f"[!] Erro ao salvar arquivo .lrc: {e}")

    def _inject_metadata(self, file_path, lyrics):
        if not lyrics: return
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == '.flac':
                audio = FLAC(file_path)
                audio['LYRICS'] = lyrics
                audio.save()
            elif ext == '.mp3':
                try: audio = ID3(file_path)
                except ID3NoHeaderError: audio = ID3()
                audio.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
                audio.save(file_path)
<<<<<<< HEAD
        except Exception:
            pass

    async def inject_manual_lyrics(self, file_path, raw_lyrics, is_synced=True, save_lrc=True):
        """Used by the fix-lyrics interactive tool to manually inject a chosen string."""
        if not raw_lyrics:
            return False

        try:
            if is_synced:
                raw_lyrics = self._clean_syllable_sync(raw_lyrics)
                final_lyrics, deepl_status = await self._process_translation(raw_lyrics, is_synced=True)
            else:
                final_lyrics, deepl_status = await self._process_translation(raw_lyrics, is_synced=False)

            self._inject_metadata(file_path, final_lyrics)
            if save_lrc:
                self._save_lrc_file(file_path, final_lyrics)

            return True
        except Exception as e:
            logger.error(f"Failed to inject manual lyrics: {e}")
            return False
=======
        except Exception as e:
            logger.error(f"[!] Erro ao injetar metadados de lyrics: {e}")
>>>>>>> 76c7cf3e7fb22c6c157c0896e32e246525f3b2e2
