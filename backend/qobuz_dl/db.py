import sqlite3
import os
import time
from typing import List, Dict, Any, Optional

class DatabaseManager:
    """Local SQLite database for tracking downloaded items and preventing duplicate downloads."""
    def __init__(self, db_path: str = "./qobuz_downloads.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        # 1. Try specified path
        try:
            if os.path.dirname(self.db_path):
                os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("SELECT 1")
            return conn
        except Exception:
            pass

        # 2. Try /tmp fallback
        try:
            fallback_path = os.path.join("/tmp", os.path.basename(self.db_path))
            conn = sqlite3.connect(fallback_path)
            conn.execute("SELECT 1")
            return conn
        except Exception:
            pass

        # 3. In-memory fallback
        return sqlite3.connect(":memory:")

    def _init_db(self):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS downloads (
                        id TEXT PRIMARY KEY,
                        item_type TEXT,
                        title TEXT,
                        artist TEXT,
                        album TEXT,
                        format_id INTEGER,
                        quality TEXT,
                        file_path TEXT,
                        downloaded_at INTEGER
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS favorites_sync (
                        item_id TEXT PRIMARY KEY,
                        item_type TEXT,
                        synced_at INTEGER
                    )
                """)
                conn.commit()
        except Exception:
            pass

    def is_downloaded(self, item_id: str, format_id: Optional[int] = None) -> bool:
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                if format_id:
                    cursor.execute("SELECT 1 FROM downloads WHERE id = ? AND format_id = ?", (str(item_id), format_id))
                else:
                    cursor.execute("SELECT 1 FROM downloads WHERE id = ?", (str(item_id),))
                return cursor.fetchone() is not None
        except Exception:
            return False

    def record_download(self, item_id: str, item_type: str, title: str, artist: str, album: str, format_id: int, quality: str, file_path: str):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO downloads (id, item_type, title, artist, album, format_id, quality, file_path, downloaded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(item_id), item_type, title, artist, album, format_id, quality, file_path, int(time.time())))
                conn.commit()
        except Exception:
            pass

    def get_download_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        try:
            with self._get_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM downloads ORDER BY downloaded_at DESC LIMIT ?", (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []
