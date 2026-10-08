"""Decodificação do streaming SSE de APIs compatíveis com a da OpenAI.

Formato (``Content-Type: text/event-stream``)::

    : OPENROUTER PROCESSING            <- comentário (keep-alive): ignorado
    data: {"id":"...","choices":[{"delta":{"content":"Olá"},"finish_reason":null}]}
    data: {"choices":[{"delta":{},"finish_reason":"stop"}]}
    data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":4}}
    data: [DONE]

O decodificador converte isso nos **mesmos eventos** do streaming NDJSON do gateway, de modo que
``Conversa`` não precisa saber de que origem veio a resposta. Regras:

- ``EventoIniciado`` sai no primeiro trecho de dados;
- ``delta.content`` vira ``EventoDelta``; ``delta.reasoning_content``/``delta.reasoning`` viram
  ``EventoRaciocinio`` (separado da resposta);
- um objeto com ``error`` (erro no meio do stream, comum no OpenRouter) vira ``EventoErro``;
- ``EventoConcluido`` sai em ``[DONE]`` — ou no fim limpo da conexão **se** já houve
  ``finish_reason``. Fim da conexão sem nenhum dos dois é :class:`StreamInterrupted`, para que a
  interação não entre no histórico (ADR-0005).
"""

from __future__ import annotations

import json
from typing import Any

from itsa_agente.gateway.errors import ProtocolError, StreamInterrupted
from itsa_agente.gateway.models import (
    EventoConcluido,
    EventoDelta,
    EventoErro,
    EventoIniciado,
    EventoRaciocinio,
    EventoStream,
    Uso,
)
from itsa_agente.security import redator_global


def _inteiro(valor: Any) -> int:
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def uso_de_objeto(usage: Any) -> Uso | None:
    if not isinstance(usage, dict):
        return None
    return Uso(
        prompt_tokens=_inteiro(usage.get("prompt_tokens")),
        completion_tokens=_inteiro(usage.get("completion_tokens")),
    )


def erro_de_objeto(erro: Any, request_id: str | None) -> EventoErro:
    """Converte o valor do campo ``error`` de um chunk em :class:`EventoErro`."""
    if isinstance(erro, dict):
        codigo = erro.get("code") if erro.get("code") is not None else erro.get("type")
        mensagem = erro.get("message")
    else:
        codigo, mensagem = None, erro
    texto = redator_global().aplicar(" ".join(str(mensagem or "").split()))[:300]
    return EventoErro(
        codigo=None if codigo is None else str(codigo),
        mensagem=texto or "O provedor reportou um erro durante a geração.",
        request_id=request_id,
    )


def eventos_de_resposta_unica(obj: dict[str, Any]) -> list[EventoStream]:
    """Eventos de uma resposta **não** transmitida (``application/json``), caso o provedor ignore
    ``stream=true``. Mantém a interface única para o restante do sistema."""
    request_id = obj.get("id") if isinstance(obj.get("id"), str) else None
    if obj.get("error"):
        return [erro_de_objeto(obj["error"], request_id)]
    escolhas = obj.get("choices")
    if not (isinstance(escolhas, list) and escolhas and isinstance(escolhas[0], dict)):
        raise ProtocolError("Resposta do provedor sem 'choices'.")
    mensagem = escolhas[0].get("message") or {}
    eventos: list[EventoStream] = [EventoIniciado(request_id=request_id, model=obj.get("model"))]
    if isinstance(mensagem, dict):
        raciocinio = mensagem.get("reasoning_content") or mensagem.get("reasoning")
        if isinstance(raciocinio, str) and raciocinio:
            eventos.append(EventoRaciocinio(raciocinio, request_id))
        conteudo = mensagem.get("content")
        if isinstance(conteudo, str) and conteudo:
            eventos.append(EventoDelta(conteudo, request_id))
    motivo = escolhas[0].get("finish_reason")
    eventos.append(
        EventoConcluido(
            request_id=request_id,
            model=obj.get("model"),
            usage=uso_de_objeto(obj.get("usage")),
            motivo=motivo if isinstance(motivo, str) else None,
        )
    )
    return eventos


class DecodificadorSSE:
    """Máquina de estados linha a linha. Não faz I/O: recebe linhas e devolve eventos."""

    def __init__(self) -> None:
        self._iniciado = False
        self._terminou = False
        self._id: str | None = None
        self._modelo: str | None = None
        self._motivo: str | None = None
        self._uso: Uso | None = None

    @property
    def terminou(self) -> bool:
        """``True`` depois de um evento terminal (``completed`` ou ``error``)."""
        return self._terminou

    def alimentar(self, linha: str) -> list[EventoStream]:
        if self._terminou:
            return []
        linha = linha.rstrip("\r\n")
        if not linha or linha.startswith(":") or not linha.startswith("data:"):
            return []  # linha em branco, comentário (keep-alive) ou campo SSE sem dados
        dado = linha[5:].strip()
        if not dado:
            return []
        if dado == "[DONE]":
            return self._concluir()
        try:
            objeto = json.loads(dado)
        except ValueError as exc:
            raise ProtocolError("Trecho do streaming do provedor não é JSON válido.") from exc
        if not isinstance(objeto, dict):
            raise ProtocolError("Trecho do streaming do provedor não é um objeto JSON.")
        return self._processar(objeto)

    def finalizar(self) -> list[EventoStream]:
        """Chamado quando a conexão fecha. Conclui ou sinaliza interrupção."""
        if self._terminou:
            return []
        if self._motivo is not None:
            return self._concluir()
        raise StreamInterrupted("A resposta foi interrompida antes de terminar.")

    # ------------------------------------------------------------------ internos
    def _concluir(self) -> list[EventoStream]:
        self._terminou = True
        return [
            EventoConcluido(
                request_id=self._id, model=self._modelo, usage=self._uso, motivo=self._motivo
            )
        ]

    def _processar(self, obj: dict[str, Any]) -> list[EventoStream]:
        if isinstance(obj.get("id"), str) and self._id is None:
            self._id = obj["id"]
        if isinstance(obj.get("model"), str) and self._modelo is None:
            self._modelo = obj["model"]

        if obj.get("error"):
            self._terminou = True
            return [erro_de_objeto(obj["error"], self._id)]

        eventos: list[EventoStream] = []
        if not self._iniciado:
            self._iniciado = True
            eventos.append(EventoIniciado(request_id=self._id, model=self._modelo))

        uso = uso_de_objeto(obj.get("usage"))
        if uso is not None:
            self._uso = uso

        escolhas = obj.get("choices")
        if isinstance(escolhas, list) and escolhas and isinstance(escolhas[0], dict):
            escolha = escolhas[0]
            delta = escolha.get("delta")
            if isinstance(delta, dict):
                raciocinio = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(raciocinio, str) and raciocinio:
                    eventos.append(EventoRaciocinio(raciocinio, self._id))
                conteudo = delta.get("content")
                if isinstance(conteudo, str) and conteudo:
                    eventos.append(EventoDelta(conteudo, self._id))
            motivo = escolha.get("finish_reason")
            if isinstance(motivo, str) and motivo:
                if motivo == "error":
                    self._terminou = True
                    eventos.append(
                        EventoErro(
                            codigo="provider_error",
                            mensagem="O provedor encerrou a resposta com erro.",
                            request_id=self._id,
                        )
                    )
                else:
                    self._motivo = motivo
        return eventos
