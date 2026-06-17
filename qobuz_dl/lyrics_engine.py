import os
import re
import asyncio
import aiohttp
import logging
import urllib.parse
from mutagen.flac import FLAC
from mutagen.id3 import ID3, USLT, ID3NoHeaderError

class Tema:
    """
    =========================================
    SISTEMA DE CORES ADAPTAVEL (CLARO/ESCURO)
    =========================================
    """
    CYAN    = "\033[36m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    BLUE    = "\033[34m"   
    PURPLE  = "\033[35m"   
    BOLD    = "\033[1m"
    OFF     = "\033[0m"

    TAG       = BLUE           
    TITULO    = BOLD           
    SUCESSO   = GREEN          
    AVISO     = YELLOW         
    ERRO      = RED            
    DETALHES  = ""             

try: 
    import lyricsgenius
except ImportError: 
    lyricsgenius = None
    
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
logger = logging.getLogger(__name__)

class LyricsEngine:
    # Mantive o parametro deepl_api_key apenas para nao quebrar o cli.py, mas ele e ignorado.
    def __init__(self, genius_token=None, deepl_api_key=None, translate=True, target_lang='PT-BR', translation_symbol="  ~ ", synced_only=True, session=None):
        self.genius_token = genius_token
        self.genius = None
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        self.synced_only = synced_only 
        self.fasttext_model = None
        self._init_fasttext()
        
        self._mxm_token = None
        self.pt_false_positives = {"oh", "yeah", "ah", "baby", "na", "la", "uh", "hey", "ooh", "woah"}

        self.external_session = bool(session)
        self._shared_session = session
        
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

    async def _fetch_free_translation(self, text):
        url = "https://translate.googleapis.com/translate_a/single"
        lang_code = self.target_lang.lower()[:2]
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": lang_code,
            "dt": "t",
            "q": text
        }
        try:
            session = await self.get_session()
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    translated_text = "".join([linha[0] for linha in data[0] if linha[0]])
                    return translated_text
        except Exception as error:
            logger.error(f"Erro na API do Google: {error}")
            
        return text

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

        if self.translate:
            for i, (l_type, ts, txt) in enumerate(mapping):
                if l_type in ('synced', 'text'):
                    txt_no_tags = re.sub(r'<\d+:\d+(?:\.\d+)?>', '', txt)
                    clean_txt = re.sub(r'[^\w\s]', '', txt_no_tags.lower())
                    clean_txt = re.sub(r'\d+', '', clean_txt).strip()
                    
                    words = set(clean_txt.split())
                    is_filler = bool(words) and words.issubset(self.pt_false_positives)
                    lang, conf = self._detect_lang(txt_no_tags)
                    
                    is_pt = lang and lang.startswith('pt') and conf > 0.75

                    if not is_pt and not is_filler:
                        texts_to_translate.append((i, txt))

        count = 0
        if texts_to_translate:
            try:
                raw_texts = "\n".join([t[1] for t in texts_to_translate])
                translated_block = await self._fetch_free_translation(raw_texts)
                translated_lines = translated_block.split('\n')
                
                # Prevenir desalinhamento caso o Google engula alguma quebra de linha
                if len(translated_lines) == len(texts_to_translate):
                    for idx_array, (original_idx, txt) in enumerate(texts_to_translate):
                        translation_map[original_idx] = translated_lines[idx_array].strip()
                else:
                    # Fallback de seguranca linha por linha
                    sem = asyncio.Semaphore(5)
                    async def translate_single(idx, text_to_trans):
                        async with sem:
                            return idx, await self._fetch_free_translation(text_to_trans)
                            
                    tasks = [translate_single(idx, txt) for idx, txt in texts_to_translate]
                    resultados = await asyncio.gather(*tasks)
                    for idx, trad in resultados:
                        translation_map[idx] = trad.strip()
            except Exception as e:
                logger.error(f"Erro traducao Google: {e}")

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

    async def _fetch_lyrics_plus(self, artist, title):
        try:
            query = urllib.parse.quote(f"{title} {artist}")
            session = await self.get_session()
            
            async with session.get(f"https://lyricsplus.binimum.org/api/search?q={query}", timeout=8) as resp_search:
                data = await resp_search.json(content_type=None)
                song_id = data["data"][0]["id"] if data.get("data") else None
                
            if not song_id: return None
            
            async with session.get(f"https://lyricsplus.binimum.org/api/lyrics?id={song_id}", timeout=8) as resp_lyric:
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
        try:
            session = await self.get_session()
            if not self._mxm_token:
                async with session.get("https://apic-appmobile.musixmatch.com/ws/1.1/token.get?app_id=mac-ios-v2.0", headers=headers, timeout=8) as resp_token:
                    data_token = await resp_token.json(content_type=None)
                    if data_token.get("message", {}).get("header", {}).get("status_code") == 200:
                        self._mxm_token = data_token["message"]["body"]["user_token"]

            params = {
                "q_artist": artist, 
                "q_track": title, 
                "format": "json", 
                "namespace": "lyrics_richsynched", 
                "usertoken": self._mxm_token,
                "app_id": "mac-ios-v2.0"
            }
            
            async with session.get("https://apic-appmobile.musixmatch.com/ws/1.1/macro.subtitles.get", params=params, headers=headers, timeout=8) as resp_lyric:
                data = await resp_lyric.json(content_type=None)
                status_code = data.get("message", {}).get("header", {}).get("status_code")
                
                if status_code in (401, 403):
                    self._mxm_token = None
                    return None
                    
                if status_code == 200:
                    body = data["message"]["body"]
                    if "macro_calls" in body and "track.subtitles.get" in body["macro_calls"]:
                        sub_msg = body["macro_calls"]["track.subtitles.get"]["message"]
                        if sub_msg["header"]["status_code"] == 200 and "subtitle_list" in sub_msg["body"]:
                            subtitle_list = sub_msg["body"]["subtitle_list"]
                            if subtitle_list:
                                return subtitle_list[0]["subtitle"]["subtitle_body"]
        except:
            pass
        return None

    async def _fetch_netease_lyrics(self, artist, title):
        try:
            session = await self.get_session()
            headers = {"User-Agent": "Mozilla/5.0"}
            
            async with session.post("https://music.163.com/api/search/get/", headers=headers, data={"s": f"{title} {artist}", "type": "1"}, timeout=8) as resp_post:
                data = await resp_post.json(content_type=None)
                song_id = data["result"]["songs"][0]["id"]
            
            async with session.get(f"https://music.163.com/api/song/lyric?id={song_id}", headers=headers, timeout=8) as resp_get:
                lyric_data = await resp_get.json(content_type=None)
                return lyric_data.get("lrc", {}).get("lyric", "")
        except: 
            return None

    async def _fetch_lrclib_lyrics(self, artist, title, album, duration=0):
        try:
            session = await self.get_session()
            params = {"artist_name": artist, "track_name": title, "album_name": album}
            if duration > 0:
                params["duration"] = int(duration)
                
            async with session.get("https://lrclib.net/api/get", params=params, timeout=8) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    synced = data.get("syncedLyrics")
                    if synced: return synced
                    if not self.synced_only: return data.get("plainLyrics")
        except:
            pass
        return None

    async def fetch_and_inject(self, file_path, album_artist, track, album, duration=0, save_lrc=True, overwrite=False, return_message=False):
        if not overwrite and self._has_lyrics(file_path, check_lrc=True):
            return (True, 0, 0, "Local")

        clean_artist = re.split(r'(?i)\s*(?:,|\&| feat\.| ft\.|;|\/)\s*',album_artist)[0].strip() if album_artist else ""

        async def run_fetch(provider_name, fetch_coro):
            try:
                text = await fetch_coro
                if text:
                    is_synced = self._is_strictly_synced(text)
                    if is_synced or not self.synced_only:
                        return provider_name, text, is_synced
            except Exception:
                pass
            return provider_name, None, False

        tasks = [
            asyncio.create_task(run_fetch("Musixmatch", self._fetch_musixmatch_lyrics(clean_artist, track))),
            asyncio.create_task(run_fetch("LyricsPlus", self._fetch_lyrics_plus(clean_artist, track))),
            asyncio.create_task(run_fetch("LRCLIB", self._fetch_lrclib_lyrics(clean_artist, track, album, duration))),
            asyncio.create_task(run_fetch("Netease", self._fetch_netease_lyrics(clean_artist, track)))
        ]

        if self.genius and not self.synced_only:
            async def fetch_g():
                try:
                    song = await asyncio.wait_for(asyncio.to_thread(self.genius.search_song, track, clean_artist), timeout=8)
                    return song.lyrics if song and song.lyrics else None
                except:
                    return None
            tasks.append(asyncio.create_task(run_fetch("Genius", fetch_g())))

        best_plain_text = None
        best_plain_provider = None

        while tasks:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            
            for task in done:
                provider_name, text, is_synced = task.result()
                
                if text:
                    if is_synced:
                        for p in pending: 
                            p.cancel()
                            
                        final_lyrics, trans_count, total_lines = await self._process_translation(text, is_synced=True)
                        self._inject_metadata(file_path, final_lyrics)
                        if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                        
                        return (True, trans_count, total_lines, f"200 [{provider_name}]")
                    else:
                        if not best_plain_text:
                            best_plain_text = text
                            best_plain_provider = provider_name
                            
            tasks = list(pending)

        if best_plain_text and not self.synced_only:
            final_lyrics, trans_count, total_lines = await self._process_translation(best_plain_text, is_synced=False)
            self._inject_metadata(file_path, final_lyrics)
            return (True, trans_count, total_lines, f"200 [{best_plain_provider}]")

        return (False, 0, 0, "Nao Encontrada")

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
            logger.error(f"Erro na injecao manual: {e}")
            return (False, 0, 0)