import logging
import sqlite3
from pathlib import Path
from collections import Counter
from typing import Any, Optional, Union, Dict, Set, Tuple

from qobuz_dl.color import YELLOW, RED, OFF

logger = logging.getLogger(__name__)

def create_db(db_path: Union[Path, str]) -> str:
    """
    Cria a base de dados SQLite ou atualiza o esquema (schema) se for uma versão antiga.
    """
    # Adicionado timeout de 15s para evitar "database is locked" em operações simultâneas
    with sqlite3.connect(db_path, timeout=15.0) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='downloads'")

        if cursor.fetchone()[0] == 1:
            cursor.execute("PRAGMA table_info(downloads)")
            columns = [info[1] for info in cursor.fetchall()]

            if 'quality' not in columns:
                logger.info(f"{YELLOW}Migrating old database to the new format...{OFF}")
                conn.execute("ALTER TABLE downloads RENAME TO downloads_old")
                conn.execute("""
                CREATE TABLE downloads (
                  "id" text NOT NULL,
                  "media_type" text NOT NULL DEFAULT 'album',
                  "quality" integer NOT NULL DEFAULT 27,
                  "file_format" text NOT NULL DEFAULT 'FLAC',
                  "quality_met" integer NOT NULL DEFAULT 0,
                  "bit_depth" text,
                  "sampling_rate" text,
                  "saved_path" text NOT NULL DEFAULT '',
                  "status" text NOT NULL DEFAULT 'downloaded',
                  "url" text NOT NULL DEFAULT '',
                  "release_date" text NOT NULL DEFAULT '',
                  "artist" text NOT NULL DEFAULT '',
                  "album" text NOT NULL DEFAULT '',
                  PRIMARY KEY ("id", "quality")
                );
                """)
                try:
                    conn.execute("INSERT INTO downloads (id) SELECT id FROM downloads_old")
                    # Só dropa a tabela antiga se o insert foi 100% bem sucedido
                    conn.execute("DROP TABLE downloads_old")
                    logger.info(f"{YELLOW}Database successfully updated!{OFF}")
                except sqlite3.Error as e:
                    logger.error(f"{RED}Failed to migrate old data: {e}{OFF}")
                    # Desfaz a alteração de nome em caso de pânico
                    conn.execute("DROP TABLE downloads")
                    conn.execute("ALTER TABLE downloads_old RENAME TO downloads")

            elif 'artist' not in columns:
                logger.info(f"{YELLOW}Upgrading database schema: Adding artist and album columns...{OFF}")
                try:
                    conn.execute("ALTER TABLE downloads ADD COLUMN artist text NOT NULL DEFAULT ''")
                    conn.execute("ALTER TABLE downloads ADD COLUMN album text NOT NULL DEFAULT ''")
                    logger.info(f"{YELLOW}Schema upgrade complete!{OFF}")
                except sqlite3.Error as e:
                    logger.error(f"{RED}Failed to add new columns: {e}{OFF}")

        else:
            try:
                conn.execute("""
                CREATE TABLE downloads (
                  "id" text NOT NULL,
                  "media_type" text NOT NULL DEFAULT 'album',
                  "quality" integer NOT NULL DEFAULT 27,
                  "file_format" text NOT NULL DEFAULT 'FLAC',
                  "quality_met" integer NOT NULL DEFAULT 0,
                  "bit_depth" text,
                  "sampling_rate" text,
                  "saved_path" text NOT NULL DEFAULT '',
                  "status" text NOT NULL DEFAULT 'downloaded',
                  "url" text NOT NULL DEFAULT '',
                  "release_date" text NOT NULL DEFAULT '',
                  "artist" text NOT NULL DEFAULT '',
                  "album" text NOT NULL DEFAULT '',
                  PRIMARY KEY ("id", "quality")
                );
                """)
                logger.info(f"{YELLOW}Download-IDs database created{OFF}")
            except sqlite3.OperationalError:
                pass

        # ---------------------------------------------------------------
        # NOVA TABELA: library_files
        # Espelho leve dos arquivos baixados, atualizado a cada faixa
        # taggeada com sucesso. Permite stats instantâneas sem rglob+mutagen.
        # ---------------------------------------------------------------
        try:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS library_files (
              "path" text NOT NULL,
              "artist" text NOT NULL DEFAULT '',
              "album_artist" text NOT NULL DEFAULT '',
              "album" text NOT NULL DEFAULT '',
              "title" text NOT NULL DEFAULT '',
              "format" text NOT NULL DEFAULT '',
              "bit_depth" text,
              "sampling_rate" text,
              "file_size" integer NOT NULL DEFAULT 0,
              "mtime" real NOT NULL DEFAULT 0,
              PRIMARY KEY ("path")
            );
            """)
        except sqlite3.OperationalError:
            pass

        return str(db_path)


def handle_download_id(
    db_path: Union[Path, str, None],
    item_id: str,
    add_id: bool = False,
    media_type: str = 'album',
    quality: int = 27,
    file_format: str = 'FLAC',
    quality_met: int = 0,
    bit_depth: Optional[str] = None,
    sampling_rate: Optional[str] = None,
    saved_path: Union[Path, str] = '',
    status: str = 'downloaded',
    url: str = '',
    release_date: str = '',
    artist: str = '',
    album: str = ''
) -> Optional[Tuple[Any, ...]]:
    """
    Grava ou verifica se um ID de download já existe na base de dados.
    """
    if not db_path:
        return None

    # Timeout essencial para o modo Batch (Parallel Downloads)
    with sqlite3.connect(db_path, timeout=15.0) as conn:
        if add_id:
            try:
                conn.execute(
                    """
                    INSERT INTO downloads (id, media_type, quality, file_format, quality_met, bit_depth,
                    sampling_rate, saved_path, url, release_date, status, artist, album)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item_id, media_type, quality, file_format, quality_met, bit_depth, sampling_rate,
                     str(saved_path), url, release_date, status, artist, album),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                logger.info(f"{YELLOW}[i] Already in database, skipping.{OFF}")
            except sqlite3.Error as e:
                logger.error(f"{RED}Unexpected DB error: {e}{OFF}")
            return None
        else:
            return conn.execute(
                "SELECT id FROM downloads WHERE id=? AND quality=?",
                (item_id, quality),
            ).fetchone()


