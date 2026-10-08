"""Provedor externo simulado (NVIDIA/OpenRouter) para testes, via ``httpx.MockTransport``.

Reproduz o formato documentado das APIs compatíveis com a da OpenAI — SSE com ``data: {...}`` e
``data: [DONE]``, ``usage`` ao final, comentários ``: OPENROUTER PROCESSING``, erros no meio do
stream — e expõe "botões" para provocar situações adversas. **Não** substitui os provedores
reais: o comportamento deles é medido pelo diagnóstico de provedores (P01–P09).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import httpx

CHAVE_NVIDIA_OK = "nvapi-CHAVE-SECRETA-DE-TESTE-0123456789"
CHAVE_OPENROUTER_OK = "sk-or-v1-CHAVE-SECRETA-DE-TESTE-0123456789"

TEXTO_LONGO = " ".join(["planejamento tributário bem feito reduz riscos e custos"] * 8)


def _erro(status: int, mensagem: str, codigo: Any = None, **cab: str) -> httpx.Response:
    corpo: dict[str, Any] = {"error": {"message": mensagem}}
    if codigo is not None:
        corpo["error"]["code"] = codigo
    return httpx.Response(status, json=corpo, headers=cab or None)


class FluxoQuebrado(httpx.SyncByteStream):
    """Entrega alguns bytes e depois falha como uma queda de rede."""

    def __init__(self, inicio: bytes) -> None:
        self._inicio = inicio

    def __iter__(self) -> Iterator[bytes]:
        yield self._inicio
        raise httpx.ReadError("conexão derrubada")


class ProvedorFalso:
    def __init__(
        self,
        chave: str = CHAVE_NVIDIA_OK,
        modelos: tuple[str, ...] = ("nvidia/nemotron-3-ultra-550b-a55b",),
    ) -> None:
        self.chave = chave
        self.modelos = modelos
        self.exige_chave_em_models = (
            False  # verificado: /models é público na NVIDIA e no OpenRouter
        )
        self.exige_chave_em_chat = True
        self.catalogo: dict[str, Any] | None = None  # corpo de GET /models (OpenRouter)
        # Comportamentos
        self.raciocinio_texto = "Pensando: 17 × 23 = 340 + 51 = 391."
        self.usage = True
        self.motivo_final = "stop"
        self.incremental = True  # False: a resposta inteira num único trecho
        self.json_unico = False  # ignora stream=true e devolve JSON comum
        self.cortar_sem_finish = False  # fecha a conexão sem finish_reason nem [DONE]
        self.cortar_com_finish_sem_done = False
        self.queda_no_meio = False
        self.erro_no_meio: dict[str, Any] | None = None
        self.rejeita_stream_options = False
        self.ignora_system = False
        self.limite_contexto: int | None = None  # acima disso o modelo "não enxerga" a agulha
        self.indisponivel_n = 0  # nº de respostas 503 antes de funcionar
        self.erro_conexao_n = 0
        self.status_forcado: int | None = None
        self.retry_after: str | None = None
        # Observação
        self.chamadas: list[httpx.Request] = []
        self.corpos_chat: list[dict[str, Any]] = []

    # ---------------------------------------------------------------- transporte
    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.chamadas.append(req)
        if self.erro_conexao_n > 0:
            self.erro_conexao_n -= 1
            raise httpx.ConnectError("conexão recusada", request=req)
        if self.indisponivel_n > 0:
            self.indisponivel_n -= 1
            return _erro(503, "Service unavailable")
        if self.status_forcado:
            cab = {"Retry-After": self.retry_after} if self.retry_after else {}
            return _erro(self.status_forcado, "erro forçado no teste", **cab)
        caminho = req.url.path.removeprefix("/v1").removeprefix("/api/v1")
        autorizado = req.headers.get("authorization") == f"Bearer {self.chave}"
        if (req.method, caminho) == ("GET", "/key"):
            if not autorizado:
                return _erro(401, "No auth credentials found", 401)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "label": "sk-or-v1-abc...xyz",
                        "limit": None,
                        "limit_remaining": None,
                        "usage": 0.0,
                        "is_free_tier": True,
                        "free_model_daily_requests": {"used": 3, "limit": 50, "remaining": 47},
                    }
                },
            )
        if (req.method, caminho) == ("GET", "/models"):
            if self.exige_chave_em_models and not autorizado:
                return _erro(401, "Invalid API key", 401)
            if self.catalogo is not None:
                return httpx.Response(200, json=self.catalogo)
            return httpx.Response(
                200, json={"data": [{"id": m, "object": "model"} for m in self.modelos]}
            )
        if (req.method, caminho) == ("POST", "/chat/completions"):
            if self.exige_chave_em_chat and not autorizado:
                return _erro(401, "Invalid API key", 401)
            return self._chat(req)
        return _erro(404, "Rota inexistente.", 404)

    # ----------------------------------------------------------------------- chat
    def _chat(self, req: httpx.Request) -> httpx.Response:
        corpo = json.loads(req.content)
        self.corpos_chat.append(corpo)
        if self.rejeita_stream_options and "stream_options" in corpo:
            return _erro(400, "Unsupported field: stream_options", "invalid_request_error")
        if corpo.get("model") not in self.modelos:
            return _erro(404, f"The model `{corpo.get('model')}` does not exist", "model_not_found")
        mensagens = corpo.get("messages", [])
        if not mensagens or mensagens[-1].get("role") != "user":
            return _erro(400, "last message must be from user", 400)

        texto = self._responder(mensagens)
        pensando = bool(
            corpo.get("chat_template_kwargs", {}).get("enable_thinking")
            or corpo.get("reasoning", {}).get("enabled")
        )
        raciocinio = self.raciocinio_texto if pensando and "17 × 23" in str(mensagens) else ""

        if self.json_unico or corpo.get("stream") is False:
            mensagem: dict[str, Any] = {"role": "assistant", "content": texto}
            if raciocinio:
                mensagem["reasoning_content"] = raciocinio
            return httpx.Response(
                200,
                json={
                    "id": "cmpl-unico",
                    "model": corpo["model"],
                    "choices": [{"message": mensagem, "finish_reason": self.motivo_final}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 5},
                },
            )

        linhas = self._sse(corpo, texto, raciocinio)
        if self.queda_no_meio:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=FluxoQuebrado("".join(linhas[:3]).encode("utf-8")),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            content="".join(linhas).encode("utf-8"),
        )

    def _responder(self, mensagens: list[dict[str, str]]) -> str:
        ultima = mensagens[-1]["content"]
        sistema = " ".join(m["content"] for m in mensagens if m["role"] == "system")
        if "BANANA" in sistema and not self.ignora_system:
            return "BANANA"
        if "código secreto" in ultima:
            achado = re.search(r"AGULHA-[0-9A-F]{8}", ultima)
            if achado and not (self.limite_contexto and len(ultima) > self.limite_contexto):
                return achado.group(0)
            return "Não encontrei nenhum código."
        if "Repita exatamente" in ultima:
            return "ação, coração, não, é, ü"
        if "200 palavras" in ultima:
            return TEXTO_LONGO
        if "17 × 23" in ultima:
            return "A resposta final é 391."
        if "apenas com a palavra OK" in ultima:
            return "OK"
        return "Olá! Como posso ajudar?"

    def _sse(self, corpo: dict[str, Any], texto: str, raciocinio: str) -> list[str]:
        def dado(obj: dict[str, Any]) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        base = {"id": "cmpl-abc123", "model": corpo["model"]}
        saida = [": OPENROUTER PROCESSING\n\n"]
        for pedaco in _pedacos(raciocinio, 4):
            saida.append(
                dado({**base, "choices": [{"delta": {"reasoning_content": pedaco}, "index": 0}]})
            )
        partes = _pedacos(texto, 6 if self.incremental else 1)
        for i, pedaco in enumerate(partes):
            delta: dict[str, Any] = {"content": pedaco}
            if i == 0:
                delta["role"] = "assistant"
            saida.append(dado({**base, "choices": [{"delta": delta, "index": 0}]}))
            if self.erro_no_meio and i == 1:
                saida.append(
                    dado(
                        {
                            "error": self.erro_no_meio,
                            "choices": [{"delta": {"content": ""}, "finish_reason": "error"}],
                        }
                    )
                )
                return saida
        if self.cortar_sem_finish:
            return saida
        saida.append(
            dado(
                {
                    **base,
                    "choices": [{"delta": {}, "finish_reason": self.motivo_final, "index": 0}],
                }
            )
        )
        if self.cortar_com_finish_sem_done:
            return saida
        if self.usage and corpo.get("stream_options", {}).get("include_usage", True):
            saida.append(
                dado(
                    {
                        **base,
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 20,
                            "completion_tokens": max(len(texto) // 4, 1),
                        },
                    }
                )
            )
        saida.append("data: [DONE]\n\n")
        return saida


def _pedacos(texto: str, n: int) -> list[str]:
    """Divide em até ``n`` pedaços (mantendo a concatenação idêntica ao original)."""
    if not texto:
        return []
    tam = max(len(texto) // n, 1)
    return [texto[i : i + tam] for i in range(0, len(texto), tam)]
