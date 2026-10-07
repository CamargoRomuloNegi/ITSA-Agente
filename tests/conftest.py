from __future__ import annotations

import logging
from collections.abc import Callable, Iterator

import httpx
import pytest

from itsa_agente.config import Settings
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.models import Credenciais
from itsa_agente.security import redator_global
from tests.gateway_falso import CPF_CNPJ_OK, TOKEN_ID_OK, USUARIO_OK, GatewayFalso


class Relogio:
    """Relógio controlável (substitui time.monotonic)."""

    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


@pytest.fixture
def gw() -> GatewayFalso:
    return GatewayFalso()


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture
def cfg() -> Settings:
    return Settings(base_url="http://gateway.test", max_retries=2, retry_backoff_base=0.0)


@pytest.fixture
def credenciais() -> Credenciais:
    return Credenciais(CPF_CNPJ_OK, TOKEN_ID_OK, USUARIO_OK)


@pytest.fixture
def esperas() -> list[float]:
    return []


@pytest.fixture
def criar_cliente(
    gw: GatewayFalso,
    cfg: Settings,
    credenciais: Credenciais,
    relogio: Relogio,
    esperas: list[float],
) -> Iterator[Callable[..., ClienteGateway]]:
    criados: list[ClienteGateway] = []

    def fabrica(**kw: object) -> ClienteGateway:
        cliente = ClienteGateway(
            kw.pop("credenciais", credenciais),  # type: ignore[arg-type]
            kw.pop("cfg", cfg),  # type: ignore[arg-type]
            transporte=httpx.MockTransport(gw),
            dormir=esperas.append,
            relogio=relogio,
            **kw,  # type: ignore[arg-type]
        )
        criados.append(cliente)
        return cliente

    yield fabrica
    for c in criados:
        c.fechar()


@pytest.fixture
def cliente(criar_cliente: Callable[..., ClienteGateway]) -> ClienteGateway:
    return criar_cliente()


@pytest.fixture(autouse=True)
def _registrar_segredos_no_redator() -> None:
    redator_global().registrar(TOKEN_ID_OK)


@pytest.fixture(autouse=True)
def _isolar_logging() -> Iterator[None]:
    """`configurar_logging` altera o logger global; restaura para não mascarar testes de caplog."""
    logger = logging.getLogger("itsa_agente")
    nivel, propaga, handlers = logger.level, logger.propagate, list(logger.handlers)
    yield
    logger.setLevel(nivel)
    logger.propagate = propaga
    logger.handlers[:] = handlers
