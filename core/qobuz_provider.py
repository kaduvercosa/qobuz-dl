import asyncio
from typing import Dict, List
from .provider_base import MusicProvider

class QobuzProvider(MusicProvider):
    def __init__(self, qobuz_instance):
        self.qobuz_core = qobuz_instance

    @property
    def provider_name(self) -> str:
        return "Qobuz"

    @property
    def supported_domains(self) -> List[str]:
        return ["play.qobuz.com", "open.qobuz.com"]

    async def authenticate(self, credentials: Dict[str, str]) -> bool:
        try:
            await self.qobuz_core.initialize_client(
                email=credentials.get("email", ""),
                pwd=credentials.get("password", ""),
                app_id=credentials.get("app_id", ""),
                secrets=credentials.get("secrets", [])
            )
            return True
        except Exception as e:
            # Silenciado, mantendo o print apenas se a autenticação falhar
            print(f"[{self.provider_name}] Erro de autenticação: {e}")
            return False

    async def process_url(self, url: str) -> None:
        """Chama a lógica de download de forma totalmente silenciosa."""
        await self.qobuz_core.handle_url(url)
        
    async def shutdown(self):
        if hasattr(self.qobuz_core, 'client') and self.qobuz_core.client:
            await self.qobuz_core.client.close()