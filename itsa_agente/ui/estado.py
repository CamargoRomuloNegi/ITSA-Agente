"""Estado de sessão do Streamlit e utilitários comuns às telas.

Segredos: o Token ID só existe dentro de :class:`Credenciais`, dentro do ``ClienteGateway`` guardado
em ``st.session_state`` (memória do servidor, isolada por sessão do navegador). Nada é gravado em
disco, em cookie ou em ``st.query_params``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import streamlit as st

from itsa_agente.config import Settings
from itsa_agente.conversation import Conversa
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.errors import (
    BadRequest,
    ConnectionFailed,
    CreditoInsuficiente,
    Forbidden,
    GatewayError,
    LocalValidationError,
    RateLimited,
    RequestTimeout,
    ServerError,
    ServiceUnavailable,
    StreamError,
    StreamInterrupted,
    Unauthorized,
)
from itsa_agente.gateway.models import Credenciais
from itsa_agente.providers.base import NOMES_PROVEDORES, OpcoesGeracao
from itsa_agente.providers.fabrica import criar_provedor
from itsa_agente.providers.openai_compat import ClienteOpenAICompat
from itsa_agente.providers.roteador import Roteador
from itsa_agente.security import configurar_logging, redator_global

CHAVE_CLIENTE = "itsa_cliente"
CHAVE_CONVERSA = "itsa_conversa"
CHAVE_MODELO = "itsa_modelo"
CHAVE_FABRICA = "itsa_fabrica"  # permite injetar um cliente de teste (AppTest)
CHAVE_RELATORIO = "itsa_relatorio"
CHAVE_EXTERNOS = "itsa_externos"  # dict[str, ClienteOpenAICompat]: provedores externos conectados
CHAVE_FABRICA_EXTERNOS = "itsa_fabrica_externos"  # injeção de dublês (AppTest)
CHAVE_OPCOES = "itsa_opcoes_geracao"
CHAVE_AVISOS = "itsa_avisos_conexao"
CHAVE_RELATORIO_EXTERNO = "itsa_relatorio_externo"

FabricaCliente = Callable[[Credenciais, Settings], ClienteGateway]
FabricaExterno = Callable[[str, str, Settings], ClienteOpenAICompat]


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


def externos_atuais() -> dict[str, ClienteOpenAICompat]:
    """Provedores externos conectados nesta sessão (``id`` -> cliente)."""
    externos: dict[str, ClienteOpenAICompat] = st.session_state.setdefault(CHAVE_EXTERNOS, {})
    return externos


def roteador() -> Roteador:
    """Fachada sobre as origens de modelos conectadas (gateway ITSA e/ou provedores externos)."""
    opcoes: OpcoesGeracao = st.session_state.get(CHAVE_OPCOES) or OpcoesGeracao()
    return Roteador(cliente_atual(), externos_atuais(), opcoes)


def exigir_ia() -> Roteador:
    """Interrompe a tela se não houver nenhuma origem de modelos conectada."""
    rot = roteador()
    if not rot.ativo:
        st.warning("Conecte-se primeiro na tela **Conexão**.")
        st.stop()
    return rot


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


def conectar_externos(chaves: Mapping[str, str], cfg: Settings) -> dict[str, GatewayError]:
    """Conecta cada provedor externo com a chave informada e valida com uma chamada leve.

    Os provedores são independentes: os que passam ficam conectados mesmo que outro falhe.

    Returns:
        As falhas por provedor (vazio se todos conectaram). Nenhuma chave é guardada em disco.
    """
    fabrica: FabricaExterno = st.session_state.get(CHAVE_FABRICA_EXTERNOS) or (
        lambda ident, chave, c: criar_provedor(ident, chave, c)
    )
    falhas: dict[str, GatewayError] = {}
    for ident, chave in chaves.items():
        if not chave.strip():
            continue
        try:
            cliente = fabrica(ident, chave, cfg)  # valida e registra a chave no redator
        except GatewayError as exc:
            falhas[ident] = exc
            continue
        try:
            cliente.verificar()
        except GatewayError as exc:
            cliente.fechar()
            falhas[ident] = exc
            continue
        antigo = externos_atuais().pop(ident, None)
        if antigo is not None:
            antigo.fechar()
        externos_atuais()[ident] = cliente
    return falhas


def desconectar_externo(ident: str) -> None:
    cliente = externos_atuais().pop(ident, None)
    if cliente is not None:
        cliente.fechar()
    st.session_state.pop(CHAVE_OPCOES, None)


def desconectar() -> None:
    antigo = cliente_atual()
    if antigo is not None:
        antigo.fechar()
    for cliente in list(externos_atuais().values()):
        cliente.fechar()
    for chave in (
        CHAVE_CLIENTE,
        CHAVE_CONVERSA,
        CHAVE_MODELO,
        CHAVE_RELATORIO,
        CHAVE_RELATORIO_EXTERNO,
        CHAVE_EXTERNOS,
        CHAVE_OPCOES,
        CHAVE_AVISOS,
    ):
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


def _texto_erro_provedor(exc: GatewayError) -> str:
    """Mensagens para erros vindos de provedores externos (chave de API, não Token ID)."""
    nome = NOMES_PROVEDORES.get(exc.provedor or "", exc.provedor or "o provedor")
    if isinstance(exc, Unauthorized):
        return (
            f"A chave de API de {nome} foi recusada (inválida, revogada ou expirada). "
            "Gere uma nova chave e conecte-se novamente."
        )
    if isinstance(exc, CreditoInsuficiente):
        return f"Créditos ou cota esgotados em {nome}. Verifique o saldo ou o plano da conta."
    if isinstance(exc, Forbidden):
        return (
            f"{nome} negou o acesso (chave sem permissão para este modelo ou política do provedor)."
        )
    if isinstance(exc, RateLimited):
        espera = f" Tente novamente em {exc.retry_after:.0f}s." if exc.retry_after else ""
        return f"{nome}: limite de requisições atingido." + espera
    if isinstance(exc, ServiceUnavailable | ServerError):
        return f"{nome} está indisponível ou instável no momento. Tente novamente em instantes."
    if isinstance(exc, BadRequest):
        return f"{nome} recusou a requisição: {exc.mensagem}"
    if isinstance(exc, ConnectionFailed):
        return f"Não foi possível conectar a {nome}. Verifique a rede e a URL configurada."
    if isinstance(exc, RequestTimeout):
        return f"{nome} demorou demais para responder."
    if isinstance(exc, StreamInterrupted):
        return f"A resposta de {nome} foi interrompida antes de terminar e não foi guardada."
    return f"Falha na comunicação com {nome}: {exc.mensagem}"


def texto_erro(exc: GatewayError) -> str:
    """Mensagem amigável (pt-BR) para o usuário final, a partir do tipo de erro."""
    if exc.provedor and not isinstance(exc, LocalValidationError):
        return _texto_erro_provedor(exc)
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
