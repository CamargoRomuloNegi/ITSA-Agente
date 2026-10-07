"""Tela de modelos disponíveis."""

from __future__ import annotations

import streamlit as st

from itsa_agente.gateway.errors import GatewayError
from itsa_agente.ui import estado

W_MODELO = "itsa_w_modelo_pagina"


def renderizar() -> None:
    st.header("🧠 Modelos disponíveis")
    cliente = estado.exigir_conexao()

    forcar = st.button("Atualizar lista")

    try:
        with st.spinner("Consultando modelos..."):
            modelos = cliente.listar_modelos(forcar=forcar)
    except GatewayError as exc:
        estado.mostrar_erro(exc)
        return

    if not modelos:
        st.info(
            "O gateway não informou nenhum modelo habilitado e instalado para este cliente. "
            "Uma lista vazia é uma resposta válida; verifique o licenciamento/instalação."
        )
        return

    st.dataframe(
        [{"ID (usar no chat)": m.id, "Nome": m.rotulo} for m in modelos],
        hide_index=True,
        use_container_width=True,
    )
    ids = [m.id for m in modelos]
    if st.session_state.get(W_MODELO) not in ids:
        atual = st.session_state.get(estado.CHAVE_MODELO)
        st.session_state[W_MODELO] = atual if atual in ids else ids[0]
    escolhido = st.selectbox(
        "Modelo padrão para o chat de teste",
        ids,
        key=W_MODELO,
        format_func=lambda i: next(m.rotulo for m in modelos if m.id == i),
    )
    st.session_state[estado.CHAVE_MODELO] = escolhido
