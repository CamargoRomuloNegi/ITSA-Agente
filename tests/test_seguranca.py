from __future__ import annotations

import logging

from itsa_agente.security import FiltroRedacao, Redator, mascarar_valor

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c3VhcmlvIn0.assinaturaAssinatura123"


def test_mascarar_valor() -> None:
    assert mascarar_valor("segredo") == "***"
    assert mascarar_valor("abcdefghij", visivel=3) == "***hij"
    assert mascarar_valor("abc", visivel=3) == "***"
    assert mascarar_valor("") == ""


def test_remove_segredos_registrados() -> None:
    r = Redator(["TOKEN-ABC-123"])
    assert r.aplicar("o token é TOKEN-ABC-123 mesmo") == "o token é *** mesmo"


def test_ignora_segredos_curtos_demais() -> None:
    r = Redator(["ab"])
    assert r.aplicar("abacaxi") == "abacaxi"


def test_remove_jwt_e_bearer() -> None:
    r = Redator()
    assert JWT not in r.aplicar(f"jwt={JWT}")
    saida = r.aplicar("Authorization: Bearer abcdefgh12345678")
    assert "abcdefgh12345678" not in saida


def test_remove_campos_json_sensiveis() -> None:
    r = Redator()
    saida = r.aplicar(
        '{"tokenId": "valor-secreto", "accessToken":"outro-segredo", "erpUserName":"ANA"}'
    )
    assert "valor-secreto" not in saida and "outro-segredo" not in saida
    assert "ANA" in saida


def test_mascara_cpf_cnpj_numerico() -> None:
    r = Redator()
    assert r.aplicar("cliente 12345678000195 ok") == "cliente 123******95 ok"
    assert r.aplicar("cpf 12345678909") == "cpf 123******09"


def test_aplicar_em_estruturas_aninhadas() -> None:
    r = Redator(["SEGREDO-XYZ"])
    saida = r.aplicar_em(
        {"a": ["x SEGREDO-XYZ", {"b": "SEGREDO-XYZ"}], "n": 3, "t": ("SEGREDO-XYZ",)}
    )
    assert "SEGREDO-XYZ" not in str(saida)
    assert saida["n"] == 3


def test_filtro_de_logging_redige_mensagem_formatada() -> None:
    r = Redator(["TOKEN-ABC-123"])
    registro = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "valor=%s", ("TOKEN-ABC-123",), None
    )
    assert FiltroRedacao(r).filter(registro) is True
    assert "TOKEN-ABC-123" not in registro.getMessage()
