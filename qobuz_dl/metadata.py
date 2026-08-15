import os
import urllib.request
from typing import Dict, Any, Optional

class MetadataTagger:
    """Handles Vorbis Comment & ID3 tagging with embedded artwork."""
    @staticmethod
    def fetch_cover_art(url: str) -> Optional[bytes]:
        if not url:
            return None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Qobuz-DL/3.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception:
            return None
        return None

    @staticmethod
    def save_cover_file(folder_path: str, cover_bytes: bytes, filename: str = "cover.jpg"):
        if not cover_bytes:
            return
        os.makedirs(folder_path, exist_ok=True)
        dest = os.path.join(folder_path, filename)
        if not os.path.exists(dest):
            with open(dest, "wb") as f:
                f.write(cover_bytes)
