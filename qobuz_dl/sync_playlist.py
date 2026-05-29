"""
Sincronização bidirecional entre uma pasta local e uma playlist do Qobuz.
"""

import os
import logging
from pathlib import Path
from typing import Tuple, Dict, List, Any

from mutagen.flac import FLAC
from mutagen.id3 import ID3

from qobuz_dl.color import CYAN, GREEN, RED, YELLOW, OFF

logger = logging.getLogger(__name__)

def _scan_local_tracks(directory: str | Path) -> Tuple[Dict[str, Path], List[Path]]:
    """
    Percorre a pasta local em busca de ficheiros de áudio e lê as suas tags.
    
    Retorna:
        Um dicionário com {track_id: caminho_do_ficheiro} e uma lista de ficheiros sem tag.
    """
    local_tracks = {}
    untagged_files = []
    
    # Usamos o Path.rglob para procurar recursivamente, o que substitui o os.walk de forma mais limpa.
    base_dir = Path(directory)
    
    for fpath in base_dir.rglob('*'):
        if fpath.suffix.lower() not in ['.flac', '.mp3']:
            continue

        track_id = None

        try:
            if fpath.suffix.lower() == '.flac':
                audio = FLAC(fpath)
                track_id = audio.get("QOBUZTRACKID", [None])[0]
            else:
                audio = ID3(fpath)
                txxx = audio.get("TXXX:QOBUZTRACKID")
                if txxx:
                    track_id = txxx.text[0]
        except Exception as e:
            logger.debug(f"Falha ao ler tags de {fpath}: {e}")

        if track_id:
            local_tracks[str(track_id)] = fpath
        else:
            untagged_files.append(fpath)

    return local_tracks, untagged_files

async def _fetch_remote_tracks(client: Any, playlist_id: str) -> Tuple[str, List[Dict]]:
    """
    Descarrega os metadados da playlist do Qobuz de forma assíncrona.
    """
    all_items = []
    playlist_name = "Unknown Playlist"
    
    async for chunk in client.get_plist_meta(playlist_id):
        if "name" in chunk and playlist_name == "Unknown Playlist":
            playlist_name = chunk.get("name")
        items = chunk.get("tracks", {}).get("items", [])
        all_items.extend(items)
        
    return playlist_name, all_items

def _sanitize_dirname(name: str) -> str:
    """
    Remove caracteres que não são permitidos em nomes de pastas/ficheiros.
    """
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name.strip()
    
def _clean_empty_dirs(base_directory: str | Path, exclude_dirs: set = None) -> None:
    """
    Limpa pastas vazias que possam ter ficado após a exclusão de músicas.
    """
    exclude = exclude_dirs or set()
    exclude.add("_Playlists")
    base_dir = Path(base_directory)
    
    # O os.walk ainda é útil aqui para varrer de baixo para cima (topdown=False)
    for root, dirs, files in os.walk(base_dir, topdown=False):
        for d in dirs:
            dir_path = Path(root) / d
            try:
                if d in exclude:
                    continue
                # Se a pasta estiver vazia (sem conteúdo)
                if not any(dir_path.iterdir()):
                    dir_path.rmdir()
                    rel = dir_path.relative_to(base_dir)
                    logger.info(f"  {RED}[-] Removed empty dir: {rel}{OFF}")
            except OSError:
                pass

async def _execute_sync(qobuz_dl: Any, target_folder: Path, to_delete_ids: set, 
                        to_download_ids: set, local_tracks: dict, remote_items: list, 
                        remote_ids: dict) -> None:
    """
    Função dedicada exclusivamente a executar as eliminações e os downloads.
    Separar isto da função principal torna o código mais legível.
    """
    logger.info(f"\n{CYAN}[4/4] Executing sync...{OFF}")

    # 1. Eliminação de ficheiros
    deleted_count = 0
    for tid in to_delete_ids:
        fpath = local_tracks[tid]
        try:
            fpath.unlink() # Substitui os.remove()
            deleted_count += 1
            logger.info(f"  {RED}[-] Deleted: {fpath.name}{OFF}")

            # Apaga o ficheiro .lrc se existir
            lrc_path = fpath.with_suffix(".lrc")
            if lrc_path.is_file():
                lrc_path.unlink()
                logger.info(f"  {RED}[-] Deleted: {lrc_path.name}{OFF}")
        except OSError as e:
            logger.error(f"  {RED}[!] Failed to delete {fpath}: {e}{OFF}")
    
    _clean_empty_dirs(target_folder, exclude_dirs={"_Playlists"})

    # 2. Configurações temporárias para o download
    original_folder_format = qobuz_dl.folder_format
    original_multi_disc = qobuz_dl.settings.multiple_disc_one_dir
    qobuz_dl.folder_format = "."
    qobuz_dl.settings.multiple_disc_one_dir = True

    position_map = {str(item["id"]): idx for idx, item in enumerate(remote_items, start=1)}

    # 3. Download de novos ficheiros
    downloaded_count = 0
    for tid in to_download_ids:
        playlist_idx = position_map.get(tid, 0)
        try:
            await qobuz_dl.download_from_id(
                tid,
                album=False,
                alt_path=str(target_folder),
                is_playlist=True,
                playlist_index=playlist_idx,
            )
            downloaded_count += 1
        except Exception as e:
            logger.error(f"  {RED}[!] Failed to download track {tid}: {e}{OFF}")

    # Restaura as configurações
    qobuz_dl.folder_format = original_folder_format
    qobuz_dl.settings.multiple_disc_one_dir = original_multi_disc

    # 4. Finalização
    from qobuz_dl.utils import make_m3u
    if not getattr(qobuz_dl, 'no_m3u_for_playlists', False):
        make_m3u(str(target_folder), remote_items)

    logger.info(f"\n{GREEN}━━━ SYNC COMPLETE ━━━{OFF}")
    logger.info(f"  {GREEN}↓ Downloaded   : {downloaded_count} tracks{OFF}")
    logger.info(f"  {RED}✕ Deleted      : {deleted_count} files{OFF}")
    logger.info(f"  {GREEN}✓ Total active : {len(remote_ids)} tracks{OFF}\n")


