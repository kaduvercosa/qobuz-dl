import os
import re
import asyncio
import aiohttp
import logging
import sys
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
    print(f"\n\033[93m[!] AVISO: deep-translator não está instalado!")
    print(f"    Erro: {TRANSLATOR_IMPORT_ERROR}")
    print(f"    Instale com: pip install deep-translator\033[0m\n")
except Exception as unexpected_error:
    # BUG FIX: Captura QUALQUER erro, não apenas ImportError
    TRANSLATOR_IMPORT_ERROR = str(unexpected_error)
    print(f"\n\033[91m[!] ERRO ao importar deep-translator!")
    print(f"    Erro: {TRANSLATOR_IMPORT_ERROR}")
    print(f"    Tipo: {type(unexpected_error).__name__}")
    print(f"    Tente: pip install --upgrade deep-translator beautifulsoup4 typing-extensions\033[0m\n")

# Import langdetect para evitar traduzir músicas que já são em português
try:
    from langdetect import detect
except ImportError:
    detect = None

# Configurar logging
logger = logging.getLogger(__name__)

class LyricsEngine:
    def __init__(self, genius_token=None, translate=True, target_lang='pt', translation_symbol=" ¬ "):
        self.genius_token = genius_token
        self.genius = None
        self.translate = translate
        self.target_lang = target_lang
        self.translation_symbol = translation_symbol
        
        # BUG FIX: Verificar se deep-translator está disponível E mostrar erro real
        if self.translate and not DEEP_TRANSLATOR_AVAILABLE:
            print("\n\033[93m[!] AVISO: Tradução desabilitada!")
            if TRANSLATOR_IMPORT_ERROR:
                print(f"    Motivo: {TRANSLATOR_IMPORT_ERROR}")
            print(f"    Instale/atualize com: pip install --upgrade deep-translator beautifulsoup4\033[0m\n")
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

    async def _process_translation(self, lyrics, is_synced=True):
        """Traduz a letra mantendo o idioma original e duplicando os timestamps."""
        # BUG FIX: Retornar original se tradução desabilitada
        if not self.translate:
            logger.info("[*] Tradução desabilitada, retornando lyrics original")
            return lyrics
        
        # BUG FIX: Verificar disponibilidade real do tradutor com mensagem de erro
        if not DEEP_TRANSLATOR_AVAILABLE or GoogleTranslator is None:
            error_msg = TRANSLATOR_IMPORT_ERROR or "GoogleTranslator não disponível"
            logger.error(f"[!] Erro ao usar tradutor: {error_msg}")
            print(f"\n\033[91m[!] Tradução não disponível: {error_msg}\033[0m")
            print(f"    Tente: pip install --upgrade deep-translator beautifulsoup4\n")
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
            logger.debug("[*] Sem linhas para traduzir, retornando original")
            return lyrics

        try:
            # BUG FIX: Inicializar translator com debug melhorado
            translator = GoogleTranslator(source='auto', target=self.target_lang)
            logger.info(f"[*] Tradutor inicializado para {self.target_lang}. Linhas: {len(texts_to_translate)}")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"[!] Erro ao inicializar GoogleTranslator: {error_msg}")
            print(f"\n\033[91m[!] Erro ao inicializar tradutor: {error_msg}\033[0m")
            print(f"    Tente: pip install --upgrade deep-translator beautifulsoup4 typing-extensions\n")
            return lyrics

        translated_texts = []
        try:
            # Tenta traduzir tudo em um único bloco se não for muito grande
            separator_block = " |&| "
            joined_text = separator_block.join(texts_to_translate)

            if len(joined_text) < 4500:
                logger.debug(f"[*] Tentando tradução em lote (tamanho: {len(joined_text)})")
                translated_joined = await asyncio.to_thread(translator.translate, joined_text)
                if translated_joined:
                    # BUG FIX: Melhor separação respeitando o separador original
                    translated_texts = [t.strip() for t in translated_joined.split(separator_block) if t.strip()]
                    logger.info(f"[*] Tradução em lote bem-sucedida: {len(translated_texts)} linhas")
            else:
                logger.warning(f"[*] Texto muito grande ({len(joined_text)}), usando fallback sequencial")
                translated_texts = []

            # Se falhou ou a quantidade de linhas descasou, usa fallback
            if not translated_texts or len(translated_texts) != len(texts_to_translate):
                logger.warning(f"Batch translation falhou. Esperado: {len(texts_to_translate)}, Obtido: {len(translated_texts)}. Usando fallback sequencial.")
                translated_texts = []

                # Para não tomar bloqueio de API por limite de taxa, usamos semáforo
                sem = asyncio.Semaphore(5)

                async def trans_line(line):
                    async with sem:
                        try:
                            # Adiciona pequeno delay para evitar 429 too many requests
                            await asyncio.sleep(0.1)
                            res = await asyncio.to_thread(translator.translate, line)
                            return res if res else line
                        except Exception as fallback_error:
                            logger.error(f"Erro ao traduzir linha '{line}': {fallback_error}")
                            return line

                logger.info(f"[*] Iniciando tradução sequencial para {len(texts_to_translate)} linhas")
                translated_texts = await asyncio.gather(*(trans_line(line) for line in texts_to_translate))
                logger.info(f"[*] Tradução sequencial concluída: {len(translated_texts)} linhas")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"[!] Erro no processo de tradução: {error_msg}")
            print(f"\n\033[91m[!] Erro durante tradução: {error_msg}\033[0m\n")
            return lyrics 

        # Garante o mesmo tamanho para evitar index out of bounds
        if len(translated_texts) < len(texts_to_translate):
            logger.warning(f"Completando lacunas: {len(translated_texts)} -> {len(texts_to_translate)}")
            translated_texts.extend([""] * (len(texts_to_translate) - len(translated_texts)))

        result_lines = []
        trans_idx = 0
        translation_count = 0

        for item in line_mapping:
            l_type, ts, txt = item
            
            if l_type == 'synced':
                result_lines.append(f"{ts}{txt}")
                if trans_idx < len(translated_texts):
                    traducao = translated_texts[trans_idx]
                    if traducao and txt.strip().lower() != traducao.strip().lower():
                        result_lines.append(f"{ts}{self.translation_symbol}{traducao}")
                        translation_count += 1
                trans_idx += 1
                
            elif l_type == 'text':
                result_lines.append(txt)
                if trans_idx < len(translated_texts):
                    traducao = translated_texts[trans_idx]
                    if traducao and txt.strip().lower() != traducao.strip().lower():
                        result_lines.append(f"{self.translation_symbol}{traducao}")
                        translation_count += 1
                trans_idx += 1
                
            elif l_type == 'empty_synced':
                result_lines.append(f"{ts}")
                
            elif l_type in ('raw', 'empty'):
                result_lines.append(txt)

        logger.info(f"[*] Tradução completa: {translation_count} linhas traduzidas")
        return '\n'.join(result_lines)

    async def fetch_and_inject(self, file_path, album_artist, track, album, save_lrc=True, overwrite=False):
        """
        Busca e injeta as letras em arquivo de áudio.
        
        Retorna:
            (bool, bool): Tupla contendo (sucesso, tem_traducao)
        """
        # BUG FIX: Sempre verifica .lrc como parte da detecção
        if not overwrite and self._has_lyrics(file_path, check_lrc=True):
            logger.debug(f"[*] Arquivo já possui letras: {file_path}")
            return (False, False)

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
                    logger.info(f"[*] Letras sincronizadas encontradas para: {track}")
                    final_lyrics = await self._process_translation(synced_lyrics, is_synced=True)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    logger.info(f"[*] Injeção concluída. Tem tradução: {has_translation}")
                    return (True, has_translation)
                    
                elif plain_lyrics:
                    logger.info(f"[*] Letras simples encontradas para: {track}")
                    final_lyrics = await self._process_translation(plain_lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    logger.info(f"[*] Injeção concluída. Tem tradução: {has_translation}")
                    return (True, has_translation)

            if self.genius:
                logger.info(f"[*] Tentando Genius API para: {track}")
                song = await asyncio.to_thread(self.genius.search_song, track, album_artist)
                if song and song.lyrics:
                    logger.info(f"[*] Letra encontrada via Genius para: {track}")
                    final_lyrics = await self._process_translation(song.lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    has_translation = (self.translation_symbol in final_lyrics)
                    logger.info(f"[*] Injeção concluída. Tem tradução: {has_translation}")
                    return (True, has_translation)

            logger.warning(f"[!] Nenhuma letra encontrada para: {track}")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            print(f"\033[91m[!] Erro ao buscar letras: {error_msg}\033[0m")
            logger.error(f"[!] Erro ao buscar letras: {error_msg}", exc_info=True)

        # BUG FIX: Sempre retorna tupla consistente
        return (False, False)

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        """Salva as letras em arquivo .lrc com tratamento de erro."""
        try:
            base_name = os.path.splitext(audio_file_path)[0]
            lrc_path = f"{base_name}.lrc"
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
            logger.info(f"[*] Arquivo .lrc salvo: {lrc_path}")
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
                logger.info(f"[*] Metadados FLAC injetados: {file_path}")
            elif ext == '.mp3':
                try:
                    audio = ID3(file_path)
                except ID3NoHeaderError:
                    audio = ID3()
                audio.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
                audio.save(file_path)
                logger.info(f"[*] Metadados ID3 injetados: {file_path}")
        except Exception as e:
            logger.error(f"[!] Erro ao injetar metadados de lyrics: {e}")
