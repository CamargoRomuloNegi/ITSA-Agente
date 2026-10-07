"""Obtenção e renovação do JWT (``POST /api/auth/token``).

Decisões de projeto:

- O prazo de validade é calculado com ``expiresIn`` **relativo ao instante de recebimento**
  (relógio monotônico), não com ``expiresAtUtc``: assim, diferença de relógio entre a máquina do
  cliente e o servidor não invalida token bom nem mantém token vencido. ``expiresAtUtc`` é guardado
  apenas para exibição.
- O token é renovado ``token_skew_seconds`` antes de vencer, evitando 401 no meio de uma conversa.
- Acesso protegido por ``Lock`` (Streamlit pode executar callbacks em threads distintas).
- O Token ID só trafega no corpo do ``POST``; nunca é guardado fora de :class:`Credenciais`
  nem escrito em log.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from pydantic import ValidationError

from itsa_agente.gateway.errors import (
    ConnectionFailed,
    ProtocolError,
    RequestTimeout,
)
from itsa_agente.gateway.models import Credenciais, TokenResponse

log = logging.getLogger("itsa_agente.auth")


@dataclass(frozen=True, slots=True)
class InfoToken:
    """Estado público do token (sem o valor do JWT)."""

    expira_em_s: float
    expira_em_utc: datetime | None
    validade_total_s: int


class GerenciadorToken:
    """Mantém um JWT válido para um conjunto de :class:`Credenciais`."""

    def __init__(
        self,
        *,
        credenciais: Credenciais,
        emitir: Callable[[Credenciais], httpx.Response],
        skew_s: int = 60,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._credenciais = credenciais
        self._emitir = emitir
        self._skew = skew_s
        self._relogio = relogio
        self._lock = threading.Lock()
        self._jwt: str | None = None
        self._vence_em: float = 0.0
        self._emitido_em: float = 0.0
        self._resposta: TokenResponse | None = None

    # ------------------------------------------------------------------ estado
    @property
    def credenciais(self) -> Credenciais:
        return self._credenciais

    def _valido(self) -> bool:
        return self._jwt is not None and self._relogio() < self._vence_em - self._skew

    @property
    def autenticado(self) -> bool:
        with self._lock:
            return self._valido()

    def info(self) -> InfoToken | None:
        with self._lock:
            if self._jwt is None or self._resposta is None:
                return None
            return InfoToken(
                expira_em_s=max(self._vence_em - self._relogio(), 0.0),
                expira_em_utc=self._resposta.expires_at_utc,
                validade_total_s=self._resposta.expires_in,
            )

    # -------------------------------------------------------------------- ações
    def obter(self) -> str:
        """Retorna um JWT válido, emitindo/renovando se necessário."""
        with self._lock:
            if not self._valido():
                self._renovar_sem_lock()
            assert self._jwt is not None
            return self._jwt

    def renovar(self) -> str:
        """Força nova emissão (ex.: após receber 401 com token aparentemente válido)."""
        with self._lock:
            self._renovar_sem_lock()
            assert self._jwt is not None
            return self._jwt

    def invalidar(self) -> None:
        with self._lock:
            self._jwt = None
            self._vence_em = 0.0

    # ----------------------------------------------------------------- internos
    def _renovar_sem_lock(self) -> None:
        try:
            resposta = self._emitir(self._credenciais)
        except httpx.TimeoutException as exc:
            raise RequestTimeout("Tempo esgotado ao solicitar o token de acesso.") from exc
        except httpx.TransportError as exc:
            raise ConnectionFailed(
                f"Falha de rede ao solicitar o token de acesso ({type(exc).__name__})."
            ) from exc

        # Respostas de erro são convertidas em exceções tipadas por quem injetou `emitir`
        # (GatewayClient), que conhece o mapeamento status -> exceção.
        try:
            token = TokenResponse.model_validate(resposta.json())
        except (ValueError, ValidationError) as exc:
            raise ProtocolError("Resposta de /api/auth/token fora do contrato esperado.") from exc

        agora = self._relogio()
        self._jwt = token.access_token
        self._emitido_em = agora
        self._vence_em = agora + token.expires_in
        self._resposta = token
        log.info(
            "Token emitido para usuário %s (validade %ss).",
            self._credenciais.usuario_erp,
            token.expires_in,
        )
