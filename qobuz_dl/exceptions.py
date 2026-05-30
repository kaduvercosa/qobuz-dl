"""
Exceções personalizadas para o projeto qobuz-dl.
Centralizar estas exceções ajuda a identificar, capturar e tratar 
erros específicos de negócio sem recorrer a exceções genéricas do Python.
"""

class AuthenticationError(Exception):
    """Lançada quando há uma falha no login (ex: email, palavra-passe ou token incorretos)."""


class IneligibleError(Exception):
    """Lançada quando a conta não tem os direitos ou a subscrição necessários para a operação."""


class InvalidAppIdError(Exception):
    """Lançada quando o App ID fornecido à API do Qobuz é considerado inválido."""


class InvalidAppSecretError(Exception):
    """Lançada quando o App Secret (chave de segurança) falha a validação na API."""


class InvalidQuality(Exception):
    """Lançada quando o ID de qualidade de áudio solicitado (ex: 5, 6, 7, 27) não existe ou não é suportado."""


class NonStreamable(Exception):
    """Lançada quando uma faixa ou álbum está bloqueado por região ou indisponível para streaming/download."""
