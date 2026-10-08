"""Tela de diagnóstico: executa as suítes contra o gateway real e os provedores externos.

Cada suíte mede o comportamento **real** da origem (limites, formato de erros, latência, vazão,
obediência a instruções) e exporta um relatório redigido, sem segredos.
"""

from __future__ import annotations

import streamlit as st

from itsa_agente.diagnostics import (
    Diagnostico,
    OpcoesDiagnostico,
    Relatorio,
    Resultado,
    relatorio_json,
    relatorio_markdown,
)
from itsa_agente.diagnostics.provedores import DiagnosticoProvedor, OpcoesDiagnosticoProvedor
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.errors import GatewayError
from itsa_agente.providers.base import NOMES_PROVEDORES, separar
from itsa_agente.providers.fabrica import PROVEDORES_EXTERNOS
from itsa_agente.providers.openai_compat import ClienteOpenAICompat
from itsa_agente.ui import estado


def renderizar() -> None:
    st.header("🩺 Diagnóstico do gateway")
    cliente = estado.cliente_atual()
    externos = estado.externos_atuais()
    if cliente is None and not externos:
        st.warning("Conecte-se primeiro na tela **Conexão**.")
        st.stop()

    if cliente is not None:
        _secao_gateway(cliente)
    else:
        st.info("Sem conexão com o gateway ITSA: o diagnóstico do gateway não está disponível.")

    for ident in PROVEDORES_EXTERNOS:
        if ident in externos:
            _secao_provedor(ident, externos[ident])


# ----------------------------------------------------------------------------- gateway
def _secao_gateway(cliente: ClienteGateway) -> None:
    st.write(
        "Executa uma bateria de verificações contra o gateway real e gera um relatório com o "
        "**catálogo de respostas de erro** e os limites medidos. Use-o para completar o contrato "
        "documentado (`docs/sdd/03-contrato-api-gateway.md`)."
    )

    with st.form("form_diagnostico"):
        col1, col2 = st.columns(2)
        with col1:
            carga = st.checkbox(
                "Incluir teste de tamanho de contexto (D19)",
                help="Envia conteúdos de 2 mil a 192 mil caracteres. Mais lento: usa inferência.",
            )
        with col2:
            invalida = st.checkbox(
                "Incluir credencial inválida (D18)",
                help="Envia um Token ID propositalmente errado. Pode acionar bloqueio ou "
                "limite de taxa no licenciamento — use com cuidado.",
            )
        executar = st.form_submit_button("▶️ Executar diagnóstico", type="primary")

    if executar:
        opcoes = OpcoesDiagnostico(
            modelo=st.session_state.get(estado.CHAVE_MODELO),
            incluir_carga=carga,
            incluir_credencial_invalida=invalida,
        )
        with st.status("Executando verificações...", expanded=True) as caixa:

            def progresso(r: Resultado) -> None:
                st.write(f"{r.status.icone} **{r.id}** — {r.titulo}: {r.detalhe}")

            try:
                relatorio = Diagnostico(cliente, opcoes, ao_concluir=progresso).executar()
            except GatewayError as exc:
                caixa.update(label="Diagnóstico interrompido", state="error")
                estado.mostrar_erro(exc)
                return
            caixa.update(
                label="Diagnóstico concluído" + ("" if relatorio.aprovado else " (com falhas)"),
                state="complete" if relatorio.aprovado else "error",
                expanded=False,
            )
        st.session_state[estado.CHAVE_RELATORIO] = relatorio

    relatorio_salvo = st.session_state.get(estado.CHAVE_RELATORIO)
    if relatorio_salvo is not None:
        _mostrar_relatorio(relatorio_salvo, "gateway")


