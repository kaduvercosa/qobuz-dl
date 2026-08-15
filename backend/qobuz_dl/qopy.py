import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional, List

from qobuz_dl.constants import FORMAT_IDS
from qobuz_dl.exceptions import (
    AuthenticationError,
    ItemNotFoundError,
    GeoblockingError,
    DownloadError,
)

QOBUZ_BASE_URL = "https://www.qobuz.com/api.json/0.2"

APP_SECRETS = {
    "712108709": "b59a6858e945c7d0d0c3260c6d7bb5e4",
    "285473176": "4b68453be1a20ee43db2b0cb3ec0cfbe",
    "100000001": "e6a2eb68160cf1c0d4529a96e95ce3e1",
}

class Client:
    def __init__(self, email: str = "", pwd: str = "", app_id: str = "712108709", token: str = ""):
        self.email = email
        self.pwd = pwd
        self.app_id = app_id or "712108709"
        self.app_secret = APP_SECRETS.get(self.app_id, "b59a6858e945c7d0d0c3260c6d7bb5e4")
        self.user_auth_token = token or ""
        self.user_info: Dict[str, Any] = {}
        self.session_valid = False
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-App-Id": self.app_id
        }

    def api_call(self, endpoint: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Dict[str, Any]:
        if params is None:
            params = {}

        params["app_id"] = self.app_id
        if self.user_auth_token:
            params["user_auth_token"] = self.user_auth_token

        if signed and self.app_secret:
            ts = str(int(time.time()))
            params["request_ts"] = ts
            sig_raw = endpoint.replace("/", "") + "".join(f"{k}{v}" for k, v in sorted(params.items())) + self.app_secret
            params["request_sig"] = hashlib.md5(sig_raw.encode("utf-8")).hexdigest()

        query_str = urllib.parse.urlencode(params)
        url = f"{QOBUZ_BASE_URL}/{endpoint}?{query_str}"
        req = urllib.request.Request(url, headers=self.headers)

        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message") or err_json.get("error") or str(e)
            except Exception:
                msg = str(e)
            if e.code == 401 or e.code == 400 and "token" in msg.lower():
                raise AuthenticationError(f"Auth error: {msg}")
            elif e.code == 404:
                raise ItemNotFoundError(f"Item not found: {msg}")
            elif e.code == 403:
                raise GeoblockingError(f"Content restricted: {msg}")
            raise DownloadError(f"API HTTP {e.code}: {msg}")
        except Exception as e:
            raise DownloadError(f"API Connection error: {str(e)}")

    def auth(self, email: str = "", pwd: str = "", token: str = "") -> Dict[str, Any]:
        if token:
            self.user_auth_token = token
            res = self.api_call("user/get", signed=True)
            self.user_info = res
            self.session_valid = True
            return res
        elif email and pwd:
            res = self.api_call("user/login", {"username": email, "password": pwd}, signed=True)
            self.user_auth_token = res.get("user_auth_token", "")
            self.user_info = res.get("user", res)
            self.session_valid = True
            return res
        raise AuthenticationError("Credentials missing")

    def search(self, query: str, limit: int = 15, offset: int = 0) -> Dict[str, Any]:
        return self.api_call("catalog/search", {"query": query, "limit": limit, "offset": offset})

    def get_featured(self, type_: str = "new-releases", limit: int = 20) -> Dict[str, Any]:
        try:
            return self.api_call("album/getFeatured", {"type": type_, "limit": limit})
        except Exception:
            return {"albums": {"items": []}}

    def get_track(self, track_id: str) -> Dict[str, Any]:
        return self.api_call("track/get", {"track_id": track_id})

    def get_album(self, album_id: str) -> Dict[str, Any]:
        return self.api_call("album/get", {"album_id": album_id, "extra": "tracks"})

    def get_artist(self, artist_id: str) -> Dict[str, Any]:
        return self.api_call("artist/get", {"artist_id": artist_id, "extra": "albums"})

    def get_playlist(self, playlist_id: str) -> Dict[str, Any]:
        return self.api_call("playlist/get", {"playlist_id": playlist_id, "extra": "tracks"})

    def get_file_url(self, track_id: str, format_id: int = 27) -> Dict[str, Any]:
        return self.api_call("track/getFileUrl", {"track_id": track_id, "format_id": format_id, "intent": "stream"}, signed=True)
