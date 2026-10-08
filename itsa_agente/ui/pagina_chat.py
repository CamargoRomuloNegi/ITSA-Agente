"""Chat de teste: conversa livre com o modelo, sem agente especialista nem guardrails.

Serve para validar ponta a ponta o fluxo token → modelos → chat/streaming e o contrato de
histórico (a interação só entra no histórico após ``completed``). Funciona com o gateway ITSA e/ou
com provedores externos (NVIDIA, OpenRouter): o modelo escolhido define o destino. Os agentes
especialistas (comercial, fiscal, contábil...) terão telas próprias e o modelo **fixado em
configuração**, sem escolha do usuário — ver ``docs/sdd/06-agentes-e-modulos.md`` e ADR-0010.
"""

from __future__ import annotations

import streamlit as st

from itsa_agente.conversation import Conversa
from itsa_agente.gateway.errors import GatewayError
from itsa_agente.providers.base import (
    NOMES_PROVEDORES,
    PROVEDOR_ITSA,
    OpcoesGeracao,
    qualificar,
    separar,
)
from itsa_agente.ui import estado

W_PROVEDOR = "itsa_w_provedor_chat"
W_MODELO = "itsa_w_modelo_chat"
W_MODELO_LIVRE = "itsa_w_modelo_livre_chat"
W_RACIOCINIO = "itsa_w_raciocinio_chat"
W_SISTEMA = "itsa_w_prompt_sistema"

_RACIOCINIO = {"Padrão do ITSA-Agente": None, "Ligado": True, "Desligado": False}


def renderizar() -> None:
    st.header("💬 Chat de teste")
    roteador = estado.exigir_ia()
    cfg = estado.configuracao()
    conversa = estado.conversa_atual(cfg.max_history_chars)

    catalogo = roteador.catalogo()
    for exc in catalogo.falhas.values():
        estado.mostrar_erro(exc)
    ativos = roteador.provedores_ativos
    if not catalogo.modelos and not any(p != PROVEDOR_ITSA for p in ativos):
        if not catalogo.falhas:
            st.info("Nenhum modelo disponível para este cliente.")
        return

    # Widgets com `key` perdem o valor quando a tela não é renderizada (troca de página); por isso
    # o valor "oficial" fica em chaves próprias (CHAVE_MODELO, Conversa.prompt_sistema) e o widget
    # é re-semeado a partir delas.
    if W_SISTEMA not in st.session_state:
        st.session_state[W_SISTEMA] = conversa.prompt_sistema or ""

    with st.sidebar:
        st.subheader("Chat de teste")

        # Provedor: só aparece quando há mais de uma origem conectada.
        if len(ativos) > 1:
            if st.session_state.get(W_PROVEDOR) not in ativos:
                padrao = st.session_state.get(estado.CHAVE_MODELO, "")
                prov_padrao = separar(padrao)[0]
                st.session_state[W_PROVEDOR] = prov_padrao if prov_padrao in ativos else ativos[0]
            provedor = st.selectbox(
                "Provedor",
                ativos,
                key=W_PROVEDOR,
                format_func=lambda p: NOMES_PROVEDORES.get(p, p),
            )
        else:
            provedor = ativos[0]
        externo = provedor != PROVEDOR_ITSA

        modelos = catalogo.do_provedor(provedor)
        ids = [m.id for m in modelos]
        modelo = ""
        if ids:
            if st.session_state.get(W_MODELO) not in ids:
                padrao = st.session_state.get(estado.CHAVE_MODELO)
                st.session_state[W_MODELO] = padrao if padrao in ids else ids[0]
            modelo = st.selectbox(
                "Modelo",
                ids,
                key=W_MODELO,
                format_func=lambda i: next(m.rotulo for m in modelos if m.id == i),
            )
        if externo:
            livre = st.text_input(
                "Outro ID de modelo (opcional)",
                key=W_MODELO_LIVRE,
                help="Usa um modelo do catálogo do provedor que não está na lista acima. "
                "Ex.: nvidia/llama-3.3-nemotron-super-49b-v1.5",
            ).strip()
            if livre:
                modelo = qualificar(provedor, livre)
            rotulo_rac = st.selectbox(
                "Raciocínio (thinking)",
                list(_RACIOCINIO),
                key=W_RACIOCINIO,
                help="Liga ou desliga o raciocínio em modelos que o suportam. Ligado: respostas "
                "melhores em questões difíceis, porém mais lentas e com mais tokens.",
            )
            st.session_state[estado.CHAVE_OPCOES] = OpcoesGeracao(
                raciocinio=_RACIOCINIO[rotulo_rac]
            )
            roteador.opcoes = st.session_state[estado.CHAVE_OPCOES]
        if not modelo:
            st.info("Nenhum modelo disponível neste provedor. Informe um ID de modelo acima.")
            return
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

    ultimo = len(conversa.historico) - 1
    for i, msg in enumerate(conversa.historico):
        with st.chat_message("user" if msg.role == "user" else "assistant"):
            st.markdown(msg.content)
            if i == ultimo and msg.role == "assistant":
                _anexos_da_resposta(conversa)

    pergunta = st.chat_input("Digite sua pergunta")
    if not pergunta:
        return

    with st.chat_message("user"):
        st.markdown(pergunta)
    with st.chat_message("assistant"):
        antes = len(conversa.historico)
        try:
            janela = conversa.montar_janela(pergunta)
            if janela.descartadas:
                st.caption(
                    f"ℹ️ {janela.descartadas} mensagens antigas ficaram fora do contexto "
                    "(limite de mensagens/caracteres)."
                )
            st.write_stream(conversa.perguntar(roteador, modelo=modelo, pergunta=pergunta))
        except GatewayError as exc:
            estado.mostrar_erro(exc)
            st.caption("Esta interação não foi incorporada ao histórico.")
            return
        if len(conversa.historico) == antes:  # concluiu, mas sem texto de resposta
            st.warning(
                "O modelo não produziu texto de resposta. Se o raciocínio estiver ligado, ele pode "
                "ter esgotado o limite de tokens pensando (veja ITSA_PROVIDER_MAX_TOKENS)."
            )
            _anexos_da_resposta(conversa)
            st.caption("Esta interação não foi incorporada ao histórico.")
            return
    st.rerun()


def _anexos_da_resposta(conversa: Conversa) -> None:
    """Raciocínio (recolhido) e aviso de resposta cortada, junto da última resposta."""
    if conversa.ultimo_raciocinio:
        with st.expander("Raciocínio do modelo"):
            st.markdown(conversa.ultimo_raciocinio)
    if conversa.ultimo_motivo == "length":
        st.caption("⚠️ Resposta cortada pelo limite de tokens (ITSA_PROVIDER_MAX_TOKENS).")
