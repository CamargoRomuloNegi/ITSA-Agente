"""Testes de interface com o framework de teste do Streamlit (AppTest), sem navegador."""

from __future__ import annotations

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from itsa_agente.config import RAIZ_PROJETO, Settings
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.models import Credenciais
from itsa_agente.ui import estado
from tests.gateway_falso import CPF_CNPJ_OK, TOKEN_ID_OK, USUARIO_OK, GatewayFalso


@pytest.fixture
def app(gw: GatewayFalso) -> AppTest:
    cfg = Settings(base_url="http://gateway.test", max_retries=0)

    def fabrica(cred: Credenciais, _: Settings) -> ClienteGateway:
        return ClienteGateway(cred, cfg, transporte=httpx.MockTransport(gw), dormir=lambda s: None)

    at = AppTest.from_file(str(RAIZ_PROJETO / "app.py"), default_timeout=30)
    at.session_state[estado.CHAVE_FABRICA] = fabrica
    at.session_state["itsa_cfg"] = cfg
    return at.run()


def conectar(at: AppTest, token: str = TOKEN_ID_OK) -> AppTest:
    at.text_input[0].set_value(CPF_CNPJ_OK)
    at.text_input[1].set_value(token)
    at.text_input[2].set_value(USUARIO_OK)
    at.button[0].click()
    return at.run()


def test_tela_inicial_pede_credenciais(app: AppTest) -> None:
    assert not app.exception
    assert app.header[0].value.endswith("Conexão com o gateway")
    # 3 campos do gateway + 2 chaves de provedores externos (opcionais), todos de senha, exceto
    # CPF/CNPJ e usuário.
    assert len(app.text_input) == 5
    assert app.text_input[1].proto.type == 1  # PASSWORD: o Token ID é mascarado na tela
    assert app.text_input[3].proto.type == 1  # chave NVIDIA mascarada
    assert app.text_input[4].proto.type == 1  # chave OpenRouter mascarada


def test_conexao_com_sucesso(app: AppTest) -> None:
    at = conectar(app)
    assert not at.exception
    assert any("Conectado como **CARLOS**" in s.value for s in at.success)
    assert estado.CHAVE_CLIENTE in at.session_state
    assert TOKEN_ID_OK not in str([e.value for e in at.markdown])  # o segredo nunca é renderizado


def test_conexao_com_token_errado_mostra_erro_amigavel(app: AppTest) -> None:
    at = conectar(app, token="TOKEN-ERRADO")
    assert not at.exception
    assert any("Credenciais inválidas" in e.value for e in at.error)
    assert estado.CHAVE_CLIENTE not in at.session_state


def test_conexao_com_cnpj_invalido_e_validada_localmente(app: AppTest, gw: GatewayFalso) -> None:
    app.text_input[0].set_value("123")
    app.text_input[1].set_value("t")
    app.text_input[2].set_value("ANA")
    app.button[0].click()
    at = app.run()
    assert any("CPF/CNPJ inválido" in e.value for e in at.error)
    assert gw.chamadas == []


def test_desconectar_limpa_a_sessao(app: AppTest) -> None:
    at = conectar(app)
    at.button[0].click()  # "Desconectar"
    at = at.run()
    assert estado.CHAVE_CLIENTE not in at.session_state
    assert len(at.text_input) == 5


def _pagina_protegida(nome: str) -> None:
    import importlib

    importlib.import_module(f"itsa_agente.ui.pagina_{nome}").renderizar()


@pytest.mark.parametrize("nome", ["modelos", "chat", "diagnostico"])
def test_telas_protegidas_exigem_conexao(nome: str) -> None:
    at = AppTest.from_function(_pagina_protegida, args=(nome,), default_timeout=30).run()
    assert not at.exception
    assert any("Conecte-se primeiro" in w.value for w in at.warning)


