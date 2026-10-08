from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from itsa_agente.config import Settings
from itsa_agente.diagnostics import (
    Diagnostico,
    OpcoesDiagnostico,
    Relatorio,
    Resultado,
    Status,
    relatorio_dict,
    relatorio_json,
    relatorio_markdown,
)
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.models import Credenciais
from tests.gateway_falso import TOKEN_ID_OK, GatewayFalso

Fabrica = Callable[..., ClienteGateway]


def executar(cliente: ClienteGateway, **opcoes: object) -> Relatorio:
    return Diagnostico(cliente, OpcoesDiagnostico(**opcoes)).executar()  # type: ignore[arg-type]


def por_id(rel: Relatorio, id_: str) -> Resultado:
    return next(r for r in rel.resultados if r.id == id_)


def test_gateway_saudavel_nao_tem_falhas(cliente: ClienteGateway) -> None:
    rel = executar(cliente)
    assert rel.aprovado, [
        (r.id, r.status, r.detalhe) for r in rel.resultados if r.status is Status.FALHA
    ]
    assert [r.id for r in rel.resultados] == [f"D{i:02d}" for i in range(1, 20)]
    assert por_id(rel, "D07").status is Status.OK
    assert por_id(rel, "D09").status is Status.OK
    assert por_id(rel, "D10").status is Status.OK
    assert por_id(rel, "D18").status is Status.PULADO  # opcional, desligado
    assert por_id(rel, "D19").status is Status.PULADO


def test_catalogo_de_erros_e_preenchido(cliente: ClienteGateway) -> None:
    rel = executar(cliente)
    cenarios = {o.cenario: o for o in rel.observacoes}
    assert cenarios["sem token"].status_http == 401
    assert cenarios["sem token"].codigo == "nao_autenticado"
    assert cenarios["modelo inexistente"].codigo == "modelo_invalido"
    assert cenarios["31 mensagens"].status_http == 400
    assert cenarios["stream=false"].status_http == 400
    assert cenarios["campo extra 'temperature'"].status_http == 400
    assert len(rel.observacoes) >= 12


def test_d07_mede_sequencia_uso_e_latencia(cliente: ClienteGateway) -> None:
    r = por_id(executar(cliente), "D07")
    assert r.dados["sequencia"] == "started, delta×2, completed"
    assert r.dados["request_ids_distintos"] == 1
    assert r.dados["uso"]["prompt_tokens"] >= 1
    assert r.dados["primeiro_trecho_s"] is not None


def test_system_recusado_vira_alerta_com_orientacao(
    cliente: ClienteGateway, gw: GatewayFalso
) -> None:
    gw.aceita_system = False
    r = por_id(executar(cliente), "D10")
    assert r.status is Status.ALERTA
    assert "mensagem de usuário" in r.detalhe


def test_system_ignorado_pelo_modelo_vira_alerta(cliente: ClienteGateway, gw: GatewayFalso) -> None:
    gw.respeita_system = False
    r = por_id(executar(cliente), "D10")
    assert r.status is Status.ALERTA and "NÃO obedecido" in r.detalhe


def test_regra_afrouxada_do_servidor_e_sinalizada(credenciais: Credenciais, cfg: Settings) -> None:
    """Se o servidor ACEITAR 31 mensagens, o diagnóstico deve alertar (contrato divergente)."""

    class Frouxo(GatewayFalso):
        def _validar_chat(self, corpo):  # type: ignore[no-untyped-def]
            if isinstance(corpo, dict) and len(corpo.get("messages", [])) == 31:
                return None
            return super()._validar_chat(corpo)

    gw = Frouxo()
    c = ClienteGateway(credenciais, cfg, transporte=httpx.MockTransport(gw), dormir=lambda s: None)
    r = por_id(executar(c), "D13")
    assert r.status is Status.ALERTA and "ACEITO" in r.detalhe
    c.fechar()


def test_servidor_com_erro_500_e_falha(credenciais: Credenciais, cfg: Settings) -> None:
    class Quebrado(GatewayFalso):
        def _validar_chat(self, corpo):  # type: ignore[no-untyped-def]
            return httpx.Response(500, text="boom")

    c = ClienteGateway(
        credenciais, cfg, transporte=httpx.MockTransport(Quebrado()), dormir=lambda s: None
    )
    rel = executar(c)
    assert por_id(rel, "D12").status is Status.FALHA
    assert not rel.aprovado
    c.fechar()


def test_rejeicao_do_framework_fora_do_formato_e_informativa(
    credenciais: Credenciais, cfg: Settings
) -> None:
    gw = GatewayFalso()

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/models" and "authorization" not in req.headers:
            return httpx.Response(401, text="Unauthorized")
        return gw(req)

    c = ClienteGateway(credenciais, cfg, transporte=httpx.MockTransport(h), dormir=lambda s: None)
    rel = executar(c)
    r = por_id(rel, "D01")
    assert r.status is Status.INFO and "fora do formato" in r.detalhe
    # O catálogo guarda o corpo bruto, para mostrar o formato real do erro.
    obs = next(
        o for o in rel.observacoes if o.cenario == "sem token" and o.endpoint.startswith("GET")
    )
    assert obs.corpo == "Unauthorized"
    c.fechar()


