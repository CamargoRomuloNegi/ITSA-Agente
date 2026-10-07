"""Testes da CLI de diagnóstico (`python -m itsa_agente.diagnostics`)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

import itsa_agente.diagnostics.__main__ as cli
from tests.gateway_falso import CPF_CNPJ_OK, TOKEN_ID_OK, USUARIO_OK, GatewayFalso


@pytest.fixture
def cli_com_transporte(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    original = cli.ClienteGateway

    def instalar(manipulador) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(
            cli,
            "ClienteGateway",
            lambda cred, cfg: original(
                cred, cfg, transporte=httpx.MockTransport(manipulador), dormir=lambda s: None
            ),
        )

    monkeypatch.setenv("ITSA_TOKEN_ID", TOKEN_ID_OK)
    return instalar


def argumentos(saida: Path, *extra: str) -> list[str]:
    return [
        "--cpf-cnpj", CPF_CNPJ_OK,
        "--usuario", USUARIO_OK,
        "--url", "http://gateway.test",
        "--saida", str(saida),
        *extra,
    ]  # fmt: skip


def test_executa_grava_relatorios_e_retorna_zero(
    tmp_path: Path, cli_com_transporte, gw: GatewayFalso, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_com_transporte(gw)
    assert cli.principal(argumentos(tmp_path)) == 0

    arquivos = sorted(tmp_path.glob("diagnostico-*"))
    assert [a.suffix for a in arquivos] == [".json", ".md"]
    assert "D07" in capsys.readouterr().out
    for arquivo in arquivos:
        texto = arquivo.read_text(encoding="utf-8")
        assert TOKEN_ID_OK not in texto
        assert "APROVADO" in texto or '"aprovado": true' in texto


def test_opcoes_opcionais_sao_repassadas(
    tmp_path: Path, cli_com_transporte, gw: GatewayFalso
) -> None:
    cli_com_transporte(gw)
    cli.principal(argumentos(tmp_path, "--com-credencial-invalida", "--com-carga"))
    md = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "| D18 |" in md and "| D19 |" in md
    assert "PULADO" not in md.split("| D18 |")[1].split("\n")[0]


def test_gateway_fora_do_ar_retorna_um(tmp_path: Path, cli_com_transporte) -> None:
    def fora(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede", request=req)

    cli_com_transporte(fora)
    assert cli.principal(argumentos(tmp_path)) == 1
    assert list(tmp_path.glob("*.md"))  # o relatório é gerado mesmo com falhas


def test_sem_credenciais_retorna_dois(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for chave in ("ITSA_CPF_CNPJ", "ITSA_ERP_USER"):
        monkeypatch.delenv(chave, raising=False)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls, *a, **k: cls()))
    assert cli.principal(["--saida", str(tmp_path)]) == 2
    assert "--cpf-cnpj" in capsys.readouterr().err


def test_credencial_malformada_retorna_dois(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ITSA_TOKEN_ID", "qualquer")
    codigo = cli.principal(
        [
            "--cpf-cnpj",
            "123",
            "--usuario",
            "ANA",
            "--url",
            "http://x.test",
            "--saida",
            str(tmp_path),
        ]
    )
    assert codigo == 2
    assert "CPF/CNPJ inválido" in capsys.readouterr().err


def test_nao_existe_parametro_para_token_id() -> None:
    with pytest.raises(SystemExit):
        cli.principal(["--token-id", "segredo"])
