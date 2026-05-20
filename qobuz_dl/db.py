import logging
import sqlite3

from qobuz_dl.color import YELLOW, RED, OFF

logger = logging.getLogger(__name__)


def create_db(db_path):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Check if the table already exists
        cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='downloads'")
        
        if cursor.fetchone()[0] == 1:
            # Table exists. Read current columns
            cursor.execute("PRAGMA table_info(downloads)")
            columns = [info[1] for info in cursor.fetchall()]
            
            # Legacy migration (v1 to v2)
            if 'quality' not in columns:
                logger.info(f"{YELLOW}Migrating old database to the new format...{OFF}")
                
                # Rename the old table
                conn.execute("ALTER TABLE downloads RENAME TO downloads_old")
                
                # Create the new table with updated schema including artist and album
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
                
                # Copy old historical IDs
                try:
                    conn.execute("INSERT INTO downloads (id) SELECT id FROM downloads_old")
                except sqlite3.Error as e:
                    logger.error(f"{RED}Failed to migrate old data: {e}{OFF}")
                
                # Drop the temporary old table
                conn.execute("DROP TABLE downloads_old")
                logger.info(f"{YELLOW}Database successfully updated!{OFF}")
                
            # New Migration (v2 to v2.1.4): Add artist and album if missing
            elif 'artist' not in columns:
                logger.info(f"{YELLOW}Upgrading database schema: Adding artist and album columns...{OFF}")
                try:
                    conn.execute("ALTER TABLE downloads ADD COLUMN artist text NOT NULL DEFAULT ''")
                    conn.execute("ALTER TABLE downloads ADD COLUMN album text NOT NULL DEFAULT ''")
                    logger.info(f"{YELLOW}Schema upgrade complete!{OFF}")
                except sqlite3.Error as e:
                    logger.error(f"{RED}Failed to add new columns: {e}{OFF}")
                
        else:
            # Table does not exist, create it from scratch
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


def handle_download_id(db_path, item_id, add_id=False, media_type='album', quality=27, file_format='FLAC',
                       quality_met=0, bit_depth=None, sampling_rate=None, saved_path='', status='downloaded',
                       url='', release_date='', artist='', album=''):
    if not db_path:
        return

    with sqlite3.connect(db_path) as conn:
        if add_id:
            try:
                # Inject artist and album dynamically into the database
                conn.execute(
                    """
                    INSERT INTO downloads (id, media_type, quality, file_format, quality_met, bit_depth, 
                    sampling_rate, saved_path, url, release_date, status, artist, album) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item_id, media_type, quality, file_format, quality_met, bit_depth, sampling_rate,
                     saved_path, url, release_date, status, artist, album),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # Provide clean visual feedback instead of an error
                logger.info(f"{YELLOW}[i] Already in database, skipping.{OFF}")
            except sqlite3.Error as e:
                logger.error(f"{RED}Unexpected DB error: {e}{OFF}")
        else:
            return conn.execute(
                "SELECT id FROM downloads WHERE id=? AND quality=?",
                (item_id, quality),
            ).fetchone()
 
 
def get_stats(db_path):
    """Returns a comprehensive set of statistics from the database."""
    if not db_path:
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            stats = {}

            # Total tracks downloaded
            cursor.execute("SELECT COUNT(*) FROM downloads WHERE media_type = 'track'")
            stats['total_tracks'] = cursor.fetchone()[0]

            # Total albums downloaded
            cursor.execute("SELECT COUNT(*) FROM downloads WHERE media_type = 'album'")
            stats['total_albums'] = cursor.fetchone()[0]

            # Quality distribution
            cursor.execute("SELECT quality, COUNT(*) FROM downloads GROUP BY quality")
            quality_counts = cursor.fetchall()
            stats['quality_distribution'] = {str(q): count for q, count in quality_counts}

            # Unique artists count
            cursor.execute("SELECT COUNT(DISTINCT artist) FROM downloads WHERE artist != ''")
            stats['total_artists'] = cursor.fetchone()[0]

            # Top 5 artists
            cursor.execute("SELECT artist, COUNT(*) as count FROM downloads WHERE artist != '' GROUP BY artist ORDER BY count DESC LIMIT 5")
            stats['top_artists'] = cursor.fetchall()

            return stats
    except sqlite3.Error:
        return None

def get_folder_stats(directory):
    """
    Scans the actual download directory and builds real-time statistics
    directly from the audio files on disk, reading embedded tags via mutagen.

    Unlike get_stats() which reads from the database (a historical record),
    this function reflects the true current state of the collection:
    deleted or moved files are not counted, and quality is read from the
    actual audio stream metadata rather than what was recorded at download time.
    """
    import os
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, ID3NoHeaderError

    stats = {
        'total_tracks': 0,
        'total_albums': 0,
        'total_artists': 0,
        'quality_distribution': {},
        'top_artists': [],
        'total_size_bytes': 0,
    }

    artist_counts = {}
    # Each directory that contains at least one audio file counts as one album folder.
    album_dirs = set()

    for root, _, files in os.walk(directory):
        for fname in files:
            fpath = os.path.join(root, fname)
            lower = fname.lower()

            if not lower.endswith(('.flac', '.mp3')):
                continue

            stats['total_tracks'] += 1
            try:
                stats['total_size_bytes'] += os.path.getsize(fpath)
            except OSError:
                pass
            album_dirs.add(root)

            try:
                if lower.endswith('.flac'):
                    audio = FLAC(fpath)

                    # Prefer album artist for grouping (avoids counting "Various Artists"
                    # compilations under each individual performer).
                    artist = (
                        audio.get('albumartist')
                        or audio.get('album_artist')
                        or audio.get('artist')
                        or ['Unknown']
                    )[0]

                    # mutagen exposes the real technical metadata via audio.info,
                    # which is read directly from the FLAC stream header — reliable
                    # regardless of what tags were manually written.
                    bd = getattr(audio.info, 'bits_per_sample', 16)
                    sr = getattr(audio.info, 'sample_rate', 44100)

                    # Map to the same quality tiers Qobuz uses internally
                    # (quality IDs 27, 7, 6) so the output is familiar.
                    if bd >= 24 and sr > 96000:
                        q_label = "Hi-Res+ (24b/>96kHz)"
                    elif bd >= 24:
                        q_label = "Hi-Res (24b/\u226496kHz)"
                    else:
                        q_label = "CD (16b/44.1kHz)"

                else:  # .mp3
                    try:
                        audio = ID3(fpath)
                        # TPE2 = Album Artist (preferred), TPE1 = Track Artist
                        frame = audio.get('TPE2') or audio.get('TPE1')
                        artist = frame.text[0] if frame else 'Unknown'
                    except ID3NoHeaderError:
                        artist = 'Unknown'
                    q_label = "MP3 (320kbps)"

                artist_counts[artist] = artist_counts.get(artist, 0) + 1
                stats['quality_distribution'][q_label] = (
                    stats['quality_distribution'].get(q_label, 0) + 1
                )

            except Exception:
                # Corrupt or unreadable file: count it but mark quality as unknown
                # so the total track count remains accurate.
                stats['quality_distribution']['Unknown'] = (
                    stats['quality_distribution'].get('Unknown', 0) + 1
                )

    stats['total_albums'] = len(album_dirs)
    stats['total_artists'] = len(artist_counts)
    # Top 5 artists by track count, descending
    stats['top_artists'] = sorted(artist_counts.items(), key=lambda x: -x[1])[:5]

    return stats