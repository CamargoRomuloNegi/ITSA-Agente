"""Tela de diagnóstico: executa a suíte contra o gateway real e exporta o relatório."""

from __future__ import annotations

import streamlit as st

from itsa_agente.diagnostics import (
    Diagnostico,
    OpcoesDiagnostico,
    Resultado,
    relatorio_json,
    relatorio_markdown,
)
from itsa_agente.gateway.errors import GatewayError
from itsa_agente.ui import estado


def renderizar() -> None:
    st.header("🩺 Diagnóstico do gateway")
    cliente = estado.exigir_conexao()
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
                help="Envia conteúdos de 2 mil a 96 mil caracteres. Mais lento: usa inferência.",
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

    relatorio = st.session_state.get(estado.CHAVE_RELATORIO)
    if relatorio is None:
        return

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
        file_name="diagnostico-gateway.md",
        mime="text/markdown",
    )
    col_b.download_button(
        "⬇️ Relatório (JSON)",
        relatorio_json(relatorio),
        file_name="diagnostico-gateway.json",
        mime="application/json",
    )
