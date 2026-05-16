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

# Import deep-translator para traduções automáticas
GoogleTranslator = None
DEEP_TRANSLATOR_AVAILABLE = False
TRANSLATOR_IMPORT_ERROR = None

try:
    from deep_translator import GoogleTranslator
    DEEP_TRANSLATOR_AVAILABLE = True
except ImportError as import_error:
    TRANSLATOR_IMPORT_ERROR = str(import_error)
except Exception as unexpected_error:
    TRANSLATOR_IMPORT_ERROR = str(unexpected_error)

# Import langdetect para evitar traduzir músicas que já são em português
try:
    from langdetect import detect
except ImportError:
    detect = None

# Configurar logging (Mantido no modo debug para não poluir a tela)
logger = logging.getLogger(__name__)

class LyricsEngine:
    def __init__(self, genius_token=None, translate=True, target_lang='pt', translation_symbol=" ¬ "):
        self.genius_token = genius_token
        self.genius = None
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        
        if self.translate and not DEEP_TRANSLATOR_AVAILABLE:
            print(f"\n\033[93m[!] AVISO: Tradução desabilitada! (Erro: {TRANSLATOR_IMPORT_ERROR})\033[0m")
            self.translate = False
        
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
        (ex: 'cê' -> 'você') sejam consideradas como traduções válidas.
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
            
        # Filtro 2: Similaridade alta (acima de 75%). 
        # Traduzir "Cê tá pronta" para "Você está pronta" dá ~85% de similaridade, então é bloqueado.
        ratio = difflib.SequenceMatcher(None, o_no_punct, t_no_punct).ratio()
        if ratio > 0.75:
            return False
            
        return True

    async def _process_translation(self, lyrics, is_synced=True):
        """Traduz a letra mantendo o idioma original e duplicando os timestamps."""
        if not self.translate:
            return lyrics

        # Verificação Global de Idioma (Evitar Duplicação de PT-BR)
        if detect:
            try:
                texto_limpo = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', lyrics).strip()
                if texto_limpo:
                    idioma_original = detect(texto_limpo)
                    if idioma_original == self.target_lang:
                        return lyrics # Já está no idioma alvo, não traduz
            except Exception:
                pass
        
        if not DEEP_TRANSLATOR_AVAILABLE or GoogleTranslator is None:
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

        try:
            translator = GoogleTranslator(source='auto', target=self.target_lang)
        except Exception:
            return lyrics

        translated_texts = []
        try:
            separator_block = " |&| "
            joined_text = separator_block.join(texts_to_translate)

            if len(joined_text) < 4500:
                translated_joined = await asyncio.to_thread(translator.translate, joined_text)
                if translated_joined:
                    translated_texts = [t.strip() for t in translated_joined.split(separator_block) if t.strip()]
            else:
                translated_texts = []

            if not translated_texts or len(translated_texts) != len(texts_to_translate):
                translated_texts = []
                sem = asyncio.Semaphore(5)

                async def trans_line(line):
                    async with sem:
                        try:
                            await asyncio.sleep(0.1)
                            res = await asyncio.to_thread(translator.translate, line)
                            return res if res else line
                        except Exception:
                            return line

                translated_texts = await asyncio.gather(*(trans_line(line) for line in texts_to_translate))

        except Exception:
            return lyrics 

        if len(translated_texts) < len(texts_to_translate):
            translated_texts.extend([""] * (len(texts_to_translate) - len(translated_texts)))

        result_lines = []
        trans_idx = 0

        for item in line_mapping:
            l_type, ts, txt = item
            
            if l_type == 'synced':
                result_lines.append(f"{ts}{txt}")
                if trans_idx < len(translated_texts):
                    traducao = translated_texts[trans_idx]
                    # Usa o novo filtro de inteligência para evitar duplicação
                    if self._is_valid_translation(txt, traducao):
                        result_lines.append(f"{ts}{self.translation_symbol}{traducao}")
                trans_idx += 1
                
            elif l_type == 'text':
                result_lines.append(txt)
                if trans_idx < len(translated_texts):
                    traducao = translated_texts[trans_idx]
                    # Usa o novo filtro de inteligência para evitar duplicação
                    if self._is_valid_translation(txt, traducao):
                        result_lines.append(f"{self.translation_symbol}{traducao}")
                trans_idx += 1
                
            elif l_type == 'empty_synced':
                result_lines.append(f"{ts}")
                
            elif l_type in ('raw', 'empty'):
                result_lines.append(txt)

        return '\n'.join(result_lines)

    async def fetch_and_inject(self, file_path, album_artist, track, album, save_lrc=True, overwrite=False):
        """
        Busca e injeta as letras em arquivo de áudio.
        
        Retorna:
            (bool, bool): Tupla contendo (sucesso, tem_traducao)
        """
        if not overwrite and self._has_lyrics(file_path, check_lrc=True):
            return (False, False)

        try:
            lrclib_url = "https://lrclib.net/api/get"
            headers = {"User-Agent": "qobuz-dl-master/2.5 (https://github.com/kaduvercosa/qobuz-dl)"}
            
            params = {"artist_name": album_artist, "track_name": track, "album_name": album}
            
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
                    final_lyrics = await self._process_translation(synced_lyrics, is_synced=True)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    
                    trad_status = "Sim" if has_translation else "Não"
                    print(f"  [*] Letra Encontrada: {album_artist} - {track} | Sincronizada: Sim | Traduzida: {trad_status}")
                    return (True, has_translation)
                    
                elif plain_lyrics:
                    final_lyrics = await self._process_translation(plain_lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    
                    trad_status = "Sim" if has_translation else "Não"
                    print(f"  [*] Letra Encontrada: {album_artist} - {track} | Sincronizada: Não | Traduzida: {trad_status}")
                    return (True, has_translation)

            if self.genius:
                song = await asyncio.to_thread(self.genius.search_song, track, album_artist)
                if song and song.lyrics:
                    final_lyrics = await self._process_translation(song.lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    
                    trad_status = "Sim" if has_translation else "Não"
                    print(f"  [*] Letra Encontrada: {album_artist} - {track} (via Genius) | Sincronizada: Não | Traduzida: {trad_status}")
                    return (True, has_translation)

            print(f"  [-] Letra não encontrada: {track}")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            print(f"  [!] Falha ao buscar letra de {track} ({error_msg})")

        return (False, False)

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        """Salva as letras em arquivo .lrc com tratamento de erro."""
        try:
            base_name = os.path.splitext(audio_file_path)[0]
            lrc_path = f"{base_name}.lrc"
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
        except Exception:
            pass # Silenciado

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
            elif ext == '.mp3':
                try:
                    audio = ID3(file_path)
                except ID3NoHeaderError:
                    audio = ID3()
                audio.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
                audio.save(file_path)
        except Exception:
            pass # Silenciado
