"""Gestão do histórico de conversa conforme o contrato do gateway.

Regras do swagger incorporadas aqui (ver ``docs/sdd/03-contrato-api-gateway.md``):

1. O histórico enviado tem de 1 a 30 mensagens, em ordem cronológica, e a última é do usuário.
2. **Só se incorpora a interação ao histórico depois do evento ``completed``.** Em ``error``,
   cancelamento ou queda, a interação fica incompleta e é descartada.
3. O ``conversationId`` é estável durante toda a conversa.

Além disso, como os modelos são locais e de contexto limitado, aplica-se uma **janela deslizante**
por número de mensagens (30) e por orçamento de caracteres (``max_history_chars``), sempre
preservando a mensagem de sistema e a pergunta atual. A poda remove os turnos mais antigos em
pares (usuário + assistente) para não deixar uma resposta órfã no início do histórico.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from itsa_agente.gateway.errors import LocalValidationError, StreamError
from itsa_agente.gateway.models import (
    MAX_MENSAGENS,
    EventoConcluido,
    EventoDelta,
    EventoErro,
    EventoStream,
    Mensagem,
    Uso,
)


class TransmissorChat(Protocol):
    """Contrato mínimo exigido do cliente (facilita testes com dublês)."""

    def transmitir_chat(
        self,
        *,
        modelo: str,
        mensagens: Sequence[Mensagem],
        conversa_id: uuid.UUID | None = None,
    ) -> Iterator[EventoStream]: ...


@dataclass(frozen=True, slots=True)
class JanelaContexto:
    """Resultado da montagem das mensagens de uma rodada."""

    mensagens: list[Mensagem]
    descartadas: int  # mensagens antigas removidas por limite de contagem/caracteres

    @property
    def caracteres(self) -> int:
        return sum(len(m.content) for m in self.mensagens)


@dataclass(slots=True)
class Conversa:
    """Uma conversa com histórico **confirmado** (somente interações concluídas)."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    prompt_sistema: str | None = None
    max_caracteres: int = 24_000
    max_mensagens: int = MAX_MENSAGENS
    historico: list[Mensagem] = field(default_factory=list)
    ultimo_uso: Uso | None = None
    ultimo_request_id: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.max_mensagens <= MAX_MENSAGENS:
            raise ValueError(f"max_mensagens deve estar entre 1 e {MAX_MENSAGENS}.")
        if self.max_caracteres < 1:
            raise ValueError("max_caracteres deve ser positivo.")

    # ------------------------------------------------------------------ janela
    def montar_janela(self, pergunta: str) -> JanelaContexto:
        """Monta ``[sistema?] + histórico podado + pergunta`` respeitando os limites."""
        if not pergunta.strip():
            raise LocalValidationError("A pergunta não pode ser vazia.")
        fixas: list[Mensagem] = []
        if self.prompt_sistema and self.prompt_sistema.strip():
            fixas.append(Mensagem.sistema(self.prompt_sistema))
        atual = Mensagem.usuario(pergunta)

        orcamento_msgs = self.max_mensagens - len(fixas) - 1
        orcamento_chars = (
            self.max_caracteres - sum(len(m.content) for m in fixas) - len(atual.content)
        )

        # Percorre do mais recente para o mais antigo, em pares (assistente, usuário), e
        # mantém enquanto couber. O histórico confirmado é sempre composto por pares.
        mantidos: list[Mensagem] = []
        usados_chars = 0
        i = len(self.historico)
        while i >= 2 and len(mantidos) + 2 <= orcamento_msgs:
            par = self.historico[i - 2 : i]
            custo = sum(len(m.content) for m in par)
            if usados_chars + custo > orcamento_chars:
                break
            mantidos = par + mantidos
            usados_chars += custo
            i -= 2

        return JanelaContexto(
            mensagens=[*fixas, *mantidos, atual],
            descartadas=len(self.historico) - len(mantidos),
        )

    # ---------------------------------------------------------------- confirmação
    def confirmar(self, pergunta: str, resposta: str) -> None:
        """Incorpora uma interação **concluída** ao histórico."""
        self.historico.append(Mensagem.usuario(pergunta))
        self.historico.append(Mensagem.assistente(resposta))

    def reiniciar(self) -> None:
        """Nova conversa: novo ``conversationId`` e histórico vazio."""
        self.id = uuid.uuid4()
        self.historico.clear()
        self.ultimo_uso = None
        self.ultimo_request_id = None

    # ---------------------------------------------------------------- execução
    def perguntar(self, cliente: TransmissorChat, *, modelo: str, pergunta: str) -> Iterator[str]:
        """Envia a pergunta e **gera os trechos de texto** à medida que chegam.

        A interação só é confirmada no histórico quando o evento ``completed`` é recebido.
        Qualquer exceção (``StreamError``, ``StreamInterrupted``, rede) ou interrupção do
        consumidor deixa o histórico intacto.

        Raises:
            StreamError: evento ``error`` recebido do gateway.
        """
        janela = self.montar_janela(pergunta)
        partes: list[str] = []
        concluido = False
        for evento in cliente.transmitir_chat(
            modelo=modelo, mensagens=janela.mensagens, conversa_id=self.id
        ):
            if isinstance(evento, EventoDelta):
                if evento.content:
                    partes.append(evento.content)
                    yield evento.content
            elif isinstance(evento, EventoErro):
                raise StreamError(
                    evento.mensagem or "O gateway reportou erro durante a geração.",
                    codigo=evento.codigo,
                    request_id=evento.request_id,
                )
            elif isinstance(evento, EventoConcluido):
                concluido = True
                self.ultimo_uso = evento.usage
                self.ultimo_request_id = evento.request_id

        resposta = "".join(partes)
        if concluido and resposta.strip():
            self.confirmar(pergunta, resposta)
