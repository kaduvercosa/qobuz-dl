import urllib.request
import urllib.parse
import json
import os
import re
from typing import Optional, Dict, Any

class LyricsEngine:
    """Public synchronized lyrics engine (LRC / Plain text)."""
    BASE_URL = "https://lrclib.net/api/get"

    @classmethod
    def fetch_lyrics(cls, artist: str, title: str, album: str = "", duration: float = 0.0) -> Optional[Dict[str, Any]]:
        params = {
            "artist_name": artist,
            "track_name": title,
        }
        if album:
            params["album_name"] = album
        if duration > 0:
            params["duration"] = int(duration)
        
        query = urllib.parse.urlencode(params)
        url = f"{cls.BASE_URL}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "Qobuz-DL-Ultimate/3.0"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    synced = data.get("syncedLyrics")
                    plain = data.get("plainLyrics")
                    if synced or plain:
                        return {"synced": synced, "plain": plain}
        except Exception:
            return None
        return None

    @classmethod
    def save_lrc_file(cls, lrc_path: str, synced_lyrics: str):
        if not synced_lyrics:
            return
        os.makedirs(os.path.dirname(lrc_path), exist_ok=True)
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(synced_lyrics)
