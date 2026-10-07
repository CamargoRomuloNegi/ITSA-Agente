from __future__ import annotations

import json

import pytest

from itsa_agente.gateway.errors import ProtocolError, StreamInterrupted
from itsa_agente.gateway.models import (
    EventoConcluido,
    EventoDelta,
    EventoDesconhecido,
    EventoErro,
    EventoIniciado,
    Uso,
)
from itsa_agente.gateway.ndjson import evento_de_linha, iterar_eventos


def L(**obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


def test_exemplo_do_swagger() -> None:
    linhas = [
        '{"type":"started","requestId":"r1","conversationId":"c1","model":"iaitsa-geral"}',
        '{"type":"delta","requestId":"r1","content":"Um ERP é um sistema integrado."}',
        '{"type":"completed","requestId":"r1","model":"iaitsa-geral","usage":{"promptTokens":23,"completionTokens":111}}',
    ]
    eventos = list(iterar_eventos(linhas))
    assert isinstance(eventos[0], EventoIniciado)
    assert eventos[0].model == "iaitsa-geral"
    assert eventos[0].conversation_id == "c1"
    assert isinstance(eventos[1], EventoDelta)
    assert eventos[1].content == "Um ERP é um sistema integrado."
    assert isinstance(eventos[2], EventoConcluido)
    assert eventos[2].usage == Uso(23, 111)
    assert eventos[2].usage.total == 134  # type: ignore[union-attr]


def test_linhas_em_branco_sao_ignoradas() -> None:
    eventos = list(
        iterar_eventos(["", "  ", L(type="delta", content="a"), "\n", L(type="completed")])
    )
    assert [e.tipo for e in eventos] == ["delta", "completed"]


def test_para_no_primeiro_evento_terminal() -> None:
    eventos = list(iterar_eventos([L(type="completed"), L(type="delta", content="lixo")]))
    assert len(eventos) == 1


def test_erro_com_campos_no_topo() -> None:
    (e,) = iterar_eventos([L(type="error", requestId="r", code="falha", message="Quebrou")])
    assert isinstance(e, EventoErro)
    assert (e.codigo, e.mensagem, e.request_id) == ("falha", "Quebrou", "r")


def test_erro_aninhado() -> None:
    (e,) = iterar_eventos([L(type="error", error={"code": "x", "message": "y"})])
    assert isinstance(e, EventoErro)
    assert (e.codigo, e.mensagem) == ("x", "y")


def test_erro_sem_detalhes_nao_quebra() -> None:
    (e,) = iterar_eventos([L(type="error")])
    assert isinstance(e, EventoErro)
    assert e.codigo is None and e.mensagem is None


def test_tipo_desconhecido_e_preservado_e_nao_encerra() -> None:
    eventos = list(iterar_eventos([L(type="ping", x=1), L(type="completed")]))
    assert isinstance(eventos[0], EventoDesconhecido)
    assert eventos[0].tipo_original == "ping"
    assert eventos[0].bruto == {"type": "ping", "x": 1}


def test_delta_sem_content_vira_vazio() -> None:
    (e,) = list(iterar_eventos([L(type="delta"), L(type="completed")]))[:1]
    assert isinstance(e, EventoDelta) and e.content == ""


def test_usage_malformado_e_tolerado() -> None:
    eventos = list(
        iterar_eventos([L(type="completed", usage={"promptTokens": "x", "completionTokens": -5})])
    )
    assert eventos[0].usage == Uso(0, 0)  # type: ignore[union-attr]
    eventos = list(iterar_eventos([L(type="completed", usage="nada")]))
    assert eventos[0].usage is None  # type: ignore[union-attr]


def test_fluxo_sem_evento_terminal_e_interrupcao() -> None:
    with pytest.raises(StreamInterrupted):
        list(iterar_eventos([L(type="started"), L(type="delta", content="parcial")]))
    with pytest.raises(StreamInterrupted):
        list(iterar_eventos([]))


@pytest.mark.parametrize("linha", ["isto não é json", "{incompleto", "[1,2,3]", '"texto"', "42"])
def test_linha_invalida_levanta_protocol_error(linha: str) -> None:
    with pytest.raises(ProtocolError):
        evento_de_linha(linha)


def test_mensagem_de_protocol_error_limita_o_trecho() -> None:
    with pytest.raises(ProtocolError) as info:
        evento_de_linha("x" * 5000)
    assert len(str(info.value)) < 400


def test_unicode_e_preservado() -> None:
    (e, *_) = iterar_eventos([L(type="delta", content="coração — ü 😀"), L(type="completed")])
    assert e.content == "coração — ü 😀"  # type: ignore[union-attr]
