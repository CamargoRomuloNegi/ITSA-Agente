"""Estado de sessão do Streamlit e utilitários comuns às telas.

Segredos: o Token ID só existe dentro de :class:`Credenciais`, dentro do ``ClienteGateway`` guardado
em ``st.session_state`` (memória do servidor, isolada por sessão do navegador). Nada é gravado em
disco, em cookie ou em ``st.query_params``.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from itsa_agente.config import Settings
from itsa_agente.conversation import Conversa
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.errors import (
    BadRequest,
    ConnectionFailed,
    Forbidden,
    GatewayError,
    LocalValidationError,
    RateLimited,
    RequestTimeout,
    ServiceUnavailable,
    StreamError,
    StreamInterrupted,
    Unauthorized,
)
from itsa_agente.gateway.models import Credenciais
from itsa_agente.security import configurar_logging, redator_global

CHAVE_CLIENTE = "itsa_cliente"
CHAVE_CONVERSA = "itsa_conversa"
CHAVE_MODELO = "itsa_modelo"
CHAVE_FABRICA = "itsa_fabrica"  # permite injetar um cliente de teste (AppTest)
CHAVE_RELATORIO = "itsa_relatorio"

FabricaCliente = Callable[[Credenciais, Settings], ClienteGateway]


def configuracao() -> Settings:
    """Configuração (``.env`` + ambiente), carregada uma vez por sessão."""
    if "itsa_cfg" not in st.session_state:
        cfg = Settings.from_env()
        configurar_logging(cfg.log_level)
        st.session_state["itsa_cfg"] = cfg
    cfg_sessao: Settings = st.session_state["itsa_cfg"]
    return cfg_sessao


def _fabrica() -> FabricaCliente:
    fab: FabricaCliente = st.session_state.get(CHAVE_FABRICA, ClienteGateway)
    return fab


def cliente_atual() -> ClienteGateway | None:
    cliente: ClienteGateway | None = st.session_state.get(CHAVE_CLIENTE)
    return cliente


def conversa_atual(max_caracteres: int) -> Conversa:
    if CHAVE_CONVERSA not in st.session_state:
        st.session_state[CHAVE_CONVERSA] = Conversa(max_caracteres=max_caracteres)
    conversa: Conversa = st.session_state[CHAVE_CONVERSA]
    return conversa


def conectar(credenciais: Credenciais, cfg: Settings) -> None:
    """Cria o cliente, emite o token (valida as credenciais) e guarda na sessão.

    Raises:
        GatewayError: credenciais recusadas ou gateway inacessível — a sessão não é alterada.
    """
    redator_global().registrar(credenciais.token_id)
    novo = _fabrica()(credenciais, cfg)
    try:
        novo.autenticar()
    except GatewayError:
        novo.fechar()
        raise
    desconectar()
    st.session_state[CHAVE_CLIENTE] = novo


def desconectar() -> None:
    antigo = cliente_atual()
    if antigo is not None:
        antigo.fechar()
    for chave in (CHAVE_CLIENTE, CHAVE_CONVERSA, CHAVE_MODELO, CHAVE_RELATORIO):
        st.session_state.pop(chave, None)
    for chave in [c for c in st.session_state if str(c).startswith("itsa_w_")]:
        del st.session_state[chave]  # estado de widgets das telas (modelo, instrução de sistema)


def exigir_conexao() -> ClienteGateway:
    """Interrompe a renderização da tela se não houver conexão ativa."""
    cliente = cliente_atual()
    if cliente is None:
        st.warning("Conecte-se primeiro na tela **Conexão**.")
        st.stop()
    assert cliente is not None
    return cliente


def texto_erro(exc: GatewayError) -> str:
    """Mensagem amigável (pt-BR) para o usuário final, a partir do tipo de erro."""
    if isinstance(exc, LocalValidationError):
        return f"Dados inválidos: {exc.mensagem}"
    if isinstance(exc, Unauthorized):
        return (
            "Credenciais inválidas ou sessão expirada. "
            "Verifique CPF/CNPJ e Token ID e conecte-se novamente."
        )
    if isinstance(exc, Forbidden):
        return "Acesso negado para este cliente (licença vencida, bloqueada ou sem este módulo)."
    if isinstance(exc, RateLimited):
        espera = f" Tente novamente em {exc.retry_after:.0f}s." if exc.retry_after else ""
        return "Muitas requisições em pouco tempo." + espera
    if isinstance(exc, ServiceUnavailable):
        return "O serviço de IA está indisponível no momento. Tente novamente em instantes."
    if isinstance(exc, BadRequest):
        return f"A requisição foi recusada pelo gateway: {exc.mensagem}"
    if isinstance(exc, ConnectionFailed):
        return "Não foi possível conectar ao servidor de IA. Verifique a rede e a URL configurada."
    if isinstance(exc, RequestTimeout):
        return "O servidor de IA demorou demais para responder."
    if isinstance(exc, StreamInterrupted):
        return "A resposta foi interrompida antes de terminar. Ela não foi guardada no histórico."
    if isinstance(exc, StreamError):
        return f"O modelo reportou um erro durante a resposta: {exc.mensagem}"
    return f"Falha na comunicação com o gateway: {exc.mensagem}"


def mostrar_erro(exc: GatewayError) -> None:
    st.error(texto_erro(exc))
    detalhes = []
    if exc.codigo:
        detalhes.append(f"código: `{exc.codigo}`")
    if exc.status:
        detalhes.append(f"HTTP {exc.status}")
    if exc.request_id:
        detalhes.append(f"requestId: `{exc.request_id}`")
    if detalhes:
        st.caption(" · ".join(detalhes))
