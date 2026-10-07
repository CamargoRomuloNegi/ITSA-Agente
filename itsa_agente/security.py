"""Higiene de segredos: mascaramento em logs e relatórios.

Princípio: **nenhum segredo (Token ID, JWT) e nenhum conteúdo de conversa vai para log ou
relatório.** Esta camada é a última linha de defesa — o código já evita logar esses valores — e
é usada de forma obrigatória na geração de relatórios de diagnóstico, que o usuário pode anexar a
chamados de suporte.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable
from typing import Any

# JWT: três segmentos base64url separados por ponto, iniciando por "eyJ" (cabeçalho JSON).
_RE_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")
_RE_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_RE_CAMPO_SEGREDO = re.compile(
    r'(?i)("?(?:tokenId|accessToken|token_id|access_token|authorization)"?\s*[:=]\s*)'
    r'("?)[^",\s}]+("?)'
)
_RE_DOC = re.compile(r"\b(\d{3})\d{6,9}(\d{2})\b")

MASCARA = "***"


def mascarar_valor(valor: str, *, visivel: int = 0) -> str:
    """Mascara um segredo, opcionalmente mantendo ``visivel`` caracteres finais."""
    if not valor:
        return valor
    if visivel and len(valor) > visivel * 2:
        return f"{MASCARA}{valor[-visivel:]}"
    return MASCARA


class Redator:
    """Remove segredos conhecidos e padrões sensíveis de textos."""

    def __init__(self, segredos: Iterable[str] = ()) -> None:
        self._segredos: set[str] = set()
        self._lock = threading.Lock()
        for s in segredos:
            self.registrar(s)

    def registrar(self, segredo: str | None) -> None:
        """Registra um segredo literal a ser removido onde quer que apareça."""
        if segredo and len(segredo) >= 4:
            with self._lock:
                self._segredos.add(segredo)

    def aplicar(self, texto: str) -> str:
        with self._lock:
            conhecidos = sorted(self._segredos, key=len, reverse=True)
        for segredo in conhecidos:
            texto = texto.replace(segredo, MASCARA)
        texto = _RE_JWT.sub(MASCARA, texto)
        texto = _RE_BEARER.sub(rf"\1{MASCARA}", texto)
        texto = _RE_CAMPO_SEGREDO.sub(rf"\1\2{MASCARA}\3", texto)
        return _RE_DOC.sub(rf"\1{'*' * 6}\2", texto)

    def aplicar_em(self, valor: Any) -> Any:
        """Aplica a redação recursivamente em str, list, tuple e dict."""
        if isinstance(valor, str):
            return self.aplicar(valor)
        if isinstance(valor, dict):
            return {k: self.aplicar_em(v) for k, v in valor.items()}
        if isinstance(valor, list | tuple):
            return [self.aplicar_em(v) for v in valor]
        return valor


class FiltroRedacao(logging.Filter):
    """Filtro de ``logging`` que aplica um :class:`Redator` à mensagem final."""

    def __init__(self, redator: Redator) -> None:
        super().__init__()
        self._redator = redator

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redator.aplicar(record.getMessage())
        record.args = None
        return True


_REDATOR_GLOBAL = Redator()


def redator_global() -> Redator:
    """Redator compartilhado pela aplicação (os segredos são registrados ao conectar)."""
    return _REDATOR_GLOBAL


def configurar_logging(nivel: str = "INFO") -> None:
    """Configura o logger raiz ``itsa_agente`` com redação. Idempotente."""
    # O filtro vai no *handler*: filtros de logger não se aplicam a registros de loggers filhos
    # (itsa_agente.client, itsa_agente.auth...), que chegam aos handlers por propagação.
    logger = logging.getLogger("itsa_agente")
    logger.setLevel(nivel)
    for handler in logger.handlers:
        if any(isinstance(f, FiltroRedacao) for f in handler.filters):
            return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(FiltroRedacao(_REDATOR_GLOBAL))
    logger.addHandler(handler)
    logger.propagate = False
