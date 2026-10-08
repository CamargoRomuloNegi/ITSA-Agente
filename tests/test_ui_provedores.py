"""Interface com provedores externos (NVIDIA/OpenRouter), via ``AppTest`` e provedores simulados."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from itsa_agente.config import RAIZ_PROJETO, Settings
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.models import Credenciais
from itsa_agente.providers.fabrica import criar_provedor
from itsa_agente.ui import estado
from tests.gateway_falso import CPF_CNPJ_OK, TOKEN_ID_OK, USUARIO_OK, GatewayFalso
from tests.provedor_falso import CHAVE_NVIDIA_OK, CHAVE_OPENROUTER_OK, ProvedorFalso

MODELO_NV = "nvidia/nemotron-3-ultra-550b-a55b"
MODELO_OR = "nvidia/nemotron-3-ultra-550b-a55b:free"


def _cfg() -> Settings:
    return Settings(
        base_url="http://gateway.test",
        nvidia_base_url="http://nvidia.test/v1",
        openrouter_base_url="http://openrouter.test/api/v1",
        max_retries=0,
    )


@pytest.fixture
def falsos() -> dict[str, ProvedorFalso]:
    return {
        "nvidia": ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO_NV,)),
        "openrouter": ProvedorFalso(CHAVE_OPENROUTER_OK, (MODELO_OR,)),
    }


@pytest.fixture
def app(gw: GatewayFalso, falsos: dict[str, ProvedorFalso]) -> AppTest:
    cfg = _cfg()

    def fabrica_gw(cred: Credenciais, _: Settings) -> ClienteGateway:
        return ClienteGateway(cred, cfg, transporte=httpx.MockTransport(gw), dormir=lambda s: None)

    def fabrica_ext(ident: str, chave: str, c: Settings) -> Any:
        return criar_provedor(
            ident, chave, c, transporte=httpx.MockTransport(falsos[ident]), dormir=lambda s: None
        )

    at = AppTest.from_file(str(RAIZ_PROJETO / "app.py"), default_timeout=30)
    at.session_state[estado.CHAVE_FABRICA] = fabrica_gw
    at.session_state[estado.CHAVE_FABRICA_EXTERNOS] = fabrica_ext
    at.session_state["itsa_cfg"] = cfg
    return at.run()


def _preencher(at: AppTest, *, gateway: bool, nvidia: str = "", openrouter: str = "") -> AppTest:
    if gateway:
        at.text_input[0].set_value(CPF_CNPJ_OK)
        at.text_input[1].set_value(TOKEN_ID_OK)
        at.text_input[2].set_value(USUARIO_OK)
    at.text_input[3].set_value(nvidia)
    at.text_input[4].set_value(openrouter)
    at.button[0].click()
    return at.run()


def _textos(at: AppTest) -> str:
    partes: list[str] = []
    for grupo in (at.markdown, at.success, at.warning, at.error, at.caption, at.info):
        partes += [str(e.value) for e in grupo]
    return "\n".join(partes)


# =============================================================================== conexão
class TestConexao:
    def test_somente_chave_nvidia_dispensa_o_gateway(self, app: AppTest) -> None:
        at = _preencher(app, gateway=False, nvidia=CHAVE_NVIDIA_OK)
        assert not at.exception
        assert estado.CHAVE_CLIENTE not in at.session_state
        assert list(at.session_state[estado.CHAVE_EXTERNOS]) == ["nvidia"]
        assert any("provedores externos: **NVIDIA**" in s.value for s in at.success)
        assert CHAVE_NVIDIA_OK not in _textos(at)

    def test_gateway_e_os_dois_provedores_juntos(self, app: AppTest) -> None:
        at = _preencher(app, gateway=True, nvidia=CHAVE_NVIDIA_OK, openrouter=CHAVE_OPENROUTER_OK)
        assert not at.exception
        assert estado.CHAVE_CLIENTE in at.session_state
        assert set(at.session_state[estado.CHAVE_EXTERNOS]) == {"nvidia", "openrouter"}
        assert any("Conectado como **CARLOS**" in s.value for s in at.success)
        assert CHAVE_NVIDIA_OK not in _textos(at) and CHAVE_OPENROUTER_OK not in _textos(at)

    def test_openrouter_mostra_a_cota_diaria_de_modelos_gratuitos(self, app: AppTest) -> None:
        at = _preencher(app, gateway=False, openrouter=CHAVE_OPENROUTER_OK)
        assert any("modelos gratuitos hoje: 3/50" in c.value for c in at.caption)

    def test_gateway_sozinho_continua_igual(self, app: AppTest) -> None:
        at = _preencher(app, gateway=True)
        assert estado.CHAVE_CLIENTE in at.session_state
        assert not at.session_state[estado.CHAVE_EXTERNOS]

    def test_chave_errada_mostra_mensagem_do_provedor_e_nao_conecta(self, app: AppTest) -> None:
        at = _preencher(app, gateway=False, nvidia="nvapi-CHAVE-ERRADA-0123456789")
        assert not at.exception
        assert any("chave de API de NVIDIA foi recusada" in w.value for w in at.warning)
        assert not at.session_state[estado.CHAVE_EXTERNOS]
        assert len(at.text_input) == 5  # o formulário continua à disposição

    def test_gateway_ok_e_chave_externa_errada_mantem_o_gateway(self, app: AppTest) -> None:
        at = _preencher(app, gateway=True, openrouter="sk-or-v1-CHAVE-ERRADA-0123456789")
        assert not at.exception
        assert estado.CHAVE_CLIENTE in at.session_state
        assert any("chave de API de OpenRouter foi recusada" in w.value for w in at.warning)

    def test_um_provedor_bom_e_outro_ruim_ficam_independentes(self, app: AppTest) -> None:
        at = _preencher(
            app,
            gateway=False,
            nvidia=CHAVE_NVIDIA_OK,
            openrouter="sk-or-v1-CHAVE-ERRADA-0123456789",
        )
        assert list(at.session_state[estado.CHAVE_EXTERNOS]) == ["nvidia"]
        assert any("OpenRouter" in w.value for w in at.warning)

    def test_chave_com_espaco_e_validada_localmente(
        self, app: AppTest, falsos: dict[str, ProvedorFalso]
    ) -> None:
        at = _preencher(app, gateway=False, nvidia="nvapi-com espaço no meio")
        assert not at.exception
        assert any("espaços" in e.value for e in at.warning)
        assert falsos["nvidia"].chamadas == []

    def test_adicionar_provedor_depois_de_conectar_o_gateway(self, app: AppTest) -> None:
        at = _preencher(app, gateway=True)
        assert len(at.text_input) == 2  # só o formulário das duas chaves
        at.text_input[0].set_value(CHAVE_NVIDIA_OK)
        next(b for b in at.button if "Conectar provedores" in b.label).click()
        at = at.run()
        assert not at.exception
        assert list(at.session_state[estado.CHAVE_EXTERNOS]) == ["nvidia"]
        assert len(at.text_input) == 1  # resta a chave do OpenRouter

    def test_remover_provedor(self, app: AppTest) -> None:
        at = _preencher(app, gateway=True, nvidia=CHAVE_NVIDIA_OK)
        next(b for b in at.button if b.label == "Remover").click()
        at = at.run()
        assert not at.session_state[estado.CHAVE_EXTERNOS]
        assert estado.CHAVE_CLIENTE in at.session_state

    def test_desconectar_fecha_tudo(self, app: AppTest) -> None:
        at = _preencher(app, gateway=True, nvidia=CHAVE_NVIDIA_OK)
        at.button[0].click()
        at = at.run()
        assert estado.CHAVE_CLIENTE not in at.session_state
        assert not at.session_state[estado.CHAVE_EXTERNOS]
        assert len(at.text_input) == 5


# =========================================================================== telas conectadas
def _pagina_multi(nome: str, com_gateway: bool, externos: tuple[str, ...]) -> None:
    import importlib

    import httpx as _httpx
    import streamlit as st

    from itsa_agente.config import Settings as _S
    from itsa_agente.gateway.client import ClienteGateway as _C
    from itsa_agente.gateway.models import Credenciais as _Cred
    from itsa_agente.providers.fabrica import criar_provedor as _criar
    from itsa_agente.ui import estado as _e
    from tests.gateway_falso import CPF_CNPJ_OK as _cpf
    from tests.gateway_falso import TOKEN_ID_OK as _tok
    from tests.gateway_falso import USUARIO_OK as _usr
    from tests.gateway_falso import GatewayFalso as _G
    from tests.provedor_falso import CHAVE_NVIDIA_OK as _cn
    from tests.provedor_falso import CHAVE_OPENROUTER_OK as _co
    from tests.provedor_falso import ProvedorFalso as _P

    if "montado" not in st.session_state:
        cfg = _S(
            base_url="http://gateway.test",
            nvidia_base_url="http://nvidia.test/v1",
            openrouter_base_url="http://openrouter.test/api/v1",
            max_retries=0,
        )
        st.session_state["itsa_cfg"] = cfg
        if com_gateway:
            gw = _G()
            st.session_state["gw"] = gw
            cliente = _C(
                _Cred(_cpf, _tok, _usr),
                cfg,
                transporte=_httpx.MockTransport(gw),
                dormir=lambda s: None,
            )
            cliente.autenticar()
            st.session_state[_e.CHAVE_CLIENTE] = cliente
        falsos = {
            "nvidia": _P(_cn, ("nvidia/nemotron-3-ultra-550b-a55b",)),
            "openrouter": _P(_co, ("nvidia/nemotron-3-ultra-550b-a55b:free",)),
        }
        chaves = {"nvidia": _cn, "openrouter": _co}
        st.session_state["falsos"] = falsos
        for ident in externos:
            _e.externos_atuais()[ident] = _criar(
                ident,
                chaves[ident],
                cfg,
                transporte=_httpx.MockTransport(falsos[ident]),
                dormir=lambda s: None,
            )
        st.session_state["montado"] = True
    importlib.import_module(f"itsa_agente.ui.pagina_{nome}").renderizar()


def _tela(nome: str, *, gateway: bool, externos: tuple[str, ...]) -> AppTest:
    return AppTest.from_function(
        _pagina_multi, args=(nome, gateway, externos), default_timeout=30
    ).run()


def _por_rotulo(widgets: Any, rotulo: str) -> Any:
    return next(w for w in widgets if w.label == rotulo)


class TestModelos:
    def test_somente_gateway_mantem_as_colunas_originais(self) -> None:
        at = _tela("modelos", gateway=True, externos=())
        assert not at.exception
        assert list(at.dataframe[0].value.columns) == ["ID (usar no chat)", "Nome"]

    def test_gateway_mais_provedores_mostra_origem_e_ids_qualificados(self) -> None:
        at = _tela("modelos", gateway=True, externos=("nvidia", "openrouter"))
        assert not at.exception
        df = at.dataframe[0].value
        assert "Provedor" in df.columns
        assert set(df["ID (usar no chat)"]) == {
            "iaitsa-geral",
            f"nvidia::{MODELO_NV}",
            f"openrouter::{MODELO_OR}",
        }

    def test_provedor_com_falha_nao_esconde_os_demais(self) -> None:
        at = _tela("modelos", gateway=True, externos=("openrouter",))
        at.session_state["falsos"]["openrouter"].status_forcado = 500
        at.button[0].click()  # "Atualizar lista" força nova consulta ao OpenRouter
        at = at.run()
        assert any("indisponível ou instável" in e.value for e in at.error)
        assert list(at.dataframe[0].value["ID (usar no chat)"]) == ["iaitsa-geral"]


class TestChat:
    def test_com_um_unico_provedor_nao_aparece_o_seletor_de_provedor(self) -> None:
        at = _tela("chat", gateway=True, externos=())
        assert [s.label for s in at.sidebar.selectbox] == ["Modelo"]

    def test_gateway_mais_nvidia_oferece_provedor_e_roteia_para_o_escolhido(self) -> None:
        at = _tela("chat", gateway=True, externos=("nvidia",))
        assert not at.exception
        assert [s.label for s in at.sidebar.selectbox][:2] == ["Provedor", "Modelo"]
        _por_rotulo(at.sidebar.selectbox, "Provedor").select("nvidia").run()
        at.chat_input[0].set_value("Responda apenas com a palavra OK.").run()
        assert not at.exception, at.exception
        conversa = at.session_state[estado.CHAVE_CONVERSA]
        assert [m.content for m in conversa.historico][-1] == "OK"
        falso = at.session_state["falsos"]["nvidia"]
        assert falso.corpos_chat[0]["model"] == MODELO_NV
        assert at.session_state["gw"].contar("POST", "/api/chat") == 0

    def test_o_gateway_continua_respondendo_quando_ha_provedores_conectados(self) -> None:
        at = _tela("chat", gateway=True, externos=("nvidia",))
        at.chat_input[0].set_value("oi").run()
        assert not at.exception
        assert at.session_state["gw"].contar("POST", "/api/chat") == 1
        assert at.session_state["falsos"]["nvidia"].corpos_chat == []

    def test_somente_externo_com_raciocinio_ligado_mostra_o_raciocinio_a_parte(self) -> None:
        at = _tela("chat", gateway=False, externos=("nvidia",))
        assert not at.exception
        assert "Provedor" not in [s.label for s in at.sidebar.selectbox]
        _por_rotulo(at.sidebar.selectbox, "Raciocínio (thinking)").select("Ligado").run()
        at.chat_input[0].set_value("Quanto é 17 × 23?").run()
        assert not at.exception, at.exception
        corpo = at.session_state["falsos"]["nvidia"].corpos_chat[0]
        assert corpo["chat_template_kwargs"] == {"enable_thinking": True}
        assert any(e.label == "Raciocínio do modelo" for e in at.expander)
        historico = at.session_state[estado.CHAVE_CONVERSA].historico
        assert historico[-1].content == "A resposta final é 391."

    def test_raciocinio_desligado_por_padrao_para_o_nemotron(self) -> None:
        at = _tela("chat", gateway=False, externos=("nvidia",))
        at.chat_input[0].set_value("Oi").run()
        corpo = at.session_state["falsos"]["nvidia"].corpos_chat[0]
        assert corpo["chat_template_kwargs"]["enable_thinking"] is False

    def test_id_de_modelo_livre_substitui_a_lista(self) -> None:
        at = _tela("chat", gateway=False, externos=("nvidia",))
        _por_rotulo(at.sidebar.text_input, "Outro ID de modelo (opcional)").set_value(
            "meta/inexistente"
        ).run()
        at.chat_input[0].set_value("Oi").run()
        assert not at.exception
        assert any("recusou a requisição" in e.value for e in at.error)
        assert at.session_state[estado.CHAVE_CONVERSA].historico == []

    def test_chave_revogada_no_meio_da_sessao_mostra_mensagem_de_chave(self) -> None:
        at = _tela("chat", gateway=False, externos=("openrouter",))
        at.session_state["falsos"]["openrouter"].chave = "outra-chave-que-nao-e-a-da-sessao"
        at.chat_input[0].set_value("Oi").run()
        assert any("chave de API de OpenRouter foi recusada" in e.value for e in at.error)
        assert not any("Token ID" in e.value for e in at.error)
        assert at.session_state[estado.CHAVE_CONVERSA].historico == []

    def test_erro_no_meio_da_resposta_nao_entra_no_historico(self) -> None:
        at = _tela("chat", gateway=False, externos=("nvidia",))
        at.session_state["falsos"]["nvidia"].erro_no_meio = {"code": 502, "message": "caiu"}
        at.chat_input[0].set_value("Oi").run()
        assert not at.exception
        assert any("erro durante a resposta" in e.value for e in at.error)
        assert at.session_state[estado.CHAVE_CONVERSA].historico == []

    def test_resposta_cortada_por_limite_de_tokens_e_avisada(self) -> None:
        at = _tela("chat", gateway=False, externos=("nvidia",))
        at.session_state["falsos"]["nvidia"].motivo_final = "length"
        at.chat_input[0].set_value("Oi").run()
        assert any("cortada pelo limite de tokens" in c.value for c in at.caption)

    def test_conexao_sem_origem_pede_para_conectar(self) -> None:
        at = AppTest.from_function(_pagina_sem_origem, default_timeout=30).run()
        assert any("Conecte-se primeiro" in w.value for w in at.warning)


def _pagina_sem_origem() -> None:
    from itsa_agente.ui import pagina_chat

    pagina_chat.renderizar()


class TestDiagnostico:
    def test_somente_provedor_mostra_aviso_do_gateway_e_a_secao_do_provedor(self) -> None:
        at = _tela("diagnostico", gateway=False, externos=("nvidia",))
        assert not at.exception
        assert any("diagnóstico do gateway não está disponível" in i.value for i in at.info)
        assert any("Provedor externo — NVIDIA" in s.value for s in at.subheader)

    def test_executa_a_bateria_do_provedor_e_oferece_o_relatorio(self) -> None:
        at = _tela("diagnostico", gateway=False, externos=("nvidia",))
        next(b for b in at.button if "diagnóstico de NVIDIA" in b.label).click()
        at = at.run()
        assert not at.exception, at.exception
        relatorio = at.session_state[estado.CHAVE_RELATORIO_EXTERNO]["nvidia"]
        ids = [r.id for r in relatorio.resultados]
        assert ids == [f"P0{i}" for i in range(1, 10)]
        assert relatorio.aprovado
        assert CHAVE_NVIDIA_OK not in _textos(at)

    def test_gateway_e_provedor_aparecem_na_mesma_tela(self) -> None:
        at = _tela("diagnostico", gateway=True, externos=("nvidia", "openrouter"))
        assert not at.exception
        rotulos = [s.value for s in at.subheader]
        assert any("NVIDIA" in r for r in rotulos) and any("OpenRouter" in r for r in rotulos)
        assert any(b.label.replace("▶️ ", "") == "Executar diagnóstico" for b in at.button)


def test_texto_erro_de_provedor_nao_fala_em_token_id() -> None:
    from itsa_agente.gateway.errors import (
        BadRequest,
        CreditoInsuficiente,
        RateLimited,
        ServiceUnavailable,
        Unauthorized,
    )

    assert "chave de API de NVIDIA" in estado.texto_erro(Unauthorized("x", provedor="nvidia"))
    assert "Créditos" in estado.texto_erro(CreditoInsuficiente("x", provedor="openrouter"))
    assert "20s" in estado.texto_erro(RateLimited("x", retry_after=20, provedor="nvidia"))
    assert "NVIDIA está indisponível" in estado.texto_erro(
        ServiceUnavailable("x", provedor="nvidia")
    )
    assert "modelo inexistente" in estado.texto_erro(
        BadRequest("modelo inexistente", provedor="openrouter")
    )
    # sem provedor, o texto do gateway é preservado
    assert "Credenciais inválidas" in estado.texto_erro(Unauthorized("x"))
