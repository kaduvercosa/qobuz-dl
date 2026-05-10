import os
import re
import requests
import mutagen
from mutagen.id3 import ID3, USLT, ID3NoHeaderError
from mutagen.flac import FLAC
from deep_translator import GoogleTranslator

# Import lyricsgenius only if the user has configured the token
try:
    import lyricsgenius
except ImportError:
    lyricsgenius = None

class LyricsEngine:
    def __init__(self, genius_token=None):
        self.genius_token = genius_token
        self.genius = None
        # Inicializa o tradutor automático para o Português
        self.translator = GoogleTranslator(source='auto', target='pt')
        
        if self.genius_token and lyricsgenius:
            # Initialize Genius in silent mode (verbose=False)
            self.genius = lyricsgenius.Genius(self.genius_token, verbose=False, remove_section_headers=True)

    def _translate_synced_lyrics(self, synced_lyrics):
        """Lê o LRC original e cria uma versão bilíngue na mesma linha para o Neutron"""
        print(f"    🌍 Verificando idioma e traduzindo letras...")
        bilingual_lrc = []
        
        for line in synced_lyrics.splitlines():
            # Tenta encontrar o padrão do timestamp: [00:12.34] Letra
            match = re.match(r'(\[\d{2}:\d{2}\.\d{2,3}\])(.*)', line)
            if match:
                timestamp = match.group(1)
                text = match.group(2).strip()
                
                if text:
                    try:
                        translated_text = self.translator.translate(text)
                        
                        # --- VERIFICAÇÃO DE IDIOMA ---
                        # Se a tradução for idêntica ao original (ignorando maiúsculas/minúsculas),
                        # a música já é em português ou é um vocal sem tradução (ex: "Ah", "Yeah").
                        if text.lower() == translated_text.lower():
                            bilingual_lrc.append(line)
                        else:
                            # Opção B: Inglês e Português na mesma linha
                            bilingual_lrc.append(f"{timestamp}{text}  |  {translated_text}")
                            
                    except Exception:
                        # Se a tradução falhar por falha de rede, mantém a original
                        bilingual_lrc.append(line)
                else:
                    bilingual_lrc.append(line)
            else:
                bilingual_lrc.append(line)
                
        return "\n".join(bilingual_lrc)

    def fetch_and_inject(self, file_path, artist, track, album, save_lrc=True):
        """Waterfall engine: first try LRCLIB (for LRC format), then Genius."""
        try:
            print(f"    🔍 Searching lyrics for: {track}...")
            
            # ATTEMPT 1: LRCLIB (Free search, priority to synchronized lyrics)
            lrclib_url = "https://lrclib.net/api/get"
            
            # Add an official User-Agent to avoid blocks or throttling from the API
            headers = {"User-Agent": "qobuz-dl-ultimate/1.0 (https://github.com/Sei969/qobuz-dl)"}
            
            # Try A: Exact match (Artist + Track + Album)
            params = {"artist_name": artist, "track_name": track, "album_name": album}
            response = requests.get(lrclib_url, params=params, headers=headers, timeout=12) 
            
            # Try B: If it fails, try again without album (often solves version/remaster issues)
            if response.status_code != 200:
                params = {"artist_name": artist, "track_name": track}
                response = requests.get(lrclib_url, params=params, headers=headers, timeout=12)

            if response.status_code == 200:
                data = response.json()
                synced_lyrics = data.get("syncedLyrics")
                plain_lyrics = data.get("plainLyrics")
                
                if synced_lyrics:
                    # Traduz o arquivo LRC antes da injeção
                    bilingual_synced = self._translate_synced_lyrics(synced_lyrics)
                    
                    self._inject_metadata(file_path, bilingual_synced)
                    
                    if save_lrc:
                        self._save_lrc_file(file_path, bilingual_synced)
                        print(f"    ✅ Synchronized and translated lyrics saved as .lrc!")
                    else:
                        print(f"    ✅ Synchronized and translated lyrics injected into metadata!")
                    return
                elif plain_lyrics:
                    # If no synchronized version exists, fallback to the static one
                    self._inject_metadata(file_path, plain_lyrics)
                    print(f"    ✅ Standard lyrics injected into metadata!")
                    return

            # ATTEMPT 2: GENIUS FALLBACK (If the user provided a token)
            if self.genius:
                song = self.genius.search_song(track, artist)
                if song and song.lyrics:
                    self._inject_metadata(file_path, song.lyrics)
                    print(f"    ✅ Lyrics injected via Genius (Fallback)!")
                    return

            print(f"    ❌ No lyrics found for this track.")

        except Exception as e:
            # Catch network or API errors to avoid interrupting the audio download
            print(f"    ⚠️ Error during lyrics search: {e}")

    def _save_lrc_file(self, audio_file_path, synced_lyrics):
        """Creates the .lrc file next to the audio file."""
        base_name = os.path.splitext(audio_file_path)[0]
        lrc_path = f"{base_name}.lrc"
        with open(lrc_path, 'w', encoding='utf-8') as f:
            f.write(synced_lyrics)

    def _inject_metadata(self, file_path, lyrics):
        """Injects lyrics directly into FLAC or MP3 tags."""
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
            pass # Ignore writing errors to avoid crashing the program
