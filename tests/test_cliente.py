from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

import httpx
import pytest

from itsa_agente.config import Settings
from itsa_agente.gateway.client import ClienteGateway, erro_de_resposta, extrair_erro_api
from itsa_agente.gateway.errors import (
    BadRequest,
    ConnectionFailed,
    Forbidden,
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
    Credenciais,
    EventoConcluido,
    EventoDelta,
    EventoIniciado,
    Mensagem,
)
from itsa_agente.security import configurar_logging
from tests.conftest import Relogio
from tests.gateway_falso import CPF_CNPJ_OK, TOKEN_ID_OK, USUARIO_OK, GatewayFalso

Fabrica = Callable[..., ClienteGateway]
U = Mensagem.usuario


# ============================================================================ autenticação
class TestAutenticacao:
    def test_emite_token_e_informa_validade(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        info = cliente.autenticar()
        assert info.validade_total_s == 900
        assert info.expira_em_s == pytest.approx(900)
        assert cliente.autenticado
        assert gw.contar("POST", "/api/auth/token") == 1

    def test_token_e_reaproveitado_entre_chamadas(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        cliente.listar_modelos(forcar=True)
        cliente.listar_modelos(forcar=True)
        assert gw.contar("POST", "/api/auth/token") == 1

    def test_renova_antes_de_vencer(
        self, cliente: ClienteGateway, gw: GatewayFalso, relogio: Relogio
    ) -> None:
        cliente.listar_modelos(forcar=True)
        relogio.avancar(900 - 61)  # ainda fora da margem de 60 s
        cliente.listar_modelos(forcar=True)
        assert gw.contar("POST", "/api/auth/token") == 1
        relogio.avancar(2)  # entrou na margem de segurança
        cliente.listar_modelos(forcar=True)
        assert gw.contar("POST", "/api/auth/token") == 2

    def test_credencial_invalida_vira_unauthorized(self, criar_cliente: Fabrica) -> None:
        ruim = Credenciais(CPF_CNPJ_OK, "TOKEN-ERRADO", USUARIO_OK)
        with pytest.raises(Unauthorized) as info:
            criar_cliente(credenciais=ruim).autenticar()
        assert info.value.codigo == "credenciais_invalidas"
        assert info.value.status == 401
        assert "TOKEN-ERRADO" not in str(info.value)

    def test_429_no_token_expõe_retry_after_e_nao_repete(
        self, cliente: ClienteGateway, gw: GatewayFalso, esperas: list[float]
    ) -> None:
        gw.token_429 = True
        with pytest.raises(RateLimited) as info:
            cliente.autenticar()
        assert info.value.retry_after == 7
        assert gw.contar("POST", "/api/auth/token") == 1
        assert esperas == []

    def test_resposta_de_token_fora_do_contrato(
        self, criar_cliente: Fabrica, cfg: Settings, credenciais: Credenciais
    ) -> None:
        c = ClienteGateway(
            credenciais,
            cfg,
            transporte=httpx.MockTransport(lambda r: httpx.Response(200, json={"foo": "bar"})),
        )
        with pytest.raises(ProtocolError):
            c.autenticar()
        c.fechar()

    def test_token_id_nao_vai_para_nenhum_log(
        self, cliente: ClienteGateway, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="itsa_agente"):
            cliente.autenticar()
            cliente.listar_modelos(forcar=True)
        assert TOKEN_ID_OK not in caplog.text
        assert "eyJhbGci" not in caplog.text

    def test_fechar_descarta_o_token(self, cliente: ClienteGateway) -> None:
        cliente.autenticar()
        cliente.fechar()
        assert not cliente.autenticado


# ============================================================================== modelos
class TestModelos:
    def test_lista_modelos(self, cliente: ClienteGateway) -> None:
        modelos = cliente.listar_modelos()
        assert [(m.id, m.display_name) for m in modelos] == [("iaitsa-geral", "IAitsa Geral")]

    def test_lista_vazia_e_valida(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        gw.modelos = []
        assert cliente.listar_modelos() == []

    def test_cache_e_forcar(
        self, cliente: ClienteGateway, gw: GatewayFalso, relogio: Relogio
    ) -> None:
        cliente.listar_modelos()
        cliente.listar_modelos()
        assert gw.contar("GET", "/api/models") == 1
        cliente.listar_modelos(forcar=True)
        assert gw.contar("GET", "/api/models") == 2
        relogio.avancar(61)  # cache de 60 s expirou
        cliente.listar_modelos()
        assert gw.contar("GET", "/api/models") == 3

    def test_401_reemite_token_e_repete_uma_vez(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        cliente.autenticar()
        gw.revogar_tokens()  # o servidor "esqueceu" o token (ex.: reinício/rotação de chave)
        assert cliente.listar_modelos(forcar=True)
        assert gw.contar("POST", "/api/auth/token") == 2

    def test_401_persistente_nao_entra_em_laco(
        self, criar_cliente: Fabrica, gw: GatewayFalso, cfg: Settings, credenciais: Credenciais
    ) -> None:
        class Sempre401(GatewayFalso):
            def _autenticado(self, req: httpx.Request) -> bool:
                return False

        falso = Sempre401()
        c = ClienteGateway(
            credenciais, cfg, transporte=httpx.MockTransport(falso), dormir=lambda s: None
        )
        with pytest.raises(Unauthorized):
            c.listar_modelos()
        assert falso.contar("POST", "/api/auth/token") == 2
        assert falso.contar("GET", "/api/models") == 2
        c.fechar()

    def test_corpo_fora_do_contrato(self, credenciais: Credenciais, cfg: Settings) -> None:
        def h(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/api/auth/token":
                return httpx.Response(200, json={"accessToken": "t", "expiresIn": 900})
            return httpx.Response(200, json={"models": [{"semId": 1}]})

        c = ClienteGateway(
            credenciais, cfg, transporte=httpx.MockTransport(h), dormir=lambda s: None
        )
        with pytest.raises(ProtocolError):
            c.listar_modelos()
        c.fechar()


# ================================================================== retentativas e erros
class TestResiliencia:
    def test_503_e_repetido_com_backoff_e_depois_funciona(
        self, cliente: ClienteGateway, gw: GatewayFalso, esperas: list[float]
    ) -> None:
        gw.indisponivel_n = 2
        assert cliente.listar_modelos()
        assert gw.contar("GET", "/api/models") == 3
        assert len(esperas) == 2

    def test_503_persistente_vira_service_unavailable(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        gw.indisponivel_n = 99
        with pytest.raises(ServiceUnavailable) as info:
            cliente.listar_modelos()
        assert info.value.status == 503
        assert gw.contar("GET", "/api/models") == 3  # 1 + 2 retentativas

    def test_falha_de_conexao_e_repetida(
        self, cliente: ClienteGateway, gw: GatewayFalso, esperas: list[float]
    ) -> None:
        gw.erro_conexao_n = 2
        assert cliente.autenticar().validade_total_s == 900
        assert len(esperas) == 2

    def test_conexao_que_nunca_volta(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        gw.erro_conexao_n = 99
        with pytest.raises(ConnectionFailed):
            cliente.autenticar()
        assert len(gw.chamadas) == 3

    def test_timeout_de_leitura_nao_e_repetido(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        gw.timeout_leitura = True
        with pytest.raises(RequestTimeout):
            list(cliente.transmitir_chat(modelo="iaitsa-geral", mensagens=[U("oi")]))
        assert gw.contar("POST", "/api/chat") == 1  # evita gerar/cobrar duas vezes

    def test_retry_after_e_respeitado_com_teto(
        self, credenciais: Credenciais, cfg: Settings, esperas: list[float]
    ) -> None:
        respostas = iter([503, 503, 200])

        def h(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/api/auth/token":
                return httpx.Response(200, json={"accessToken": "t", "expiresIn": 900})
            codigo = next(respostas)
            cab = {"Retry-After": "120"} if codigo == 503 else {}
            return httpx.Response(codigo, json={"models": []}, headers=cab)

        c = ClienteGateway(
            credenciais, cfg, transporte=httpx.MockTransport(h), dormir=esperas.append
        )
        assert c.listar_modelos() == []
        assert esperas == [10.0, 10.0]  # 120 s limitado a 10 s
        c.fechar()

    @pytest.mark.parametrize(
        ("status", "classe"),
        [
            (400, BadRequest),
            (401, Unauthorized),
            (403, Forbidden),
            (429, RateLimited),
            (503, ServiceUnavailable),
            (500, ServerError),
            (502, ServerError),
        ],
    )
    def test_mapeamento_de_status(self, status: int, classe: type[Exception]) -> None:
        resp = httpx.Response(status, json={"error": {"code": "cod_x", "message": "Mensagem X"}})
        erro = erro_de_resposta(resp)
        assert isinstance(erro, classe)
        assert erro.codigo == "cod_x"  # type: ignore[attr-defined]
        assert erro.mensagem == "Mensagem X"  # type: ignore[attr-defined]

    def test_corpo_de_erro_sem_formato_usa_mensagem_padrao(self) -> None:
        assert extrair_erro_api(403, "<html>Forbidden</html>") == (
            None,
            "Acesso negado para esta credencial.",
        )
        assert extrair_erro_api(418, "")[0] is None

    def test_retry_after_nao_numerico_e_ignorado(self) -> None:
        resp = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        assert erro_de_resposta(resp).retry_after is None  # type: ignore[attr-defined]


# ===================================================================================== chat
class TestChat:
    def test_sequencia_de_eventos(self, cliente: ClienteGateway) -> None:
        eventos = list(cliente.transmitir_chat(modelo="iaitsa-geral", mensagens=[U("Responda OK")]))
        assert isinstance(eventos[0], EventoIniciado)
        assert all(isinstance(e, EventoDelta) for e in eventos[1:-1])
        assert isinstance(eventos[-1], EventoConcluido)
        assert "".join(e.content for e in eventos if isinstance(e, EventoDelta)) == "OK"
        assert eventos[-1].usage is not None
        assert {getattr(e, "request_id", None) for e in eventos} != {None}

    def test_eventos_apos_completed_sao_ignorados(self, cliente: ClienteGateway) -> None:
        texto = cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")]).texto
        assert "IGNORADO" not in texto

    def test_conversar_agrega_texto_metricas_e_ids(self, cliente: ClienteGateway) -> None:
        cid = uuid.uuid4()
        r = cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")], conversa_id=cid)
        assert r.texto == "OK"
        assert r.conversation_id == cid
        assert r.model == "iaitsa-geral"
        assert r.request_id
        assert r.usage is not None and r.usage.total > 0
        assert r.trechos == 2  # o falso divide "OK" em dois deltas
        assert r.tempo_primeiro_trecho_s is not None

    def test_corpo_enviado_respeita_o_swagger(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        cid = uuid.uuid4()
        cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")], conversa_id=cid)
        assert gw.corpos_chat[-1] == {
            "conversationId": str(cid),
            "model": "iaitsa-geral",
            "messages": [{"role": "user", "content": "oi"}],
            "stream": True,
        }
        req = [r for r in gw.chamadas if r.url.path == "/api/chat"][-1]
        assert req.headers["authorization"].startswith("Bearer eyJ")
        assert req.headers["user-agent"].startswith("ITSA-Agente/")

    def test_acentuacao_ida_e_volta(self, cliente: ClienteGateway) -> None:
        r = cliente.conversar(modelo="iaitsa-geral", mensagens=[U("Repita exatamente: ação")])
        assert r.texto == "ação, coração, não, é, ü"

    def test_validacao_local_nao_toca_a_rede(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        trinta_e_uma = [
            U(f"m{i}") if i % 2 == 0 else Mensagem.assistente(f"r{i}") for i in range(31)
        ]
        with pytest.raises(LocalValidationError):
            cliente.transmitir_chat(modelo="iaitsa-geral", mensagens=trinta_e_uma)
        with pytest.raises(LocalValidationError, match="user"):
            cliente.transmitir_chat(
                modelo="iaitsa-geral", mensagens=[U("a"), Mensagem.assistente("b")]
            )
        with pytest.raises(LocalValidationError):
            cliente.transmitir_chat(modelo="", mensagens=[U("a")])
        assert gw.chamadas == []

    def test_mensagem_de_validacao_nao_ecoa_o_conteudo(self, cliente: ClienteGateway) -> None:
        segredo = "DADO-SENSIVEL-DO-CLIENTE"
        with pytest.raises(LocalValidationError) as info:
            cliente.transmitir_chat(modelo="", mensagens=[U(segredo)])
        assert segredo not in str(info.value)

    def test_modelo_inexistente_e_400_no_inicio(self, cliente: ClienteGateway) -> None:
        with pytest.raises(BadRequest) as info:
            cliente.transmitir_chat(modelo="nao-existe", mensagens=[U("oi")])
        assert info.value.codigo == "modelo_invalido"

    def test_401_no_chat_reemite_e_repete(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        cliente.autenticar()
        gw.revogar_tokens()
        assert cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")]).texto == "OK"
        assert gw.contar("POST", "/api/auth/token") == 2

    def test_503_no_chat_e_repetido_antes_do_streaming(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        gw.indisponivel_n = 1
        assert cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")]).texto == "OK"
        assert gw.contar("POST", "/api/chat") == 2

    def test_evento_error_vira_stream_error(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        gw.modo_stream = "evento_erro"
        with pytest.raises(StreamError) as info:
            cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")])
        assert info.value.codigo == "falha_modelo"
        assert info.value.request_id

    def test_evento_error_aninhado(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        gw.modo_stream = "erro_aninhado"
        with pytest.raises(StreamError) as info:
            cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")])
        assert info.value.codigo == "falha_modelo"

    def test_corte_no_meio_do_streaming(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        gw.modo_stream = "corte"
        with pytest.raises(StreamInterrupted):
            cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")])
        assert gw.contar("POST", "/api/chat") == 1  # sem retentativa no meio do streaming

    def test_fim_sem_completed(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        gw.modo_stream = "sem_completed"
        with pytest.raises(StreamInterrupted):
            cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")])

    def test_linha_malformada(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        gw.modo_stream = "lixo"
        with pytest.raises(ProtocolError):
            cliente.conversar(modelo="iaitsa-geral", mensagens=[U("oi")])

    def test_fechar_o_iterador_cedo_nao_levanta(self, cliente: ClienteGateway) -> None:
        it = cliente.transmitir_chat(modelo="iaitsa-geral", mensagens=[U("oi")])
        assert isinstance(next(it), EventoIniciado)
        it.close()  # type: ignore[attr-defined]


# ===================================================================== cabeçalhos / sondar
class TestCabecalhosESondagem:
    def test_cabecalhos_de_telemetria(self, gw: GatewayFalso, credenciais: Credenciais) -> None:
        cfg = Settings(
            base_url="http://gateway.test",
            erp_version="9.1.2",
            chat_module_version="0.1.0",
            installation_id="5f3e5ce8-45ca-4fb3-8cc0-2af35df25d8d",
        )
        c = ClienteGateway(
            credenciais, cfg, transporte=httpx.MockTransport(gw), dormir=lambda s: None
        )
        c.listar_modelos()
        req = gw.chamadas[-1]
        assert req.headers["x-erp-version"] == "9.1.2"
        assert req.headers["x-chat-module-version"] == "0.1.0"
        assert req.headers["x-installation-id"] == "5f3e5ce8-45ca-4fb3-8cc0-2af35df25d8d"
        c.fechar()

    def test_sondar_nao_levanta_por_status(self, cliente: ClienteGateway) -> None:
        r = cliente.sondar("GET", "/api/models", token=None)
        assert r.status == 401
        assert r.codigo_erro == "nao_autenticado"
        assert r.mensagem_erro
        assert r.erro_rede is None

    def test_sondar_com_token_adulterado(self, cliente: ClienteGateway) -> None:
        assert cliente.sondar("GET", "/api/models", token="x.y.z").status == 401

    def test_sondar_autenticado_e_eventos(self, cliente: ClienteGateway) -> None:
        r = cliente.sondar(
            "POST",
            "/api/chat",
            json_corpo={
                "conversationId": str(uuid.uuid4()),
                "model": "iaitsa-geral",
                "stream": True,
                "messages": [{"role": "user", "content": "oi"}],
            },
        )
        assert r.status == 200
        assert next(e.tipo for e in r.eventos()) == "started"

    def test_sondar_captura_erro_de_rede(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        cliente.autenticar()
        gw.erro_conexao_n = 1
        r = cliente.sondar("GET", "/api/models")
        assert r.status is None
        assert "ConnectError" in (r.erro_rede or "")

    def test_sondar_corpo_bruto_malformado(self, cliente: ClienteGateway) -> None:
        r = cliente.sondar(
            "POST",
            "/api/chat",
            conteudo_bruto=b"{nao-json",
            cabecalhos={"Content-Type": "application/json"},
        )
        assert r.status == 400

    def test_sondar_limita_o_tamanho_do_corpo(
        self, credenciais: Credenciais, cfg: Settings
    ) -> None:
        c = ClienteGateway(
            credenciais,
            cfg,
            transporte=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 5000)),
        )
        r = c.sondar("GET", "/qualquer", token=None, limite_corpo=1000)
        assert r.truncado and len(r.corpo) >= 1000
        c.fechar()


def test_logging_com_redacao_nao_vaza_token(
    cliente: ClienteGateway, capsys: pytest.CaptureFixture[str]
) -> None:
    import logging as _l

    configurar_logging("DEBUG")
    _l.getLogger("itsa_agente.client").info(
        "Enviando tokenId=%s e Bearer abcdefgh12345678", TOKEN_ID_OK
    )
    saida = capsys.readouterr().err
    assert TOKEN_ID_OK not in saida
    assert "abcdefgh12345678" not in saida


def test_caractere_utf8_dividido_entre_pacotes_de_rede(
    credenciais: Credenciais, cfg: Settings
) -> None:
    """Um caractere multibyte cortado ao meio entre dois pacotes não pode corromper o texto."""
    linhas = (
        '{"type":"started","requestId":"r"}\n'
        '{"type":"delta","requestId":"r","content":"coração ação 😀"}\n'
        '{"type":"completed","requestId":"r"}\n'
    ).encode()
    corte = linhas.index("ç".encode()) + 1  # no meio dos 2 bytes de "ç"

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/auth/token":
            return httpx.Response(200, json={"accessToken": "t", "expiresIn": 900})
        return httpx.Response(200, content=iter([linhas[:corte], linhas[corte:]]))

    c = ClienteGateway(credenciais, cfg, transporte=httpx.MockTransport(h), dormir=lambda s: None)
    assert c.conversar(modelo="m", mensagens=[U("oi")]).texto == "coração ação 😀"
    c.fechar()


def test_resposta_chat_com_content_type_sem_charset_e_lida_como_utf8(
    credenciais: Credenciais, cfg: Settings
) -> None:
    corpo = '{"type":"delta","content":"é"}\n{"type":"completed"}\n'.encode()

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/auth/token":
            return httpx.Response(200, json={"accessToken": "t", "expiresIn": 900})
        return httpx.Response(200, content=corpo, headers={"content-type": "application/x-ndjson"})

    c = ClienteGateway(credenciais, cfg, transporte=httpx.MockTransport(h), dormir=lambda s: None)
    assert c.conversar(modelo="m", mensagens=[U("oi")]).texto == "é"
    c.fechar()
