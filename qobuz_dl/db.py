import logging
import sqlite3
from pathlib import Path
from collections import Counter
from typing import Optional, Dict, Any

from qobuz_dl.color import YELLOW, RED, OFF

logger = logging.getLogger(__name__)

def create_db(db_path: str) -> str:
    """
    Cria a base de dados SQLite ou atualiza o esquema (schema) se for uma versão antiga.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Verifica se a tabela já existe
        cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='downloads'")
        
        if cursor.fetchone()[0] == 1:
            # A tabela existe. Lê as colunas atuais
            cursor.execute("PRAGMA table_info(downloads)")
            columns = [info[1] for info in cursor.fetchall()]
            
            # Migração Legada (v1 para v2)
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
                except sqlite3.Error as e:
                    logger.error(f"{RED}Failed to migrate old data: {e}{OFF}")
                
                conn.execute("DROP TABLE downloads_old")
                logger.info(f"{YELLOW}Database successfully updated!{OFF}")
                
            # Nova Migração (v2 para v2.1.4): Adiciona artista e álbum se faltarem
            elif 'artist' not in columns:
                logger.info(f"{YELLOW}Upgrading database schema: Adding artist and album columns...{OFF}")
                try:
                    conn.execute("ALTER TABLE downloads ADD COLUMN artist text NOT NULL DEFAULT ''")
                    conn.execute("ALTER TABLE downloads ADD COLUMN album text NOT NULL DEFAULT ''")
                    logger.info(f"{YELLOW}Schema upgrade complete!{OFF}")
                except sqlite3.Error as e:
                    logger.error(f"{RED}Failed to add new columns: {e}{OFF}")
                
        else:
            # A tabela não existe, cria do zero
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
                
        return db_path


def handle_download_id(db_path: str, item_id: str, add_id: bool = False, media_type: str = 'album', 
                       quality: int = 27, file_format: str = 'FLAC', quality_met: int = 0, 
                       bit_depth: str = None, sampling_rate: str = None, saved_path: str = '', 
                       status: str = 'downloaded', url: str = '', release_date: str = '', 
                       artist: str = '', album: str = '') -> Optional[tuple]:
    """
    Grava ou verifica se um ID de download já existe na base de dados.
    """
    if not db_path:
        return None

    with sqlite3.connect(db_path) as conn:
        if add_id:
            try:
                conn.execute(
                    """
                    INSERT INTO downloads (id, media_type, quality, file_format, quality_met, bit_depth, 
                    sampling_rate, saved_path, url, release_date, status, artist, album) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item_id, media_type, quality, file_format, quality_met, bit_depth, sampling_rate,
                     saved_path, url, release_date, status, artist, album),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                logger.info(f"{YELLOW}[i] Already in database, skipping.{OFF}")
            except sqlite3.Error as e:
                logger.error(f"{RED}Unexpected DB error: {e}{OFF}")
        else:
            return conn.execute(
                "SELECT id FROM downloads WHERE id=? AND quality=?",
                (item_id, quality),
            ).fetchone()
 
 
def get_stats(db_path: str) -> Optional[Dict[str, Any]]:
    """
    Retorna um conjunto de estatísticas com base no histórico gravado na base de dados.
    """
    if not db_path:
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            stats = {}

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


def get_folder_stats(directory: str) -> Dict[str, Any]:
    """
    Lê diretamente os ficheiros de áudio reais na pasta (via mutagen) para gerar estatísticas.
    Usa o collections.Counter para contagem eficiente.
    """
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, ID3NoHeaderError

    stats = {
        'total_tracks': 0,
        'total_albums': 0,
        'total_artists': 0,
        'total_size_bytes': 0,
    }

    # Usamos o Counter, que é otimizado para contar ocorrências matemáticas
    artist_counts = Counter()
    quality_counts = Counter()
    
    album_dirs = set()
    dir_path = Path(directory)

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

            else:  # .mp3
                try:
                    audio = ID3(fpath)
                    frame = audio.get('TPE2') or audio.get('TPE1')
                    artist = frame.text[0] if frame else 'Unknown'
                except ID3NoHeaderError:
                    artist = 'Unknown'
                q_label = "MP3 (320kbps)"

            # O Counter simplifica imenso a contagem!
            artist_counts[artist] += 1
            quality_counts[q_label] += 1

        except Exception:
            quality_counts['Unknown'] += 1

    stats['total_albums'] = len(album_dirs)
    stats['total_artists'] = len(artist_counts)
    stats['quality_distribution'] = dict(quality_counts)
    
    # most_common(5) substitui toda a tua lógica de lambda sortings
    stats['top_artists'] = artist_counts.most_common(5)

    return stats