"""Testes da camada de provedores externos (NVIDIA, OpenRouter): SSE, erros, cliente, roteador."""

from __future__ import annotations

import json
import logging
import uuid

import httpx
import pytest

from itsa_agente.config import Settings
from itsa_agente.conversation import Conversa
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.errors import (
    BadRequest,
    ConnectionFailed,
    CreditoInsuficiente,
    Forbidden,
    GatewayError,
    LocalValidationError,
    ProtocolError,
    RateLimited,
    RequestTimeout,
    ServerError,
    ServiceUnavailable,
    StreamError,
    StreamInterrupted,
    Unauthorized,
)
from itsa_agente.gateway.models import (
    EventoConcluido,
    EventoDelta,
    EventoErro,
    EventoIniciado,
    EventoRaciocinio,
    Mensagem,
)
from itsa_agente.providers.base import (
    PROVEDOR_NVIDIA,
    OpcoesGeracao,
    qualificar,
    separar,
)
from itsa_agente.providers.erros import erro_de_resposta, extrair_erro_openai
from itsa_agente.providers.fabrica import criar_provedor
from itsa_agente.providers.nvidia import ProvedorNvidia
from itsa_agente.providers.openai_compat import ClienteOpenAICompat
from itsa_agente.providers.openrouter import ProvedorOpenRouter, modelos_de_resposta
from itsa_agente.providers.roteador import Roteador
from itsa_agente.providers.sse import DecodificadorSSE, eventos_de_resposta_unica
from itsa_agente.security import Redator, redator_global
from tests.provedor_falso import CHAVE_NVIDIA_OK, CHAVE_OPENROUTER_OK, ProvedorFalso

MODELO = "nvidia/nemotron-3-ultra-550b-a55b"
PERGUNTA = [Mensagem.usuario("Responda apenas com a palavra OK.")]


@pytest.fixture
def cfg_p() -> Settings:
    return Settings(
        base_url="http://gateway.test",
        nvidia_base_url="http://nvidia.test/v1",
        openrouter_base_url="http://openrouter.test/api/v1",
        openrouter_referer="https://itsa.example",
        max_retries=2,
        retry_backoff_base=0.0,
    )


@pytest.fixture
def nv() -> ProvedorFalso:
    return ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))


@pytest.fixture
def esperas_p() -> list[float]:
    return []


@pytest.fixture
def nvidia(nv: ProvedorFalso, cfg_p: Settings, esperas_p: list[float]) -> ProvedorNvidia:
    cliente = ProvedorNvidia(
        CHAVE_NVIDIA_OK, cfg_p, transporte=httpx.MockTransport(nv), dormir=esperas_p.append
    )
    yield cliente  # type: ignore[misc]
    cliente.fechar()


def tipos(cliente: ClienteOpenAICompat, **kw: object) -> list[str]:
    return [e.tipo for e in cliente.transmitir_chat(modelo=MODELO, mensagens=PERGUNTA, **kw)]  # type: ignore[arg-type]


def texto_de(cliente: ClienteOpenAICompat, mensagens: list[Mensagem] = PERGUNTA) -> str:
    return "".join(
        e.content
        for e in cliente.transmitir_chat(modelo=MODELO, mensagens=mensagens)
        if isinstance(e, EventoDelta)
    )


# ======================================================================== identificadores
class TestIdentificadores:
    def test_qualificar_e_separar_sao_inversos(self) -> None:
        assert qualificar("nvidia", "nvidia/x") == "nvidia::nvidia/x"
        assert separar("nvidia::nvidia/x") == ("nvidia", "nvidia/x")
        assert separar("openrouter::a/b:free") == ("openrouter", "a/b:free")

    def test_modelo_do_gateway_nunca_tem_prefixo(self) -> None:
        assert qualificar("itsa", "iaitsa-geral") == "iaitsa-geral"
        assert separar("iaitsa-geral") == ("itsa", "iaitsa-geral")

    @pytest.mark.parametrize("valor", ["nvidia::", "::x", ""])
    def test_identificador_malformado_cai_no_gateway(self, valor: str) -> None:
        assert separar(valor)[0] == "itsa"


# ============================================================================ decodificador SSE
def _sse(*linhas: str) -> DecodificadorSSE:
    dec = DecodificadorSSE()
    for linha in linhas:
        dec.alimentar(linha)
    return dec


def _alimentar(linhas: list[str]) -> list:  # type: ignore[type-arg]
    dec = DecodificadorSSE()
    eventos: list = []  # type: ignore[type-arg]
    for linha in linhas:
        eventos += dec.alimentar(linha)
        if dec.terminou:
            break
    else:
        eventos += dec.finalizar()
    return eventos


def _d(obj: dict) -> str:  # type: ignore[type-arg]
    return "data: " + json.dumps(obj)


