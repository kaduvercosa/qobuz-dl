from abc import ABC, abstractmethod
from typing import Dict, Any, List

class MusicProvider(ABC):
    """
    O contrato oficial para qualquer serviço de música no Maestro.
    """
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Retorna o nome do serviço (ex: 'Qobuz', 'Apple', 'Tidal')"""
        pass

    @property
    @abstractmethod
    def supported_domains(self) -> List[str]:
        """Domínios que este provedor aceita. Ex: ['play.qobuz.com', 'open.qobuz.com']"""
        pass

    @abstractmethod
    async def authenticate(self, credentials: Dict[str, str]) -> bool:
        """Autentica o serviço com os tokens necessários (App ID, Secrets, etc)."""
        pass

    @abstractmethod
    async def process_url(self, url: str) -> None:
        """
        Recebe a URL validada pelo Maestro e inicia o processo de extração 
        de metadados e download.
        """
        pass