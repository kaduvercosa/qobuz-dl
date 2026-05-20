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
        """Retorna o código do idioma usando fasttext (primário) ou langdetect."""
        if self.fasttext_model:
            try:
                text_clean = text.replace('\n', ' ')
                res = self.fasttext_model.predict(text_clean)
                label = res[0][0] # ex: '__label__en'
                return label.replace('__label__', '')
            except Exception:
                pass

        if langdetect_detect:
            try:
                return langdetect_detect(text)
            except Exception:
                pass
        return None

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

        dominant_lang = self._detect_lang(full_text)
        if dominant_lang and dominant_lang.lower() == target_lang_code:
            logger.debug(f"[*] Texto já está em {self.target_lang}, pulando tradução")
            return lyrics, 0, total_lines

        # 2. PREPARAR LINHAS PARA TRADUÇÃO (Restaurado filtro linha-por-linha via Fasttext)
        lines_to_translate = []
        indices_to_translate = []
        
        for i, txt in enumerate(texts_to_translate):
            txt_clean = txt.strip()
            if not txt_clean:
                continue

            # Filtro re-adicionado usando Fasttext e dicionário de falsos positivos
            words = txt_clean.lower().split()
            if len(words) >= 1:
                # Se for apenas palavras irrelevantes/ruídos, evite pular achando que é PT-BR
                is_false_positive = all(w in self.pt_false_positives for w in words)

                if not is_false_positive:
                    line_lang = self._detect_lang(txt_clean)
                    if line_lang and line_lang.lower() == target_lang_code:
                        continue  # Já está no idioma alvo real, pula

            lines_to_translate.append(txt_clean)
            indices_to_translate.append(i)

        if not lines_to_translate:
            logger.debug("[*] Nenhuma linha para traduzir após filtros")
            return lyrics, 0, total_lines

        # 3. TRADUÇÃO EM LOTE COM DEEPL
        translated_texts = [""] * len(texts_to_translate)
        try:
            logger.debug(f"[*] Iniciando tradução DeepL para {len(lines_to_translate)} linhas (idioma alvo: {self.target_lang})")
            
            # Executa tradução de forma assíncrona
            translated_results = await asyncio.to_thread(
                self.deepl_translator.translate_text,
                lines_to_translate,
                target_lang=self.target_lang
            )

            # Se retornar um único resultado, converte para lista
            if not isinstance(translated_results, list):
                translated_results = [translated_results]

            # Mapeia os resultados de volta ao índice original
            for original_idx, translated_text in zip(indices_to_translate, translated_results):
                translated_texts[original_idx] = translated_text.text if hasattr(translated_text, 'text') else str(translated_text)

            logger.debug(f"[*] Tradução concluída: {len([t for t in translated_texts if t])} linhas traduzidas")

        except Exception as e:
            logger.error(f"[!] Erro fatal na tradução DeepL: {e}")
            print(f"\n\033[91m[!] Erro ao traduzir com DeepL: {e}\033[0m")
            return lyrics, 0, total_lines

        # 4. REMONTAR AS LINHAS COM TRADUÇÃO
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

        logger.debug(f"[*] Tradução processada: {translation_count} linhas com tradução válida")
        return '\n'.join(result_lines), translation_count, total_lines

    async def _fetch_lyrics_plus(self, artist, title):
        """Busca letras no LyricsPlus (Apple Music)."""
        import urllib.parse
        try:
            query = urllib.parse.quote(f"{title} {artist}")
            search_url = f"https://lyricsplus.binimum.org/api/search?q={query}"

            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, timeout=10) as resp:
                    data = await resp.json(content_type=None)
                    items = data.get("data", [])
                    if not items:
                        return None
                    song_id = items[0]["id"]

                lyric_url = f"https://lyricsplus.binimum.org/api/lyrics?id={song_id}"
                async with session.get(lyric_url, timeout=10) as resp:
                    lyric_data = await resp.json(content_type=None)
                    lrc = lyric_data.get("data", {}).get("syncedLyrics", "")
                    if not lrc:
                        lrc = lyric_data.get("data", {}).get("plainLyrics", "")
                    return lrc if lrc else None
        except Exception as e:
            logger.debug(f"[*] Erro ao buscar no LyricsPlus: {e}")
        return None

    async def _fetch_musixmatch_lyrics(self, artist, title):
        """Busca letras sincronizadas no Musixmatch usando endpoint mobile."""
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
                async with session.get(url, timeout=10) as resp:
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
                async with session.get(url, timeout=10) as resp:
                    data = await resp.json(content_type=None)
                    if data.get("message", {}).get("header", {}).get("status_code") == 200:
                        macro_calls = data["message"]["body"]["macro_calls"]
                        subtitles = macro_calls.get("track.subtitles.get", {}).get("message", {}).get("body", {})
                        if subtitles and "subtitle_list" in subtitles and len(subtitles["subtitle_list"]) > 0:
                            return subtitles["subtitle_list"][0]["subtitle"]["subtitle_body"]

                        lyrics = macro_calls.get("track.lyrics.get", {}).get("message", {}).get("body", {})
                        if lyrics and "lyrics" in lyrics:
                            return lyrics["lyrics"]["lyrics_body"]
        except Exception as e:
            logger.debug(f"[*] Erro ao buscar no Musixmatch: {e}")
        return None

    async def _fetch_netease_lyrics(self, artist, title):
        """Busca letras no Netease Music."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        search_url = "https://music.163.com/api/search/get/"
        params = {
            "s": f"{title} {artist}",
            "type": "1",
            "offset": "0",
            "limit": "5"
        }

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(search_url, data=params, timeout=10) as resp:
                    data = await resp.json(content_type=None)
                    items = data.get("result", {}).get("songs", [])
                    if not items:
                        return None
                    song_id = items[0]["id"]

                lyric_url = f"https://music.163.com/api/song/lyric?os=pc&id={song_id}&lv=-1&kv=-1&tv=-1"
                async with session.get(lyric_url, timeout=10) as resp:
                    lyric_data = await resp.json(content_type=None)
                    lrc = lyric_data.get("lrc", {}).get("lyric", "")
                    return lrc if lrc else None
        except Exception as e:
            logger.debug(f"[*] Erro ao buscar no Netease: {e}")
        return None

    async def inject_manual_lyrics(self, file_path, raw_lyrics, is_synced=True):
        """Injeta a letra manualmente no arquivo. Retorna bool indicando sucesso."""
        if not raw_lyrics:
            return False

        try:
            final_lyrics, _, _ = await self._process_translation(raw_lyrics, is_synced=is_synced)
            self._inject_metadata(file_path, final_lyrics)
            if is_synced:
                self._save_lrc_file(file_path, final_lyrics)
            return True
        except Exception as e:
            logger.error(f"[!] Erro em inject_manual_lyrics: {e}")
            return False

    async def fetch_and_inject(self, file_path, album_artist, track, album, save_lrc=True, overwrite=False):
        """
        Busca e injeta as letras em arquivo de áudio.
        
        Retorna:
            (bool, int, int, str|int): (sucesso, linhas_traduzidas, total_linhas, status_code)
        """
        if not overwrite and self._has_lyrics(file_path, check_lrc=True):
            logger.debug(f"[*] Arquivo já possui letras: {file_path}")
            return (True, 0, 0, "Local")

        status = None
        try:
            # 1. Tentar Musixmatch (Prioridade Máxima)
            logger.debug(f"[*] Tentando Musixmatch para: {track}")
            mxm_lyrics = await self._fetch_musixmatch_lyrics(album_artist, track)
            if mxm_lyrics:
                logger.debug(f"[*] Letra encontrada no Musixmatch para: {track}")
                final_lyrics, trans_count, total_lines = await self._process_translation(mxm_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc:
                    self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [Musixmatch]")

            # 2. Tentar LyricsPlus (Apple Music)
            logger.debug(f"[*] Tentando LyricsPlus para: {track}")
            lyricsplus_lyrics = await self._fetch_lyrics_plus(album_artist, track)
            if lyricsplus_lyrics:
                logger.debug(f"[*] Letra encontrada no LyricsPlus para: {track}")
                final_lyrics, trans_count, total_lines = await self._process_translation(lyricsplus_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc:
                    self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [LyricsPlus]")

            # 3. Tentar LRCLIB (Fallback 1)
            logger.debug(f"[*] Tentando LRCLIB para: {track}")
            lrclib_url = "https://lrclib.net/api/get"
            headers = {"User-Agent": "qobuz-dl-master/2.5 (https://github.com/kaduvercosa/qobuz-dl)"}
            
            params = {"artist_name": album_artist, "track_name": track, "album_name": album}
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(lrclib_url, params=params, headers=headers, timeout=12) as response:
                        status = response.status
                        if status == 200:
                            data = await response.json()

                    if status != 200:
                        params = {"artist_name": album_artist, "track_name": track}
                        async with session.get(lrclib_url, params=params, headers=headers, timeout=12) as response:
                            status = response.status
                            if status == 200:
                                data = await response.json()
            except asyncio.TimeoutError:
                logger.debug(f"[*] LRCLIB demorou muito a responder (Timeout) para: {track}")
                status = "Timeout"
            except aiohttp.ClientError as e:
                logger.debug(f"[*] Erro de rede ao contatar LRCLIB para {track}: {e}")
                status = "Erro_Rede"

            if status == 200:
                synced_lyrics = data.get("syncedLyrics")
                plain_lyrics = data.get("plainLyrics")
                
                if synced_lyrics:
                    logger.debug(f"[*] Letras sincronizadas encontradas no LRCLIB para: {track}")
                    final_lyrics, trans_count, total_lines = await self._process_translation(synced_lyrics, is_synced=True)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return (True, trans_count, total_lines, f"{status} [LRCLIB]")
                    
                elif plain_lyrics:
                    logger.debug(f"[*] Letras simples encontradas no LRCLIB para: {track}")
                    final_lyrics, trans_count, total_lines = await self._process_translation(plain_lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return (True, trans_count, total_lines, f"{status} [LRCLIB]")

            # 4. Tentar Netease (Fallback 2)
            logger.debug(f"[*] Tentando Netease para: {track}")
            netease_lyrics = await self._fetch_netease_lyrics(album_artist, track)
            if netease_lyrics:
                logger.debug(f"[*] Letra encontrada no Netease para: {track}")
                final_lyrics, trans_count, total_lines = await self._process_translation(netease_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc:
                    self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [Netease]")

            # 5. Tentar Genius (Fallback Final)
            if self.genius:
                logger.debug(f"[*] Tentando Genius API para: {track}")
                song = await asyncio.to_thread(self.genius.search_song, track, album_artist)
                if song and song.lyrics:
                    logger.debug(f"[*] Letra encontrada via Genius para: {track}")
                    final_lyrics, trans_count, total_lines = await self._process_translation(song.lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return (True, trans_count, total_lines, "200 [Genius]")

            logger.debug(f"[!] Nenhuma letra encontrada para: {track}")

        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            print(f"\033[91m[!] Erro interno ao processar letras: {error_msg}\033[0m")
            logger.error(f"[!] Erro interno no fetch_and_inject: {error_msg}", exc_info=True)

        return (False, 0, 0, status if status else "Não")

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        """Salva as letras em arquivo .lrc com tratamento de erro."""
        try:
            base_name = os.path.splitext(audio_file_path)[0]
            lrc_path = f"{base_name}.lrc"
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
            logger.debug(f"[*] Arquivo .lrc salvo: {lrc_path}")
        except Exception as e:
            logger.error(f"[!] Erro ao salvar arquivo .lrc: {e}")

    def _inject_metadata(self, file_path, lyrics):
        """Injeta as letras nos metadados do arquivo de áudio."""
        if not lyrics:
            return
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == '.flac':
                audio = FLAC(file_path)
                audio['LYRICS'] = lyrics
                audio.save()
                logger.debug(f"[*] Metadados FLAC injetados: {file_path}")
            elif ext == '.mp3':
                try:
                    audio = ID3(file_path)
                except ID3NoHeaderError:
                    audio = ID3()
                audio.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
                audio.save(file_path)
                logger.debug(f"[*] Metadados ID3 injetados: {file_path}")
        except Exception as e:
            logger.error(f"[!] Erro ao injetar metadados de lyrics: {e}")