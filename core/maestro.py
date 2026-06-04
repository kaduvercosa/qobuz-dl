import asyncio
from typing import Dict, List
from colorama import init

from .provider_base import MusicProvider

# Trazendo o Tema de volta para garantir alertas padronizados
class Tema:
    CYAN    = "\033[36m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    BLUE    = "\033[34m"   
    BOLD    = "\033[1m"
    OFF     = "\033[0m"
    SYS     = f"{BLUE}[MAESTRO]{OFF} ❯ "

class MaestroEngine:
    def __init__(self):
        self.providers: Dict[str, MusicProvider] = {}
        init(autoreset=True)

    def register_provider(self, provider_instance: MusicProvider):
        """Regista o provedor silenciosamente."""
        for domain in provider_instance.supported_domains:
            self.providers[domain] = provider_instance

    def _identify_provider(self, url: str) -> MusicProvider:
        """Encontra o provedor silenciosamente."""
        for domain, provider in self.providers.items():
            if domain in url:
                return provider
        raise ValueError(f"URL não suportada ou nenhum módulo instalado para: {url}")

    async def process_batch(self, urls: List[str]):
        """O fluxo principal, agora invisível no terminal (exceto para erros críticos)."""
        for url in urls:
            try:
                provider = self._identify_provider(url)
                await provider.process_url(url)
            except Exception as e:
                # O Maestro usa o seu Tema para reportar o erro com estilo
                print(f"{Tema.SYS}{Tema.RED}Falha na orquestração: {e}{Tema.OFF}")