"""Decodificação do streaming NDJSON do ``POST /api/chat``.

Contrato (swagger): cada linha é um objeto JSON completo com ``type`` em
``started | delta | completed | error``. Esta camada:

- ignora linhas em branco (keep-alives);
- converte cada linha em um evento tipado (:mod:`itsa_agente.gateway.models`);
- tolera campos extras e ``type`` desconhecido (preservado como ``EventoDesconhecido``);
- aceita as duas formas plausíveis do evento ``error`` (campos no topo **ou** ``{"error": {...}}``),
  já que o formato exato não está documentado — a suíte de diagnóstico registra o real;
- termina na primeira ocorrência de evento terminal (``completed``/``error``);
- se as linhas acabarem sem evento terminal, levanta :class:`StreamInterrupted`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from itsa_agente.gateway.errors import ProtocolError, StreamInterrupted
from itsa_agente.gateway.models import (
    EVENTOS_TERMINAIS,
    EventoConcluido,
    EventoDelta,
    EventoDesconhecido,
    EventoErro,
    EventoIniciado,
    EventoStream,
    Uso,
)

_LIMITE_TRECHO_ERRO = 200


def _inteiro(valor: Any) -> int:
    try:
        return max(int(valor), 0)
    except (TypeError, ValueError):
        return 0


def _texto_ou_none(valor: Any) -> str | None:
    return valor if isinstance(valor, str) else None


def _uso(bruto: Any) -> Uso | None:
    if not isinstance(bruto, dict):
        return None
    return Uso(
        prompt_tokens=_inteiro(bruto.get("promptTokens")),
        completion_tokens=_inteiro(bruto.get("completionTokens")),
    )


def evento_de_dict(obj: dict[str, Any]) -> EventoStream:
    """Converte um objeto JSON já decodificado em evento tipado."""
    tipo = obj.get("type")
    request_id = _texto_ou_none(obj.get("requestId"))

    if tipo == "started":
        return EventoIniciado(
            request_id=request_id,
            conversation_id=_texto_ou_none(obj.get("conversationId")),
            model=_texto_ou_none(obj.get("model")),
        )
    if tipo == "delta":
        conteudo = obj.get("content")
        return EventoDelta(
            content=conteudo if isinstance(conteudo, str) else "", request_id=request_id
        )
    if tipo == "completed":
        return EventoConcluido(
            request_id=request_id,
            model=_texto_ou_none(obj.get("model")),
            usage=_uso(obj.get("usage")),
        )
    if tipo == "error":
        aninhado = obj.get("error")
        origem = aninhado if isinstance(aninhado, dict) else obj
        return EventoErro(
            codigo=_texto_ou_none(origem.get("code")),
            mensagem=_texto_ou_none(origem.get("message")),
            request_id=request_id,
            bruto=obj,
        )
    return EventoDesconhecido(tipo_original=_texto_ou_none(tipo), bruto=obj)


def evento_de_linha(linha: str) -> EventoStream | None:
    """Decodifica uma linha NDJSON. Retorna ``None`` para linha em branco.

    Raises:
        ProtocolError: JSON inválido ou valor que não é um objeto.
    """
    texto = linha.strip()
    if not texto:
        return None
    try:
        obj = json.loads(texto)
    except json.JSONDecodeError as exc:
        # O trecho NÃO é incluído na mensagem de forma integral: pode conter dados do cliente.
        raise ProtocolError(
            f"Linha do streaming não é JSON válido (posição {exc.pos}, "
            f"{len(texto)} caracteres): {texto[:_LIMITE_TRECHO_ERRO]!r}"
        ) from exc
    if not isinstance(obj, dict):
        raise ProtocolError("Linha do streaming não é um objeto JSON.")
    return evento_de_dict(obj)


def iterar_eventos(linhas: Iterable[str]) -> Iterator[EventoStream]:
    """Itera os eventos de um fluxo de linhas, parando no primeiro evento terminal.

    Raises:
        ProtocolError: linha malformada.
        StreamInterrupted: o fluxo acabou antes de ``completed``/``error``.
    """
    for linha in linhas:
        evento = evento_de_linha(linha)
        if evento is None:
            continue
        yield evento
        if isinstance(evento, EVENTOS_TERMINAIS):
            return
    raise StreamInterrupted(
        "O streaming terminou sem o evento 'completed'. A resposta está incompleta e "
        "não deve ser incorporada ao histórico."
    )