# ------------------------------------------------------------------------ provedores
def _secao_provedor(ident: str, cliente: ClienteOpenAICompat) -> None:
    nome = NOMES_PROVEDORES[ident]
    st.divider()
    st.subheader(f"Provedor externo — {nome}")
    st.write(
        f"Mede o comportamento real de {nome} com a sua chave: latência, streaming incremental, "
        "vazão de geração, raciocínio, obediência a instruções e erros. Cada verificação consome "
        "poucos tokens; a leitura de contexto longo consome mais."
    )
    with st.form(f"form_diag_{ident}"):
        modelo = st.text_input(
            "Modelo de teste (ID no provedor; vazio = escolha automática)",
            value=_modelo_padrao(ident),
            key=f"itsa_w_diag_modelo_{ident}",
        )
        col1, col2 = st.columns(2)
        with col1:
            raciocinio = st.checkbox("Raciocínio ligado × desligado (P06)", value=True)
            longa = st.checkbox("Resposta longa: streaming e vazão (P05)", value=True)
        with col2:
            invalida = st.checkbox("Chave inválida é rejeitada (P07)", value=True)
            contexto = st.checkbox(
                "Contexto longo — agulha no palheiro (P09)",
                help="Envia 24 mil e 96 mil caracteres. Consome tokens (no OpenRouter, créditos).",
            )
        executar = st.form_submit_button(f"▶️ Executar diagnóstico de {nome}", type="primary")

    relatorios: dict[str, Relatorio] = st.session_state.setdefault(
        estado.CHAVE_RELATORIO_EXTERNO, {}
    )
    if executar:
        opcoes = OpcoesDiagnosticoProvedor(
            modelo=modelo.strip() or None,
            incluir_raciocinio=raciocinio,
            incluir_resposta_longa=longa,
            incluir_chave_invalida=invalida,
            incluir_contexto_longo=contexto,
        )
        with st.status(f"Executando verificações em {nome}...", expanded=True) as caixa:

            def progresso(r: Resultado) -> None:
                st.write(f"{r.status.icone} **{r.id}** — {r.titulo}: {r.detalhe}")

            relatorio = DiagnosticoProvedor(cliente, opcoes, ao_concluir=progresso).executar()
            caixa.update(
                label="Diagnóstico concluído" + ("" if relatorio.aprovado else " (com falhas)"),
                state="complete" if relatorio.aprovado else "error",
                expanded=False,
            )
        relatorios[ident] = relatorio

    if ident in relatorios:
        _mostrar_relatorio(relatorios[ident], ident)


def _modelo_padrao(ident: str) -> str:
    """Pré-preenche com o modelo escolhido no chat, se for deste provedor."""
    escolhido = st.session_state.get(estado.CHAVE_MODELO, "")
    provedor, local = separar(escolhido)
    return local if provedor == ident else ""


# --------------------------------------------------------------------------- exibição
def _mostrar_relatorio(relatorio: Relatorio, chave: str) -> None:
    c = relatorio.contagem()
    cols = st.columns(5)
    for col, (nome, valor) in zip(cols, c.items(), strict=True):
        col.metric(nome, valor)

    st.subheader("Resultados")
    st.dataframe(
        [
            {
                "ID": r.id,
                "Status": f"{r.status.icone} {r.status.value}",
                "Verificação": r.titulo,
                "Detalhe": r.detalhe,
                "ms": round(r.duracao_ms),
            }
            for r in relatorio.resultados
        ],
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Catálogo de respostas de erro observadas")
    if relatorio.observacoes:
        st.dataframe(
            [
                {
                    "Endpoint": o.endpoint,
                    "Cenário": o.cenario,
                    "HTTP": o.status_http if o.status_http is not None else f"rede: {o.erro_rede}",
                    "error.code": o.codigo,
                    "Mensagem": o.mensagem,
                    "Corpo bruto (resumo)": o.corpo,
                }
                for o in relatorio.observacoes
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("Nenhuma resposta de erro observada.")

    col_a, col_b = st.columns(2)
    col_a.download_button(
        "⬇️ Relatório (Markdown)",
        relatorio_markdown(relatorio),
        file_name=f"diagnostico-{chave}.md",
        mime="text/markdown",
        key=f"itsa_w_baixar_md_{chave}",
    )
    col_b.download_button(
        "⬇️ Relatório (JSON)",
        relatorio_json(relatorio),
        file_name=f"diagnostico-{chave}.json",
        mime="application/json",
        key=f"itsa_w_baixar_json_{chave}",
    )
