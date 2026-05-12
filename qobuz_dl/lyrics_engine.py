import os
import re
import requests
import mutagen
from mutagen.id3 import ID3, USLT, ID3NoHeaderError
from mutagen.flac import FLAC
from deep_translator import GoogleTranslator
from langdetect import detect

# Importa o lyricsgenius apenas se o usuário tiver configurado o token
try:
    import lyricsgenius
except ImportError:
    lyricsgenius = None

class LyricsEngine:
    def __init__(self, genius_token=None, target_lang='pt'):
        self.genius_token = genius_token
        self.genius = None
        self.target_lang = target_lang
        # Inicializa o tradutor automático
        self.translator = GoogleTranslator(source='auto', target=self.target_lang)
        
        if self.genius_token and lyricsgenius:
            self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)

    def _clean_search_term(self, text):
        """
        Remove termos como (Remastered 2011), - Radio Edit, (feat. X) 
        para aumentar drasticamente a chance de achar a letra no LRCLIB.
        """
        if not text:
            return ""
        # Remove tudo que estiver após " - " (ex: - Remastered)
        text = text.split(' - ')[0]
        # Remove parênteses e colchetes que contenham palavras como feat, remaster, mix, version
        text = re.sub(r'(?i)\s*[\(\[][^\)\]]*(remaster|feat|mix|version|edit|mono|stereo)[\)\]]', '', text)
        return text.strip()

    def _clean_genius_lyrics(self, lyrics):
        """Remove o lixo que a API do Genius insere no final da letra ('123Embed')"""
        if not lyrics:
            return ""
        lyrics = re.sub(r'\d*Embed$', '', lyrics)
        lyrics = re.sub(r'EmbedShare URLCopyEmbedCopy$', '', lyrics)
        return lyrics.strip()

    def _translate_synced_lyrics(self, synced_lyrics):
        """Lê o LRC, traduz em lote e detecta o idioma LINHA POR LINHA para os prefixos."""
        print(f"    🌍 Verificando idiomas e traduzindo letras...")
        bilingual_lrc = []
        parsed_lines = []
        texts_to_translate = []
        
        # Suporta tempos múltiplos na mesma linha: [00:10.00][00:20.00] Letra
        regex_lrc = re.compile(r'^((?:\[\d{2}:\d{2}\.\d{2,3}\])+)(.*)')

        # PASSO 1: Extrair os textos das linhas
        for line in synced_lyrics.splitlines():
            match = regex_lrc.match(line)
            if match:
                timestamps = match.group(1)
                text = match.group(2).strip()
                
                parsed_lines.append({"type": "lyric", "timestamps": timestamps, "text": text})
                if text:
                    texts_to_translate.append(text)
            else:
                parsed_lines.append({"type": "raw", "line": line})

        # Mapeamento de idiomas comuns para exibir na tela
        lang_map = {
            'en': 'EN', 'es': 'ES', 'fr': 'FR', 'it': 'IT', 
            'de': 'DE', 'ja': 'JP', 'ko': 'KR', 'pt': 'PT'
        }

        # PASSO 2: Descobrir o "Idioma Principal" da música como escudo de segurança
        main_prefix = "ORIG"
        if texts_to_translate:
            sample_text = " ".join(texts_to_translate[:5])
            try:
                main_lang = detect(sample_text)
                main_prefix = lang_map.get(main_lang, main_lang.upper())
            except Exception:
                pass

        # PASSO 3: Traduzir TUDO em lote (Super rápido via rede)
        translated_texts = []
        if texts_to_translate:
            try:
                translated_texts = self.translator.translate_batch(texts_to_translate)
            except Exception as e:
                print(f"    ⚠️ Falha na tradução automática: {e}")
                translated_texts = texts_to_translate 

        # PASSO 4: Montar o LRC detectando o idioma LINHA POR LINHA (Local/Rápido)
        trans_index = 0
        for item in parsed_lines:
            if item["type"] == "raw":
                bilingual_lrc.append(item["line"])
            else:
                timestamps = item["timestamps"]
                text = item["text"]
                
                if not text:
                    # Mantém pausas instrumentais
                    bilingual_lrc.append(f"{timestamps}")
                else:
                    translated_text = translated_texts[trans_index] if trans_index < len(translated_texts) else text
                    trans_index += 1
                    
                    # Trava de segurança caso o Google Translator retorne None
                    if translated_text is None:
                        translated_text = text

                    # --- DETECÇÃO LINHA POR LINHA ---
                    line_prefix = main_prefix
                    # Só tenta detectar se a linha tiver mais de 3 letras (evita erros em "Oh", "Ah")
                    if len(text) > 3:
                        try:
                            line_lang = detect(text)
                            line_prefix = lang_map.get(line_lang, line_lang.upper())
                        except Exception:
                            pass # Falhou, continua usando o idioma principal da faixa
                    # --------------------------------

                    # Se a linha já for PT ou for idêntica à tradução, não duplica
                    if line_prefix == self.target_lang.upper() or text.lower() == translated_text.lower():
                        bilingual_lrc.append(f"{timestamps}{text}")
                    else:
                        bilingual_lrc.append(f"{timestamps}{line_prefix}: {text}")
                        bilingual_lrc.append(f"{timestamps}{self.target_lang.upper()}: {translated_text}")
                        
        return "\n".join(bilingual_lrc)

    def fetch_and_inject(self, file_path, artist, track, album, save_lrc=True):
        """Motor em cascata: Tenta LRCLIB primeiro, se falhar tenta Genius."""
        try:
            print(f"    🔍 Buscando letras para: {track}...")
            
            clean_track = self._clean_search_term(track)
            clean_artist = self._clean_search_term(artist)
            
            lrclib_url = "https://lrclib.net/api/get"
            headers = {"User-Agent": "qobuz-dl-ultimate/1.0"}
            
            # Tentativa 1: LRCLIB (Match exato com Álbum)
            params = {"artist_name": clean_artist, "track_name": clean_track, "album_name": album}
            response = requests.get(lrclib_url, params=params, headers=headers, timeout=12) 
            
            # Tentativa 2: Sem Álbum (Resolve problemas de singles/deluxe)
            if response.status_code != 200:
                params = {"artist_name": clean_artist, "track_name": clean_track}
                response = requests.get(lrclib_url, params=params, headers=headers, timeout=12)

            if response.status_code == 200:
                data = response.json()
                synced_lyrics = data.get("syncedLyrics")
                plain_lyrics = data.get("plainLyrics")
                
                if synced_lyrics:
                    bilingual_synced = self._translate_synced_lyrics(synced_lyrics)
                    self._inject_metadata(file_path, bilingual_synced)
                    
                    if save_lrc:
                        self._save_lrc_file(file_path, bilingual_synced)
                        print(f"    ✅ Letra sincronizada e traduzida salva como .lrc!")
                    else:
                        print(f"    ✅ Letra sincronizada injetada nos metadados!")
                    return
                elif plain_lyrics:
                    self._inject_metadata(file_path, plain_lyrics)
                    print(f"    ✅ Letra padrão injetada nos metadados!")
                    return

            # FALLBACK PARA GENIUS
            if self.genius:
                song = self.genius.search_song(clean_track, clean_artist)
                if song and song.lyrics:
                    clean_lyrics = self._clean_genius_lyrics(song.lyrics)
                    self._inject_metadata(file_path, clean_lyrics)
                    print(f"    ✅ Letra injetada via Genius (Fallback)!")
                    return

            print(f"    ❌ Nenhuma letra encontrada para esta faixa.")

        except requests.exceptions.RequestException as re_err:
            print(f"    ⚠️ Erro de rede ao buscar letras: {re_err}")
        except Exception as e:
            print(f"    ⚠️ Erro no processamento da letra: {e}")

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        """Cria o arquivo .lrc e protege contra caminhos inválidos."""
        base_name = os.path.splitext(audio_file_path)[0]
        lrc_path = f"{base_name}.lrc"
        
        try:
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
        except OSError as e:
            print(f"    ⚠️ Falha ao salvar arquivo .lrc (Caminho inválido ou sem permissão): {e}")

    def _inject_metadata(self, file_path, lyrics):
        """Injeta a letra diretamente nas tags FLAC ou MP3."""
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
                # Remove letras antigas para evitar duplicação ou bugs de exibição no Player
                audio.delall('USLT')
                audio.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
                audio.save(file_path)
        except Exception as e:
            print(f"    ⚠️ Falha ao injetar letra no arquivo {os.path.basename(file_path)}: {e}")