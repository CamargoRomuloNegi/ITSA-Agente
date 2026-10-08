"""Diagnóstico de provedores externos (P01–P09) contra o provedor simulado."""

from __future__ import annotations

import httpx
import pytest

from itsa_agente.config import Settings
from itsa_agente.diagnostics import (
    DiagnosticoProvedor,
    OpcoesDiagnosticoProvedor,
    Relatorio,
    Status,
    relatorio_json,
    relatorio_markdown,
)
from itsa_agente.providers.nvidia import ProvedorNvidia
from itsa_agente.providers.openrouter import ProvedorOpenRouter
from tests.provedor_falso import CHAVE_NVIDIA_OK, CHAVE_OPENROUTER_OK, ProvedorFalso

MODELO = "nvidia/nemotron-3-ultra-550b-a55b"


@pytest.fixture
def cfg_d() -> Settings:
    return Settings(
        nvidia_base_url="http://nvidia.test/v1",
        openrouter_base_url="http://openrouter.test/api/v1",
        max_retries=0,
    )


def executar(
    falso: ProvedorFalso, cfg: Settings, **opcoes: object
) -> tuple[Relatorio, dict[str, Status]]:
    cliente = ProvedorNvidia(CHAVE_NVIDIA_OK, cfg, transporte=httpx.MockTransport(falso))
    try:
        rel = DiagnosticoProvedor(
            cliente,
            OpcoesDiagnosticoProvedor(modelo=MODELO, **opcoes),  # type: ignore[arg-type]
        ).executar()
    finally:
        cliente.fechar()
    return rel, {r.id: r.status for r in rel.resultados}


def resultado(rel: Relatorio, id_: str):  # type: ignore[no-untyped-def]
    return next(r for r in rel.resultados if r.id == id_)


class TestBateriaSaudavel:
    def test_todas_as_verificacoes_ativas_passam(self, cfg_d: Settings) -> None:
        rel, st = executar(ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,)), cfg_d)
        assert rel.aprovado
        assert st == {
            "P01": Status.OK,
            "P02": Status.OK,
            "P03": Status.OK,
            "P04": Status.OK,
            "P05": Status.OK,
            "P06": Status.INFO,
            "P07": Status.OK,
            "P08": Status.OK,
            "P09": Status.PULADO,
        }

    def test_p02_mede_latencia_uso_e_motivo(self, cfg_d: Settings) -> None:
        rel, _ = executar(ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,)), cfg_d)
        d = resultado(rel, "P02").dados
        assert d["motivo"] == "stop" and d["uso"]["prompt_tokens"] == 20
        assert d["primeiro_trecho_s"] is not None and d["amostra"] == "OK"
        assert d["sequencia"] == "started, delta, completed"

    def test_p05_reporta_trechos_e_vazao(self, cfg_d: Settings) -> None:
        rel, _ = executar(ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,)), cfg_d)
        d = resultado(rel, "P05").dados
        assert d["trechos_resposta"] > 2
        assert d["uso"]["completion_tokens"] > 0

    def test_p06_compara_raciocinio_ligado_e_desligado(self, cfg_d: Settings) -> None:
        rel, _ = executar(ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,)), cfg_d)
        r = resultado(rel, "P06")
        assert r.dados["ligado"]["caracteres_raciocinio"] > 0
        assert r.dados["desligado"]["caracteres_raciocinio"] == 0
        assert "Raciocínio recebido à parte" in r.detalhe

    def test_p06_sem_raciocinio_no_provedor(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.raciocinio_texto = ""
        rel, _ = executar(falso, cfg_d)
        assert "Nenhum raciocínio separado" in resultado(rel, "P06").detalhe

    def test_catalogo_de_erros_traz_o_corpo_bruto(self, cfg_d: Settings) -> None:
        rel, _ = executar(ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,)), cfg_d)
        por_cenario = {o.cenario: o for o in rel.observacoes}
        assert por_cenario["chave inválida"].status_http == 401
        assert "Invalid API key" in (por_cenario["chave inválida"].corpo or "")
        assert por_cenario["modelo inexistente"].status_http == 404


