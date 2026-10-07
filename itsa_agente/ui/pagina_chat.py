"""Chat de teste: conversa livre com o modelo, sem agente especialista nem guardrails.

Serve para validar ponta a ponta o fluxo token → modelos → chat/streaming e o contrato de
histórico (a interação só entra no histórico após ``completed``). Os agentes especialistas
(comercial, fiscal, contábil...) terão telas próprias — ver ``docs/sdd/06-agentes-e-modulos.md``.
"""

from __future__ import annotations

import streamlit as st

from itsa_agente.gateway.errors import GatewayError
from itsa_agente.ui import estado

W_MODELO = "itsa_w_modelo_chat"
W_SISTEMA = "itsa_w_prompt_sistema"


def renderizar() -> None:
    st.header("💬 Chat de teste")
    cliente = estado.exigir_conexao()
    cfg = estado.configuracao()
    conversa = estado.conversa_atual(cfg.max_history_chars)

    try:
        modelos = cliente.listar_modelos()
    except GatewayError as exc:
        estado.mostrar_erro(exc)
        return
    if not modelos:
        st.info("Nenhum modelo disponível para este cliente.")
        return

    ids = [m.id for m in modelos]
    # Widgets com `key` perdem o valor quando a tela não é renderizada (troca de página); por isso
    # o valor "oficial" fica em chaves próprias (CHAVE_MODELO, Conversa.prompt_sistema) e o widget
    # é re-semeado a partir delas.
    if st.session_state.get(W_MODELO) not in ids:
        padrao = st.session_state.get(estado.CHAVE_MODELO)
        st.session_state[W_MODELO] = padrao if padrao in ids else ids[0]
    if W_SISTEMA not in st.session_state:
        st.session_state[W_SISTEMA] = conversa.prompt_sistema or ""

    with st.sidebar:
        st.subheader("Chat de teste")
        modelo = st.selectbox(
            "Modelo",
            ids,
            key=W_MODELO,
            format_func=lambda i: next(m.rotulo for m in modelos if m.id == i),
        )
        st.session_state[estado.CHAVE_MODELO] = modelo
        texto_sistema = st.text_area(
            "Instrução de sistema (opcional)",
            key=W_SISTEMA,
            height=120,
            help="Enviada como a primeira mensagem (role=system). Use o diagnóstico D10 "
            "para saber se o modelo obedece.",
        )
        conversa.prompt_sistema = texto_sistema.strip() or None
        if st.button("🗑️ Nova conversa"):
            conversa.reiniciar()
            st.rerun()
        st.caption(f"Conversa `{str(conversa.id)[:8]}…` · {len(conversa.historico)} mensagens")
        if conversa.ultimo_uso:
            st.metric("Tokens (última resposta)", conversa.ultimo_uso.total)
            st.caption(
                f"entrada {conversa.ultimo_uso.prompt_tokens} · "
                f"saída {conversa.ultimo_uso.completion_tokens}"
            )

    for msg in conversa.historico:
        with st.chat_message("user" if msg.role == "user" else "assistant"):
            st.markdown(msg.content)

    pergunta = st.chat_input("Digite sua pergunta")
    if not pergunta:
        return

    with st.chat_message("user"):
        st.markdown(pergunta)
    with st.chat_message("assistant"):
        try:
            janela = conversa.montar_janela(pergunta)
            if janela.descartadas:
                st.caption(
                    f"ℹ️ {janela.descartadas} mensagens antigas ficaram fora do contexto "
                    "(limite de mensagens/caracteres)."
                )
            st.write_stream(conversa.perguntar(cliente, modelo=modelo, pergunta=pergunta))
        except GatewayError as exc:
            estado.mostrar_erro(exc)
            st.caption("Esta interação não foi incorporada ao histórico.")
            return
    st.rerun()
