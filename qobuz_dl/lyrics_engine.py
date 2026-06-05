import os
import re
import asyncio
import aiohttp
import logging
import urllib.parse
from mutagen.flac import FLAC
from mutagen.id3 import ID3, USLT, ID3NoHeaderError

# Imports opcionais
try: 
    import lyricsgenius
except ImportError: 
    lyricsgenius = None
    
try: 
    import deepl
    DEEPL_AVAILABLE = True
except ImportError: 
    deepl = None
    DEEPL_AVAILABLE = False
    
try: 
    import fasttext
    fasttext.FastText.eprint = lambda x: None
except ImportError: 
    fasttext = None
    
try: 
    from langdetect import detect as langdetect_detect
except ImportError: 
    langdetect_detect = None

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("deepl").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

class LyricsEngine:
    # O parâmetro session=None foi restaurado aqui!
    def __init__(self, genius_token=None, deepl_api_key=None, translate=True, target_lang='PT-BR', translation_symbol=" ¬ ", synced_only=True, session=None):
        self.genius_token = genius_token
        self.genius = None
        self.deepl_api_key = deepl_api_key
        self.deepl_translator = None
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        self.synced_only = synced_only 
        self.fasttext_model = None
        self._init_fasttext()
        
        # Cache do token para evitar Rate Limit e Banimentos do Musixmatch
        self._mxm_token = None
        
        # Lista de palavras que não precisam de tradução isolada
        self.pt_false_positives = {"oh", "yeah", "ah", "baby", "na", "la", "uh", "hey", "ooh", "woah"}

        # Gestão Inteligente da Sessão
        self.external_session = bool(session)
        self._shared_session = session

        if self.translate and self.deepl_api_key and DEEPL_AVAILABLE:
            try:
                self.deepl_translator = deepl.Translator(deepl_api_key)
            except Exception as e:
                logger.error(f"Erro DeepL: {e}")
                self.translate = False
        
        if self.genius_token and lyricsgenius:
            self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)

    async def get_session(self):
        if self._shared_session is None or self._shared_session.closed:
            connector = aiohttp.TCPConnector(ssl=False, limit=0)
            self._shared_session = aiohttp.ClientSession(connector=connector)
            self.external_session = False
        return self._shared_session

    async def close(self):
        if not self.external_session and self._shared_session and not self._shared_session.closed:
            await self._shared_session.close()

    def _init_fasttext(self):
        if not fasttext: return
        model_path = os.path.join(os.path.dirname(__file__), "lid.176.ftz")
        try:
            if not os.path.exists(model_path):
                import urllib.request
                urllib.request.urlretrieve("https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz", model_path)
            self.fasttext_model = fasttext.load_model(model_path)
        except: 
            pass

    def _detect_lang(self, text):
        if self.fasttext_model:
            try:
                res = self.fasttext_model.predict(text.replace('\n', ' '))
                return res[0][0].replace('__label__', ''), float(res[1][0])
            except: 
                pass
        if langdetect_detect:
            try: 
                return langdetect_detect(text), 0.5
            except: 
                pass
        return None, 0.0

    def _is_strictly_synced(self, text):
        return bool(re.search(r'\[\d+:\d+(?:\.\d+)?\]', text))

    def _has_lyrics(self, file_path, check_lrc=True):
        if check_lrc:
            base_name = os.path.splitext(file_path)[0]
            if os.path.exists(f"{base_name}.lrc"):
                return True
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == '.flac':
                audio = FLAC(file_path)
                if audio.get('LYRICS') or audio.get('UNSYNCEDLYRICS'): return True
            elif ext == '.mp3':
                try: 
                    audio = ID3(file_path)
                except ID3NoHeaderError: 
                    return False
                if any(frame.FrameID in ['USLT', 'SYLT'] for frame in audio.values()): return True
        except: 
            pass
        return False

    async def _process_translation(self, lyrics, is_synced=True):
        lines = lyrics.split('\n')
        mapping = []
        texts_to_translate = []
        translation_map = {}

        for i, line in enumerate(lines):
            if not line.strip(): 
                mapping.append(('empty', None, ''))
                continue
                
            match = re.match(r'^((?:\[\d+:\d+(?:\.\d+)?\]\s*)+)(.*)', line) if is_synced else None
            if match:
                ts, txt = match.group(1), match.group(2).strip()
                if txt: 
                    mapping.append(('synced', ts, txt))
                else: 
                    mapping.append(('empty_synced', ts, ''))
            else:
                txt = line.strip()
                if txt: 
                    mapping.append(('text', None, txt))
                else: 
                    mapping.append(('empty', None, ''))

        if self.translate and self.deepl_translator:
            for i, (l_type, ts, txt) in enumerate(mapping):
                if l_type in ('synced', 'text'):
                    clean_txt = re.sub(r'[^\w\s]', '', txt.lower()).strip()
                    words = set(clean_txt.split())
                    
                    is_filler = bool(words) and words.issubset(self.pt_false_positives)
                    lang, conf = self._detect_lang(txt)
                    is_pt = lang and lang.startswith('pt') and conf > 0.75

                    if not is_pt and not is_filler:
                        texts_to_translate.append((i, txt))

        count = 0
        if texts_to_translate:
            try:
                raw_texts = [t[1] for t in texts_to_translate]
                results = await asyncio.to_thread(self.deepl_translator.translate_text, raw_texts, target_lang=self.target_lang)
                if not isinstance(results, list): 
                    results = [results]
                
                for idx_in_translate, res in enumerate(results):
                    original_idx = texts_to_translate[idx_in_translate][0]
                    translation_map[original_idx] = res.text
            except Exception as e:
                logger.error(f"Erro tradução DeepL: {e}")

        res_lines = []
        for i, (l_type, ts, txt) in enumerate(mapping):
            if l_type in ('synced', 'text'):
                res_lines.append(f"{ts if ts else ''}{txt}")
                
                if i in translation_map:
                    trad = translation_map[i]
                    if txt.lower() != trad.lower():
                        res_lines.append(f"{ts if ts else ''}{self.translation_symbol}{trad}")
                        count += 1
            elif l_type == 'empty_synced': 
                res_lines.append(ts)
            else: 
                res_lines.append(txt)

        total_valid_lines = len([m for m in mapping if m[0] in ('synced', 'text')])
        return '\n'.join(res_lines), count, total_valid_lines

    # ---------------------------------------------------------
    # SCRAPERS BLINDADOS (Uso de get_session() nativo)
    # ---------------------------------------------------------
    async def _fetch_lyrics_plus(self, artist, title):
        try:
            query = urllib.parse.quote(f"{title} {artist}")
            session = await self.get_session()
            
            async with session.get(f"https://lyricsplus.binimum.org/api/search?q={query}", timeout=40) as resp_search:
                data = await resp_search.json(content_type=None)
                song_id = data["data"][0]["id"] if data.get("data") else None
                
            if not song_id: return None
            
            async with session.get(f"https://lyricsplus.binimum.org/api/lyrics?id={song_id}", timeout=40) as resp_lyric:
                lyric_data = await resp_lyric.json(content_type=None)
                lrc = lyric_data.get("data", {}).get("syncedLyrics", "")
                if not lrc and not self.synced_only: 
                    lrc = lyric_data.get("data", {}).get("plainLyrics", "")
                return lrc if lrc else None
        except: 
            return None

    async def _fetch_musixmatch_lyrics(self, artist, title):
        headers = {
            "x-mxm-app-version": "10.1.1", 
            "User-Agent": "Musixmatch/2025120901 CFNetwork/1404.0.5 Darwin/22.3.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        max_retries = 2
        for attempt in range(max_retries):
            try:
                session = await self.get_session()
                
                if not self._mxm_token:
                    async with session.get("https://apic-appmobile.musixmatch.com/ws/1.1/token.get?app_id=mac-ios-v2.0", headers=headers, timeout=30) as resp_token:
                        data_token = await resp_token.json(content_type=None)
                        if data_token.get("message", {}).get("header", {}).get("status_code") == 200:
                            self._mxm_token = data_token["message"]["body"]["user_token"]
                        else:
                            await asyncio.sleep(1)
                            continue

                params = {
                    "q_artist": artist, 
                    "q_track": title, 
                    "format": "json", 
                    "namespace": "lyrics_richsynched", 
                    "usertoken": self._mxm_token,
                    "app_id": "mac-ios-v2.0"
                }
                
                async with session.get("https://apic-appmobile.musixmatch.com/ws/1.1/macro.subtitles.get", params=params, headers=headers, timeout=30) as resp_lyric:
                    data = await resp_lyric.json(content_type=None)
                    status_code = data.get("message", {}).get("header", {}).get("status_code")
                    
                    if status_code in (401, 403):
                        logger.debug("[!] Musixmatch revogou o token. Gerando um novo...")
                        self._mxm_token = None
                        await asyncio.sleep(1.5)
                        continue
                        
                    if status_code == 200:
                        body = data["message"]["body"]
                        if "macro_calls" in body and "track.subtitles.get" in body["macro_calls"]:
                            sub_msg = body["macro_calls"]["track.subtitles.get"]["message"]
                            if sub_msg["header"]["status_code"] == 200 and "subtitle_list" in sub_msg["body"]:
                                subtitle_list = sub_msg["body"]["subtitle_list"]
                                if subtitle_list:
                                    return subtitle_list[0]["subtitle"]["subtitle_body"]
                    break
                    
            except Exception as e: 
                logger.debug(f"[*] Erro Musixmatch (tentativa {attempt+1}): {e}")
                await asyncio.sleep(1)
                
        return None

    async def _fetch_netease_lyrics(self, artist, title):
        try:
            session = await self.get_session()
            headers = {"User-Agent": "Mozilla/5.0"}
            
            async with session.post("https://music.163.com/api/search/get/", headers=headers, data={"s": f"{title} {artist}", "type": "1"}, timeout=35) as resp_post:
                data = await resp_post.json(content_type=None)
                song_id = data["result"]["songs"][0]["id"]
            
            async with session.get(f"https://music.163.com/api/song/lyric?id={song_id}", headers=headers, timeout=40) as resp_get:
                lyric_data = await resp_get.json(content_type=None)
                return lyric_data.get("lrc", {}).get("lyric", "")
        except: 
            return None

    # ---------------------------------------------------------

    async def fetch_and_inject(self, file_path, album_artist, track, album, save_lrc=True, overwrite=False, return_message=False):
        if not overwrite and self._has_lyrics(file_path, check_lrc=True):
            return (True, 0, 0, "Local")

        clean_artist = re.split(r'(?i)\s*(?:,|\&| feat\.| ft\.|;|\/)\s*',album_artist)[0].strip() if album_artist else ""
 
        status = None
        try:
            mxm_lyrics = await self._fetch_musixmatch_lyrics(clean_artist, track)
            if mxm_lyrics and (not self.synced_only or self._is_strictly_synced(mxm_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(mxm_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [Musixmatch]")

            lyricsplus_lyrics = await self._fetch_lyrics_plus(clean_artist, track)
            if lyricsplus_lyrics and (not self.synced_only or self._is_strictly_synced(lyricsplus_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(lyricsplus_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [LyricsPlus]")

            try:
                session = await self.get_session()
                params = {"artist_name": clean_artist, "track_name": track, "album_name": album}
                async with session.get("https://lrclib.net/api/get", params=params, timeout=15) as resp:
                    status = resp.status
                    if status == 200:
                        data = await resp.json()
                        synced_lyrics = data.get("syncedLyrics")
                        plain_lyrics = data.get("plainLyrics")
                        if synced_lyrics and (not self.synced_only or self._is_strictly_synced(synced_lyrics)):
                            final_lyrics, trans_count, total_lines = await self._process_translation(synced_lyrics, is_synced=True)
                            self._inject_metadata(file_path, final_lyrics)
                            if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                            return (True, trans_count, total_lines, f"{status} [LRCLIB]")
                        elif plain_lyrics and not self.synced_only:
                            final_lyrics, trans_count, total_lines = await self._process_translation(plain_lyrics, is_synced=False)
                            self._inject_metadata(file_path, final_lyrics)
                            return (True, trans_count, total_lines, f"{status} [LRCLIB]")
            except Exception as e:
                logger.debug(f"[*] Erro LRCLIB: {e}")

            netease_lyrics = await self._fetch_netease_lyrics(clean_artist, track)
            if netease_lyrics and (not self.synced_only or self._is_strictly_synced(netease_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(netease_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [Netease]")

            if self.genius and not self.synced_only:
                song = await asyncio.to_thread(self.genius.search_song, track, clean_artist)
                if song and song.lyrics:
                    final_lyrics, trans_count, total_lines = await self._process_translation(song.lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    return (True, trans_count, total_lines, "200 [Genius]")

        except Exception as e:
            logger.error(f"[!] Erro no fetch_and_inject: {e}")

        return (False, 0, 0, status if status else "Não (Sem Sync)")

    def _inject_metadata(self, file_path, lyrics):
        if not lyrics: return
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
        except Exception as e: 
            logger.error(f"Erro metadados: {e}")

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        try:
            with open(f"{os.path.splitext(audio_file_path)[0]}.lrc", 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
        except: 
            pass
            
    async def inject_manual_lyrics(self, file_path, raw_lyrics, is_synced=True, save_lrc=True, **kwargs):
        if not raw_lyrics:
            return (False, 0, 0)

        try:
            final_lyrics, trans_count, total_lines = await self._process_translation(raw_lyrics, is_synced=is_synced)
            self._inject_metadata(file_path, final_lyrics)
            
            if save_lrc and is_synced:
                self._save_lrc_file(file_path, final_lyrics)
                
            return (True, trans_count, total_lines)
            
        except Exception as e:
            logger.error(f"Erro na injeção manual: {e}")
            return (False, 0, 0)