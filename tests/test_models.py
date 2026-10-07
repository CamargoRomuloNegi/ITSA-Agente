from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from itsa_agente.gateway.errors import LocalValidationError
from itsa_agente.gateway.models import (
    ChatRequest,
    Credenciais,
    Mensagem,
    ModelsResponse,
    TokenResponse,
    normalizar_cpf_cnpj,
)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("123.456.789-09", "12345678909"),
        ("12.345.678/0001-95", "12345678000195"),
        ("12abc34501de35", "12ABC34501DE35"),  # CNPJ alfanumérico, caixa baixa
        (" 12ABC34501DE35 ", "12ABC34501DE35"),
    ],
)
def test_normaliza_cpf_cnpj(entrada: str, esperado: str) -> None:
    assert normalizar_cpf_cnpj(entrada) == esperado


@pytest.mark.parametrize("ruim", ["", "123", "1234567890A", "123456789012345", "12ABC3450-1DE3!"])
def test_cpf_cnpj_invalido(ruim: str) -> None:
    with pytest.raises(LocalValidationError):
        normalizar_cpf_cnpj(ruim)


def test_credenciais_validas_e_segredo_oculto() -> None:
    c = Credenciais("12.ABC.345/01DE-35", "  meu-token-secreto  ", " CARLOS ")
    assert c.cpf_cnpj == "12ABC34501DE35"
    assert c.token_id == "meu-token-secreto"
    assert c.usuario_erp == "CARLOS"
    assert c.payload() == {
        "cpfCnpj": "12ABC34501DE35",
        "tokenId": "meu-token-secreto",
        "erpUserName": "CARLOS",
    }
    assert "meu-token-secreto" not in repr(c)
    assert "meu-token-secreto" not in str(c)
    assert c.cpf_cnpj_mascarado.startswith("12A") and c.cpf_cnpj_mascarado.endswith("35")
    assert "BC345" not in c.cpf_cnpj_mascarado


@pytest.mark.parametrize("usuario", ["", "   ", "X" * 16])
def test_usuario_erp_fora_de_1_a_15(usuario: str) -> None:
    with pytest.raises(LocalValidationError):
        Credenciais("12345678909", "tok", usuario)


def test_token_id_obrigatorio() -> None:
    with pytest.raises(LocalValidationError):
        Credenciais("12345678909", "   ", "ANA")


def test_usuario_com_15_caracteres_e_aceito() -> None:
    assert Credenciais("12345678909", "t", "A" * 15).usuario_erp == "A" * 15


def _msgs(n: int, ultima: str = "user") -> list[Mensagem]:
    itens = [
        Mensagem(role="user" if i % 2 == 0 else "assistant", content=f"m{i}") for i in range(n - 1)
    ]
    itens.append(Mensagem(role=ultima, content="final"))  # type: ignore[arg-type]
    return itens


def test_chat_request_serializa_com_aliases_do_swagger() -> None:
    cid = uuid.uuid4()
    req = ChatRequest(conversation_id=cid, model="iaitsa-geral", messages=_msgs(1))
    assert req.para_json() == {
        "conversationId": str(cid),
        "model": "iaitsa-geral",
        "messages": [{"role": "user", "content": "final"}],
        "stream": True,
    }


def test_chat_request_limites_de_mensagens() -> None:
    ChatRequest(conversation_id=uuid.uuid4(), model="m", messages=_msgs(30))
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id=uuid.uuid4(), model="m", messages=_msgs(31))
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id=uuid.uuid4(), model="m", messages=[])


def test_chat_request_ultima_deve_ser_usuario() -> None:
    with pytest.raises(ValidationError, match="user"):
        ChatRequest(conversation_id=uuid.uuid4(), model="m", messages=_msgs(2, ultima="assistant"))


def test_chat_request_stream_deve_ser_true() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id=uuid.uuid4(), model="m", messages=_msgs(1), stream=False)  # type: ignore[arg-type]


def test_chat_request_modelo_vazio_e_rejeitado() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id=uuid.uuid4(), model="", messages=_msgs(1))


@pytest.mark.parametrize("conteudo", ["", "   ", "\n\t"])
def test_mensagem_vazia_e_rejeitada(conteudo: str) -> None:
    with pytest.raises(ValidationError):
        Mensagem.usuario(conteudo)


def test_mensagem_papel_invalido() -> None:
    with pytest.raises(ValidationError):
        Mensagem(role="tool", content="x")  # type: ignore[arg-type]


def test_mensagem_preserva_conteudo_original() -> None:
    assert Mensagem.usuario("  olá  \n").content == "  olá  \n"


def test_token_response_e_tolerante_a_campos_extras() -> None:
    t = TokenResponse.model_validate(
        {
            "accessToken": "abc",
            "tokenType": "Bearer",
            "expiresIn": 900,
            "novo": 1,
            "expiresAtUtc": "2026-08-21T16:56:29Z",
        }
    )
    assert t.expires_in == 900
    assert t.expires_at_utc is not None
    assert "abc" not in repr(t)


def test_token_response_exige_validade_positiva() -> None:
    with pytest.raises(ValidationError):
        TokenResponse.model_validate({"accessToken": "abc", "expiresIn": 0})


def test_models_response_aceita_lista_nula_ou_ausente() -> None:
    assert ModelsResponse.model_validate({"models": None}).models == []
    assert ModelsResponse.model_validate({}).models == []
    m = ModelsResponse.model_validate({"models": [{"id": "a"}, {"id": "b", "displayName": "B"}]})
    assert [x.rotulo for x in m.models] == ["a", "B"]
