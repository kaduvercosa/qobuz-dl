import os
import re
import time
import json
from typing import Dict, Any, List, Optional, Tuple

from qobuz_dl.bundle import Bundle
from qobuz_dl.qopy import Client
from qobuz_dl.constants import FORMAT_IDS, DEFAULT_FOLDER_FORMAT, DEFAULT_TRACK_FORMAT
from qobuz_dl.utils import sanitize_filename, get_quality_badge, format_bytes
from qobuz_dl.exceptions import AuthenticationError, ItemNotFoundError, DownloadError

class QobuzDL:
    def __init__(self, email: str = "", password: str = "", app_id: str = "", token: str = ""):
        self.bundle = Bundle()
        self.app_id = app_id or self.bundle.get_app_id()
        self.secrets = self.bundle.get_secrets()
        self.client = Client(email=email, pwd=password, app_id=self.app_id, token=token)
        self.directory = "./downloads"
        self.folder_format = DEFAULT_FOLDER_FORMAT
        self.track_format = DEFAULT_TRACK_FORMAT
        self.format_id = 27  # Default 24/192 FLAC

    def get_tokens(self) -> Tuple[str, Dict[str, str]]:
        """Fetch latest App ID and Secrets dynamically from Qobuz web player bundle."""
        self.app_id, self.secrets = self.bundle.get_tokens()
        self.client.app_id = self.app_id
        if self.secrets:
            # Pick first available secret as primary
            first_secret = next(iter(self.secrets.values()))
            self.client.app_secret = first_secret
        return self.app_id, self.secrets

    def initialize_client(self, email: str = "", password: str = "", token: str = "", app_id: str = "") -> Dict[str, Any]:
        """Initialize client and authenticate."""
        if app_id:
            self.app_id = app_id
        elif not self.app_id:
            self.get_tokens()

        self.client = Client(email=email, pwd=password, app_id=self.app_id, token=token)
        if self.secrets:
            self.client.app_secret = next(iter(self.secrets.values()))
        return self.client.auth(email=email, pwd=password, token=token)

    def get_track_info(self, track_id: str) -> Dict[str, Any]:
        return self.client.get_track(track_id)

    def get_album_info(self, album_id: str) -> Dict[str, Any]:
        return self.client.get_album(album_id)

    def get_playlist_info(self, playlist_id: str) -> Dict[str, Any]:
        return self.client.get_playlist(playlist_id)

    def get_artist_info(self, artist_id: str) -> Dict[str, Any]:
        return self.client.get_artist(artist_id)
