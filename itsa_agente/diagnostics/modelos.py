"""Tipos do relatório de diagnóstico."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    OK = "OK"
    ALERTA = "ALERTA"
    FALHA = "FALHA"
    INFO = "INFO"
    PULADO = "PULADO"

    @property
    def icone(self) -> str:
        return {
            Status.OK: "✅",
            Status.ALERTA: "⚠️",
            Status.FALHA: "❌",
            Status.INFO: "ℹ️",
            Status.PULADO: "⏭️",
        }[self]


@dataclass(slots=True)
class Resultado:
    """Resultado de uma verificação."""

    id: str
    titulo: str
    status: Status
    detalhe: str
    duracao_ms: float = 0.0
    dados: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Observacao:
    """Uma resposta de erro observada — alimenta o catálogo de erros do gateway."""

    endpoint: str
    cenario: str
    status_http: int | None
    codigo: str | None
    mensagem: str | None
    tempo_ms: float
    erro_rede: str | None = None
    corpo: str | None = None  # resumo curto do corpo de erro (já sem segredos após a redação)


@dataclass(slots=True)
class Relatorio:
    versao_app: str
    iniciado_em: str
    base_url: str
    usuario_erp: str
    cpf_cnpj_mascarado: str
    opcoes: dict[str, Any]
    resultados: list[Resultado] = field(default_factory=list)
    observacoes: list[Observacao] = field(default_factory=list)
    duracao_total_s: float = 0.0

    def contagem(self) -> dict[str, int]:
        c = {s.value: 0 for s in Status}
        for r in self.resultados:
            c[r.status.value] += 1
        return c

    @property
    def aprovado(self) -> bool:
        return not any(r.status is Status.FALHA for r in self.resultados)
