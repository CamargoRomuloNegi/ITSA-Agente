"""Tela de modelos disponíveis (gateway ITSA e provedores externos conectados)."""

from __future__ import annotations

import streamlit as st

from itsa_agente.ui import estado

W_MODELO = "itsa_w_modelo_pagina"


def renderizar() -> None:
    st.header("🧠 Modelos disponíveis")
    roteador = estado.exigir_ia()

    forcar = st.button("Atualizar lista")

    with st.spinner("Consultando modelos..."):
        catalogo = roteador.catalogo(forcar=forcar)
    for exc in catalogo.falhas.values():
        estado.mostrar_erro(exc)

    modelos = catalogo.modelos
    if not modelos:
        if not catalogo.falhas:
            st.info(
                "Nenhum modelo habilitado e instalado para as conexões ativas. "
                "Uma lista vazia é uma resposta válida; verifique o licenciamento/instalação."
            )
        return

    externos = any(m.externo for m in modelos)
    linhas: list[dict[str, object]] = []
    for m in modelos:
        linha: dict[str, object] = {"ID (usar no chat)": m.id, "Nome": m.rotulo}
        if externos:
            linha["Provedor"] = m.nome_provedor
            linha["Contexto (tokens)"] = m.contexto
            linha["Gratuito"] = {True: "sim", False: "não", None: ""}[m.gratuito]
        linhas.append(linha)
    st.dataframe(linhas, hide_index=True, use_container_width=True)

    ids = [m.id for m in modelos]
    if st.session_state.get(W_MODELO) not in ids:
        atual = st.session_state.get(estado.CHAVE_MODELO)
        st.session_state[W_MODELO] = atual if atual in ids else ids[0]
    rotulos = {m.id: (f"{m.rotulo} — {m.nome_provedor}" if externos else m.rotulo) for m in modelos}
    escolhido = st.selectbox(
        "Modelo padrão para o chat de teste",
        ids,
        key=W_MODELO,
        format_func=lambda i: rotulos[i],
    )
    st.session_state[estado.CHAVE_MODELO] = escolhido
