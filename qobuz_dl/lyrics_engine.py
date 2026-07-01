import os
import re
import asyncio
import aiohttp
import logging
import urllib.parse
import json
from mutagen.flac import FLAC
from mutagen.id3 import ID3, USLT, ID3NoHeaderError
from qobuz_dl.color import Tema

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
    def __init__(self, genius_token=None, deepl_api_key=None, translate=True, target_lang='PT-BR', translation_symbol="   ~ ", synced_only=True, session=None):
        self.genius_token = genius_token
        self.deepl_api_key = deepl_api_key
        self._deepl_quota_exceeded = False
        self.genius = None
        self.translate = translate 
        self.target_lang = target_lang
        self.translation_symbol = self._decode_symbol_escapes(translation_symbol)
        self.synced_only = synced_only 
        self.fasttext_model = None
        self._init_fasttext()
        
        self._mxm_token = None
        self.pt_false_positives = {"oh", "yeah", "ah", "baby", "na", "la", "uh", "hey", "ooh", "woah"}

        self.external_session = bool(session)
        self._shared_session = session
        
        if self.genius_token and lyricsgenius:
            self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)

    @staticmethod
    def _decode_symbol_escapes(raw: str) -> str:
        """
        Converte sequências de escape em caracteres reais protegidos contra o trim dos leitores.
        - \\s vira 1 Non-Breaking Space (\\u00A0)
        - \\t vira 4 Non-Breaking Spaces (\\u00A0\\u00A0\\u00A0\\u00A0) para simular um Tab indestrutível
        - \\n vira uma quebra de linha real
        """
        if not raw:
            return raw
        return (raw
                .replace("\\\\", "\x00")  # Protege as barras invertidas literais
                .replace("\\t", "\u00A0\u00A0\u00A0\u00A0") # Tab convertido em 4 NBSP contra trim
                .replace("\\s", "\u00A0") # Espaço convertido em NBSP
                .replace("\\n", "\n")
                .replace("\x00", "\\"))

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

    def _target_lang_code(self):
        """Código ISO 639-1 (2 letras) do idioma alvo definido no config.ini (ex: 'PT-BR' -> 'pt')."""
        return self.target_lang.lower()[:2]

    def _line_matches_target(self, lang, conf, min_conf=0.75):
        """Verifica se o idioma detectado de uma linha já corresponde ao idioma alvo do config.ini."""
        if not lang:
            return False
        return lang.lower().startswith(self._target_lang_code()) and conf > min_conf

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

    async def _fetch_deepl_translation(self, text):
        if getattr(self, '_deepl_quota_exceeded', False) or not self.deepl_api_key:
            return None
        
        url = "https://api-free.deepl.com/v2/translate" if self.deepl_api_key.endswith(":fx") else "https://api.deepl.com/v2/translate"
        tl = self.target_lang.upper()
        if tl.startswith("PT"): tl = "PT-BR" if "BR" in tl else "PT-PT"
        elif tl.startswith("EN"): tl = "EN-US"
        else: tl = tl[:2]

        params = {"auth_key": self.deepl_api_key, "text": text, "target_lang": tl}
        try:
            session = await self.get_session()
            async with session.post(url, data=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["translations"][0]["text"]
                elif response.status == 456:
                    self._deepl_quota_exceeded = True
                    print(f" {Tema.AVISO}⚠️ Cota mensal do DeepL (500k) excedida! Transição invisível para o Google Translate ativada.{Tema.OFF}")
                    return None
        except Exception as e:
            logger.error(f"Erro na API do DeepL: {e}")
        return None

    async def _fetch_free_translation(self, text, max_retries=3):
        url = "https://translate.googleapis.com/translate_a/single"
        lang_code = self._target_lang_code()
        params = {"client": "gtx", "sl": "auto", "tl": lang_code, "dt": "t", "q": text}
        session = await self.get_session()

        for tentativa in range(max_retries):
            try:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return "".join([linha[0] for linha in data[0] if linha[0]])
                    elif response.status == 429:
                        espera = 2 ** tentativa
                        logger.warning(f"Google Translate retornou 429 (rate limit). Aguardando {espera}s antes de tentar novamente...")
                        await asyncio.sleep(espera)
                        continue
                    else:
                        break
            except Exception as e:
                logger.error(f"Erro na API do Google: {e}")
                break
        return text

    async def _translate_text(self, text):
        if self.deepl_api_key:
            res = await self._fetch_deepl_translation(text)
            if res: return res, "DeepL API"
        res = await self._fetch_free_translation(text)
        return res, "Google Translate"

    async def process_qobuz_native_json(self, q_data: dict, use_enhanced_lrc: bool = False):
        original_lines = q_data.get("original", {}).get("lines", [])
        if not original_lines:
            return None, 0, 0, "Falha"

        fonte_traducao = "Local"
        translation_sequence = []
        
        translations_data = q_data.get("translation", {}).get("lines", [])
        if not translations_data:
            translations_data = q_data.get("translated", {}).get("lines", [])
            if not translations_data and "translations" in q_data:
                for t_item in q_data["translations"]:
                    if t_item.get("language", "").startswith(self.target_lang[:2].lower()):
                        translations_data = t_item.get("lines", [])
                        break
        
        if translations_data:
            fonte_traducao = "Nativa (Qobuz)"
            for t_line in translations_data:
                t_text = t_line.get("line", "").strip()
                t_text = t_text.replace("~", "").replace("˜", "").strip()
                if t_text:
                    translation_sequence.append(t_text)
                    
        def format_ts(ms):
            minutos = ms // 60000
            segundos = (ms % 60000) / 1000
            return f"{minutos:02d}:{segundos:05.2f}"

        lrc_lines = []
        trans_count = 0
        total_valid_lines = 0
        trad_index = 0
        
        for linha_data in original_lines:
            texto = linha_data.get("line", "").strip()
            texto = texto.replace("~", "").replace("˜", "").strip()
            if not texto: continue
            
            total_valid_lines += 1
            start_ms = linha_data.get("start", 0)
            words = linha_data.get("words", [])
            
            if use_enhanced_lrc and words:
                line_str = f"[{format_ts(start_ms)}]"
                for w in words:
                    line_str += f"<{format_ts(w.get('start', 0))}>{w.get('word', '')} "
                lrc_lines.append(line_str.strip())
            else:
                lrc_lines.append(f"[{format_ts(start_ms)}]{texto}")
                
            if self.translate and trad_index < len(translation_sequence):
                trad = translation_sequence[trad_index]
                if texto.lower() != trad.lower():
                    lrc_lines.append(f"[{format_ts(start_ms)}]{self.translation_symbol}{trad}")
                    trans_count += 1
                trad_index += 1
                    
        final_lrc = "\n".join(lrc_lines)
        
        if trans_count == 0 and self.translate:
            final_lrc, t_count, _, fonte_fallback = await self._process_translation(final_lrc, is_synced=True)
            return final_lrc, t_count, total_valid_lines, fonte_fallback
            
        return final_lrc, trans_count, total_valid_lines, fonte_traducao

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
                if txt: mapping.append(('synced', ts, txt))
                else: mapping.append(('empty_synced', ts, ''))
            else:
                txt = line.strip()
                if txt: mapping.append(('text', None, txt))
                else: mapping.append(('empty', None, ''))

        detected_source_langs = []

        if self.translate:
            for i, (l_type, ts, txt) in enumerate(mapping):
                if l_type in ('synced', 'text'):
                    txt_no_tags = re.sub(r'<\d+:\d+(?:\.\d+)?>', '', txt)
                    clean_txt = re.sub(r'[^\w\s]', '', txt_no_tags.lower())
                    clean_txt = re.sub(r'\d+', '', clean_txt).strip()
                    words = set(clean_txt.split())
                    is_filler = bool(words) and words.issubset(self.pt_false_positives)
                    lang, conf = self._detect_lang(txt_no_tags)
                    ja_no_idioma_alvo = self._line_matches_target(lang, conf)
                    if not ja_no_idioma_alvo and not is_filler:
                        texts_to_translate.append((i, txt))
                        detected_source_langs.append(lang)

        count = 0
        fonte_usada = "Original"

        if texts_to_translate:
            try:
                grupos = {}
                for (idx, txt), lang in zip(texts_to_translate, detected_source_langs):
                    chave = lang or "desconhecido"
                    grupos.setdefault(chave, []).append((idx, txt))

                for chave, itens in grupos.items():
                    textos_unicos = list(dict.fromkeys(txt for _, txt in itens))

                    if len(textos_unicos) == 1:
                        trad_unica, fonte_grupo = await self._translate_text(textos_unicos[0])
                        for idx, txt in itens:
                            translation_map[idx] = trad_unica.strip()
                        
                        # Atualiza a fonte dinamicamente, seja Google ou DeepL
                        if fonte_grupo: fonte_usada = fonte_grupo
                        continue

                    raw_texts = "\n".join(textos_unicos)
                    translated_block, fonte_grupo = await self._translate_text(raw_texts)
                    translated_lines = translated_block.split('\n')

                    if len(translated_lines) == len(textos_unicos):
                        mapa_unico = {orig: trad.strip() for orig, trad in zip(textos_unicos, translated_lines)}
                        for idx, txt in itens:
                            translation_map[idx] = mapa_unico.get(txt, txt)
                            
                        # Atualiza a fonte dinamicamente
                        if fonte_grupo: fonte_usada = fonte_grupo
                    else:
                        sem = asyncio.Semaphore(3)
                        async def translate_single(idx, text_to_trans):
                            async with sem:
                                t_res, f_usada = await self._translate_text(text_to_trans)
                                return idx, t_res, f_usada

                        tasks = [translate_single(idx, txt) for idx, txt in itens]
                        resultados = await asyncio.gather(*tasks)
                        for idx, trad, f_usada in resultados:
                            translation_map[idx] = trad.strip()
                            # Atualiza a fonte dinamicamente
                            if f_usada: fonte_usada = f_usada
            except Exception as e:
                logger.error(f"Erro traducao: {e}")

        res_lines = []
        for i, (l_type, ts, txt) in enumerate(mapping):
            if l_type in ('synced', 'text'):
                res_lines.append(f"{ts if ts else ''}{txt}")
                if i in translation_map:
                    trad = translation_map[i]
                    if txt.lower() != trad.lower():
                        res_lines.append(f"{ts if ts else ''}{self.translation_symbol}{trad}")
                        count += 1
            elif l_type == 'empty_synced': res_lines.append(ts)
            else: res_lines.append(txt)

        total_valid_lines = len([m for m in mapping if m[0] in ('synced', 'text')])
        return '\n'.join(res_lines), count, total_valid_lines, fonte_usada

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
                if not lrc and not self.synced_only: lrc = lyric_data.get("data", {}).get("plainLyrics", "")
                return lrc if lrc else None
        except: return None

    async def _fetch_musixmatch_lyrics(self, artist, title):
        headers = {"x-mxm-app-version": "10.1.1", "User-Agent": "Musixmatch/2025120901 CFNetwork/1404.0.5 Darwin/22.3.0"}
        try:
            session = await self.get_session()
            if not self._mxm_token:
                async with session.get("https://apic-appmobile.musixmatch.com/ws/1.1/token.get?app_id=mac-ios-v2.0", headers=headers, timeout=8) as resp_token:
                    data_token = await resp_token.json(content_type=None)
                    if data_token.get("message", {}).get("header", {}).get("status_code") == 200:
                        self._mxm_token = data_token["message"]["body"]["user_token"]

            params = {"q_artist": artist, "q_track": title, "format": "json", "namespace": "lyrics_richsynched", "usertoken": self._mxm_token, "app_id": "mac-ios-v2.0"}
            async with session.get("https://apic-appmobile.musixmatch.com/ws/1.1/macro.subtitles.get", params=params, headers=headers, timeout=8) as resp_lyric:
                data = await resp_lyric.json(content_type=None)
                if data.get("message", {}).get("header", {}).get("status_code") == 200:
                    body = data["message"]["body"]
                    if "macro_calls" in body and "track.subtitles.get" in body["macro_calls"]:
                        sub_msg = body["macro_calls"]["track.subtitles.get"]["message"]
                        if sub_msg["header"]["status_code"] == 200 and "subtitle_list" in sub_msg["body"]:
                            subtitle_list = sub_msg["body"]["subtitle_list"]
                            if subtitle_list: return subtitle_list[0]["subtitle"]["subtitle_body"]
        except: pass
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
        except: return None

    async def _fetch_lrclib_lyrics(self, artist, title, album, duration=0):
        try:
            session = await self.get_session()
            params = {"artist_name": artist, "track_name": title, "album_name": album}
            if duration > 0: params["duration"] = int(duration)
            async with session.get("https://lrclib.net/api/get", params=params, timeout=8) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    synced = data.get("syncedLyrics")
                    if synced: return synced
                    if not self.synced_only: return data.get("plainLyrics")
        except: pass
        return None

    async def fetch_and_inject(self, file_path, album_artist, track, album, duration=0, save_lrc=True, overwrite=False, return_message=False):
        if not overwrite and self._has_lyrics(file_path, check_lrc=True): return (True, 0, 0, "Local", "Nenhuma")

        clean_artist = re.split(r'(?i)\s*(?:,|\&| feat\.| ft\.|;|\/)\s*',album_artist)[0].strip() if album_artist else ""

        async def run_fetch(provider_name, fetch_coro):
            try:
                text = await fetch_coro
                if text:
                    is_synced = self._is_strictly_synced(text)
                    if is_synced or not self.synced_only: return provider_name, text, is_synced
            except Exception: pass
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
                except: return None
            tasks.append(asyncio.create_task(run_fetch("Genius", fetch_g())))

        best_plain_text = None
        best_plain_provider = None

        while tasks:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                provider_name, text, is_synced = task.result()
                if text:
                    if is_synced:
                        for p in pending: p.cancel()
                        final_lyrics, trans_count, total_lines, fonte = await self._process_translation(text, is_synced=True)
                        self._inject_metadata(file_path, final_lyrics)
                        if save_lrc: self._save_lrc_file(file_path, final_lyrics)
                        return (True, trans_count, total_lines, provider_name, fonte)
                    else:
                        if not best_plain_text:
                            best_plain_text = text
                            best_plain_provider = provider_name
            tasks = list(pending)

        if best_plain_text and not self.synced_only:
            final_lyrics, trans_count, total_lines, fonte = await self._process_translation(best_plain_text, is_synced=False)
            self._inject_metadata(file_path, final_lyrics)
            return (True, trans_count, total_lines, best_plain_provider, fonte)

        return (False, 0, 0, "Nao Encontrada", "Nenhuma")

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
        except Exception as e: logger.error(f"Erro metadados: {e}")

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        try:
            with open(f"{os.path.splitext(audio_file_path)[0]}.lrc", 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
        except Exception as e: logger.warning(f"Não foi possível salvar .lrc: {e}")

            
    async def inject_manual_lyrics(self, file_path, raw_lyrics, is_synced=True, save_lrc=True, **kwargs):
        if not raw_lyrics: return (False, 0, 0, "Nenhuma")
        try:
            final_lyrics, trans_count, total_lines, fonte = await self._process_translation(raw_lyrics, is_synced=is_synced)
            self._inject_metadata(file_path, final_lyrics)
            if save_lrc and is_synced: self._save_lrc_file(file_path, final_lyrics)
            return (True, trans_count, total_lines, fonte)
        except Exception as e:
            logger.error(f"Erro na injecao manual: {e}")
            return (False, 0, 0, "Nenhuma")
