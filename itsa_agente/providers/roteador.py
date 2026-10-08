"""Roteador: expõe gateway ITSA e provedores externos como **uma única** fonte de modelos.

Implementa o contrato mínimo que ``Conversa`` exige (``transmitir_chat``), escolhendo o destino
pelo prefixo do identificador do modelo (ver :mod:`itsa_agente.providers.base`). Em produção,
cada agente terá o modelo fixado em configuração (ADR-0010); a tela de teste deixa o usuário
escolher.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.errors import GatewayError, LocalValidationError
from itsa_agente.gateway.models import EventoStream, Mensagem
from itsa_agente.providers.base import (
    NOMES_PROVEDORES,
    ORDEM_PROVEDORES,
    PROVEDOR_ITSA,
    ModeloCatalogo,
    OpcoesGeracao,
    separar,
)
from itsa_agente.providers.openai_compat import ClienteOpenAICompat


@dataclass(slots=True)
class Catalogo:
    """Modelos de todas as origens ativas e as falhas de listagem, por provedor.

    Uma origem fora do ar não impede o uso das demais: sua falha fica em ``falhas``.
    """

    modelos: list[ModeloCatalogo] = field(default_factory=list)
    falhas: dict[str, GatewayError] = field(default_factory=dict)

    def do_provedor(self, provedor: str) -> list[ModeloCatalogo]:
        return [m for m in self.modelos if m.provedor == provedor]

    @property
    def provedores(self) -> list[str]:
        presentes = {m.provedor for m in self.modelos}
        return [p for p in ORDEM_PROVEDORES if p in presentes]


class Roteador:
    """Fachada sobre o gateway (opcional) e os provedores externos conectados."""

    def __init__(
        self,
        gateway: ClienteGateway | None = None,
        externos: Mapping[str, ClienteOpenAICompat] | None = None,
        opcoes: OpcoesGeracao | None = None,
    ) -> None:
        self.gateway = gateway
        self.externos: dict[str, ClienteOpenAICompat] = dict(externos or {})
        #: Parâmetros de geração aplicados às chamadas a provedores externos.
        self.opcoes = opcoes or OpcoesGeracao()

    # ------------------------------------------------------------------ estado
    @property
    def ativo(self) -> bool:
        """Há ao menos uma origem de modelos conectada?"""
        return self.gateway is not None or bool(self.externos)

    @property
    def provedores_ativos(self) -> list[str]:
        ativos = set(self.externos)
        if self.gateway is not None:
            ativos.add(PROVEDOR_ITSA)
        return [p for p in ORDEM_PROVEDORES if p in ativos]

    # ---------------------------------------------------------------- catálogo
    def catalogo(self, *, forcar: bool = False) -> Catalogo:
        resultado = Catalogo()
        if self.gateway is not None:
            try:
                for m in self.gateway.listar_modelos(forcar=forcar):
                    resultado.modelos.append(
                        ModeloCatalogo(
                            id=m.id, rotulo=m.rotulo, provedor=PROVEDOR_ITSA, externo=False
                        )
                    )
            except GatewayError as exc:
                resultado.falhas[PROVEDOR_ITSA] = exc
        for id_provedor in ORDEM_PROVEDORES:
            cliente = self.externos.get(id_provedor)
            if cliente is None:
                continue
            try:
                resultado.modelos.extend(cliente.listar_modelos(forcar=forcar))
            except GatewayError as exc:
                resultado.falhas[id_provedor] = exc
        return resultado

    # -------------------------------------------------------------------- chat
    def transmitir_chat(
        self,
        *,
        modelo: str,
        mensagens: Sequence[Mensagem],
        conversa_id: uuid.UUID | None = None,
    ) -> Iterator[EventoStream]:
        provedor, local = separar(modelo)
        if provedor == PROVEDOR_ITSA:
            if self.gateway is None:
                raise LocalValidationError(
                    "O modelo escolhido é do gateway ITSA, mas não há conexão com o gateway."
                )
            return self.gateway.transmitir_chat(
                modelo=local, mensagens=mensagens, conversa_id=conversa_id
            )
        cliente = self.externos.get(provedor)
        if cliente is None:
            nome = NOMES_PROVEDORES.get(provedor, provedor)
            raise LocalValidationError(f"Não há conexão ativa com {nome} para este modelo.")
        return cliente.transmitir_chat(
            modelo=local, mensagens=mensagens, conversa_id=conversa_id, opcoes=self.opcoes
        )

    # ------------------------------------------------------------ ciclo de vida
    def fechar_externos(self) -> None:
        for cliente in self.externos.values():
            cliente.fechar()
        self.externos.clear()
