import os
import re
import asyncio
import aiohttp
import logging
import sys
import difflib
import string
from mutagen.flac import FLAC
from mutagen.id3 import ID3, USLT, ID3NoHeaderError

# Import lyricsgenius apenas se o usuário tiver configurado o token
try:
    import lyricsgenius
except ImportError:
    lyricsgenius = None

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
        self.genius_token = genius_token
        self.genius = None
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        self.deepl_api_key = deepl_api_key
        self.translator = None
        
        if self.translate:
            if not DEEPL_AVAILABLE:
                print(f"\n\033[93m[!] AVISO: Módulo langdetect ausente. Tradução desabilitada! (Erro: {TRANSLATOR_IMPORT_ERROR})\033[0m")
                self.translate = False
            elif not self.deepl_api_key:
                print(f"\n\033[93m[!] AVISO: Nenhuma API Key do DeepL fornecida no config.ini. Tradução desabilitada!\033[0m")
                self.translate = False
            # O Translator oficial foi retirado para fazermos requisições nativas limpas (aiohttp)
        
        if self.genius_token and lyricsgenius:
            self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)

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
        """
        Filtro de Inteligência: Impede que correções gramaticais de gírias
        (ex: 'cê' -> 'você') ou linhas já no idioma alvo sejam duplicadas.
        """
        if not translated:
            return False

        orig_clean = original.strip().lower()
        trad_clean = translated.strip().lower()

        if orig_clean == trad_clean:
            return False

        # Remove pontuações para focar apenas nas palavras
        o_no_punct = orig_clean.translate(str.maketrans('', '', string.punctuation)).strip()
        t_no_punct = trad_clean.translate(str.maketrans('', '', string.punctuation)).strip()

        if not o_no_punct or not t_no_punct:
            return False

        if o_no_punct == t_no_punct:
            return False

        # Filtro 1: Se for uma palavra muito curta (gíria) que foi expandida (ex: "vê" em "veja")
        if len(o_no_punct) <= 5 and o_no_punct in t_no_punct:
            return False

        # Filtro 2: Similaridade alta.
        # Ajustado de 0.75 para 0.85 para permitir a tradução de palavras curtas de idiomas parecidos
        # (ex: espanhol "mi amor" para português "meu amor" dá 0.80)
        ratio = difflib.SequenceMatcher(None, o_no_punct, t_no_punct).ratio()
        if ratio > 0.85:
            return False

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

        if not texts_to_translate:
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
        # Removemos o filtro de tamanho (len) conforme solicitado, para traduzir qualquer palavra isolada.
        lines_to_deepl = []
        indices_to_translate = [] # Mapeia quais índices do 'texts_to_translate' realmente enviamos

        for i, txt in enumerate(texts_to_translate):
            txt_clean = txt.strip()
            if not txt_clean:
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

        result_lines = []
        trans_idx = 0
        has_valid_translations = False # Variável para checar se traduziu pelo menos uma linha útil

        for item in line_mapping:
            l_type, ts, txt = item

            if l_type == 'synced':
                result_lines.append(f"{ts}{txt}")
                if trans_idx < len(translated_texts):
                    traducao = translated_texts[trans_idx]
                    if self._is_valid_translation(txt, traducao):
                        result_lines.append(f"{ts}{self.translation_symbol}{traducao}")
                        has_valid_translations = True
                trans_idx += 1

            elif l_type == 'text':
                result_lines.append(txt)
                if trans_idx < len(translated_texts):
                    traducao = translated_texts[trans_idx]
                    if self._is_valid_translation(txt, traducao):
                        result_lines.append(f"{self.translation_symbol}{traducao}")
                        has_valid_translations = True
                trans_idx += 1

            elif l_type == 'empty_synced':
                result_lines.append(f"{ts}")

            elif l_type in ('raw', 'empty'):
                result_lines.append(txt)

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

        if not overwrite and self._has_lyrics(file_path, check_lrc=True):
            return (False, False, messages) if return_message else (False, False)

        try:
            lrclib_url = "https://lrclib.net/api/get"
            headers = {"User-Agent": "qobuz-dl-master/2.5 (https://github.com/kaduvercosa/qobuz-dl)"}

            params = {"artist_name": album_artist, "track_name": track, "album_name": album}

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
                        status = response.status
                        if status == 200:
                            data = await response.json()

            if status == 200:
                synced_lyrics = data.get("syncedLyrics")
                plain_lyrics = data.get("plainLyrics")

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

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        try:
            base_name = os.path.splitext(audio_file_path)[0]
            lrc_path = f"{base_name}.lrc"
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
        except Exception:
            pass

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
                audio.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
                audio.save(file_path)
        except Exception:
            pass
