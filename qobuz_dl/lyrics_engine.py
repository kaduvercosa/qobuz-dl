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
    def __init__(self, genius_token=None, deepl_api_key=None, translate=True, target_lang='PT-BR', translation_symbol=" ¬ ", synced_only=True):
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
        
        # Lista de palavras que não precisam de tradução isolada
        self.pt_false_positives = {"oh", "yeah", "ah", "baby", "na", "la", "uh", "hey", "ooh", "woah"}

        if self.translate and self.deepl_api_key and DEEPL_AVAILABLE:
            try:
                self.deepl_translator = deepl.Translator(deepl_api_key)
            except Exception as e:
                logger.error(f"Erro DeepL: {e}")
                self.translate = False
        
        if self.genius_token and lyricsgenius:
            self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)

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

        # 1. Separar timestamps e textos, mantendo a estrutura original
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

        # 2. Filtrar linha por linha para ver o que realmente precisa de tradução
        if self.translate and self.deepl_translator:
            for i, (l_type, ts, txt) in enumerate(mapping):
                if l_type in ('synced', 'text'):
                    # Limpar pontuação para checar falsos positivos com precisão
                    clean_txt = re.sub(r'[^\w\s]', '', txt.lower()).strip()
                    words = set(clean_txt.split())
                    
                    # Ignora se a linha for composta APENAS por palavras como "oh", "yeah", "baby"
                    is_filler = bool(words) and words.issubset(self.pt_false_positives)
                    
                    # Detecta o idioma da linha
                    lang, conf = self._detect_lang(txt)
                    is_pt = lang and lang.startswith('pt') and conf > 0.75

                    # Adiciona na fila do DeepL apenas se NÃO for português e NÃO for filler
                    if not is_pt and not is_filler:
                        texts_to_translate.append((i, txt))

        count = 0
        # 3. Enviar para o DeepL em lote (somente as linhas estrangeiras)
        if texts_to_translate:
            try:
                raw_texts = [t[1] for t in texts_to_translate]
                results = await asyncio.to_thread(self.deepl_translator.translate_text, raw_texts, target_lang=self.target_lang)
                if not isinstance(results, list): 
                    results = [results]
                
                # Mapear o resultado de volta para o índice original da linha
                for idx_in_translate, res in enumerate(results):
                    original_idx = texts_to_translate[idx_in_translate][0]
                    translation_map[original_idx] = res.text
            except Exception as e:
                logger.error(f"Erro tradução DeepL: {e}")

        # 4. Reconstruir a letra final mesclando originais e traduções
        res_lines = []
        for i, (l_type, ts, txt) in enumerate(mapping):
            if l_type in ('synced', 'text'):
                res_lines.append(f"{ts if ts else ''}{txt}")
                
                # Se essa linha específica foi traduzida, injeta a tradução embaixo
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
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://lyricsplus.binimum.org/api/search?q={query}", timeout=40) as resp:
                    data = await resp.json(content_type=None)
                    song_id = data["data"][0]["id"] if data.get("data") else None
                    if not song_id: return None
                    resp = await session.get(f"https://lyricsplus.binimum.org/api/lyrics?id={song_id}", timeout=40)
                    lyric_data = await resp.json(content_type=None)
                    lrc = lyric_data.get("data", {}).get("syncedLyrics", "")
                    if not lrc and not self.synced_only: 
                        lrc = lyric_data.get("data", {}).get("plainLyrics", "")
                    return lrc if lrc else None
        except: 
            return None

    async def _fetch_musixmatch_lyrics(self, artist, title):
        headers = {"x-mxm-app-version": "10.1.1", "User-Agent": "Musixmatch/2025120901"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                resp = await session.get("https://apic-appmobile.musixmatch.com/ws/1.1/token.get?app_id=mac-ios-v2.0", timeout=50)
                data = await resp.json(content_type=None)
                token = data["message"]["body"]["user_token"]
                params = {"q_artist": artist, "q_track": title, "format": "json", "namespace": "lyrics_richsynched", "usertoken": token}
                resp = await session.get("https://apic-appmobile.musixmatch.com/ws/1.1/macro.subtitles.get?" + urllib.parse.urlencode(params), timeout=50)
                data = await resp.json(content_type=None)
                subtitles = data["message"]["body"]["macro_calls"]["track.subtitles.get"]["message"]["body"]
                if "subtitle_list" in subtitles: 
                    return subtitles["subtitle_list"][0]["subtitle"]["subtitle_body"]
        except: 
            return None

    async def _fetch_netease_lyrics(self, artist, title):
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                resp = await session.post("https://music.163.com/api/search/get/", data={"s": f"{title} {artist}", "type": "1"}, timeout=35)
                data = await resp.json(content_type=None)
                song_id = data["result"]["songs"][0]["id"]
                resp = await session.get(f"https://music.163.com/api/song/lyric?id={song_id}", timeout=40)
                return (await resp.json(content_type=None)).get("lrc", {}).get("lyric", "")
        except: 
            return None

    async def fetch_and_inject(self, file_path, album_artist, track, album, save_lrc=True, overwrite=False, return_message=False):
        if not overwrite and self._has_lyrics(file_path, check_lrc=True):
            return (True, 0, 0, "Local")

        status = None
        try:
            mxm_lyrics = await self._fetch_musixmatch_lyrics(album_artist, track)
            if mxm_lyrics and (not self.synced_only or self._is_strictly_synced(mxm_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(mxm_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [Musixmatch]")

            lyricsplus_lyrics = await self._fetch_lyrics_plus(album_artist, track)
            if lyricsplus_lyrics and (not self.synced_only or self._is_strictly_synced(lyricsplus_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(lyricsplus_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [LyricsPlus]")

            try:
                async with aiohttp.ClientSession() as session:
                    params = {"artist_name": album_artist, "track_name": track, "album_name": album}
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

            netease_lyrics = await self._fetch_netease_lyrics(album_artist, track)
            if netease_lyrics and (not self.synced_only or self._is_strictly_synced(netease_lyrics)):
                final_lyrics, trans_count, total_lines = await self._process_translation(netease_lyrics, is_synced=True)
                self._inject_metadata(file_path, final_lyrics)
                if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                return (True, trans_count, total_lines, "200 [Netease]")

            # Genius só será chamado se synced_only=False
            if self.genius and not self.synced_only:
                song = await asyncio.to_thread(self.genius.search_song, track, album_artist)
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
       # Injeta uma letra fornecida pelo menu interativo do retro_tagger
        if not raw_lyrics:
            return (False, 0, 0)

        try:
            # Passa a letra escolhida pelo nosso novo motor inteligente de tradução
            final_lyrics, trans_count, total_lines = await self._process_translation(raw_lyrics, is_synced=is_synced)
            
            # Injeta os metadados no arquivo de áudio (FLAC/MP3)
            self._inject_metadata(file_path, final_lyrics)
            
            # Salva o arquivo .lrc apenas se a letra for sincronizada
            if save_lrc and is_synced:
                self._save_lrc_file(file_path, final_lyrics)
                
            # Retornando EXATAMENTE os 3 valores que o retro_tagger espera
            return (True, trans_count, total_lines)
            
        except Exception as e:
            logger.error(f"Erro na injeção manual: {e}")
            return (False, 0, 0)

