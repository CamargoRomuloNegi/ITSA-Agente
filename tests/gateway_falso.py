"""Gateway simulado para testes (``httpx.MockTransport``).

Reproduz o contrato do swagger v1 — incluindo as rejeições (400/401) e o streaming NDJSON — e
expõe "botões" para provocar situações adversas (token revogado, 503 intermitente, corte no meio
do streaming, evento ``error``, linha malformada...). **Não** substitui o gateway real: o que o
servidor de fato faz nos cenários limite é medido pela suíte de diagnóstico.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

CPF_CNPJ_OK = "12ABC34501DE35"
TOKEN_ID_OK = "TOKEN-SECRETO-DO-CLIENTE-123"
USUARIO_OK = "CARLOS"


def _erro(status: int, codigo: str, mensagem: str, **cab: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": codigo, "message": mensagem}}, headers=cab or None
    )


class GatewayFalso:
    def __init__(self) -> None:
        self.modelos: list[dict[str, str]] = [{"id": "iaitsa-geral", "displayName": "IAitsa Geral"}]
        self.validade_s = 900
        self.aceita_system = True
        self.respeita_system = True
        self.max_chars_conteudo: int | None = None
        # Falhas provocadas
        self.indisponivel_n = (
            0  # nº de respostas 503 antes de funcionar (em /api/models e /api/chat)
        )
        self.erro_conexao_n = 0  # nº de ConnectError antes de funcionar
        self.timeout_leitura = False
        self.modo_stream = (
            "normal"  # normal | evento_erro | corte | lixo | sem_completed | erro_aninhado
        )
        self.token_429 = False
        # Observação
        self.chamadas: list[httpx.Request] = []
        self.corpos_chat: list[dict[str, Any]] = []
        self.tokens_validos: set[str] = set()
        self._seq = 0

    # ------------------------------------------------------------------ utilitários
    def revogar_tokens(self) -> None:
        self.tokens_validos.clear()

    def contar(self, metodo: str, caminho: str) -> int:
        return sum(1 for r in self.chamadas if r.method == metodo and r.url.path == caminho)

    def _jwt(self) -> str:
        self._seq += 1
        n = f"{self._seq:04d}"
        token = f"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ{n}In0.c2lnbmF0dXJl{n}"
        self.tokens_validos.add(token)
        return token

    def _autenticado(self, req: httpx.Request) -> bool:
        cab = req.headers.get("authorization", "")
        return cab.startswith("Bearer ") and cab[7:] in self.tokens_validos

    # ----------------------------------------------------------------- transporte
    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.chamadas.append(req)
        if self.erro_conexao_n > 0:
            self.erro_conexao_n -= 1
            raise httpx.ConnectError("conexão recusada", request=req)
        rota = (req.method, req.url.path)
        if rota == ("POST", "/api/auth/token"):
            return self._token(req)
        if rota == ("GET", "/api/models"):
            return self._modelos(req)
        if rota == ("POST", "/api/chat"):
            return self._chat(req)
        return _erro(404, "nao_encontrado", "Rota inexistente.")

    def _token(self, req: httpx.Request) -> httpx.Response:
        if self.token_429:
            return _erro(429, "muitas_requisicoes", "Aguarde.", **{"Retry-After": "7"})
        try:
            corpo = json.loads(req.content)
        except ValueError:
            return _erro(400, "corpo_invalido", "JSON inválido.")
        if set(corpo) != {"cpfCnpj", "tokenId", "erpUserName"}:
            return _erro(400, "requisicao_invalida", "Campos inválidos.")
        if not 1 <= len(corpo["erpUserName"]) <= 15:
            return _erro(400, "usuario_invalido", "Usuário inválido.")
        if corpo["cpfCnpj"] != CPF_CNPJ_OK or corpo["tokenId"] != TOKEN_ID_OK:
            return _erro(401, "credenciais_invalidas", "Credenciais inválidas.")
        return httpx.Response(
            200,
            json={
                "accessToken": self._jwt(),
                "tokenType": "Bearer",
                "expiresIn": self.validade_s,
                "expiresAtUtc": "2099-01-01T00:00:00Z",
            },
        )

    def _modelos(self, req: httpx.Request) -> httpx.Response:
        if not self._autenticado(req):
            return _erro(401, "nao_autenticado", "Token ausente ou inválido.")
        if self.indisponivel_n > 0:
            self.indisponivel_n -= 1
            return _erro(503, "indisponivel", "Indisponível.")
        return httpx.Response(200, json={"models": self.modelos})

    # ----------------------------------------------------------------------- chat
    def _validar_chat(self, corpo: Any) -> httpx.Response | None:
        def ruim(msg: str) -> httpx.Response:
            return _erro(400, "requisicao_invalida", msg)

        if not isinstance(corpo, dict):
            return ruim("Corpo deve ser um objeto.")
        if set(corpo) - {"conversationId", "model", "messages", "stream"}:
            return ruim("Campos desconhecidos.")
        try:
            uuid.UUID(str(corpo.get("conversationId")))
        except ValueError:
            return ruim("conversationId inválido.")
        if corpo.get("stream") is not True:
            return ruim("stream deve ser true.")
        msgs = corpo.get("messages")
        if not isinstance(msgs, list) or not 1 <= len(msgs) <= 30:
            return ruim("messages deve ter de 1 a 30 itens.")
        for m in msgs:
            if not isinstance(m, dict) or m.get("role") not in {"system", "user", "assistant"}:
                return ruim("role inválido.")
            if not str(m.get("content", "")).strip():
                return ruim("content vazio.")
            if self.max_chars_conteudo and len(m["content"]) > self.max_chars_conteudo:
                return _erro(400, "conteudo_muito_grande", "Conteúdo excede o limite.")
        if msgs[-1]["role"] != "user":
            return ruim("A última mensagem deve ser do usuário.")
        if msgs[0]["role"] == "system" and not self.aceita_system:
            return ruim("role system não é aceito.")
        if corpo.get("model") not in {m["id"] for m in self.modelos}:
            return _erro(400, "modelo_invalido", "Modelo desconhecido.")
        return None

    def _resposta_modelo(self, msgs: list[dict[str, str]]) -> str:
        ultima = msgs[-1]["content"]
        sistema = msgs[0]["content"] if msgs[0]["role"] == "system" else ""
        if "BANANA" in sistema and self.respeita_system:
            return "BANANA"
        if "Repita exatamente" in ultima:
            return "ação, coração, não, é, ü"
        if "código secreto" in ultima and any("ZEBRA-42" in m["content"] for m in msgs[:-1]):
            return "ZEBRA-42"
        return "OK"

    def _chat(self, req: httpx.Request) -> httpx.Response:
        if not self._autenticado(req):
            return _erro(401, "nao_autenticado", "Token ausente ou inválido.")
        try:
            corpo = json.loads(req.content)
        except ValueError:
            return _erro(400, "corpo_invalido", "JSON inválido.")
        invalido = self._validar_chat(corpo)
        if invalido is not None:
            return invalido
        self.corpos_chat.append(corpo)
        if self.indisponivel_n > 0:
            self.indisponivel_n -= 1
            return _erro(503, "indisponivel", "Indisponível.")
        if self.timeout_leitura:
            raise httpx.ReadTimeout("sem resposta", request=req)

        texto = self._resposta_modelo(corpo["messages"])
        rid = str(uuid.uuid4())
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson; charset=utf-8"},
            content=self._stream(corpo, texto, rid),
        )

    def _stream(self, corpo: dict[str, Any], texto: str, rid: str) -> Iterator[bytes]:
        def linha(obj: dict[str, Any]) -> bytes:
            return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

        yield linha(
            {
                "type": "started",
                "requestId": rid,
                "conversationId": corpo["conversationId"],
                "model": corpo["model"],
            }
        )
        meio = max(len(texto) // 2, 1)
        partes = [texto[:meio], texto[meio:]] if len(texto) > 1 else [texto]
        yield linha({"type": "delta", "requestId": rid, "content": partes[0]})
        yield b"\n"  # linha em branco (keep-alive) deve ser ignorada

        if self.modo_stream == "corte":
            raise httpx.ReadError("conexão derrubada")
        if self.modo_stream == "lixo":
            yield b"isto-nao-e-json\n"
            return
        if self.modo_stream == "evento_erro":
            yield linha(
                {
                    "type": "error",
                    "requestId": rid,
                    "code": "falha_modelo",
                    "message": "O modelo falhou.",
                }
            )
            return
        if self.modo_stream == "erro_aninhado":
            yield linha(
                {
                    "type": "error",
                    "requestId": rid,
                    "error": {"code": "falha_modelo", "message": "Aninhado."},
                }
            )
            return

        for parte in partes[1:]:
            yield linha({"type": "delta", "requestId": rid, "content": parte})
        if self.modo_stream == "sem_completed":
            return
        chars = sum(len(m["content"]) for m in corpo["messages"])
        yield linha(
            {
                "type": "completed",
                "requestId": rid,
                "model": corpo["model"],
                "usage": {
                    "promptTokens": max(chars // 4, 1),
                    "completionTokens": max(len(texto) // 4, 1),
                },
            }
        )
        yield linha({"type": "delta", "requestId": rid, "content": "IGNORADO-APOS-COMPLETED"})
