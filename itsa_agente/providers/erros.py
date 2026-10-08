"""Conversão de respostas de erro de APIs compatíveis com a da OpenAI em exceções tipadas.

Formatos observados na documentação dos provedores (e tolerados aqui):

- OpenAI/NVIDIA/OpenRouter: ``{"error": {"message": "...", "type": "...", "code": ...}}``;
- ``{"error": "texto"}``;
- FastAPI/NIM: ``{"detail": "..."}`` ou ``{"title": "...", "detail": "..."}``;
- ``{"message": "..."}``.

As mensagens dos provedores são em inglês e podem ecoar trechos da requisição (ex.: moderação do
OpenRouter). Por isso são **truncadas** e passam pelo redator antes de ir à tela ou ao log.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from itsa_agente.gateway.errors import (
    BadRequest,
    CreditoInsuficiente,
    Forbidden,
    GatewayError,
    RateLimited,
    RequestTimeout,
    ServerError,
    ServiceUnavailable,
    Unauthorized,
)
from itsa_agente.security import redator_global

LIMITE_MENSAGEM = 300
LIMITE_CORPO = 64 * 1024
LIMITE_RETRY_AFTER_S = 10.0

_MENSAGENS_PADRAO: dict[int, str] = {
    400: "Requisição recusada pelo provedor.",
    401: "Chave de API ausente, inválida ou expirada.",
    402: "Créditos ou cota esgotados no provedor.",
    403: "Acesso negado pela chave de API ou pela política do provedor.",
    404: "Modelo ou recurso não encontrado no provedor.",
    408: "O provedor não respondeu a tempo.",
    422: "Requisição recusada pelo provedor.",
    429: "Limite de requisições do provedor atingido.",
    502: "O provedor está indisponível no momento.",
    503: "O provedor está indisponível no momento.",
    504: "O provedor está indisponível no momento.",
}


def _texto_curto(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = " ".join(str(valor).split())
    if not texto:
        return None
    return redator_global().aplicar(texto)[:LIMITE_MENSAGEM]


def extrair_erro_openai(status: int, corpo: str) -> tuple[str | None, str]:
    """Retorna ``(codigo, mensagem)`` a partir do corpo de uma resposta de erro."""
    codigo: str | None = None
    mensagem: str | None = None
    try:
        dados = json.loads(corpo[:LIMITE_CORPO]) if corpo.strip() else None
    except ValueError:
        dados = None
    if isinstance(dados, dict):
        erro = dados.get("error")
        if isinstance(erro, dict):
            bruto_codigo = erro.get("code")
            codigo = _texto_curto(bruto_codigo if bruto_codigo is not None else erro.get("type"))
            mensagem = _texto_curto(erro.get("message"))
        elif isinstance(erro, str):
            mensagem = _texto_curto(erro)
        if mensagem is None:
            mensagem = _texto_curto(
                dados.get("detail") or dados.get("message") or dados.get("title")
            )
    elif corpo.strip() and dados is None:
        mensagem = _texto_curto(corpo)  # corpo de texto puro (ex.: "Unauthorized")
    return codigo, mensagem or _MENSAGENS_PADRAO.get(status, f"Falha no provedor (HTTP {status}).")


def retry_after(cabecalhos: httpx.Headers) -> float | None:
    bruto = cabecalhos.get("retry-after")
    if bruto is None:
        return None
    try:
        return max(0.0, float(bruto))
    except ValueError:
        return None


def erro_de_resposta(resposta: httpx.Response, provedor: str) -> GatewayError:
    """Mapeia uma resposta de erro (corpo já lido) para a exceção correspondente."""
    status = resposta.status_code
    codigo, mensagem = extrair_erro_openai(status, resposta.text)
    comuns: dict[str, Any] = {"codigo": codigo, "status": status, "provedor": provedor}
    if status in (400, 404, 422):
        return BadRequest(mensagem, **comuns)
    if status == 401:
        return Unauthorized(mensagem, **comuns)
    if status == 402:
        return CreditoInsuficiente(mensagem, **comuns)
    if status == 403:
        return Forbidden(mensagem, **comuns)
    if status == 408:
        return RequestTimeout(mensagem, **comuns)
    if status == 429:
        return RateLimited(mensagem, retry_after=retry_after(resposta.headers), **comuns)
    if status in (502, 503, 504):
        return ServiceUnavailable(mensagem, **comuns)
    if status >= 500:
        return ServerError(mensagem, **comuns)
    return GatewayError(mensagem, **comuns)
