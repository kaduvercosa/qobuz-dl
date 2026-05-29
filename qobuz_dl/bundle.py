"""
Módulo responsável por extrair dinamicamente o App ID e os Secrets diretamente 
do código-fonte (bundle.js) do Web Player do Qobuz, evitando que o programa 
pare de funcionar quando as chaves são alteradas no servidor.

Baseado na lógica original do DashLt's spoofbuz.
"""

import base64
import logging
import re
from collections import OrderedDict
from typing import Dict

from requests import Session

logger = logging.getLogger(__name__)

# Expressões regulares compiladas para localizar os dados fragmentados no JavaScript
_SEED_TIMEZONE_REGEX = re.compile(
    r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)'
)
_INFO_EXTRAS_REGEX = r'name:"\w+/(?P<timezone>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
_APP_ID_REGEX = re.compile(
    r'production:{api:{appId:"(?P<app_id>\d{9})",appSecret:"\w{32}"'
)
_BUNDLE_URL_REGEX = re.compile(
    r'<script src="(/resources/\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)"></script>'
)

_BASE_URL = "https://play.qobuz.com"


class Bundle:
    def __init__(self):
        logger.debug("Getting logging page")
        
        # Usar o context manager (with) garante que a sessão HTTP é fechada corretamente
        # após o download do código fonte, libertando recursos do sistema.
        with Session() as session:
            response = session.get(f"{_BASE_URL}/login")
            response.raise_for_status()

            bundle_url_match = _BUNDLE_URL_REGEX.search(response.text)
            if not bundle_url_match:
                raise NotImplementedError("Bundle URL NOT found in login page.")

            bundle_url = bundle_url_match.group(1)

            logger.debug("Getting bundle.js content")
            response = session.get(_BASE_URL + bundle_url)
            response.raise_for_status()

            self._bundle = response.text

    def get_app_id(self) -> str:
        """Procura e devolve o App ID de 9 dígitos da Qobuz."""
        match = _APP_ID_REGEX.search(self._bundle)
        if not match:
            raise NotImplementedError("Failed to match APP ID in bundle.")

        return match.group("app_id")

    def get_secrets(self) -> Dict[str, str]:
        """Reconstrói e descodifica as chaves (App Secrets) escondidas no código."""
        logger.debug("Getting and decoding secrets")
        seed_matches = _SEED_TIMEZONE_REGEX.finditer(self._bundle)
        secrets = OrderedDict()

        # 1. Recolhe as 'seeds' iniciais
        for match in seed_matches:
            seed, timezone = match.group("seed", "timezone")
            secrets[timezone] = [seed]

        # Evita erro caso o dicionário não tenha itens suficientes (proteção extra)
        keypairs = list(secrets.items())
        if len(keypairs) > 1:
            secrets.move_to_end(keypairs[1][0], last=False)
            
        info_extras_regex = _INFO_EXTRAS_REGEX.format(
            timezones="|".join([timezone.capitalize() for timezone in secrets])
        )
        
        # 2. Localiza as partes 'info' e 'extras' correspondentes a cada fuso horário
        info_extras_matches = re.finditer(info_extras_regex, self._bundle)
        for match in info_extras_matches:
            timezone, info, extras = match.group("timezone", "info", "extras")
            secrets[timezone.lower()] += [info, extras]
            
        # 3. Junta tudo, recorta o "lixo" (-44 caracteres finais) e descodifica
        for secret_pair in secrets:
            encoded_string = "".join(secrets[secret_pair])[:-44]
            secrets[secret_pair] = base64.standard_b64decode(encoded_string).decode("utf-8")
            
        return dict(secrets)