def upsert_library_file(
    db_path: Union[Path, str, None],
    path: Union[Path, str],
    artist: str = '',
    album_artist: str = '',
    album: str = '',
    title: str = '',
    file_format: str = '',
    bit_depth: Optional[Any] = None,
    sampling_rate: Optional[Any] = None,
    file_size: int = 0,
    mtime: float = 0.0,
) -> None:
    """
    Insere ou atualiza a entrada de um arquivo na tabela library_files.
    Chamado pelo downloader logo após uma faixa ser taggeada com sucesso.
    """
    if not db_path:
        return

    try:
        with sqlite3.connect(db_path, timeout=15.0) as conn:
            conn.execute(
                """
                INSERT INTO library_files
                    (path, artist, album_artist, album, title, format, bit_depth, sampling_rate, file_size, mtime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    artist=excluded.artist,
                    album_artist=excluded.album_artist,
                    album=excluded.album,
                    title=excluded.title,
                    format=excluded.format,
                    bit_depth=excluded.bit_depth,
                    sampling_rate=excluded.sampling_rate,
                    file_size=excluded.file_size,
                    mtime=excluded.mtime
                """,
                (
                    str(path), artist, album_artist, album, title, file_format,
                    str(bit_depth) if bit_depth is not None else None,
                    str(sampling_rate) if sampling_rate is not None else None,
                    file_size, mtime,
                ),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}Erro ao atualizar library_files: {e}{OFF}")


def remove_library_file(db_path: Union[Path, str, None], path: Union[Path, str]) -> None:
    """
    Remove a entrada de um arquivo da tabela library_files (ex: ao apagar do disco).
    """
    if not db_path:
        return
    try:
        with sqlite3.connect(db_path, timeout=15.0) as conn:
            conn.execute("DELETE FROM library_files WHERE path=?", (str(path),))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}Erro ao remover library_files: {e}{OFF}")

def rename_library_path_prefix(db_path: Union[Path, str, None], old_prefix: Union[Path, str], new_prefix: Union[Path, str]) -> None:

    old_prefix, new_prefix = str(old_prefix), str(new_prefix)
    if not db_path or old_prefix == new_prefix:
        return
    try:
        with sqlite3.connect(db_path, timeout=15.0) as conn:
            conn.execute(
                "UPDATE library_files SET path = ? || substr(path, ?) WHERE path LIKE ? || '%'",
                (new_prefix, len(old_prefix) + 1, old_prefix),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}Erro ao renomear caminhos em library_files: {e}{OFF}")


def get_stats(db_path: Union[Path, str, None]) -> Optional[Dict[str, Any]]:
    """
    Retorna um conjunto de estatísticas com base no histórico gravado na base de dados.
    """
    if not db_path:
        return None
    try:
        with sqlite3.connect(db_path, timeout=15.0) as conn:
            cursor = conn.cursor()
            stats: Dict[str, Any] = {}

            cursor.execute("SELECT COUNT(*) FROM downloads WHERE media_type = 'track'")
            stats['total_tracks'] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM downloads WHERE media_type = 'album'")
            stats['total_albums'] = cursor.fetchone()[0]

            cursor.execute("SELECT quality, COUNT(*) FROM downloads GROUP BY quality")
            stats['quality_distribution'] = {str(q): count for q, count in cursor.fetchall()}

            cursor.execute("SELECT COUNT(DISTINCT artist) FROM downloads WHERE artist != ''")
            stats['total_artists'] = cursor.fetchone()[0]

            cursor.execute("SELECT artist, COUNT(*) as count FROM downloads WHERE artist != '' GROUP BY artist ORDER BY count DESC LIMIT 5")
            stats['top_artists'] = cursor.fetchall()

            return stats
    except sqlite3.Error:
        return None


