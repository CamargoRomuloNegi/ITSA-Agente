"""Tela de conexão: credenciais do gateway ITSA e, opcionalmente, chaves de provedores externos."""

from __future__ import annotations

import streamlit as st

from itsa_agente.config import Settings
from itsa_agente.gateway.errors import GatewayError
from itsa_agente.gateway.models import Credenciais
from itsa_agente.providers.base import NOMES_PROVEDORES, PROVEDOR_NVIDIA, PROVEDOR_OPENROUTER
from itsa_agente.providers.fabrica import PROVEDORES_EXTERNOS
from itsa_agente.providers.openrouter import ProvedorOpenRouter
from itsa_agente.ui import estado

_AJUDA_CHAVE = {
    PROVEDOR_NVIDIA: "Gere em build.nvidia.com ('Generate API Key'). Começa com `nvapi-`.",
    PROVEDOR_OPENROUTER: "Gere em openrouter.ai/keys. Começa com `sk-or-`.",
}


def _campos_externos() -> dict[str, str]:
    """Campos de chave dos provedores externos (usados dentro de um ``st.form``)."""
    chaves: dict[str, str] = {}
    for ident in PROVEDORES_EXTERNOS:
        chaves[ident] = st.text_input(
            f"Chave de API — {NOMES_PROVEDORES[ident]}",
            type="password",
            autocomplete="off",
            help=_AJUDA_CHAVE[ident],
        )
    return chaves


def _conectar_externos(chaves: dict[str, str], cfg: Settings) -> bool:
    """Conecta os provedores; guarda as falhas para exibição. Devolve ``True`` se algum conectou."""
    informadas = {k: v for k, v in chaves.items() if v.strip()}
    if not informadas:
        return False
    falhas = estado.conectar_externos(informadas, cfg)
    if falhas:
        st.session_state[estado.CHAVE_AVISOS] = {
            ident: (estado.texto_erro(exc), exc) for ident, exc in falhas.items()
        }
    return len(falhas) < len(informadas)


def _mostrar_avisos() -> None:
    """Exibe (uma vez) as falhas de conexão guardadas antes do ``st.rerun``."""
    avisos = st.session_state.pop(estado.CHAVE_AVISOS, None)
    if not avisos:
        return
    for _ident, (texto, exc) in avisos.items():
        st.warning(texto)
        detalhes = [f"HTTP {exc.status}"] if exc.status else []
        if exc.codigo:
            detalhes.append(f"código: `{exc.codigo}`")
        if detalhes:
            st.caption(" · ".join(detalhes))


def _detalhe_da_chave(cliente: object) -> str | None:
    """Resumo da conta no OpenRouter (cota diária de modelos gratuitos e créditos), se houver."""
    if not isinstance(cliente, ProvedorOpenRouter) or cliente.info_chave is None:
        return None
    info = cliente.info_chave
    partes: list[str] = []
    if info.gratuitos_limite is not None and info.gratuitos_usados is not None:
        partes.append(f"modelos gratuitos hoje: {info.gratuitos_usados}/{info.gratuitos_limite}")
    if info.creditos_restantes is not None:
        partes.append(f"créditos restantes da chave: {info.creditos_restantes:.2f}")
    return " · ".join(partes) or None


def _exibir_conectado(cfg: Settings) -> None:
    cliente = estado.cliente_atual()
    externos = estado.externos_atuais()

    if cliente is not None:
        info = cliente.info_token()
        cred = cliente.credenciais
        st.success(
            f"Conectado como **{cred.usuario_erp}** — cliente {cred.cpf_cnpj_mascarado}.",
            icon="✅",
        )
        if info is not None:
            st.caption(
                f"Token válido por mais {info.expira_em_s / 60:.1f} min "
                "(renovado automaticamente antes de vencer)."
            )
    else:
        nomes = ", ".join(NOMES_PROVEDORES[i] for i in PROVEDORES_EXTERNOS if i in externos)
        st.success(f"Conectado a provedores externos: **{nomes}**.", icon="✅")
        st.caption("Sem conexão com o gateway ITSA: os modelos locais não estão disponíveis.")

    if st.button("Desconectar", type="secondary"):
        estado.desconectar()
        st.rerun()

    _mostrar_avisos()

    st.subheader("Provedores externos")
    for ident in PROVEDORES_EXTERNOS:
        if ident in externos:
            col_a, col_b = st.columns([3, 1])
            col_a.write(f"✅ **{NOMES_PROVEDORES[ident]}** conectado (chave só na memória).")
            detalhe = _detalhe_da_chave(externos[ident])
            if detalhe:
                col_a.caption(detalhe)
            if col_b.button("Remover", key=f"itsa_w_remover_{ident}"):
                estado.desconectar_externo(ident)
                st.rerun()

    pendentes = [i for i in PROVEDORES_EXTERNOS if i not in externos]
    if not pendentes:
        return
    with st.form("form_externos", clear_on_submit=True):
        chaves: dict[str, str] = {}
        for ident in pendentes:
            chaves[ident] = st.text_input(
                f"Chave de API — {NOMES_PROVEDORES[ident]}",
                type="password",
                autocomplete="off",
                help=_AJUDA_CHAVE[ident],
            )
        enviado = st.form_submit_button("Conectar provedores")
    if (enviado and _conectar_externos(chaves, cfg)) or st.session_state.get(estado.CHAVE_AVISOS):
        st.rerun()


def renderizar() -> None:
    st.header("🔌 Conexão com o gateway")
    cfg = estado.configuracao()

    if estado.cliente_atual() is not None or estado.externos_atuais():
        _exibir_conectado(cfg)
        return

    st.write(
        "Informe as credenciais fornecidas pelo licenciamento. O **Token ID** fica apenas na "
        "memória desta sessão e nunca é gravado em disco."
    )
    with st.form("form_conexao", clear_on_submit=True):
        cpf_cnpj = st.text_input(
            "CPF/CNPJ do cliente",
            value=cfg.cpf_cnpj_padrao,
            help="CPF com 11 dígitos ou CNPJ com 14 caracteres. Pontuação é ignorada.",
        )
        token_id = st.text_input(
            "Token ID", value=cfg.token_id_dev, type="password", autocomplete="off"
        )
        usuario = st.text_input(
            "Usuário do ERP",
            value=cfg.usuario_erp_padrao,
            max_chars=15,
            help="Usuário corrente do ERP (1 a 15 caracteres).",
        )
        with st.expander("Provedores externos (opcional): NVIDIA e OpenRouter"):
            st.caption(
                "Chaves de API digitadas aqui ficam só na memória desta sessão. Com o Token ID "
                "em branco, conecta-se apenas aos provedores externos (sem modelos locais)."
            )
            chaves = _campos_externos()
        enviado = st.form_submit_button("Conectar", type="primary")

    st.caption(f"Gateway: `{cfg.base_url}`")

    if not enviado:
        return

    com_chaves = any(v.strip() for v in chaves.values())
    conectou_algo = False
    # Só o Token ID em branco, com chaves externas informadas, dispensa o gateway.
    if token_id.strip() or not com_chaves:
        try:
            credenciais = Credenciais(cpf_cnpj, token_id, usuario)
            with st.spinner("Autenticando..."):
                estado.conectar(credenciais, cfg)
        except GatewayError as exc:
            estado.mostrar_erro(exc)
            return
        conectou_algo = True
    if com_chaves:
        with st.spinner("Verificando as chaves dos provedores..."):
            conectou_algo = _conectar_externos(chaves, cfg) or conectou_algo
    if conectou_algo:
        st.rerun()
    _mostrar_avisos()
