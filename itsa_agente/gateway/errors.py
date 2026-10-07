"""Hierarquia de erros do cliente do gateway.

Todos herdam de :class:`GatewayError`, de modo que a camada de interface possa capturar um único
tipo e decidir a mensagem ao usuário a partir de ``codigo`` (estável, vindo do gateway) e
``status``. As mensagens do gateway são "seguras em português" segundo o contrato; ainda assim,
nunca incluímos corpo de requisição nelas.
"""

from __future__ import annotations


class GatewayError(Exception):
    """Erro base. ``codigo`` é o ``error.code`` do gateway, quando houver."""

    def __init__(
        self,
        mensagem: str,
        *,
        codigo: str | None = None,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.status = status
        self.request_id = request_id

    def __str__(self) -> str:
        partes = [self.mensagem]
        if self.codigo:
            partes.append(f"[código={self.codigo}]")
        if self.status is not None:
            partes.append(f"[HTTP {self.status}]")
        return " ".join(partes)


class ConfigurationError(GatewayError):
    """Configuração local inválida (variável de ambiente, URL etc.)."""


class LocalValidationError(GatewayError):
    """Entrada rejeitada **antes** de chegar ao gateway (contrato do swagger violado)."""


class ConnectionFailed(GatewayError):
    """Não foi possível estabelecer conexão com o gateway (DNS, TCP, TLS)."""


class RequestTimeout(GatewayError):
    """O gateway não respondeu dentro do tempo limite."""


class BadRequest(GatewayError):
    """HTTP 400 — requisição inválida segundo o gateway."""


class Unauthorized(GatewayError):
    """HTTP 401 — credencial ausente, inválida ou token expirado."""


class Forbidden(GatewayError):
    """HTTP 403 — credencial válida sem permissão (cliente vencido/bloqueado/módulo)."""


class RateLimited(GatewayError):
    """HTTP 429 — excesso de requisições. ``retry_after`` em segundos, se informado."""

    def __init__(
        self, mensagem: str, *, retry_after: float | None = None, **kwargs: object
    ) -> None:
        super().__init__(mensagem, **kwargs)  # type: ignore[arg-type]
        self.retry_after = retry_after


class ServiceUnavailable(GatewayError):
    """HTTP 503 — gateway ou modelo indisponível no momento."""


class ServerError(GatewayError):
    """Outros HTTP 5xx."""


class ProtocolError(GatewayError):
    """Resposta fora do contrato (JSON inválido, evento inesperado, corpo vazio)."""


class StreamInterrupted(GatewayError):
    """O streaming terminou sem o evento ``completed`` (queda de rede, corte, cancelamento)."""


class StreamError(GatewayError):
    """O gateway enviou um evento ``error`` durante o streaming."""