def test_formato_fora_do_contrato_em_erro_de_aplicacao_continua_alerta(
    credenciais: Credenciais, cfg: Settings
) -> None:
    """Só as rejeições do framework são toleradas; erros de validação da aplicação, não."""
    gw = GatewayFalso()

    def h(req: httpx.Request) -> httpx.Response:
        corpo = json.loads(req.content) if req.content and req.url.path == "/api/chat" else {}
        if corpo.get("stream") is False:
            return httpx.Response(400, text="stream obrigatório")
        return gw(req)

    c = ClienteGateway(credenciais, cfg, transporte=httpx.MockTransport(h), dormir=lambda s: None)
    r = por_id(executar(c), "D12")
    assert r.status is Status.ALERTA and "fora do formato" in r.detalhe
    c.fechar()


def test_gateway_fora_do_ar_nao_derruba_a_suite(credenciais: Credenciais) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede", request=req)

    c = ClienteGateway(
        credenciais,
        Settings(base_url="http://x.test", max_retries=0),
        transporte=httpx.MockTransport(h),
        dormir=lambda s: None,
    )
    rel = executar(c)
    assert len(rel.resultados) == 19
    assert not rel.aprovado
    assert por_id(rel, "D01").status is Status.FALHA
    assert por_id(rel, "D02").status is Status.FALHA
    c.fechar()


def test_sem_modelos_pula_os_testes_de_chat(cliente: ClienteGateway, gw: GatewayFalso) -> None:
    gw.modelos = []
    rel = executar(cliente)
    assert por_id(rel, "D03").status is Status.ALERTA
    assert por_id(rel, "D07").status is Status.PULADO
    assert por_id(rel, "D09").status is Status.PULADO


def test_modelo_escolhido_inexistente_e_falha(cliente: ClienteGateway) -> None:
    assert por_id(executar(cliente, modelo="outro"), "D03").status is Status.FALHA


def test_credencial_invalida_aceita_400_de_validacao_de_entrada(
    credenciais: Credenciais, cfg: Settings
) -> None:
    """Gateway real: Token ID de formato inválido -> 400 INVALID_REQUEST (medido)."""
    gw = GatewayFalso()

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/auth/token" and b"TOKEN-INVALIDO" in req.content:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Os dados informados são inválidos.",
                    }
                },
            )
        return gw(req)

    c = ClienteGateway(credenciais, cfg, transporte=httpx.MockTransport(h), dormir=lambda s: None)
    r = por_id(executar(c, incluir_credencial_invalida=True), "D18")
    assert r.status is Status.OK and r.dados["codigo"] == "INVALID_REQUEST"
    c.fechar()


def test_credencial_invalida_opcional(cliente: ClienteGateway, gw: GatewayFalso) -> None:
    rel = executar(cliente, incluir_credencial_invalida=True)
    assert por_id(rel, "D18").status is Status.OK
    corpos = [json.loads(r.content) for r in gw.chamadas if r.url.path == "/api/auth/token"]
    assert any(c["tokenId"] == "TOKEN-INVALIDO-DIAGNOSTICO" for c in corpos)


def test_carga_encontra_o_limite(cliente: ClienteGateway, gw: GatewayFalso) -> None:
    gw.max_chars_conteudo = 10_000
    rel = executar(cliente, incluir_carga=True, tamanhos_carga=(1_000, 5_000, 20_000, 50_000))
    r = por_id(rel, "D19")
    assert r.status is Status.INFO
    assert r.dados["maior_tamanho_ok"] == 5_000
    assert r.dados["medidas"][-1]["codigo"] == "conteudo_muito_grande"
    assert len(r.dados["medidas"]) == 3  # parou na primeira falha
    assert r.dados["medidas"][0]["caracteres_por_token"] > 0


def test_carga_sem_limite(cliente: ClienteGateway) -> None:
    r = por_id(executar(cliente, incluir_carga=True, tamanhos_carga=(500, 1_000)), "D19")
    assert r.status is Status.OK and r.dados["maior_tamanho_ok"] == 1_000


def test_callback_de_progresso_recebe_cada_resultado(cliente: ClienteGateway) -> None:
    vistos: list[str] = []
    Diagnostico(cliente, ao_concluir=lambda r: vistos.append(r.id)).executar()
    assert vistos == [f"D{i:02d}" for i in range(1, 20)]


# ------------------------------------------------------------------------------ relatórios
def test_relatorios_nao_vazam_segredos(cliente: ClienteGateway) -> None:
    rel = executar(cliente, incluir_credencial_invalida=True)
    md, js = relatorio_markdown(rel), relatorio_json(rel)
    token = cliente._token._jwt
    for texto in (md, js):
        assert TOKEN_ID_OK not in texto
        assert token is None or token not in texto
        assert "eyJhbGci" not in texto
    assert "12ABC34501DE35" not in md  # só a versão mascarada


def test_markdown_contem_secoes_esperadas(cliente: ClienteGateway) -> None:
    md = relatorio_markdown(executar(cliente))
    for trecho in (
        "# Relatório de diagnóstico",
        "## Resultados",
        "## Catálogo de respostas de erro observadas",
        "## Dados medidos",
        "APROVADO",
        "| D07 |",
    ):
        assert trecho in md


def test_json_e_valido_e_completo(cliente: ClienteGateway) -> None:
    dados = json.loads(relatorio_json(executar(cliente)))
    assert dados["aprovado"] is True
    assert dados["contagem"]["FALHA"] == 0
    assert len(dados["resultados"]) == 19
    assert dados["resultados"][0]["status"] in {s.value for s in Status}


def test_relatorio_dict_e_redigido(cliente: ClienteGateway) -> None:
    rel = executar(cliente)
    rel.resultados[0].detalhe = f"vazou {TOKEN_ID_OK}"
    assert TOKEN_ID_OK not in json.dumps(relatorio_dict(rel))