class TestDecodificadorSSE:
    def test_sequencia_normal_com_uso(self) -> None:
        eventos = _alimentar(
            [
                ": OPENROUTER PROCESSING",
                "",
                _d({"id": "c1", "model": "m", "choices": [{"delta": {"content": "Olá "}}]}),
                _d({"choices": [{"delta": {"content": "mundo"}}]}),
                _d({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                _d({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4}}),
                "data: [DONE]",
            ]
        )
        assert [type(e) for e in eventos] == [
            EventoIniciado,
            EventoDelta,
            EventoDelta,
            EventoConcluido,
        ]
        assert eventos[0].request_id == "c1" and eventos[0].model == "m"
        assert "".join(e.content for e in eventos if isinstance(e, EventoDelta)) == "Olá mundo"
        final = eventos[-1]
        assert final.motivo == "stop"
        assert final.usage is not None and final.usage.total == 14

    def test_comentarios_e_campos_sse_sao_ignorados(self) -> None:
        dec = DecodificadorSSE()
        for linha in (": keep-alive", "event: message", "id: 7", "retry: 100", "", "data:"):
            assert dec.alimentar(linha) == []

    def test_raciocinio_nos_dois_nomes_de_campo(self) -> None:
        eventos = _alimentar(
            [
                _d({"choices": [{"delta": {"reasoning_content": "a"}}]}),
                _d({"choices": [{"delta": {"reasoning": "b"}}]}),
                _d({"choices": [{"delta": {"content": "R"}, "finish_reason": "stop"}]}),
                "data: [DONE]",
            ]
        )
        rac = [e.content for e in eventos if isinstance(e, EventoRaciocinio)]
        assert rac == ["a", "b"]
        assert [e.content for e in eventos if isinstance(e, EventoDelta)] == ["R"]

    def test_conteudo_nulo_ou_vazio_nao_gera_delta(self) -> None:
        eventos = _alimentar(
            [
                _d({"choices": [{"delta": {"content": None}}]}),
                _d({"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}]}),
                "data: [DONE]",
            ]
        )
        assert not any(isinstance(e, EventoDelta) for e in eventos)

    def test_erro_no_meio_do_stream_e_terminal(self) -> None:
        dec = DecodificadorSSE()
        dec.alimentar(_d({"choices": [{"delta": {"content": "ok"}}]}))
        eventos = dec.alimentar(
            _d({"error": {"code": 502, "message": "Provider disconnected"}, "choices": []})
        )
        assert isinstance(eventos[0], EventoErro)
        assert eventos[0].codigo == "502" and "disconnected" in (eventos[0].mensagem or "")
        assert dec.terminou
        assert dec.alimentar(_d({"choices": [{"delta": {"content": "tarde"}}]})) == []

    def test_finish_reason_error_vira_evento_de_erro(self) -> None:
        eventos = _alimentar([_d({"choices": [{"delta": {}, "finish_reason": "error"}]})])
        assert isinstance(eventos[-1], EventoErro)

    def test_motivo_length_e_informado(self) -> None:
        eventos = _alimentar(
            [
                _d({"choices": [{"delta": {"content": "x"}, "finish_reason": "length"}]}),
                "data: [DONE]",
            ]
        )
        assert eventos[-1].motivo == "length"

    def test_fim_sem_finish_reason_nem_done_e_interrupcao(self) -> None:
        with pytest.raises(StreamInterrupted):
            _alimentar([_d({"choices": [{"delta": {"content": "x"}}]})])

    def test_fim_limpo_apos_finish_reason_sem_done_conclui(self) -> None:
        eventos = _alimentar(
            [_d({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]})]
        )
        assert isinstance(eventos[-1], EventoConcluido)

    def test_json_invalido_e_erro_de_protocolo(self) -> None:
        with pytest.raises(ProtocolError):
            DecodificadorSSE().alimentar("data: {nao-e-json")
        with pytest.raises(ProtocolError):
            DecodificadorSSE().alimentar("data: [1, 2]")

    def test_done_sozinho_conclui_sem_texto(self) -> None:
        eventos = _alimentar(["data: [DONE]"])
        assert [type(e) for e in eventos] == [EventoConcluido]

    def test_uso_com_valores_invalidos_vira_zero(self) -> None:
        eventos = _alimentar(
            [
                _d({"choices": [], "usage": {"prompt_tokens": "x", "completion_tokens": None}}),
                "data: [DONE]",
            ]
        )
        assert eventos[-1].usage is not None and eventos[-1].usage.total == 0

    def test_resposta_unica_sem_streaming(self) -> None:
        eventos = eventos_de_resposta_unica(
            {
                "id": "u1",
                "model": "m",
                "choices": [
                    {
                        "message": {"content": "Oi", "reasoning_content": "pensei"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }
        )
        assert [type(e) for e in eventos] == [
            EventoIniciado,
            EventoRaciocinio,
            EventoDelta,
            EventoConcluido,
        ]

    def test_resposta_unica_com_erro_e_malformada(self) -> None:
        assert isinstance(eventos_de_resposta_unica({"error": {"message": "x"}})[0], EventoErro)
        with pytest.raises(ProtocolError):
            eventos_de_resposta_unica({"foo": 1})


# ========================================================================== erros do provedor
class TestErros:
    @pytest.mark.parametrize(
        ("corpo", "codigo", "trecho"),
        [
            ('{"error":{"message":"Invalid API key","code":401}}', "401", "Invalid"),
            (
                '{"error":{"message":"m","type":"invalid_request_error"}}',
                "invalid_request_error",
                "m",
            ),
            ('{"error":"texto simples"}', None, "texto simples"),
            ('{"detail":"Authentication failed"}', None, "Authentication"),
            ('{"title":"Unauthorized","status":401}', None, "Unauthorized"),
            ("Unauthorized", None, "Unauthorized"),
            ("", None, "Chave de API"),
        ],
    )
    def test_formatos_de_corpo(self, corpo: str, codigo: str | None, trecho: str) -> None:
        c, mensagem = extrair_erro_openai(401, corpo)
        assert c == codigo and trecho in mensagem

    def test_mensagem_longa_e_truncada_e_redigida(self) -> None:
        redator_global().registrar("segredo-que-nao-pode-vazar")
        corpo = json.dumps({"error": {"message": "x " * 400 + " segredo-que-nao-pode-vazar"}})
        _, mensagem = extrair_erro_openai(400, corpo)
        assert len(mensagem) <= 300
        corpo2 = json.dumps({"error": {"message": "falhou com segredo-que-nao-pode-vazar ok"}})
        assert "segredo-que-nao-pode-vazar" not in extrair_erro_openai(400, corpo2)[1]

    @pytest.mark.parametrize(
        ("status", "classe"),
        [
            (400, BadRequest),
            (404, BadRequest),
            (422, BadRequest),
            (401, Unauthorized),
            (402, CreditoInsuficiente),
            (403, Forbidden),
            (408, RequestTimeout),
            (429, RateLimited),
            (502, ServiceUnavailable),
            (503, ServiceUnavailable),
            (504, ServiceUnavailable),
            (500, ServerError),
        ],
    )
    def test_mapeamento_de_status(self, status: int, classe: type[GatewayError]) -> None:
        exc = erro_de_resposta(httpx.Response(status, json={"error": {"message": "m"}}), "nvidia")
        assert type(exc) is classe
        assert exc.status == status and exc.provedor == "nvidia"

    def test_retry_after_e_exposto_no_429(self) -> None:
        exc = erro_de_resposta(httpx.Response(429, headers={"Retry-After": "7"}), "openrouter")
        assert isinstance(exc, RateLimited) and exc.retry_after == 7.0


# =========================================================================== cliente (NVIDIA)
class TestClienteNvidia:
    def test_chat_com_streaming_e_cabecalhos(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        assert tipos(nvidia) == ["started", "delta", "delta", "completed"]
        req = nv.chamadas[0]
        assert req.url.path == "/v1/chat/completions"
        assert req.headers["authorization"] == f"Bearer {CHAVE_NVIDIA_OK}"
        assert req.headers["user-agent"].startswith("ITSA-Agente/")
        corpo = nv.corpos_chat[0]
        assert corpo["stream"] is True and corpo["model"] == MODELO
        assert corpo["max_tokens"] == 8192
        assert corpo["stream_options"] == {"include_usage": True}
        assert corpo["messages"] == [
            {"role": "user", "content": "Responda apenas com a palavra OK."}
        ]

    def test_texto_completo_e_uso(self, nvidia: ProvedorNvidia) -> None:
        eventos = list(nvidia.transmitir_chat(modelo=MODELO, mensagens=PERGUNTA))
        assert "".join(e.content for e in eventos if isinstance(e, EventoDelta)) == "OK"
        final = eventos[-1]
        assert isinstance(final, EventoConcluido) and final.usage is not None
        assert final.motivo == "stop"

    def test_raciocinio_desligado_por_padrao_no_nemotron(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        tipos(nvidia)
        assert nv.corpos_chat[0]["chat_template_kwargs"] == {
            "enable_thinking": False,
            "force_nonempty_content": True,
        }

    def test_raciocinio_ligado_chega_separado(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        eventos = list(
            nvidia.transmitir_chat(
                modelo=MODELO,
                mensagens=[Mensagem.usuario("Quanto é 17 × 23?")],
                opcoes=OpcoesGeracao(raciocinio=True),
            )
        )
        assert nv.corpos_chat[0]["chat_template_kwargs"] == {"enable_thinking": True}
        assert any(isinstance(e, EventoRaciocinio) for e in eventos)
        assert "391" in "".join(e.content for e in eventos if isinstance(e, EventoDelta))

    def test_outros_modelos_nao_recebem_chat_template_kwargs(
        self, cfg_p: Settings, esperas_p: list[float]
    ) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, ("meta/llama-3.3-70b-instruct",))
        with ProvedorNvidia(
            CHAVE_NVIDIA_OK, cfg_p, transporte=httpx.MockTransport(falso), dormir=esperas_p.append
        ) as c:
            list(c.transmitir_chat(modelo="meta/llama-3.3-70b-instruct", mensagens=PERGUNTA))
        assert "chat_template_kwargs" not in falso.corpos_chat[0]

    def test_opcoes_de_geracao_vao_no_corpo(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        list(
            nvidia.transmitir_chat(
                modelo=MODELO,
                mensagens=PERGUNTA,
                opcoes=OpcoesGeracao(temperatura=0.2, max_tokens=300),
            )
        )
        assert nv.corpos_chat[0]["temperature"] == 0.2 and nv.corpos_chat[0]["max_tokens"] == 300

    def test_catalogo_vem_da_configuracao(self, cfg_p: Settings) -> None:
        cfg = cfg_p.com(nvidia_models=(MODELO, "meta/llama-3.3-70b-instruct"))
        with ProvedorNvidia(
            CHAVE_NVIDIA_OK, cfg, transporte=httpx.MockTransport(ProvedorFalso())
        ) as c:
            modelos = c.listar_modelos()
        assert [m.id for m in modelos] == [
            f"nvidia::{MODELO}",
            "nvidia::meta/llama-3.3-70b-instruct",
        ]
        assert all(m.externo and m.provedor == PROVEDOR_NVIDIA for m in modelos)
        assert modelos[0].rotulo.startswith("Nemotron 3 Ultra")

    def test_ultima_mensagem_deve_ser_do_usuario(self, nvidia: ProvedorNvidia) -> None:
        with pytest.raises(LocalValidationError):
            nvidia.transmitir_chat(modelo=MODELO, mensagens=[Mensagem.assistente("oi")])

    def test_conversa_id_e_aceito_e_ignorado(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        tipos(nvidia, conversa_id=uuid.uuid4())
        assert "conversationId" not in nv.corpos_chat[0]


# ========================================================================= retentativa e erros
class TestResiliencia:
    def test_503_transitorio_e_repetido(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso, esperas_p: list[float]
    ) -> None:
        nv.indisponivel_n = 2
        assert texto_de(nvidia) == "OK"
        assert len(esperas_p) == 2

    def test_503_persistente_vira_servico_indisponivel(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.indisponivel_n = 10
        with pytest.raises(ServiceUnavailable) as e:
            texto_de(nvidia)
        assert e.value.provedor == "nvidia"
        assert len(nv.chamadas) == 3  # 1 + max_retries

    def test_429_nao_e_repetido_e_informa_a_espera(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.status_forcado, nv.retry_after = 429, "12"
        with pytest.raises(RateLimited) as e:
            texto_de(nvidia)
        assert e.value.retry_after == 12.0 and len(nv.chamadas) == 1

    def test_falha_de_conexao_e_repetida_e_depois_tipada(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso, esperas_p: list[float]
    ) -> None:
        nv.erro_conexao_n = 1
        assert texto_de(nvidia) == "OK"
        nv.erro_conexao_n = 99
        with pytest.raises(ConnectionFailed) as e:
            texto_de(nvidia)
        assert e.value.provedor == "nvidia"

    def test_chave_recusada_e_401_tipado(self, cfg_p: Settings, nv: ProvedorFalso) -> None:
        with (
            ProvedorNvidia(
                "nvapi-OUTRA-CHAVE-QUALQUER", cfg_p, transporte=httpx.MockTransport(nv)
            ) as c,
            pytest.raises(Unauthorized) as e,
        ):
            texto_de(c)
        assert e.value.status == 401 and e.value.provedor == "nvidia"

    def test_modelo_inexistente_e_bad_request(self, nvidia: ProvedorNvidia) -> None:
        with pytest.raises(BadRequest):
            list(nvidia.transmitir_chat(modelo="nao/existe", mensagens=PERGUNTA))

    def test_creditos_esgotados(self, nvidia: ProvedorNvidia, nv: ProvedorFalso) -> None:
        nv.status_forcado = 402
        with pytest.raises(CreditoInsuficiente):
            texto_de(nvidia)

    def test_sem_stream_options_repete_uma_vez_sem_o_campo(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.rejeita_stream_options = True
        assert texto_de(nvidia) == "OK"
        assert len(nv.chamadas) == 2
        assert "stream_options" in nv.corpos_chat[0]
        assert "stream_options" not in nv.corpos_chat[1]

    def test_queda_no_meio_do_stream_e_interrupcao(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.queda_no_meio = True
        with pytest.raises(StreamInterrupted):
            texto_de(nvidia)

    def test_fim_sem_conclusao_e_interrupcao(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.cortar_sem_finish = True
        with pytest.raises(StreamInterrupted):
            texto_de(nvidia)

    def test_fim_limpo_apos_finish_reason_conclui(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.cortar_com_finish_sem_done = True
        assert tipos(nvidia)[-1] == "completed"

    def test_erro_no_meio_chega_como_evento(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.erro_no_meio = {"code": 502, "message": "Provider disconnected"}
        eventos = list(nvidia.transmitir_chat(modelo=MODELO, mensagens=[Mensagem.usuario("Oi")]))
        assert isinstance(eventos[-1], EventoErro) and eventos[-1].codigo == "502"

    def test_resposta_json_sem_streaming_tambem_funciona(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.json_unico = True
        assert tipos(nvidia) == ["started", "delta", "completed"]

    def test_timeout_de_leitura_e_tipado(self, cfg_p: Settings) -> None:
        def h(req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("silêncio", request=req)

        with (
            ProvedorNvidia(CHAVE_NVIDIA_OK, cfg_p, transporte=httpx.MockTransport(h)) as c,
            pytest.raises(RequestTimeout) as e,
        ):
            texto_de(c)
        assert e.value.provedor == "nvidia"

    def test_verificar_aceita_e_recusa(self, cfg_p: Settings, nv: ProvedorFalso) -> None:
        with ProvedorNvidia(CHAVE_NVIDIA_OK, cfg_p, transporte=httpx.MockTransport(nv)) as ok:
            ok.verificar()
        with (
            ProvedorNvidia(
                "nvapi-OUTRA-CHAVE-QUALQUER", cfg_p, transporte=httpx.MockTransport(nv)
            ) as ruim,
            pytest.raises(Unauthorized),
        ):
            ruim.verificar()


# ================================================================================== chaves
class TestChaves:
    @pytest.mark.parametrize(
        "chave", ["", "   ", "nvapi-com espaço", "nvapi-\nquebra", "nvapi-ação"]
    )
    def test_chave_invalida_e_recusada_localmente(self, cfg_p: Settings, chave: str) -> None:
        with pytest.raises(LocalValidationError):
            ProvedorNvidia(chave, cfg_p)

    def test_chave_nao_aparece_no_repr(self, nvidia: ProvedorNvidia) -> None:
        assert CHAVE_NVIDIA_OK not in repr(nvidia) and CHAVE_NVIDIA_OK not in str(
            vars(nvidia).keys()
        )

    def test_chave_fica_registrada_no_redator(self, nvidia: ProvedorNvidia) -> None:
        assert CHAVE_NVIDIA_OK not in redator_global().aplicar(f"falha com {CHAVE_NVIDIA_OK}")

    def test_chave_nao_vai_para_nenhum_log(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso, caplog: pytest.LogCaptureFixture
    ) -> None:
        from itsa_agente.security import FiltroRedacao

        caplog.set_level(logging.DEBUG, logger="itsa_agente")
        nv.indisponivel_n = 1
        texto_de(nvidia)
        filtro = FiltroRedacao(redator_global())
        for registro in caplog.records:
            filtro.filter(registro)
            assert CHAVE_NVIDIA_OK not in registro.getMessage()

    @pytest.mark.parametrize(
        "texto",
        ["nvapi-AbCdEf1234567890xyz", "sk-or-v1-0123456789abcdefABCDEF", "sk-or-abcdefgh12345"],
    )
    def test_redator_mascara_padroes_de_chave_mesmo_sem_registro(self, texto: str) -> None:
        saida = Redator().aplicar(f"erro com a chave {texto} no cabeçalho")
        assert texto not in saida and "***" in saida


# ================================================================================ OpenRouter
CATALOGO_OR = {
    "data": [
        {
            "id": "vendor/pago",
            "name": "Vendor: Pago",
            "context_length": 128000,
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "name": "NVIDIA: Nemotron 3 Ultra (free)",
            "context_length": 1000000,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "vendor/imagem",
            "name": "Gera Imagem",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"output_modalities": ["image"]},
        },
        {"id": "vendor/sem-preco", "name": "Sem Preço"},
        {"name": "sem id"},
    ]
}


@pytest.fixture
def orf() -> ProvedorFalso:
    f = ProvedorFalso(CHAVE_OPENROUTER_OK, ("nvidia/nemotron-3-ultra-550b-a55b:free",))
    f.catalogo = CATALOGO_OR
    return f


@pytest.fixture
def openrouter(orf: ProvedorFalso, cfg_p: Settings, esperas_p: list[float]) -> ProvedorOpenRouter:
    cliente = ProvedorOpenRouter(
        CHAVE_OPENROUTER_OK, cfg_p, transporte=httpx.MockTransport(orf), dormir=esperas_p.append
    )
    yield cliente  # type: ignore[misc]
    cliente.fechar()


class TestOpenRouter:
    def test_cabecalhos_de_identificacao_do_app(
        self, openrouter: ProvedorOpenRouter, orf: ProvedorFalso
    ) -> None:
        openrouter.listar_modelos()
        req = orf.chamadas[0]
        assert req.url.path == "/api/v1/models"
        assert req.headers["x-title"] == "ITSA-Agente"
        assert req.headers["http-referer"] == "https://itsa.example"

    def test_catalogo_filtra_ordena_e_marca_gratuitos(self, openrouter: ProvedorOpenRouter) -> None:
        modelos = openrouter.listar_modelos()
        ids = [m.id for m in modelos]
        assert ids[0] == "openrouter::nvidia/nemotron-3-ultra-550b-a55b:free"  # gratuito primeiro
        assert "openrouter::vendor/imagem" not in ids  # não gera texto
        por_id = {m.id: m for m in modelos}
        assert por_id["openrouter::vendor/pago"].gratuito is False
        assert por_id["openrouter::vendor/pago"].contexto == 128000
        assert por_id["openrouter::vendor/sem-preco"].gratuito is None
        assert len(modelos) == 3

    def test_catalogo_e_cacheado_e_pode_ser_forcado(
        self, openrouter: ProvedorOpenRouter, orf: ProvedorFalso
    ) -> None:
        openrouter.listar_modelos()
        openrouter.listar_modelos()
        assert len(orf.chamadas) == 1
        openrouter.listar_modelos(forcar=True)
        assert len(orf.chamadas) == 2

    def test_catalogo_fora_do_formato(self) -> None:
        with pytest.raises(ProtocolError):
            modelos_de_resposta({"foo": []})

    def test_raciocinio_so_e_enviado_quando_escolhido(
        self, openrouter: ProvedorOpenRouter, orf: ProvedorFalso
    ) -> None:
        modelo = "nvidia/nemotron-3-ultra-550b-a55b:free"
        list(openrouter.transmitir_chat(modelo=modelo, mensagens=PERGUNTA))
        assert "reasoning" not in orf.corpos_chat[0]
        list(
            openrouter.transmitir_chat(
                modelo=modelo, mensagens=PERGUNTA, opcoes=OpcoesGeracao(raciocinio=True)
            )
        )
        assert orf.corpos_chat[1]["reasoning"] == {"enabled": True}
        list(
            openrouter.transmitir_chat(
                modelo=modelo, mensagens=PERGUNTA, opcoes=OpcoesGeracao(raciocinio=False)
            )
        )
        assert orf.corpos_chat[2]["reasoning"] == {"enabled": False}

    def test_data_collection_deny_e_opcional(self, cfg_p: Settings, orf: ProvedorFalso) -> None:
        modelo = "nvidia/nemotron-3-ultra-550b-a55b:free"
        with ProvedorOpenRouter(
            CHAVE_OPENROUTER_OK,
            cfg_p.com(openrouter_data_collection="deny"),
            transporte=httpx.MockTransport(orf),
        ) as c:
            list(c.transmitir_chat(modelo=modelo, mensagens=PERGUNTA))
        assert orf.corpos_chat[0]["provider"] == {"data_collection": "deny"}

    def test_erro_de_modelo_e_creditos(
        self, openrouter: ProvedorOpenRouter, orf: ProvedorFalso
    ) -> None:
        orf.status_forcado = 402
        with pytest.raises(CreditoInsuficiente) as e:
            list(openrouter.transmitir_chat(modelo="x", mensagens=PERGUNTA))
        assert e.value.provedor == "openrouter"


class TestVerificacaoDaChave:
    """GET /models é público (NVIDIA e OpenRouter): a chave precisa ser provada de outro modo."""

    def test_nvidia_recusa_chave_errada_mesmo_com_models_publico(
        self, cfg_p: Settings, nv: ProvedorFalso
    ) -> None:
        assert nv.exige_chave_em_models is False
        with (
            ProvedorNvidia(
                "nvapi-OUTRA-CHAVE-QUALQUER", cfg_p, transporte=httpx.MockTransport(nv)
            ) as c,
            pytest.raises(Unauthorized),
        ):
            c.verificar()
        assert nv.chamadas[-1].url.path == "/v1/chat/completions"
        corpo = json.loads(nv.chamadas[-1].content)
        assert corpo["max_tokens"] == 1 and corpo["stream"] is False

    @pytest.mark.parametrize("status", [400, 404, 422, 429])
    def test_nvidia_aceita_quando_a_chave_foi_reconhecida(
        self, cfg_p: Settings, nv: ProvedorFalso, status: int
    ) -> None:
        nv.status_forcado = status
        with ProvedorNvidia(CHAVE_NVIDIA_OK, cfg_p, transporte=httpx.MockTransport(nv)) as c:
            c.verificar()  # não levanta

    @pytest.mark.parametrize("status", [401, 403, 500])
    def test_nvidia_recusa_auth_e_falha_de_servidor(
        self, cfg_p: Settings, nv: ProvedorFalso, status: int
    ) -> None:
        nv.status_forcado = status
        with (
            ProvedorNvidia(CHAVE_NVIDIA_OK, cfg_p, transporte=httpx.MockTransport(nv)) as c,
            pytest.raises(GatewayError),
        ):
            c.verificar()

    def test_openrouter_usa_get_key_e_guarda_os_dados_da_conta(
        self, openrouter: ProvedorOpenRouter, orf: ProvedorFalso
    ) -> None:
        openrouter.verificar()
        assert orf.chamadas[0].url.path == "/api/v1/key"
        info = openrouter.info_chave
        assert info is not None
        assert (info.gratuitos_usados, info.gratuitos_limite) == (3, 50)
        assert info.creditos_restantes is None
        assert info.rotulo is None  # o rótulo padrão é um fragmento da chave: descartado

    def test_openrouter_recusa_chave_errada_em_get_key(
        self, cfg_p: Settings, orf: ProvedorFalso
    ) -> None:
        with (
            ProvedorOpenRouter(
                "sk-or-v1-OUTRA-CHAVE-QUALQUER", cfg_p, transporte=httpx.MockTransport(orf)
            ) as c,
            pytest.raises(Unauthorized),
        ):
            c.verificar()

    def test_get_key_fora_do_formato(self, cfg_p: Settings) -> None:
        def h(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"foo": 1})

        with (
            ProvedorOpenRouter(CHAVE_OPENROUTER_OK, cfg_p, transporte=httpx.MockTransport(h)) as c,
            pytest.raises(ProtocolError),
        ):
            c.verificar()


# ================================================================================== fábrica
def test_fabrica_cria_o_cliente_certo(cfg_p: Settings) -> None:
    assert isinstance(criar_provedor("nvidia", CHAVE_NVIDIA_OK, cfg_p), ProvedorNvidia)
    assert isinstance(criar_provedor("openrouter", CHAVE_OPENROUTER_OK, cfg_p), ProvedorOpenRouter)
    with pytest.raises(LocalValidationError):
        criar_provedor("desconhecido", "x", cfg_p)


# ================================================================================== roteador
class TestRoteador:
    def test_sem_origens_nao_esta_ativo(self) -> None:
        assert not Roteador().ativo

    def test_catalogo_unificado_mantem_ids_do_gateway_sem_prefixo(
        self, cliente: ClienteGateway, nvidia: ProvedorNvidia
    ) -> None:
        rot = Roteador(cliente, {"nvidia": nvidia})
        cat = rot.catalogo()
        assert [m.id for m in cat.modelos] == ["iaitsa-geral", f"nvidia::{MODELO}"]
        assert cat.provedores == ["itsa", "nvidia"]
        assert rot.provedores_ativos == ["itsa", "nvidia"]
        assert [m.externo for m in cat.modelos] == [False, True]

    def test_falha_de_uma_origem_nao_derruba_as_outras(
        self, cliente: ClienteGateway, openrouter: ProvedorOpenRouter, orf: ProvedorFalso
    ) -> None:
        orf.status_forcado = 500
        cat = Roteador(cliente, {"openrouter": openrouter}).catalogo()
        assert [m.id for m in cat.modelos] == ["iaitsa-geral"]
        assert isinstance(cat.falhas["openrouter"], ServerError)

    def test_roteia_para_o_gateway_pelo_id_sem_prefixo(
        self, cliente: ClienteGateway, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        rot = Roteador(cliente, {"nvidia": nvidia})
        eventos = list(rot.transmitir_chat(modelo="iaitsa-geral", mensagens=PERGUNTA))
        assert isinstance(eventos[-1], EventoConcluido)
        assert nv.chamadas == []  # nada foi para a NVIDIA

    def test_roteia_para_o_externo_pelo_prefixo_com_opcoes(
        self, cliente: ClienteGateway, nvidia: ProvedorNvidia, nv: ProvedorFalso, gw
    ) -> None:  # type: ignore[no-untyped-def]
        rot = Roteador(cliente, {"nvidia": nvidia}, OpcoesGeracao(raciocinio=True))
        list(rot.transmitir_chat(modelo=f"nvidia::{MODELO}", mensagens=PERGUNTA))
        assert nv.corpos_chat[0]["chat_template_kwargs"] == {"enable_thinking": True}
        assert gw.contar("POST", "/api/chat") == 0

    def test_sem_conexao_com_a_origem_do_modelo(self, nvidia: ProvedorNvidia) -> None:
        with pytest.raises(LocalValidationError, match="gateway"):
            Roteador(None, {"nvidia": nvidia}).transmitir_chat(
                modelo="iaitsa-geral", mensagens=PERGUNTA
            )
        with pytest.raises(LocalValidationError, match="OpenRouter"):
            Roteador(None, {"nvidia": nvidia}).transmitir_chat(
                modelo="openrouter::x", mensagens=PERGUNTA
            )

    def test_fechar_externos(self, nvidia: ProvedorNvidia) -> None:
        rot = Roteador(None, {"nvidia": nvidia})
        rot.fechar_externos()
        assert rot.externos == {} and not rot.ativo


# ====================================================================== conversa + raciocínio
class TestConversaComProvedor:
    def _conversa(self, nvidia: ProvedorNvidia, **kw: object) -> tuple[Conversa, Roteador]:
        return Conversa(), Roteador(None, {"nvidia": nvidia}, OpcoesGeracao(**kw))  # type: ignore[arg-type]

    def test_raciocinio_e_motivo_ficam_na_conversa(self, nvidia: ProvedorNvidia) -> None:
        conversa, rot = self._conversa(nvidia, raciocinio=True)
        texto = "".join(
            conversa.perguntar(rot, modelo=f"nvidia::{MODELO}", pergunta="Quanto é 17 × 23?")
        )
        assert "391" in texto
        assert conversa.ultimo_raciocinio and "340" in conversa.ultimo_raciocinio
        assert conversa.ultimo_motivo == "stop"
        assert conversa.ultimo_uso is not None
        assert len(conversa.historico) == 2

    def test_raciocinio_nao_vaza_para_o_historico(self, nvidia: ProvedorNvidia) -> None:
        conversa, rot = self._conversa(nvidia, raciocinio=True)
        list(conversa.perguntar(rot, modelo=f"nvidia::{MODELO}", pergunta="Quanto é 17 × 23?"))
        assert all("Pensando" not in m.content for m in conversa.historico)

    def test_erro_no_meio_nao_entra_no_historico(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.erro_no_meio = {"code": 502, "message": "Provider disconnected"}
        conversa, rot = self._conversa(nvidia)
        with pytest.raises(StreamError):
            list(conversa.perguntar(rot, modelo=f"nvidia::{MODELO}", pergunta="Oi"))
        assert conversa.historico == []

    def test_queda_nao_entra_no_historico(self, nvidia: ProvedorNvidia, nv: ProvedorFalso) -> None:
        nv.queda_no_meio = True
        conversa, rot = self._conversa(nvidia)
        with pytest.raises(StreamInterrupted):
            list(conversa.perguntar(rot, modelo=f"nvidia::{MODELO}", pergunta="Oi"))
        assert conversa.historico == []

    def test_resposta_cortada_por_limite_e_sinalizada(
        self, nvidia: ProvedorNvidia, nv: ProvedorFalso
    ) -> None:
        nv.motivo_final = "length"
        conversa, rot = self._conversa(nvidia)
        list(conversa.perguntar(rot, modelo=f"nvidia::{MODELO}", pergunta="Oi"))
        assert conversa.ultimo_motivo == "length" and len(conversa.historico) == 2

    def test_reiniciar_limpa_raciocinio_e_motivo(self, nvidia: ProvedorNvidia) -> None:
        conversa, rot = self._conversa(nvidia, raciocinio=True)
        list(conversa.perguntar(rot, modelo=f"nvidia::{MODELO}", pergunta="Quanto é 17 × 23?"))
        conversa.reiniciar()
        assert conversa.ultimo_raciocinio is None and conversa.ultimo_motivo is None


# ================================================================================ configuração
class TestConfiguracao:
    def test_padroes_dos_provedores(self) -> None:
        cfg = Settings.from_env({})
        assert cfg.nvidia_base_url == "https://integrate.api.nvidia.com/v1"
        assert cfg.openrouter_base_url == "https://openrouter.ai/api/v1"
        assert cfg.nvidia_models == ("nvidia/nemotron-3-ultra-550b-a55b",)
        assert cfg.openrouter_data_collection is None and cfg.provider_max_tokens == 8192

    def test_sobrescrita_por_ambiente(self) -> None:
        cfg = Settings.from_env(
            {
                "ITSA_NVIDIA_BASE_URL": "https://nim.interno/v1/",
                "ITSA_NVIDIA_MODELS": "a/b; c/d ,e/f",
                "ITSA_OPENROUTER_DATA_COLLECTION": "DENY",
                "ITSA_OPENROUTER_REFERER": "https://itsa.com.br",
                "ITSA_PROVIDER_MAX_TOKENS": "2048",
            }
        )
        assert cfg.nvidia_base_url == "https://nim.interno/v1"
        assert cfg.nvidia_models == ("a/b", "c/d", "e/f")
        assert cfg.openrouter_data_collection == "deny"
        assert cfg.openrouter_referer == "https://itsa.com.br" and cfg.provider_max_tokens == 2048

    @pytest.mark.parametrize(
        "ambiente",
        [
            {"ITSA_NVIDIA_BASE_URL": "ftp://x"},
            {"ITSA_OPENROUTER_BASE_URL": "nao-e-url"},
            {"ITSA_OPENROUTER_DATA_COLLECTION": "talvez"},
            {"ITSA_PROVIDER_MAX_TOKENS": "3"},
        ],
    )
    def test_valores_invalidos(self, ambiente: dict[str, str]) -> None:
        with pytest.raises(GatewayError):
            Settings.from_env(ambiente)