class TestAlertas:
    def test_sem_streaming_incremental(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.incremental = False
        rel, st = executar(falso, cfg_d)
        assert st["P05"] is Status.ALERTA
        assert "sem streaming incremental" in resultado(rel, "P05").detalhe

    def test_instrucao_de_sistema_ignorada(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.ignora_system = True
        _, st = executar(falso, cfg_d)
        assert st["P04"] is Status.ALERTA

    def test_chave_invalida_aceita_gera_alerta(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.exige_chave_em_chat = False
        _, st = executar(falso, cfg_d)
        assert st["P07"] is Status.ALERTA

    def test_sem_uso_de_tokens_e_alerta_no_p02(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.usage = False
        rel, st = executar(falso, cfg_d)
        assert st["P02"] is Status.ALERTA
        assert "consumo de tokens" in resultado(rel, "P02").detalhe

    def test_resposta_cortada_por_limite_e_alerta_no_p02(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.motivo_final = "length"
        _, st = executar(falso, cfg_d)
        assert st["P02"] is Status.ALERTA

    def test_erro_no_meio_do_stream_reprova_o_p02(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.erro_no_meio = {"code": 502, "message": "caiu"}
        rel, st = executar(falso, cfg_d)
        assert st["P02"] is Status.FALHA and not rel.aprovado


class TestResiliencia:
    def test_provedor_fora_do_ar_gera_relatorio_sem_excecao(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.status_forcado = 500
        rel, st = executar(falso, cfg_d)
        assert st["P01"] is Status.FALHA and not rel.aprovado
        assert len(rel.resultados) == 9  # nenhuma verificação derrubou as demais

    def test_chave_errada_reprova_a_p01_com_mensagem_clara(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso("nvapi-OUTRA-CHAVE-DO-SERVIDOR", (MODELO,))
        rel, st = executar(falso, cfg_d)
        assert st["P01"] is Status.FALHA
        assert "Unauthorized" in resultado(rel, "P01").detalhe


class TestContextoLongo:
    def test_agulha_encontrada_nos_dois_tamanhos(self, cfg_d: Settings) -> None:
        rel, st = executar(
            ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,)), cfg_d, incluir_contexto_longo=True
        )
        assert st["P09"] is Status.OK
        assert [m["achou"] for m in resultado(rel, "P09").dados["medidas"]] == [True, True]

    def test_contexto_cortado_em_silencio_e_detectado(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.limite_contexto = 30_000
        rel, st = executar(falso, cfg_d, incluir_contexto_longo=True)
        assert st["P09"] is Status.ALERTA
        achou = [m["achou"] for m in resultado(rel, "P09").dados["medidas"]]
        assert achou == [True, False]
        assert "96000" in resultado(rel, "P09").detalhe


class TestOpcoes:
    def test_verificacoes_desligadas_ficam_puladas(self, cfg_d: Settings) -> None:
        _, st = executar(
            ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,)),
            cfg_d,
            incluir_raciocinio=False,
            incluir_resposta_longa=False,
            incluir_chave_invalida=False,
        )
        assert st["P05"] is st["P06"] is st["P07"] is Status.PULADO

    def test_modelo_automatico_prefere_gratuito_no_openrouter(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_OPENROUTER_OK, ("vendor/pago", "vendor/livre:free"))
        falso.catalogo = {
            "data": [
                {"id": "vendor/pago", "pricing": {"prompt": "1", "completion": "1"}},
                {"id": "vendor/livre:free", "pricing": {"prompt": "0", "completion": "0"}},
            ]
        }
        cliente = ProvedorOpenRouter(
            CHAVE_OPENROUTER_OK, cfg_d, transporte=httpx.MockTransport(falso)
        )
        rel = DiagnosticoProvedor(
            cliente,
            OpcoesDiagnosticoProvedor(
                incluir_raciocinio=False, incluir_resposta_longa=False, incluir_chave_invalida=False
            ),
        ).executar()
        cliente.fechar()
        usados = {c["model"] for c in falso.corpos_chat} - {"modelo-inexistente-diagnostico"}
        assert usados == {"vendor/livre:free"}
        assert "vendor/livre:free" in (rel.identificacao or "")


class TestRelatorio:
    def test_markdown_identifica_o_provedor_e_nao_vaza_a_chave(self, cfg_d: Settings) -> None:
        rel, _ = executar(ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,)), cfg_d)
        md = relatorio_markdown(rel)
        assert md.startswith("# Relatório de diagnóstico — NVIDIA")
        assert "**Endpoint:** http://nvidia.test/v1" in md
        assert "Corpo bruto (resumo)" in md
        assert "P05" in md and CHAVE_NVIDIA_OK not in md
        assert CHAVE_NVIDIA_OK not in relatorio_json(rel)

    def test_segredo_ecoado_pelo_provedor_e_redigido(self, cfg_d: Settings) -> None:
        falso = ProvedorFalso(CHAVE_NVIDIA_OK, (MODELO,))
        falso.exige_chave_em_chat = True
        rel, _ = executar(falso, cfg_d)
        rel.resultados[
            0
        ].detalhe += f" eco da chave {CHAVE_NVIDIA_OK} e outra nvapi-ZZZZZZZZZZ123456"
        md = relatorio_markdown(rel)
        assert CHAVE_NVIDIA_OK not in md and "nvapi-ZZZZZZZZZZ123456" not in md

    def test_relatorio_do_gateway_mantem_o_titulo_original(self) -> None:
        from itsa_agente.diagnostics.modelos import Relatorio as R

        rel = R("0", "agora", "http://x", "u", "123***", {})
        assert relatorio_markdown(rel).startswith("# Relatório de diagnóstico — IAitsaGateway")
