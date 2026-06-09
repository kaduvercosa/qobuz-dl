"""
exceptions.py
Exceções personalizadas do qobuz-dl-master.
Centralizar aqui facilita captura seletiva e mensagens claras.
"""


class AuthenticationError(Exception):
    """Falha no login: e-mail, senha ou token inválidos."""


class IneligibleError(Exception):
    """Conta sem direitos ou assinatura necessários para a operação."""


class InvalidAppIdError(Exception):
    """App ID fornecido à API do Qobuz é inválido."""


class InvalidAppSecretError(Exception):
    """App Secret falhou na validação da API."""


class InvalidQuality(Exception):
    """ID de qualidade (5/6/7/27) não existe ou não é suportado."""


class NonStreamable(Exception):
    """Faixa ou álbum bloqueado por região ou indisponível para download."""


class RateLimitError(Exception):
    """API retornou HTTP 429 -- limite de requisições atingido."""


class AccountFavoritesLimitError(Exception):
    """Conta atingiu o limite máximo de favoritos permitidos pelo plano."""