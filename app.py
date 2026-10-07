"""Ponto de entrada do ITSA-Agente (Streamlit).

Execução (sem instalar nada no sistema — usa um ambiente isolado na própria pasta)::

    Windows:  iniciar.bat
    Linux/macOS:  ./iniciar.sh

ou, com as dependências já instaladas::

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante que o pacote `itsa_agente` (pasta ao lado deste arquivo) seja importável em qualquer
# ambiente de execução (Streamlit Cloud, serviço, IDE), independentemente do diretório atual.
_RAIZ = str(Path(__file__).resolve().parent)
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

import streamlit as st  # noqa: E402

from itsa_agente import __version__  # noqa: E402
from itsa_agente.ui import (  # noqa: E402
    estado,
    pagina_chat,
    pagina_conexao,
    pagina_diagnostico,
    pagina_modelos,
)

st.set_page_config(page_title="ITSA Agente", page_icon="💬", layout="wide")


def _barra_lateral() -> None:
    cliente = estado.cliente_atual()
    with st.sidebar:
        st.caption(f"ITSA-Agente v{__version__}")
        if cliente is None:
            st.caption("🔴 Desconectado")
            return
        info = cliente.info_token()
        restante = f" · token {info.expira_em_s / 60:.0f} min" if info else ""
        st.caption(f"🟢 {cliente.credenciais.usuario_erp}{restante}")


navegacao = st.navigation(
    [
        st.Page(
            pagina_conexao.renderizar, title="Conexão", icon="🔌", url_path="conexao", default=True
        ),
        st.Page(pagina_modelos.renderizar, title="Modelos", icon="🧠", url_path="modelos"),
        st.Page(pagina_chat.renderizar, title="Chat de teste", icon="💬", url_path="chat"),
        st.Page(
            pagina_diagnostico.renderizar, title="Diagnóstico", icon="🩺", url_path="diagnostico"
        ),
    ]
)
estado.configuracao()
_barra_lateral()
navegacao.run()
