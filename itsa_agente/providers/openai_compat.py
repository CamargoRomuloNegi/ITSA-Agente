"""Cliente genérico para APIs de chat compatíveis com a da OpenAI (NVIDIA, OpenRouter).

Contrato usado (``POST {base_url}/chat/completions``, ``Authorization: Bearer <chave>``)::

    {"model": "...", "messages": [{"role": "...", "content": "..."}], "stream": true,
     "max_tokens": N, "stream_options": {"include_usage": true}, ...extras do provedor}

A resposta é SSE (ver :mod:`itsa_agente.providers.sse`). Decisões de engenharia:

- **chave só em memória**: registrada no redator global, enviada somente no cabeçalho
  ``Authorization`` e nunca presente em ``repr``, log ou relatório;
- **retentativa** apenas onde é seguro: falha ao *conectar* e HTTP 502/503/504 (antes do primeiro
  byte da resposta). Nunca após timeout de leitura nem no meio do stream; 429 não é repetido —
  o tempo de espera é informado ao usuário (mesma lógica do ADR-0004);
- ``stream_options.include_usage`` é pedido para obter o consumo de tokens; se o provedor o recusar
  (HTTP 400 citando o campo), repete-se **uma vez** sem ele;
- erros convertidos na hierarquia :class:`GatewayError` do gateway, com ``provedor`` preenchido.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from itsa_agente import __version__
from itsa_agente.config import Settings
from itsa_agente.gateway.errors import (
    ConnectionFailed,
    GatewayError,
    LocalValidationError,
    ProtocolError,
    RequestTimeout,
    StreamInterrupted,
)
from itsa_agente.gateway.models import EventoStream, Mensagem
from itsa_agente.providers.base import ModeloCatalogo, OpcoesGeracao
from itsa_agente.providers.erros import (
    LIMITE_RETRY_AFTER_S,
    erro_de_resposta,
    extrair_erro_openai,
    retry_after,
)
from itsa_agente.providers.sse import DecodificadorSSE, eventos_de_resposta_unica
from itsa_agente.security import redator_global

log = logging.getLogger("itsa_agente.provedor")

_STATUS_RETENTAVEIS = {502, 503, 504}


@dataclass(frozen=True, slots=True)
class RespostaProvedor:
    """Observação bruta de uma chamada (diagnóstico): não levanta exceção por status HTTP."""

    status: int | None
    corpo: str = ""
    tempo_ms: float = 0.0
    erro_rede: str | None = None

    @property
    def codigo_erro(self) -> str | None:
        if not self.status or self.status < 400:
            return None
        return extrair_erro_openai(self.status, self.corpo)[0]

    @property
    def mensagem_erro(self) -> str | None:
        if not self.status or self.status < 400:
            return None
        return extrair_erro_openai(self.status, self.corpo)[1]

    @property
    def corpo_resumo(self) -> str | None:
        if not self.status or self.status < 400:
            return None
        return redator_global().aplicar(" ".join(self.corpo.split()))[:300]


def validar_chave(rotulo: str, chave: str) -> str:
    """Normaliza e valida (localmente) uma chave de API digitada pelo usuário."""
    limpa = (chave or "").strip()
    if not limpa:
        raise LocalValidationError(f"A chave de API de {rotulo} é obrigatória.")
    if any(c.isspace() for c in limpa) or not limpa.isascii():
        raise LocalValidationError(
            f"A chave de API de {rotulo} contém espaços ou caracteres inválidos. "
            "Copie-a novamente, sem quebras de linha."
        )
    return limpa


class ClienteOpenAICompat:
    """Base dos provedores externos. Subclasses definem ``listar_modelos`` e ``_extras``."""

    id_provedor = "externo"
    rotulo = "Provedor externo"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        configuracao: Settings,
        cabecalhos: dict[str, str] | None = None,
        transporte: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._chave = validar_chave(self.rotulo, api_key)
        redator_global().registrar(self._chave)
        self._cfg = configuracao
        self._dormir = dormir
        self._relogio = relogio
        self._http = httpx.Client(
            base_url=base_url,
            verify=configuracao.verify_tls,
            transport=transporte,
            timeout=httpx.Timeout(
                connect=configuracao.connect_timeout,
                read=configuracao.stream_read_timeout,
                write=configuracao.request_timeout,
                pool=configuracao.connect_timeout,
            ),
            headers={
                "User-Agent": f"ITSA-Agente/{__version__}",
                "Accept": "text/event-stream, application/json;q=0.9",
                **(cabecalhos or {}),
            },
            follow_redirects=False,
        )

    def __repr__(self) -> str:  # nunca expõe a chave
        return f"<{type(self).__name__} {self.id_provedor}>"

    # ------------------------------------------------------------ ciclo de vida
    def __enter__(self) -> ClienteOpenAICompat:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    def fechar(self) -> None:
        self._http.close()

    @property
    def configuracao(self) -> Settings:
        return self._cfg

    @property
    def base_url(self) -> str:
        return str(self._http.base_url).rstrip("/")

    # ------------------------------------------------------- pontos de extensão
    def listar_modelos(self, *, forcar: bool = False) -> list[ModeloCatalogo]:
        raise NotImplementedError

    def _extras(self, modelo: str, opcoes: OpcoesGeracao) -> dict[str, Any]:
        """Campos específicos do provedor a mesclar no corpo do chat."""
        return {}

    # -------------------------------------------------------------- transporte
    def _espera(self, tentativa: int, espera_servidor: float | None) -> float:
        if espera_servidor is not None:
            return min(espera_servidor, LIMITE_RETRY_AFTER_S)
        return float(self._cfg.retry_backoff_base * (2**tentativa))

    def _enviar(
        self,
        metodo: str,
        caminho: str,
        *,
        json_corpo: Any | None = None,
        stream: bool = False,
        timeout: httpx.Timeout | None = None,
        chave: str | None = None,
    ) -> httpx.Response:
        """Envia com a política de retentativa. Devolve a resposta qualquer que seja o status."""
        tentativa = 0
        while True:
            requisicao = self._http.build_request(
                metodo,
                caminho,
                json=json_corpo,
                headers={"Authorization": f"Bearer {chave or self._chave}"},
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
            inicio = self._relogio()
            try:
                resposta = self._http.send(requisicao, stream=stream)
            except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
                if tentativa < self._cfg.max_retries:
                    log.warning(
                        "%s: falha de conexão (tentativa %d): %s",
                        self.id_provedor,
                        tentativa + 1,
                        type(exc).__name__,
                    )
                    self._dormir(self._espera(tentativa, None))
                    tentativa += 1
                    continue
                raise ConnectionFailed(
                    f"Não foi possível conectar a {self.rotulo} (DNS, rede ou TLS).",
                    codigo="connect_error",
                    provedor=self.id_provedor,
                ) from exc
            except httpx.TimeoutException as exc:
                raise RequestTimeout(
                    f"{self.rotulo} não respondeu no tempo limite.", provedor=self.id_provedor
                ) from exc
            except httpx.TransportError as exc:
                raise ConnectionFailed(
                    f"Falha de transporte na chamada a {self.rotulo} ({type(exc).__name__}).",
                    codigo="transport_error",
                    provedor=self.id_provedor,
                ) from exc

            log.debug(
                "%s %s %s -> %s (%.0f ms)",
                self.id_provedor,
                metodo,
                caminho,
                resposta.status_code,
                (self._relogio() - inicio) * 1000,
            )
            if resposta.status_code in _STATUS_RETENTAVEIS and tentativa < self._cfg.max_retries:
                espera = self._espera(tentativa, retry_after(resposta.headers))
                resposta.close()
                log.warning(
                    "%s: HTTP %s; nova tentativa em %.1fs.",
                    self.id_provedor,
                    resposta.status_code,
                    espera,
                )
                self._dormir(espera)
                tentativa += 1
                continue
            return resposta

    # ----------------------------------------------------------------- verificação
    def verificar(self) -> None:
        """Confere se a chave é aceita pelo provedor.

        Implementação padrão: ``GET /models``. **Atenção:** em vários provedores essa lista é
        pública (verificado na NVIDIA e no OpenRouter), logo uma chave errada passaria. As
        subclasses sobrescrevem este método com uma chamada que realmente exige a chave.
        """
        resposta = self._enviar(
            "GET", "/models", timeout=httpx.Timeout(self._cfg.request_timeout, connect=10)
        )
        try:
            if resposta.status_code != 200:
                raise erro_de_resposta(resposta, self.id_provedor)
        finally:
            resposta.close()

    # --------------------------------------------------------------------- chat
    def corpo_chat(
        self,
        modelo: str,
        mensagens: Sequence[Mensagem],
        opcoes: OpcoesGeracao | None = None,
        *,
        incluir_uso: bool = True,
    ) -> dict[str, Any]:
        opcoes = opcoes or OpcoesGeracao()
        corpo: dict[str, Any] = {
            "model": modelo,
            "messages": [{"role": m.role, "content": m.content} for m in mensagens],
            "stream": True,
            "max_tokens": opcoes.max_tokens or self._cfg.provider_max_tokens,
        }
        if incluir_uso:
            corpo["stream_options"] = {"include_usage": True}
        if opcoes.temperatura is not None:
            corpo["temperature"] = opcoes.temperatura
        corpo.update(self._extras(modelo, opcoes))
        return corpo

    def transmitir_chat(
        self,
        *,
        modelo: str,
        mensagens: Sequence[Mensagem],
        conversa_id: uuid.UUID | None = None,
        opcoes: OpcoesGeracao | None = None,
    ) -> Iterator[EventoStream]:
        """Envia a conversa e gera os eventos do streaming (mesmo vocabulário do gateway).

        ``conversa_id`` é aceito por compatibilidade com o gateway e ignorado: as APIs
        compatíveis com a OpenAI não mantêm conversa no servidor.
        """
        if not mensagens or mensagens[-1].role != "user":
            raise LocalValidationError("A última mensagem deve ser do usuário.")
        return self._gerar(modelo, mensagens, opcoes)

    def _gerar(
        self, modelo: str, mensagens: Sequence[Mensagem], opcoes: OpcoesGeracao | None
    ) -> Iterator[EventoStream]:
        corpo = self.corpo_chat(modelo, mensagens, opcoes)
        resposta = self._enviar("POST", "/chat/completions", json_corpo=corpo, stream=True)
        if resposta.status_code == 400 and "stream_options" in corpo:
            resposta.read()
            if "stream_options" in resposta.text.lower():
                resposta.close()
                log.info(
                    "%s: sem suporte a stream_options; repetindo sem o campo.", self.id_provedor
                )
                corpo = self.corpo_chat(modelo, mensagens, opcoes, incluir_uso=False)
                resposta = self._enviar("POST", "/chat/completions", json_corpo=corpo, stream=True)
        try:
            if resposta.status_code != 200:
                resposta.read()
                raise erro_de_resposta(resposta, self.id_provedor)
            tipo = resposta.headers.get("content-type", "").lower()
            if "json" in tipo and "event-stream" not in tipo:
                resposta.read()
                try:
                    objeto = resposta.json()
                except ValueError as exc:
                    raise ProtocolError(
                        f"Resposta de {self.rotulo} não é JSON válido.", provedor=self.id_provedor
                    ) from exc
                if not isinstance(objeto, dict):
                    raise ProtocolError(
                        f"Resposta de {self.rotulo} fora do formato esperado.",
                        provedor=self.id_provedor,
                    )
                yield from eventos_de_resposta_unica(objeto)
                return
            decodificador = DecodificadorSSE()
            try:
                for linha in resposta.iter_lines():
                    yield from decodificador.alimentar(linha)
                    if decodificador.terminou:
                        return
                yield from decodificador.finalizar()
            except httpx.TimeoutException as exc:
                raise RequestTimeout(
                    f"{self.rotulo} ficou em silêncio além do tempo limite durante a resposta.",
                    provedor=self.id_provedor,
                ) from exc
            except httpx.TransportError as exc:
                raise StreamInterrupted(
                    "A conexão foi interrompida durante a resposta.", provedor=self.id_provedor
                ) from exc
            except GatewayError as exc:
                exc.provedor = exc.provedor or self.id_provedor
                raise
        finally:
            resposta.close()

    # ------------------------------------------------------------- diagnóstico
    def sondar(
        self,
        metodo: str,
        caminho: str,
        *,
        json_corpo: Any | None = None,
        chave: str | None = None,
    ) -> RespostaProvedor:
        """Chamada crua para o diagnóstico: devolve status/corpo sem levantar por status HTTP."""
        inicio = time.perf_counter()
        try:
            resposta = self._enviar(metodo, caminho, json_corpo=json_corpo, chave=chave)
        except GatewayError as exc:
            return RespostaProvedor(
                status=None,
                tempo_ms=(time.perf_counter() - inicio) * 1000,
                erro_rede=exc.mensagem,
            )
        try:
            corpo = resposta.text[:65536]
        finally:
            resposta.close()
        return RespostaProvedor(
            status=resposta.status_code,
            corpo=corpo,
            tempo_ms=(time.perf_counter() - inicio) * 1000,
        )
