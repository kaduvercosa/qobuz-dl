from typing import Dict, Any, Optional
from core.provider_base import ProviderBase
from qobuz_dl.core import QobuzDL

class QobuzProvider(ProviderBase):
    def __init__(self, email: str = "", password: str = "", token: str = "", app_id: str = ""):
        self.qobuz = QobuzDL(email=email, password=password, token=token, app_id=app_id)

    def authenticate(self, email: str = "", password: str = "", token: str = "", app_id: str = "") -> Dict[str, Any]:
        return self.qobuz.initialize_client(email=email, password=password, token=token, app_id=app_id)

    def fetch_dynamic_tokens(self):
        return self.qobuz.get_tokens()

    def resolve(self, url: str) -> Dict[str, Any]:
        from qobuz_dl.constants import QOBUZ_URL_REGEX
        match = QOBUZ_URL_REGEX.search(url.strip())
        if match:
            return {"valid": True, "type": match.group("type"), "id": match.group("id")}
        return {"valid": False, "error": "Invalid Qobuz URL"}

    def get_track_metadata(self, track_id: str) -> Dict[str, Any]:
        return self.qobuz.get_track_info(track_id)

    def get_album_metadata(self, album_id: str) -> Dict[str, Any]:
        return self.qobuz.get_album_info(album_id)

    def get_download_url(self, track_id: str, quality: int = 27) -> Dict[str, Any]:
        return self.qobuz.client.get_file_url(track_id, format_id=quality)