async def sync_playlist(qobuz_dl: Any, url: str, folder: str, auto_confirm: bool = False) -> None:
    """
    Função principal que orquestra a verificação e sincronização da playlist.
    """
    from qobuz_dl.utils import get_url_info, make_m3u

    try:
        url_type, playlist_id = get_url_info(url)
    except (AttributeError, IndexError):
        logger.error(f"{RED}Invalid URL: {url}{OFF}")
        return

    if url_type != "playlist":
        logger.error(f"{RED}URL is not a playlist. Use a playlist URL like https://play.qobuz.com/playlist/12345{OFF}")
        return

    logger.info(f"\n{YELLOW}━━━ PLAYLIST SYNC ━━━{OFF}")
    logger.info(f"{YELLOW}URL : {url}{OFF}")

    # PASSO 1: Obter dados remotos (Qobuz)
    logger.info(f"{CYAN}[1/4] Fetching playlist from Qobuz...{OFF}")
    playlist_name, remote_items = await _fetch_remote_tracks(qobuz_dl.client, playlist_id)
    remote_ids = {str(item["id"]): item for item in remote_items}
    logger.info(f"{CYAN}      Found {len(remote_ids)} tracks in the Qobuz playlist.{OFF}")

    if not remote_ids:
        logger.info(f"{YELLOW}The Qobuz playlist is empty. Nothing to sync.{OFF}")
        return

    # Preparar a pasta de destino
    safe_playlist_name = _sanitize_dirname(playlist_name)
    folder_path = Path(folder)
    
    if folder_path.name == safe_playlist_name:
        target_folder = folder_path
    else:
        target_folder = folder_path / safe_playlist_name

    logger.info(f"{YELLOW}DIR : {target_folder}{OFF}\n")
    target_folder.mkdir(parents=True, exist_ok=True)

    # PASSO 2: Obter dados locais
    logger.info(f"{CYAN}[2/4] Scanning local folder...{OFF}")
    local_tracks, untagged = _scan_local_tracks(target_folder)
    logger.info(f"{CYAN}      Found {len(local_tracks)} tagged tracks locally.{OFF}")

    # PASSO 3: Comparar e gerar o resumo
    local_id_set = set(local_tracks.keys())
    remote_id_set = set(remote_ids.keys())

    to_download_ids = remote_id_set - local_id_set
    to_delete_ids = local_id_set - remote_id_set
    already_synced = local_id_set & remote_id_set

    logger.info(f"\n{CYAN}[3/4] Sync summary:{OFF}")
    logger.info(f"  {GREEN}↓ To download : {len(to_download_ids)} tracks{OFF}")
    logger.info(f"  {RED}✕ To delete   : {len(to_delete_ids)} files{OFF}")
    logger.info(f"    Already synced: {len(already_synced)} tracks")

    # Se já estiver tudo sincronizado, atualiza a m3u e sai
    if not to_download_ids and not to_delete_ids:
        logger.info(f"\n{GREEN}✓ Folder is already in sync with the playlist!{OFF}")
        if not getattr(qobuz_dl, 'no_m3u_for_playlists', False):
            make_m3u(str(target_folder), remote_items)
            logger.info(f"{CYAN}✓ Playlist .m3u file updated with latest track order.{OFF}")
        return

    # Mostrar o que vai ser apagado
    if to_delete_ids:
        logger.info(f"\n{RED}Files to PERMANENTLY DELETE:{OFF}")
        for tid in sorted(to_delete_ids):
            logger.info(f"  {RED}✕ {local_tracks[tid].name}{OFF}")

    # Mostrar o que vai ser descarregado
    if to_download_ids:
        logger.info(f"\n{GREEN}Tracks to DOWNLOAD:{OFF}")
        for tid in sorted(to_download_ids):
            item = remote_ids[tid]
            album_artist = item.get("album", {}).get("artist", {}).get("name")
            performer_name = item.get("performer", {}).get("name", "Unknown")
            artist = performer_name if album_artist in [None, "Various Artists"] else album_artist
            title = item.get("title", "Unknown")
            logger.info(f"  {GREEN}↓ {artist} -- {title}{OFF}")

    # Pedir confirmação ao utilizador
    if not auto_confirm:
        try:
            answer = input(f"\n{YELLOW}Proceed with sync? [y/N]: {OFF}").strip().lower()
            if answer != 'y':
                logger.info(f"{YELLOW}Sync cancelled by user.{OFF}")
                return
        except (KeyboardInterrupt, EOFError):
            logger.info(f"\n{YELLOW}Sync cancelled.{OFF}")
            return

    # PASSO 4: Executar a Sincronização (movido para uma função separada)
    await _execute_sync(qobuz_dl, target_folder, to_delete_ids, to_download_ids, 
                        local_tracks, remote_items, remote_ids)