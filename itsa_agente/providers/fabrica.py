"""Criação de clientes de provedores externos a partir do identificador."""

from __future__ import annotations

from typing import Any

from itsa_agente.config import Settings
from itsa_agente.gateway.errors import LocalValidationError
from itsa_agente.providers.base import NOMES_PROVEDORES, PROVEDOR_NVIDIA, PROVEDOR_OPENROUTER
from itsa_agente.providers.nvidia import ProvedorNvidia
from itsa_agente.providers.openai_compat import ClienteOpenAICompat
from itsa_agente.providers.openrouter import ProvedorOpenRouter

#: Provedores externos suportados, na ordem de apresentação.
PROVEDORES_EXTERNOS = (PROVEDOR_NVIDIA, PROVEDOR_OPENROUTER)


def criar_provedor(
    id_provedor: str, chave: str, configuracao: Settings, **kwargs: Any
) -> ClienteOpenAICompat:
    """Instancia o cliente do provedor. ``kwargs`` (transporte, dormir...) servem a testes."""
    if id_provedor == PROVEDOR_NVIDIA:
        return ProvedorNvidia(chave, configuracao, **kwargs)
    if id_provedor == PROVEDOR_OPENROUTER:
        return ProvedorOpenRouter(chave, configuracao, **kwargs)
    raise LocalValidationError(
        f"Provedor desconhecido: {NOMES_PROVEDORES.get(id_provedor, id_provedor)!r}."
    )
