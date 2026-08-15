import asyncio
from typing import Dict, List
from .provider_base import MusicProvider
from qobuz_dl.utils import get_url_info
from qobuz_dl.color import Tema

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

    def is_single_track(self, url: str) -> bool:
        """
        Diz ao Maestro se essa URL é uma faixa avulsa (track) ou não (álbum,
        playlist, artista, label). Usado na pré-varredura do process_batch
        pra decidir automaticamente entre o badge "SINGLE" e "LOTE DE SINGLES".
        """
        try:
            normalized = url.replace("open.qobuz.com", "play.qobuz.com")
            url_type, _ = get_url_info(normalized)
            return url_type == "track"
        except Exception:
            return False

    async def process_url(self, url: str, is_single_batch: bool = False, single_batch_index: int = 1, single_batch_total: int = 1) -> None:
        """
        Chama a lógica de download de forma totalmente silenciosa. Quando o
        Maestro identifica 2+ faixas avulsas no lote, repassa is_single_batch/
        single_batch_index/single_batch_total pro handle_url, que por sua vez
        aciona o badge "🎵 LOTE DE SINGLES" (em vez de "🎵 SINGLE") no downloader.
        """
        await self.qobuz_core.handle_url(
            url,
            is_single_batch=is_single_batch,
            single_batch_index=single_batch_index,
            single_batch_total=single_batch_total,
        )

    async def shutdown(self):
        if hasattr(self.qobuz_core, 'client') and self.qobuz_core.client:
            await self.qobuz_core.client.close()