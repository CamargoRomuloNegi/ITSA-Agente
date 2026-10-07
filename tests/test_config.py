from __future__ import annotations

from pathlib import Path

import pytest

from itsa_agente.config import Settings, ler_arquivo_env
from itsa_agente.gateway.errors import ConfigurationError


def test_padroes_sao_validos() -> None:
    cfg = Settings.from_env({})
    assert cfg.base_url == "https://suporteitsa2.ddns.net"
    assert cfg.verify_tls is True
    assert cfg.max_retries == 2
    assert cfg.url_token.endswith("/api/auth/token")


def test_variaveis_de_ambiente_sobrescrevem() -> None:
    cfg = Settings.from_env(
        {
            "ITSA_BASE_URL": "http://localhost:5000/",
            "ITSA_VERIFY_TLS": "não",
            "ITSA_STREAM_READ_TIMEOUT": "45,5",
            "ITSA_MAX_RETRIES": "0",
            "ITSA_ERP_VERSION": "9.1.2",
            "ITSA_INSTALLATION_ID": "5f3e5ce8-45ca-4fb3-8cc0-2af35df25d8d",
            "ITSA_LOG_LEVEL": "debug",
        }
    )
    assert cfg.base_url == "http://localhost:5000"  # barra final removida
    assert cfg.verify_tls is False
    assert cfg.stream_read_timeout == 45.5  # vírgula decimal aceita
    assert cfg.max_retries == 0
    assert cfg.erp_version == "9.1.2"
    assert cfg.log_level == "DEBUG"


@pytest.mark.parametrize(
    ("chave", "valor"),
    [
        ("ITSA_BASE_URL", "ftp://servidor"),
        ("ITSA_BASE_URL", "sem-esquema"),
        ("ITSA_VERIFY_TLS", "talvez"),
        ("ITSA_CONNECT_TIMEOUT", "abc"),
        ("ITSA_CONNECT_TIMEOUT", "0"),
        ("ITSA_MAX_RETRIES", "-1"),
        ("ITSA_ERP_VERSION", "x" * 51),
        ("ITSA_CHAT_MODULE_VERSION", "x" * 51),
        ("ITSA_INSTALLATION_ID", "nao-e-guid"),
        ("ITSA_LOG_LEVEL", "barulhento"),
        ("ITSA_MAX_HISTORY_CHARS", "10"),
    ],
)
def test_valores_invalidos_sao_rejeitados(chave: str, valor: str) -> None:
    with pytest.raises(ConfigurationError):
        Settings.from_env({chave: valor})


def test_leitura_do_arquivo_env(tmp_path: Path) -> None:
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "# comentário\n\nITSA_BASE_URL='http://a.test'\nexport ITSA_ERP_USER=ANA # inline\n"
        'ITSA_CPF_CNPJ="123"\nlinha-invalida\n',
        encoding="utf-8",
    )
    valores = ler_arquivo_env(arquivo)
    assert valores == {
        "ITSA_BASE_URL": "http://a.test",
        "ITSA_ERP_USER": "ANA",
        "ITSA_CPF_CNPJ": "123",
    }
    assert ler_arquivo_env(tmp_path / "nao-existe") == {}


def test_ambiente_do_processo_vence_o_arquivo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "ITSA_BASE_URL=http://arquivo.test\nITSA_ERP_USER=DOARQUIVO\n", encoding="utf-8"
    )
    monkeypatch.setenv("ITSA_BASE_URL", "http://ambiente.test")
    monkeypatch.delenv("ITSA_ERP_USER", raising=False)
    cfg = Settings.from_env(arquivo_env=arquivo)
    assert cfg.base_url == "http://ambiente.test"
    assert cfg.usuario_erp_padrao == "DOARQUIVO"


def test_token_dev_nao_aparece_no_repr() -> None:
    cfg = Settings.from_env({"ITSA_TOKEN_ID": "SEGREDO-123"})
    assert cfg.token_id_dev == "SEGREDO-123"
    assert "SEGREDO-123" not in repr(cfg)


def test_com_cria_copia_alterada() -> None:
    base = Settings()
    outra = base.com(max_retries=5)
    assert outra.max_retries == 5
    assert base.max_retries == 2
