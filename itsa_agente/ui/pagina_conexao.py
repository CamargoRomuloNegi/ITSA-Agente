"""Tela de conexão: informa as credenciais e obtém o token."""

from __future__ import annotations

import streamlit as st

from itsa_agente.gateway.errors import GatewayError
from itsa_agente.gateway.models import Credenciais
from itsa_agente.ui import estado


def renderizar() -> None:
    st.header("🔌 Conexão com o gateway")
    cfg = estado.configuracao()
    cliente = estado.cliente_atual()

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
        if st.button("Desconectar", type="secondary"):
            estado.desconectar()
            st.rerun()
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
        enviado = st.form_submit_button("Conectar", type="primary")

    st.caption(f"Gateway: `{cfg.base_url}`")

    if not enviado:
        return
    try:
        credenciais = Credenciais(cpf_cnpj, token_id, usuario)
        with st.spinner("Autenticando..."):
            estado.conectar(credenciais, cfg)
    except GatewayError as exc:
        estado.mostrar_erro(exc)
        return
    st.rerun()
