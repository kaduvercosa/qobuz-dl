import logging
import asyncio
from pathlib import Path
from typing import Any, Tuple, Optional

from mutagen.flac import FLAC
from mutagen.id3 import ID3
from qobuz_dl.db import handle_download_id
from qobuz_dl.color import GREEN, RED, YELLOW, CYAN, OFF

logger = logging.getLogger(__name__)

async def _extract_track_data(file_path: Path, client: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Lê as tags locais (FLAC ou MP3) para obter os IDs do Qobuz.
    Se não encontrar o ID mas encontrar o ISRC, faz uma pesquisa na API.
    
    Retorna:
        Uma tupla contendo (track_id, album_id).
    """
    track_id = None
    album_id = None
    isrc = None

    # 1. Leitura de ficheiros FLAC
    if file_path.suffix.lower() == ".flac":
        audio = FLAC(file_path)
        track_id = audio.get("QOBUZTRACKID", [None])[0]
        album_id = audio.get("QOBUZALBUMID", [None])[0]
        isrc = audio.get("isrc", [None])[0]
        
    # 2. Leitura de ficheiros MP3
    elif file_path.suffix.lower() == ".mp3":
        audio = ID3(file_path)
        track_txxx = audio.get("TXXX:QOBUZTRACKID")
        if track_txxx: 
            track_id = track_txxx.text[0]
        album_txxx = audio.get("TXXX:QOBUZALBUMID")
        if album_txxx: 
            album_id = album_txxx.text[0]
        tsrc = audio.get("TSRC")
        if tsrc: 
            isrc = tsrc.text[0]
            
    # 3. Fallback (Alternativa): Procurar na API usando o ISRC
    if not track_id and isrc:
        logger.info(f"{CYAN}[*] Missing local ID. Fetching via API (ISRC: {isrc})...{OFF}")
        try:
            # Substituímos o asyncio.run() por um await natural
            res = await client.search_tracks(isrc, limit=1)
            
            if res and "tracks" in res and res["tracks"]["items"]:
                q_track = res["tracks"]["items"][0]
                track_id = str(q_track["id"])
                album_id = str(q_track.get("album", {}).get("id", ""))
                
            # Substituímos o time.sleep por asyncio.sleep para não bloquear o programa
            await asyncio.sleep(0.2)
            
        except Exception as e:
            logger.debug(f"{RED}[!] Falha ao procurar ISRC na API para {file_path.name}: {e}{OFF}")
            
    return track_id, album_id


async def sync_database(directory: str | Path, db_path: str, client: Any) -> None:
    """
    Verifica o diretório local e restaura IDs do Qobuz em falta na base de dados local.
    Usa tags personalizadas embutidas ou pesquisa inversa via API do Qobuz.
    """
    logger.info(f"\n{YELLOW}[*] Starting Local Database Synchronization...{OFF}")
    logger.info(f"{YELLOW}[*] Scanning directory: {directory}{OFF}")

    target_dir = Path(directory)
    
    # Procura todos os ficheiros suportados de forma mais limpa e eficiente
    all_files_paths = [
        p for p in target_dir.rglob('*') 
        if p.is_file() and p.suffix.lower() in {'.flac', '.mp3'}
    ]

    if not all_files_paths:
        logger.info(f"{YELLOW}[!] No audio files found in {directory}.{OFF}")
        return

    logger.info(f"{YELLOW}[*] Found {len(all_files_paths)} audio files. Processing tags...{OFF}")

    added_tracks = 0
    added_albums = set()

    try:
        for file_path in all_files_paths:
            quality = 27
            file_format = "FLAC" if file_path.suffix.lower() == ".flac" else "MP3"

            try:
                # Extraímos os metadados através da nossa nova função auxiliar
                track_id, album_id = await _extract_track_data(file_path, client)
                
                # Regista a faixa na base de dados
                if track_id:
                    handle_download_id(
                        db_path=db_path, 
                        item_id=track_id, 
                        add_id=True, 
                        media_type="track",
                        quality=quality, 
                        file_format=file_format, 
                        saved_path=str(file_path)
                    )
                    added_tracks += 1
                
                # Regista o álbum na base de dados (se ainda não tiver sido adicionado)
                if album_id and album_id not in added_albums:
                    handle_download_id(
                        db_path=db_path, 
                        item_id=album_id, 
                        add_id=True, 
                        media_type="album",
                        quality=quality, 
                        file_format=file_format, 
                        # Substitui os.path.dirname por .parent do pathlib
                        saved_path=str(file_path.parent)
                    )
                    added_albums.add(album_id)

            except Exception as e:
                logger.error(f"{RED}[!] Error processing {file_path.name}: {e}{OFF}")

    except KeyboardInterrupt:
        logger.warning(f"\n{YELLOW}[!] Synchronization forcibly interrupted by user!{OFF}")
        logger.warning(f"{YELLOW}[!] Don't worry, all progress up to this point has been safely saved.{OFF}")

    logger.info(f"{GREEN}[+] Sync complete! Restored {added_tracks} tracks and {len(added_albums)} albums into the local database.{OFF}")