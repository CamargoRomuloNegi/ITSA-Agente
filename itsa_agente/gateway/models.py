"""Contratos (DTOs) da API IAitsaGateway, conforme o swagger v1.

As regras do swagger que o servidor impõe são **replicadas aqui** para falhar cedo e sem custo de
rede: 1–30 mensagens, última com ``role=user``, ``content`` não vazio, ``erpUserName`` com 1–15
caracteres, CPF com 11 dígitos ou CNPJ normalizado com 14 caracteres (alfanumérico).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from itsa_agente.gateway.errors import LocalValidationError

MAX_MENSAGENS = 30
MIN_MENSAGENS = 1
MAX_USUARIO_ERP = 15

Papel = Literal["system", "user", "assistant"]

_RE_CPF = re.compile(r"^\d{11}$")
_RE_CNPJ = re.compile(r"^[0-9A-Z]{14}$")
_RE_PONTUACAO_DOC = re.compile(r"[.\-/\s]")


# --------------------------------------------------------------------------------------
# Credenciais
# --------------------------------------------------------------------------------------
def normalizar_cpf_cnpj(valor: str) -> str:
    """Remove pontuação/espaços e converte para maiúsculas.

    Aceita CPF (11 dígitos) e CNPJ (14 caracteres, numérico ou alfanumérico). Não valida
    dígitos verificadores — isso é responsabilidade do licenciamento, no servidor.
    """
    limpo = _RE_PONTUACAO_DOC.sub("", valor or "").upper()
    if _RE_CPF.match(limpo) or _RE_CNPJ.match(limpo):
        return limpo
    raise LocalValidationError(
        "CPF/CNPJ inválido: informe 11 dígitos (CPF) ou 14 caracteres "
        "(CNPJ, numérico ou alfanumérico)."
    )


@dataclass(frozen=True, slots=True)
class Credenciais:
    """Credenciais do cliente. ``token_id`` é segredo: nunca aparece em ``repr``/logs."""

    cpf_cnpj: str
    token_id: str = field(repr=False)
    usuario_erp: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "cpf_cnpj", normalizar_cpf_cnpj(self.cpf_cnpj))
        token = (self.token_id or "").strip()
        if not token:
            raise LocalValidationError("Token ID é obrigatório.")
        object.__setattr__(self, "token_id", token)
        usuario = (self.usuario_erp or "").strip()
        if not 1 <= len(usuario) <= MAX_USUARIO_ERP:
            raise LocalValidationError(
                f"Usuário do ERP deve ter entre 1 e {MAX_USUARIO_ERP} caracteres."
            )
        object.__setattr__(self, "usuario_erp", usuario)

    def payload(self) -> dict[str, str]:
        """Corpo de ``POST /api/auth/token`` (contém o segredo — não logar)."""
        return {
            "cpfCnpj": self.cpf_cnpj,
            "tokenId": self.token_id,
            "erpUserName": self.usuario_erp,
        }

    @property
    def cpf_cnpj_mascarado(self) -> str:
        c = self.cpf_cnpj
        return f"{c[:3]}{'*' * (len(c) - 5)}{c[-2:]}"

    def __repr__(self) -> str:
        return (
            f"Credenciais(cpf_cnpj={self.cpf_cnpj_mascarado!r}, token_id='***', "
            f"usuario_erp={self.usuario_erp!r})"
        )


class TokenResponse(BaseModel):
    """Resposta de ``POST /api/auth/token``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    access_token: str = Field(alias="accessToken", min_length=1, repr=False)
    token_type: str = Field(default="Bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn", gt=0)
    expires_at_utc: datetime | None = Field(default=None, alias="expiresAtUtc")


# --------------------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------------------
class ModeloInfo(BaseModel):
    """Um item de ``GET /api/models``."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1)
    display_name: str | None = Field(default=None, alias="displayName")

    @property
    def rotulo(self) -> str:
        return self.display_name or self.id


class ModelsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    models: list[ModeloInfo] = Field(default_factory=list)

    @field_validator("models", mode="before")
    @classmethod
    def _none_vira_lista(cls, valor: Any) -> Any:
        return [] if valor is None else valor


# --------------------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------------------
class Mensagem(BaseModel):
    """Uma mensagem do histórico (``ChatMessage`` no swagger)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Papel
    content: str

    @field_validator("content")
    @classmethod
    def _nao_vazio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("content não pode ser vazio.")
        return valor

    @classmethod
    def sistema(cls, texto: str) -> Mensagem:
        return cls(role="system", content=texto)

    @classmethod
    def usuario(cls, texto: str) -> Mensagem:
        return cls(role="user", content=texto)

    @classmethod
    def assistente(cls, texto: str) -> Mensagem:
        return cls(role="assistant", content=texto)


class ChatRequest(BaseModel):
    """Corpo de ``POST /api/chat``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    conversation_id: uuid.UUID = Field(alias="conversationId")
    model: str = Field(min_length=1)
    messages: list[Mensagem] = Field(min_length=MIN_MENSAGENS, max_length=MAX_MENSAGENS)
    stream: Literal[True] = True

    @model_validator(mode="after")
    def _ultima_e_usuario(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("A última mensagem deve ter role = 'user'.")
        return self

    def para_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


# --------------------------------------------------------------------------------------
# Erros do gateway
# --------------------------------------------------------------------------------------
class ApiError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str | None = None
    message: str | None = None


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: ApiError | None = None


# --------------------------------------------------------------------------------------
# Eventos do streaming NDJSON
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Uso:
    """Consumo de tokens informado no evento ``completed``."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class EventoIniciado:
    request_id: str | None = None
    conversation_id: str | None = None
    model: str | None = None
    tipo: str = "started"


@dataclass(frozen=True, slots=True)
class EventoDelta:
    content: str
    request_id: str | None = None
    tipo: str = "delta"


@dataclass(frozen=True, slots=True)
class EventoConcluido:
    request_id: str | None = None
    model: str | None = None
    usage: Uso | None = None
    tipo: str = "completed"
    #: Motivo do fim informado por provedores externos (``stop``, ``length``...). O gateway ITSA
    #: não informa; ``length`` significa resposta cortada pelo limite de tokens.
    motivo: str | None = None


@dataclass(frozen=True, slots=True)
class EventoRaciocinio:
    """Trecho de *raciocínio* (``reasoning``) de provedores externos — separado da resposta."""

    content: str
    request_id: str | None = None
    tipo: str = "reasoning"


@dataclass(frozen=True, slots=True)
class EventoErro:
    codigo: str | None
    mensagem: str | None
    request_id: str | None = None
    bruto: dict[str, Any] = field(default_factory=dict)
    tipo: str = "error"


@dataclass(frozen=True, slots=True)
class EventoDesconhecido:
    """Evento com ``type`` não documentado — preservado para auditoria, ignorado no fluxo."""

    tipo_original: str | None
    bruto: dict[str, Any] = field(default_factory=dict)
    tipo: str = "unknown"


EventoStream = (
    EventoIniciado
    | EventoDelta
    | EventoRaciocinio
    | EventoConcluido
    | EventoErro
    | EventoDesconhecido
)
EVENTOS_TERMINAIS = (EventoConcluido, EventoErro)


@dataclass(frozen=True, slots=True)
class ResultadoChat:
    """Resultado agregado de uma chamada de chat concluída."""

    texto: str
    request_id: str | None
    model: str | None
    conversation_id: uuid.UUID
    usage: Uso | None
    tempo_total_s: float
    tempo_primeiro_trecho_s: float | None
    trechos: int