def _pagina_chat_conectada() -> None:
    import httpx as _httpx
    import streamlit as st

    from itsa_agente.config import Settings as _S
    from itsa_agente.gateway.client import ClienteGateway as _C
    from itsa_agente.gateway.models import Credenciais as _Cred
    from itsa_agente.ui import estado as _e
    from itsa_agente.ui import pagina_chat
    from tests.gateway_falso import CPF_CNPJ_OK as _cpf
    from tests.gateway_falso import TOKEN_ID_OK as _tok
    from tests.gateway_falso import USUARIO_OK as _usr
    from tests.gateway_falso import GatewayFalso as _G

    if _e.CHAVE_CLIENTE not in st.session_state:
        gw = _G()
        st.session_state["gw"] = gw
        st.session_state["itsa_cfg"] = _S(base_url="http://gateway.test", max_retries=0)
        cliente = _C(
            _Cred(_cpf, _tok, _usr),
            st.session_state["itsa_cfg"],
            transporte=_httpx.MockTransport(gw),
            dormir=lambda s: None,
        )
        cliente.autenticar()
        st.session_state[_e.CHAVE_CLIENTE] = cliente
    pagina_chat.renderizar()


def test_chat_envia_pergunta_e_guarda_no_historico() -> None:
    at = AppTest.from_function(_pagina_chat_conectada, default_timeout=30).run()
    assert not at.exception
    at.chat_input[0].set_value("Responda OK").run()
    assert not at.exception, at.exception
    textos = [m.value for m in at.markdown]
    assert "Responda OK" in textos and "OK" in textos
    conversa = at.session_state[estado.CHAVE_CONVERSA]
    assert [m.content for m in conversa.historico] == ["Responda OK", "OK"]


def test_chat_com_erro_nao_guarda_no_historico() -> None:
    at = AppTest.from_function(_pagina_chat_conectada, default_timeout=30).run()
    at.session_state["gw"].modo_stream = "evento_erro"
    at.chat_input[0].set_value("oi").run()
    assert not at.exception
    assert any("erro durante a resposta" in e.value for e in at.error)
    assert at.session_state[estado.CHAVE_CONVERSA].historico == []


def test_chat_nova_conversa_reinicia() -> None:
    at = AppTest.from_function(_pagina_chat_conectada, default_timeout=30).run()
    at.chat_input[0].set_value("oi").run()
    antigo = at.session_state[estado.CHAVE_CONVERSA].id
    next(b for b in at.sidebar.button if "Nova conversa" in b.label).click()
    at.run()
    nova = at.session_state[estado.CHAVE_CONVERSA]
    assert nova.id != antigo and nova.historico == []


def test_texto_erro_cobre_os_tipos_principais() -> None:
    from itsa_agente.gateway.errors import (
        Forbidden,
        RateLimited,
        ServiceUnavailable,
        StreamInterrupted,
        Unauthorized,
    )

    assert "Credenciais inválidas" in estado.texto_erro(Unauthorized("x"))
    assert "licença" in estado.texto_erro(Forbidden("x"))
    assert "30s" in estado.texto_erro(RateLimited("x", retry_after=30))
    assert "indisponível" in estado.texto_erro(ServiceUnavailable("x"))
    assert "não foi guardada" in estado.texto_erro(StreamInterrupted("x"))


def test_chat_envia_a_instrucao_de_sistema_e_ela_sobrevive_a_novas_rodadas() -> None:
    at = AppTest.from_function(_pagina_chat_conectada, default_timeout=30).run()
    at.sidebar.text_area[0].set_value("Responda sempre em uma frase.").run()
    at.chat_input[0].set_value("primeira").run()
    at.chat_input[0].set_value("segunda").run()
    assert not at.exception
    corpos = at.session_state["gw"].corpos_chat
    assert corpos[0]["messages"][0] == {
        "role": "system",
        "content": "Responda sempre em uma frase.",
    }
    assert corpos[1]["messages"][0]["role"] == "system"
    assert [m["content"] for m in corpos[1]["messages"]][1:] == ["primeira", "OK", "segunda"]


def test_desconectar_limpa_o_estado_dos_widgets(app: AppTest) -> None:
    at = conectar(app)
    at.session_state["itsa_w_prompt_sistema"] = "algo"
    at.button[0].click()
    at = at.run()
    assert "itsa_w_prompt_sistema" not in at.session_state
