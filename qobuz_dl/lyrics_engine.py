import os
import re
import asyncio
import aiohttp
from mutagen.flac import FLAC
from mutagen.id3 import ID3, USLT, ID3NoHeaderError

# Import lyricsgenius apenas se o usuário tiver configurado o token
try:
    import lyricsgenius
except ImportError:
    lyricsgenius = None

# Import deep-translator para traduções automáticas
try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

# Import langdetect para evitar traduzir músicas que já são em português
try:
    from langdetect import detect
except ImportError:
    detect = None

class LyricsEngine:
    def __init__(self, genius_token=None, translate=True, target_lang='pt', translation_symbol=" ¬ "):
        self.genius_token = genius_token
        self.genius = None
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        
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

    async def _process_translation(self, lyrics, is_synced=True):
        """Traduz a letra mantendo o idioma original e duplicando os timestamps."""
        if not self.translate or not GoogleTranslator:
            return lyrics

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

        if not texts_to_translate:
            return lyrics

        # Verificação de Idioma silenciosa
        if detect:
            try:
                amostra = " ".join(texts_to_translate[:10])
                detected_lang = detect(amostra)
                if detected_lang == self.target_lang:
                    import logging
                    print(f"\033[93m[*] Letra ignorada para tradução: O idioma detectado já é '{detected_lang}'\033[0m")
                    logging.info(f"Letra ignorada. Idioma detectado: {detected_lang}")
                    return lyrics
            except Exception as e:
                import logging
                print(f"\033[93m[*] langdetect falhou (Ignorando filtro): {e}\033[0m")
                pass 

        if not GoogleTranslator:
            print("\033[91m[!] O pacote deep-translator nao esta instalado ou quebrou.\033[0m")
            return lyrics

        translator = GoogleTranslator(source='auto', target=self.target_lang)

        # Usa quebra de linha como separador (mais respeitado pelo Google Tradutor)
        separator = "\n"
        joined_text = separator.join(texts_to_translate)

        translated_texts = []
        try:
            # Tenta traduzir tudo em um único bloco se não for muito grande
            if len(joined_text) < 4500:
                translated_joined = await asyncio.to_thread(translator.translate, joined_text)
                if translated_joined:
                    translated_texts = [t.strip() for t in translated_joined.split(separator)]
            else:
                translated_texts = []

            # Se falhou ou a quantidade de linhas descasou, usa fallback sequencial
            if not translated_texts or len(translated_texts) != len(texts_to_translate):
                translated_texts = []
                for line in texts_to_translate:
                    try:
                        # Executa de forma sequencial para evitar block (Rate Limit 429)
                        res = await asyncio.to_thread(translator.translate, line)
                        translated_texts.append(res if res else line)
                    except Exception:
                        translated_texts.append(line)
        except Exception as e:
            # Em vez de passar silenciosamente, registra no terminal a causa raiz
            import logging
            print(f"\n\033[91m[!] Erro no GoogleTranslator ao traduzir: {e}\033[0m")
            logging.error(f"[!] Erro no GoogleTranslator: {e}")
            return lyrics 

        # Garante o mesmo tamanho para evitar index out of bounds
        if len(translated_texts) < len(texts_to_translate):
            translated_texts.extend([""] * (len(texts_to_translate) - len(translated_texts)))

        result_lines = []
        trans_idx = 0

        for item in line_mapping:
            l_type, ts, txt = item
            
            if l_type == 'synced':
                result_lines.append(f"{ts}{txt}")
                traducao = translated_texts[trans_idx]
                if traducao and txt.strip().lower() != traducao.strip().lower():
                    result_lines.append(f"{ts}{self.translation_symbol}{traducao}")
                trans_idx += 1
            elif l_type == 'text':
                result_lines.append(txt)
                traducao = translated_texts[trans_idx]
                if traducao and txt.strip().lower() != traducao.strip().lower():
                    result_lines.append(f"{self.translation_symbol}{traducao}")
                trans_idx += 1
            elif l_type == 'empty_synced':
                result_lines.append(f"{ts}")
            elif l_type in ('raw', 'empty'):
                result_lines.append(txt)

        return '\n'.join(result_lines)

    async def fetch_and_inject(self, file_path, album_artist, track, album, save_lrc=True, overwrite=False):
        # Busca as letras de forma totalmente silenciosa. Retorna True ou False
        if not overwrite and self._has_lyrics(file_path, check_lrc=save_lrc):
            return False

        try:
            lrclib_url = "https://lrclib.net/api/get"
            headers = {"User-Agent": "qobuz-dl-master/2.5 (https://github.com/kaduvercosa/qobuz-dl)"}
            
            params = {"artist_name": album_artist, "track_name": track, "album_name": album}
            
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

            if status == 200:
                synced_lyrics = data.get("syncedLyrics")
                plain_lyrics = data.get("plainLyrics")
                
                if synced_lyrics:
                    final_lyrics = await self._process_translation(synced_lyrics, is_synced=True)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return True
                elif plain_lyrics:
                    final_lyrics = await self._process_translation(plain_lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return True

            if self.genius:
                song = await asyncio.to_thread(self.genius.search_song, track, album_artist)
                if song and song.lyrics:
                    final_lyrics = await self._process_translation(song.lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return True

        except Exception:
            pass # Ignora timeouts e erros de conexão silenciosamente

        return False

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        base_name = os.path.splitext(audio_file_path)[0]
        lrc_path = f"{base_name}.lrc"
        with open(lrc_path, 'w', encoding='utf-8') as f:
            f.write(synced_lyrics)

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
        except Exception:
            pass