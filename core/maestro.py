import asyncio
from typing import Dict, List
from colorama import init

from .provider_base import MusicProvider
from qobuz_dl.color import Tema

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

    def _is_single_track_url(self, provider: MusicProvider, url: str) -> bool:
        """
        Pergunta ao provedor se essa URL específica é uma faixa avulsa (não álbum,
        playlist, artista ou label). Cada provedor sabe identificar isso a partir
        do seu próprio formato de link (ex: Qobuz tem /track/ na URL).

        Provedores que ainda não implementam `is_single_track` simplesmente não
        participam da contagem de "lote de singles" - suas URLs continuam sendo
        processadas normalmente, uma a uma, como já era antes.
        """
        checker = getattr(provider, "is_single_track", None)
        if not callable(checker):
            return False
        try:
            return bool(checker(url))
        except Exception:
            return False

    async def process_batch(self, urls: List[str]):
        """
        O fluxo principal. Antes de baixar qualquer coisa, faz uma varredura prévia
        na lista inteira pra contar quantas URLs são faixas avulsas (tracks),
        independente da posição/ordem em que aparecem (mesmo misturadas com
        álbuns, playlists, etc no meio da lista):

          - 0 ou 1 faixa avulsa  -> cada uma é tratada como "SINGLE" (padrão atual)
          - 2 ou mais faixas     -> todas viram "LOTE DE SINGLES", numeradas
                                     [01/N], [02/N]... apenas entre si (álbuns/
                                     playlists no meio da lista não entram nessa
                                     contagem nem nessa numeração).
        """
        track_sequence: Dict[int, int] = {}
        track_total = 0

        for i, url in enumerate(urls):
            try:
                provider = self._identify_provider(url)
            except ValueError:
                continue
            if self._is_single_track_url(provider, url):
                track_total += 1
                track_sequence[i] = track_total

        is_lote = track_total > 1

        for i, url in enumerate(urls):
            try:
                provider = self._identify_provider(url)

                if is_lote and i in track_sequence:
                    try:
                        await provider.process_url(
                            url,
                            is_single_batch=True,
                            single_batch_index=track_sequence[i],
                            single_batch_total=track_total,
                        )
                    except TypeError:
                        # Provedor ainda não suporta os parâmetros de lote (ex: um
                        # provedor futuro mais simples) -> cai pro modo normal.
                        await provider.process_url(url)
                else:
                    await provider.process_url(url)
            except Exception as e:
                # O Maestro usa o seu Tema para reportar o erro com estilo
                print(f"{Tema.SYS}{Tema.RED}Falha na orquestração: {e}{Tema.OFF}")