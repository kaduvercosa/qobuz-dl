from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class ProviderBase(ABC):
    """Abstract base class for audio providers."""

    @abstractmethod
    def authenticate(self, **kwargs) -> Dict[str, Any]:
        pass

    @abstractmethod
    def resolve(self, url: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_track_metadata(self, track_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_album_metadata(self, album_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_download_url(self, track_id: str, quality: int) -> Dict[str, Any]:
        pass
