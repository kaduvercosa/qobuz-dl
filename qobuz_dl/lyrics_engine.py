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

# Import langdetect para detecção de idioma
try:
    from langdetect import detect
except ImportError:
    detect = None

# Configurar logging
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
                    logger.info(f"[*] DeepL Translator inicializado para idioma alvo: {target_lang}")
                except Exception as e:
                    logger.error(f"[!] Erro ao inicializar DeepL Translator: {e}")
                    print(f"\n\033[91m[!] Erro ao inicializar DeepL: {e}\033[0m")
                    self.translate = False
                    self.deepl_api_key = None
        
        if self.genius_token and lyricsgenius:
            try:
                self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)
                logger.info("[*] Genius API inicializado como fallback")
            except Exception as e:
                logger.error(f"[!] Erro ao inicializar Genius: {e}")
                self.genius = None

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
            logger.info("[*] Tradução desabilitada ou DeepL não configurado, retornando lyrics original")
            return lyrics, 0, total_lines

        if not texts_to_translate:
            logger.debug("[*] Sem linhas para traduzir, retornando original")
            return lyrics, 0, total_lines

        # 1. DETECÇÃO GLOBAL DE IDIOMA (economia de quota)
        full_text = " ".join(texts_to_translate)
        try:
            if detect:
                dominant_lang = detect(full_text)
                target_lang_code = self.target_lang.split('-')[0].lower()
                if dominant_lang.lower() == target_lang_code:
                    logger.info(f"[*] Texto já está em {self.target_lang}, pulando tradução")
                    return lyrics, 0, total_lines
        except Exception as e:
            logger.warning(f"[*] Erro na detecção de idioma: {e}, continuando com tradução")

        # 2. FILTRO POR LINHA (micro-detecção para linhas longas)
        lines_to_translate = []
        indices_to_translate = []
        
        for i, txt in enumerate(texts_to_translate):
            txt_clean = txt.strip()
            if not txt_clean:
                continue

            # Se a linha for longa, verifica se já está no idioma alvo
            if len(txt_clean.split()) >= 3:
                try:
                    if detect:
                        line_lang = detect(txt_clean)
                        target_lang_code = self.target_lang.split('-')[0].lower()
                        if line_lang.lower() == target_lang_code:
                            continue  # Já está no idioma alvo, pula
                except Exception:
                    pass

            lines_to_translate.append(txt_clean)
            indices_to_translate.append(i)

        if not lines_to_translate:
            logger.info("[*] Nenhuma linha para traduzir após filtro de idioma")
            return lyrics, 0, total_lines

        # 3. TRADUÇÃO EM LOTE COM DEEPL
        translated_texts = [""] * len(texts_to_translate)
        try:
            logger.info(f"[*] Iniciando tradução DeepL para {len(lines_to_translate)} linhas (idioma alvo: {self.target_lang})")
            
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

            logger.info(f"[*] Tradução concluída: {len([t for t in translated_texts if t])} linhas traduzidas")

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

        logger.info(f"[*] Tradução processada: {translation_count} linhas com tradução válida")
        return '\n'.join(result_lines), translation_count, total_lines

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
            lrclib_url = "https://lrclib.net/api/get"
            headers = {"User-Agent": "qobuz-dl-master/2.5 (https://github.com/kaduvercosa/qobuz-dl)"}
            
            params = {"artist_name": album_artist, "track_name": track, "album_name": album}
            
            # --- PROTEÇÃO CONTRA TIMEOUT E ERROS DE REDE DA API LRCLIB ---
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
            # -------------------------------------------------------------

            if status == 200:
                synced_lyrics = data.get("syncedLyrics")
                plain_lyrics = data.get("plainLyrics")
                
                if synced_lyrics:
                    logger.info(f"[*] Letras sincronizadas encontradas para: {track}")
                    final_lyrics, trans_count, total_lines = await self._process_translation(synced_lyrics, is_synced=True)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return (True, trans_count, total_lines, status)
                    
                elif plain_lyrics:
                    logger.info(f"[*] Letras simples encontradas para: {track}")
                    final_lyrics, trans_count, total_lines = await self._process_translation(plain_lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return (True, trans_count, total_lines, status)

            # --- FALLBACK DO GENIUS ---
            if self.genius:
                logger.info(f"[*] Tentando Genius API para: {track}")
                song = await asyncio.to_thread(self.genius.search_song, track, album_artist)
                if song and song.lyrics:
                    logger.info(f"[*] Letra encontrada via Genius para: {track}")
                    final_lyrics, trans_count, total_lines = await self._process_translation(song.lyrics, is_synced=False)
                    self._inject_metadata(file_path, final_lyrics)
                    if save_lrc:
                        self._save_lrc_file(file_path, final_lyrics)
                    return (True, trans_count, total_lines, 200)

            logger.warning(f"[!] Nenhuma letra encontrada para: {track}")

        except Exception as e:
            # Pegando erros internos reais para não deixar o texto da string vazio.
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