def get_library_stats(db_path: Union[Path, str, None]) -> Optional[Dict[str, Any]]:
    """
    Estatísticas da biblioteca calculadas a partir da tabela library_files
    (instantâneo, sem rglob nem leitura de tags via mutagen).
    Substitui get_folder_stats() para uso frequente; use get_folder_stats()
    apenas quando quiser detectar arquivos adicionados/alterados fora do qobuz-dl.
    """
    if not db_path:
        return None
    try:
        with sqlite3.connect(db_path, timeout=15.0) as conn:
            cursor = conn.cursor()
            stats: Dict[str, Any] = {
                'total_tracks': 0,
                'total_albums': 0,
                'total_artists': 0,
                'total_size_bytes': 0,
            }

            cursor.execute("SELECT COUNT(*) FROM library_files")
            stats['total_tracks'] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT album_artist || '||' || album) FROM library_files WHERE album != ''")
            stats['total_albums'] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT album_artist) FROM library_files WHERE album_artist != ''")
            stats['total_artists'] = cursor.fetchone()[0]

            cursor.execute("SELECT COALESCE(SUM(file_size), 0) FROM library_files")
            stats['total_size_bytes'] = cursor.fetchone()[0]

            cursor.execute("SELECT format, bit_depth, sampling_rate, COUNT(*) FROM library_files GROUP BY format, bit_depth, sampling_rate")
            quality_counts: Counter = Counter()
            for fmt, bd, sr, count in cursor.fetchall():
                if (fmt or '').upper() == 'MP3':
                    label = "MP3 (320kbps)"
                else:
                    try:
                        bd_i = int(float(bd)) if bd else 16
                    except (ValueError, TypeError):
                        bd_i = 16
                    try:
                        sr_khz = float(sr) if sr else 44.1
                    except (ValueError, TypeError):
                        sr_khz = 44.1

                    if bd_i >= 24 and sr_khz > 96:
                        label = "Hi-Res+ (24b/>96kHz)"
                    elif bd_i >= 24:
                        label = "Hi-Res (24b/\u226496kHz)"
                    else:
                        label = "CD (16b/44.1kHz)"
                quality_counts[label] += count
            stats['quality_distribution'] = dict(quality_counts)

            cursor.execute("SELECT album_artist, COUNT(*) as count FROM library_files WHERE album_artist != '' GROUP BY album_artist ORDER BY count DESC LIMIT 5")
            stats['top_artists'] = cursor.fetchall()

            return stats
    except sqlite3.Error:
        return None


def get_folder_stats(directory: Union[Path, str]) -> Dict[str, Any]:
    """
    Lê diretamente os ficheiros de áudio reais na pasta (via mutagen) para gerar estatísticas.
    """
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, ID3NoHeaderError

    stats: Dict[str, Any] = {
        'total_tracks': 0,
        'total_albums': 0,
        'total_artists': 0,
        'total_size_bytes': 0,
    }

    artist_counts: Counter = Counter()
    quality_counts: Counter = Counter()

    album_dirs: Set[str] = set()
    dir_path = Path(directory)

    # Mantemos o iterador universal porque o Linux é case-sensitive (.FLAC vs .flac)
    for fpath in dir_path.rglob('*'):
        if not fpath.is_file() or fpath.suffix.lower() not in {'.flac', '.mp3'}:
            continue

        stats['total_tracks'] += 1
        try:
            stats['total_size_bytes'] += fpath.stat().st_size
        except OSError:
            pass

        album_dirs.add(str(fpath.parent))

        try:
            if fpath.suffix.lower() == '.flac':
                audio = FLAC(fpath)
                artist = (
                    audio.get('albumartist')
                    or audio.get('album_artist')
                    or audio.get('artist')
                    or ['Unknown']
                )[0]

                bd = getattr(audio.info, 'bits_per_sample', 16)
                sr = getattr(audio.info, 'sample_rate', 44100)

                if bd >= 24 and sr > 96000:
                    q_label = "Hi-Res+ (24b/>96kHz)"
                elif bd >= 24:
                    q_label = "Hi-Res (24b/\u226496kHz)"
                else:
                    q_label = "CD (16b/44.1kHz)"

            else:
                try:
                    audio = ID3(fpath)
                    frame = audio.get('TPE2') or audio.get('TPE1')
                    artist = frame.text[0] if frame else 'Unknown'
                except ID3NoHeaderError:
                    artist = 'Unknown'
                q_label = "MP3 (320kbps)"

            artist_counts[artist] += 1
            quality_counts[q_label] += 1

        except Exception:
            quality_counts['Unknown'] += 1

    stats['total_albums'] = len(album_dirs)
    stats['total_artists'] = len(artist_counts)
    stats['quality_distribution'] = dict(quality_counts)
    stats['top_artists'] = artist_counts.most_common(5)

    return stats