import os
import logging
from pathlib import Path
from mutagen.flac import FLAC
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError
from concurrent.futures import ThreadPoolExecutor, as_completed

from qobuz_dl.lyrics_engine import LyricsEngine
from qobuz_dl.color import CYAN, GREEN, YELLOW, RED, OFF

logger = logging.getLogger(__name__)

def _process_single_file(file_path_str, engine, overwrite=False):
    try:
        title, artist, album = "", "", ""
        needs_lyrics = False
        file_path_lower = file_path_str.lower()

        if file_path_lower.endswith(".flac"):
            audio = FLAC(file_path_str)
            # Se não for para sobrescrever, checa se já tem letra e pula
            if not overwrite:
                if audio.get("LYRICS") or audio.get("UNSYNCEDLYRICS"):
                    return "skipped"
                
            title = audio.get("TITLE", [""])[0]
            album_artist = audio.get("ALBUMARTIST", [""])[0]
            performer_name = audio.get("ARTIST", ["Unknown Artist"])[0]
            artist = performer_name if album_artist in ["", "Various Artists"] else album_artist
            album = audio.get("ALBUM", [""])[0]
            needs_lyrics = True
            
        elif file_path_lower.endswith(".mp3"):
            try:
                audio = id3.ID3(file_path_str)
            except ID3NoHeaderError:
                return "skipped"
                
            # Se não for para sobrescrever, checa se já tem letra e pula
            if not overwrite:
                if audio.getall("USLT") or audio.getall("SYLT"):
                    return "skipped"
                
            title = audio.get("TIT2").text[0] if audio.get("TIT2") else ""
            artist = audio.get("TPE1").text[0] if audio.get("TPE1") else ""
            album = audio.get("TALB").text[0] if audio.get("TALB") else ""
            needs_lyrics = True

        if not title or not artist:
            return "skipped"
            
        if needs_lyrics:
            if overwrite:
                print(f"{YELLOW}  > Overwriting lyrics for: {artist} - {title}...{OFF}")
            else:
                print(f"{YELLOW}  > Missing lyrics: {artist} - {title}. Searching...{OFF}")
                
            # Chama a engine repassando a ordem de sobrescrever
            engine.fetch_and_inject(
                file_path=file_path_str,
                artist=artist,
                track=title,
                album=album,
                overwrite=overwrite 
            )
            return "injected"
                
    except Exception as e:
        logger.error(f"{RED}[!] Error reading {file_path_str}: {e}{OFF}")
        return "error"
    return "skipped"

def inject_lyrics_retroactively(directory_path, genius_token=None, overwrite=False):
    print(f"\n{CYAN}[*] Starting retroactive lyrics scan in: {directory_path}{OFF}")
    if overwrite:
        print(f"{RED}[!] OVERWRITE MODE ENABLED: Existing lyrics will be replaced.{OFF}")
    
    target_dir = Path(directory_path)
    if not target_dir.is_dir():
        print(f"{RED}[!] Error: The directory '{directory_path}' does not exist.{OFF}")
        return

    engine = LyricsEngine(genius_token)
    
    # Busca arquivos suportados ignorando case-sensitivity de extensões
    all_files = []
    for ext in ['.flac', '.mp3']:
        all_files.extend(list(target_dir.rglob(f'*{ext}')))
        all_files.extend(list(target_dir.rglob(f'*{ext.upper()}')))
        
    all_files = list(set(all_files)) # Remove duplicates
    
    processed = len(all_files)
    injected = 0
    skipped = 0
    errors = 0

    print(f"{CYAN}[*] Found {processed} compatible audio files. Processing...{OFF}")

    # Processamento paralelo
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Passando a variável overwrite para a thread
        futures = {executor.submit(_process_single_file, str(path), engine, overwrite): path for path in all_files}
        for future in as_completed(futures):
            result = future.result()
            if result == "injected":
                injected += 1
            elif result == "skipped":
                skipped += 1
            elif result == "error":
                errors += 1
                    
    print(f"\n{GREEN}[+] Retroactive Scan and Injection Completed!{OFF}")
    print(f"{CYAN}  - Total files analyzed: {processed}{OFF}")
    print(f"{GREEN}  - Injection attempts: {injected}{OFF}")
    print(f"{YELLOW}  - Skipped files (already tagged or missing data): {skipped}{OFF}")
    if errors > 0:
        print(f"{RED}  - Errors encountered: {errors}{OFF}")
    print("\n")
