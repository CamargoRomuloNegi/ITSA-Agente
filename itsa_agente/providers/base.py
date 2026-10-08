"""Tipos comuns da camada de provedores de IA.

O ITSA-Agente conversa com **três tipos de origem de modelos**:

- ``itsa``       — o IAitsaGateway, que gerencia os modelos locais (offline) da ITSA;
- ``nvidia``     — a API gratuita da NVIDIA (build.nvidia.com), compatível com a API da OpenAI;
- ``openrouter`` — o OpenRouter (openrouter.ai), um agregador de modelos, também compatível.

Para o resto do sistema (``Conversa``, telas, diagnóstico) a origem é transparente: todos emitem
os mesmos eventos de streaming (``EventoDelta``, ``EventoConcluido``...). O identificador de um
modelo externo é **qualificado** com o provedor (``nvidia::nvidia/nemotron-...``); um identificador
sem ``::`` pertence ao gateway ITSA, o que preserva integralmente o comportamento anterior.
"""

from __future__ import annotations

from dataclasses import dataclass

PROVEDOR_ITSA = "itsa"
PROVEDOR_NVIDIA = "nvidia"
PROVEDOR_OPENROUTER = "openrouter"

#: Ordem de apresentação nas telas.
ORDEM_PROVEDORES = (PROVEDOR_ITSA, PROVEDOR_NVIDIA, PROVEDOR_OPENROUTER)

NOMES_PROVEDORES = {
    PROVEDOR_ITSA: "IAitsa (local)",
    PROVEDOR_NVIDIA: "NVIDIA",
    PROVEDOR_OPENROUTER: "OpenRouter",
}

SEPARADOR = "::"


def qualificar(provedor: str, modelo: str) -> str:
    """Identificador de modelo usado nas telas e no roteador."""
    if provedor == PROVEDOR_ITSA:
        return modelo  # compatibilidade: modelos do gateway nunca têm prefixo
    return f"{provedor}{SEPARADOR}{modelo}"


def separar(modelo_id: str) -> tuple[str, str]:
    """Inverso de :func:`qualificar`: ``(provedor, id do modelo no provedor)``."""
    if SEPARADOR in modelo_id:
        provedor, _, local = modelo_id.partition(SEPARADOR)
        if provedor and local:
            return provedor, local
    return PROVEDOR_ITSA, modelo_id


@dataclass(frozen=True, slots=True)
class OpcoesGeracao:
    """Parâmetros de geração para provedores externos (o gateway ITSA não os aceita).

    ``raciocinio``: ``True`` liga, ``False`` desliga e ``None`` usa o padrão do ITSA-Agente para o
    provedor (NVIDIA: desligado; OpenRouter: não envia o parâmetro).
    """

    raciocinio: bool | None = None
    temperatura: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ModeloCatalogo:
    """Um modelo disponível em alguma origem, já com identificador qualificado."""

    id: str
    rotulo: str
    provedor: str
    externo: bool
    contexto: int | None = None
    gratuito: bool | None = None

    @property
    def nome_provedor(self) -> str:
        return NOMES_PROVEDORES.get(self.provedor, self.provedor)
