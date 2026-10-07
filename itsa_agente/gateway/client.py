"""Cliente HTTP síncrono da API IAitsaGateway.

Responsabilidades:

- anexar o JWT (renovando-o de forma transparente) e os cabeçalhos de telemetria;
- converter respostas de erro em exceções tipadas (:mod:`itsa_agente.gateway.errors`);
- repetir **somente** o que é seguro repetir (ver "Política de retentativa");
- expor o streaming NDJSON como iterador de eventos tipados;
- oferecer ``sondar`` — uma primitiva de baixo nível, sem exceções, usada pela suíte de diagnóstico
  para observar o comportamento real do gateway (inclusive em cenários de erro).

Política de retentativa (ver ADR-0004): repete-se apenas (a) falha de **conexão** (a requisição
sequer foi enviada) e (b) HTTP **503** (o gateway declara que não processou), com espera
exponencial ou ``Retry-After``. Nunca se repete após *timeout de leitura* ou erro no meio do
streaming — a geração pode ter ocorrido e ser cobrada/duplicada. HTTP 401 em chamada autenticada
dispara **uma** reemissão do token e uma nova tentativa. 400/403/429 nunca são repetidos.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from itsa_agente import __version__
from itsa_agente.config import Settings
from itsa_agente.gateway.auth import GerenciadorToken, InfoToken
from itsa_agente.gateway.errors import (
    BadRequest,
    ConnectionFailed,
    Forbidden,
    GatewayError,
    LocalValidationError,
    ProtocolError,
    RateLimited,
    RequestTimeout,
    ServerError,
    ServiceUnavailable,
    StreamError,
    StreamInterrupted,
    Unauthorized,
)
from itsa_agente.gateway.models import (
    ApiErrorResponse,
    ChatRequest,
    Credenciais,
    EventoConcluido,
    EventoDelta,
    EventoErro,
    EventoStream,
    Mensagem,
    ModeloInfo,
    ModelsResponse,
    ResultadoChat,
)
from itsa_agente.gateway.ndjson import evento_de_linha, iterar_eventos

log = logging.getLogger("itsa_agente.client")

_MENSAGENS_PADRAO: dict[int, str] = {
    400: "Requisição inválida.",
    401: "Credencial ausente, inválida ou expirada.",
    403: "Acesso negado para esta credencial.",
    429: "Muitas requisições. Aguarde antes de tentar novamente.",
    503: "Serviço de IA temporariamente indisponível.",
}
_LIMITE_RETRY_AFTER_S = 10.0
_LIMITE_CORPO_ERRO = 64 * 1024


# --------------------------------------------------------------------------------------
# Conversão de respostas de erro
# --------------------------------------------------------------------------------------
def _retry_after(cabecalhos: Mapping[str, str]) -> float | None:
    bruto = cabecalhos.get("retry-after")
    if bruto is None:
        return None
    try:
        return max(float(bruto), 0.0)
    except ValueError:
        return None  # formato HTTP-date não é suportado: tratamos como ausente


def extrair_erro_api(status: int, corpo: str) -> tuple[str | None, str]:
    """Retorna ``(codigo, mensagem)`` a partir do corpo de uma resposta de erro."""
    try:
        erro = ApiErrorResponse.model_validate_json(corpo).error
    except (ValueError, ValidationError):
        erro = None
    codigo = erro.code if erro else None
    mensagem = (erro.message if erro else None) or _MENSAGENS_PADRAO.get(
        status, f"Falha na chamada ao gateway (HTTP {status})."
    )
    return codigo, mensagem


def erro_de_resposta(resposta: httpx.Response) -> GatewayError:
    """Mapeia uma resposta HTTP de erro (corpo já lido) para a exceção correspondente."""
    status = resposta.status_code
    codigo, mensagem = extrair_erro_api(status, resposta.text[:_LIMITE_CORPO_ERRO])
    comuns: dict[str, Any] = {"codigo": codigo, "status": status}
    if status == 400:
        return BadRequest(mensagem, **comuns)
    if status == 401:
        return Unauthorized(mensagem, **comuns)
    if status == 403:
        return Forbidden(mensagem, **comuns)
    if status == 429:
        return RateLimited(mensagem, retry_after=_retry_after(resposta.headers), **comuns)
    if status == 503:
        return ServiceUnavailable(mensagem, **comuns)
    if status >= 500:
        return ServerError(mensagem, **comuns)
    return GatewayError(mensagem, **comuns)


def _resumo_validacao(exc: ValidationError) -> str:
    """Resumo sem ecoar valores (podem conter texto do usuário)."""
    partes = []
    for erro in exc.errors(include_input=False, include_url=False):
        local = ".".join(str(p) for p in erro["loc"]) or "requisição"
        partes.append(f"{local}: {erro['msg']}")
    return "; ".join(partes)


# --------------------------------------------------------------------------------------
# Resultado de sondagem (diagnóstico)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RespostaSondagem:
    """Observação bruta de uma chamada, sem levantar exceção por status HTTP."""

    status: int | None
    cabecalhos: dict[str, str] = field(default_factory=dict)
    corpo: str = ""
    tempo_ms: float = 0.0
    erro_rede: str | None = None
    truncado: bool = False

    def json(self) -> Any | None:
        import json

        try:
            return json.loads(self.corpo)
        except ValueError:
            return None

    @property
    def codigo_erro(self) -> str | None:
        return extrair_erro_api(self.status or 0, self.corpo)[0] if self.status else None

    @property
    def mensagem_erro(self) -> str | None:
        if not self.status or self.status < 400:
            return None
        return extrair_erro_api(self.status, self.corpo)[1]

    def eventos(self) -> list[EventoStream]:
        """Eventos NDJSON do corpo (ignora linhas inválidas — é diagnóstico, não produção)."""
        resultado: list[EventoStream] = []
        for linha in self.corpo.splitlines():
            try:
                evento = evento_de_linha(linha)
            except ProtocolError:
                continue
            if evento is not None:
                resultado.append(evento)
        return resultado


# --------------------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------------------
class ClienteGateway:
    """Cliente síncrono do gateway. Uma instância por sessão de usuário."""

    def __init__(
        self,
        credenciais: Credenciais,
        configuracao: Settings | None = None,
        *,
        transporte: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cfg = configuracao or Settings.from_env()
        self._dormir = dormir
        self._relogio = relogio
        self._http = httpx.Client(
            base_url=self._cfg.base_url,
            verify=self._cfg.verify_tls,
            transport=transporte,
            timeout=httpx.Timeout(
                connect=self._cfg.connect_timeout,
                read=self._cfg.request_timeout,
                write=self._cfg.request_timeout,
                pool=self._cfg.connect_timeout,
            ),
            headers=self._cabecalhos_base(),
            follow_redirects=False,
        )
        self._token = GerenciadorToken(
            credenciais=credenciais,
            emitir=self._emitir_token,
            skew_s=self._cfg.token_skew_seconds,
            relogio=relogio,
        )
        self._cache_modelos: tuple[float, list[ModeloInfo]] | None = None

    # ------------------------------------------------------------ ciclo de vida
    def __enter__(self) -> ClienteGateway:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    def fechar(self) -> None:
        """Encerra conexões e descarta o token em memória."""
        self._token.invalidar()
        self._http.close()

    @property
    def configuracao(self) -> Settings:
        return self._cfg

    @property
    def credenciais(self) -> Credenciais:
        return self._token.credenciais

    # ---------------------------------------------------------------- cabeçalhos
    def _cabecalhos_base(self) -> dict[str, str]:
        cab = {
            "User-Agent": f"ITSA-Agente/{__version__}",
            "Accept": "application/x-ndjson, application/json;q=0.9, */*;q=0.1",
        }
        if self._cfg.erp_version:
            cab["X-Erp-Version"] = self._cfg.erp_version
        if self._cfg.chat_module_version:
            cab["X-Chat-Module-Version"] = self._cfg.chat_module_version
        if self._cfg.installation_id:
            cab["X-Installation-Id"] = self._cfg.installation_id
        return cab

    # ------------------------------------------------------------- transporte
    def _espera_backoff(self, tentativa: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, _LIMITE_RETRY_AFTER_S)
        return float(self._cfg.retry_backoff_base * (2**tentativa))

    def _enviar(
        self,
        metodo: str,
        caminho: str,
        *,
        json_corpo: Any | None = None,
        token: str | None = None,
        stream: bool = False,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        """Envia com a política de retentativa. Retorna a resposta, qualquer que seja o status."""
        tentativa = 0
        while True:
            requisicao = self._http.build_request(
                metodo,
                caminho,
                json=json_corpo,
                headers={"Authorization": f"Bearer {token}"} if token else None,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
            inicio = self._relogio()
            try:
                resposta = self._http.send(requisicao, stream=stream)
            except httpx.ConnectTimeout as exc:
                if tentativa < self._cfg.max_retries:
                    self._dormir(self._espera_backoff(tentativa, None))
                    tentativa += 1
                    continue
                raise ConnectionFailed(
                    "Tempo esgotado ao conectar ao gateway.", codigo="connect_timeout"
                ) from exc
            except httpx.ConnectError as exc:
                if tentativa < self._cfg.max_retries:
                    log.warning("Falha de conexão (tentativa %d): %s", tentativa + 1, exc)
                    self._dormir(self._espera_backoff(tentativa, None))
                    tentativa += 1
                    continue
                raise ConnectionFailed(
                    "Não foi possível conectar ao gateway (DNS, rede ou TLS).",
                    codigo="connect_error",
                ) from exc
            except httpx.TimeoutException as exc:
                raise RequestTimeout("O gateway não respondeu no tempo limite.") from exc
            except httpx.TransportError as exc:
                raise ConnectionFailed(
                    f"Falha de transporte na chamada ao gateway ({type(exc).__name__}).",
                    codigo="transport_error",
                ) from exc

            log.debug(
                "%s %s -> %s (%.0f ms)",
                metodo,
                caminho,
                resposta.status_code,
                (self._relogio() - inicio) * 1000,
            )
            if resposta.status_code == 503 and tentativa < self._cfg.max_retries:
                espera = self._espera_backoff(tentativa, _retry_after(resposta.headers))
                resposta.close()
                log.warning("Gateway indisponível (503); nova tentativa em %.1fs.", espera)
                self._dormir(espera)
                tentativa += 1
                continue
            return resposta

    def _enviar_autenticado(
        self,
        metodo: str,
        caminho: str,
        *,
        json_corpo: Any | None = None,
        stream: bool = False,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        """Anexa o JWT; em 401 reemite o token uma única vez e repete."""
        for reemitido in (False, True):
            jwt = self._token.obter()
            resposta = self._enviar(
                metodo, caminho, json_corpo=json_corpo, token=jwt, stream=stream, timeout=timeout
            )
            if resposta.status_code == 401 and not reemitido:
                resposta.close()
                log.info("401 em %s %s; reemitindo o token e repetindo uma vez.", metodo, caminho)
                self._token.invalidar()
                continue
            return resposta
        raise AssertionError("inalcançável")  # pragma: no cover

    def _emitir_token(self, credenciais: Credenciais) -> httpx.Response:
        resposta = self._enviar("POST", "/api/auth/token", json_corpo=credenciais.payload())
        if resposta.status_code != 200:
            raise erro_de_resposta(resposta)
        return resposta

    # ----------------------------------------------------------------- autenticação
    def autenticar(self) -> InfoToken:
        """Força a emissão de um novo JWT e retorna seu estado."""
        self._token.renovar()
        info = self._token.info()
        assert info is not None
        return info

    def info_token(self) -> InfoToken | None:
        return self._token.info()

    @property
    def autenticado(self) -> bool:
        return self._token.autenticado

    # ------------------------------------------------------------------- modelos
    def listar_modelos(self, *, forcar: bool = False) -> list[ModeloInfo]:
        """``GET /api/models`` com cache curto (``ITSA_MODELS_CACHE_SECONDS``)."""
        agora = self._relogio()
        if (
            not forcar
            and self._cache_modelos is not None
            and agora - self._cache_modelos[0] < self._cfg.models_cache_seconds
        ):
            return list(self._cache_modelos[1])

        resposta = self._enviar_autenticado("GET", "/api/models")
        try:
            if resposta.status_code != 200:
                raise erro_de_resposta(resposta)
            try:
                modelos = ModelsResponse.model_validate(resposta.json()).models
            except (ValueError, ValidationError) as exc:
                raise ProtocolError("Resposta de /api/models fora do contrato esperado.") from exc
        finally:
            resposta.close()
        self._cache_modelos = (agora, modelos)
        return list(modelos)

    # ---------------------------------------------------------------------- chat
    def montar_requisicao_chat(
        self,
        *,
        modelo: str,
        mensagens: Sequence[Mensagem],
        conversa_id: uuid.UUID | None = None,
    ) -> ChatRequest:
        """Valida localmente o contrato do swagger e devolve a requisição."""
        try:
            return ChatRequest(
                conversation_id=conversa_id or uuid.uuid4(),
                model=modelo,
                messages=list(mensagens),
            )
        except ValidationError as exc:
            raise LocalValidationError(
                f"Requisição de chat inválida — {_resumo_validacao(exc)}"
            ) from exc

    def transmitir_chat(
        self,
        *,
        modelo: str,
        mensagens: Sequence[Mensagem],
        conversa_id: uuid.UUID | None = None,
    ) -> Iterator[EventoStream]:
        """``POST /api/chat`` — itera os eventos até ``completed`` ou ``error`` (inclusive).

        A validação local e a abertura da conexão ocorrem **na chamada** (erros de contrato,
        autenticação e disponibilidade são levantados aqui, antes de qualquer evento). Fechar o
        iterador devolvido (ex.: usuário cancela) fecha a conexão HTTP.

        Raises:
            LocalValidationError, Unauthorized, Forbidden, BadRequest, ServiceUnavailable,
            ConnectionFailed, RequestTimeout: na chamada.
            StreamInterrupted: queda/timeout/corte durante o streaming.
            ProtocolError: linha malformada.
        """
        requisicao = self.montar_requisicao_chat(
            modelo=modelo, mensagens=mensagens, conversa_id=conversa_id
        )
        timeout = httpx.Timeout(
            connect=self._cfg.connect_timeout,
            read=self._cfg.stream_read_timeout,
            write=self._cfg.request_timeout,
            pool=self._cfg.connect_timeout,
        )
        # O tempo de leitura longo vale só para o chat; token/modelos usam os tempos curtos.
        resposta = self._enviar_autenticado(
            "POST", "/api/chat", json_corpo=requisicao.para_json(), stream=True, timeout=timeout
        )
        if resposta.status_code != 200:
            try:
                resposta.read()
                raise erro_de_resposta(resposta)
            finally:
                resposta.close()
        return self._consumir_stream(resposta)

    def _consumir_stream(self, resposta: httpx.Response) -> Iterator[EventoStream]:
        try:
            resposta.encoding = "utf-8"
            try:
                yield from iterar_eventos(resposta.iter_lines())
            except httpx.TimeoutException as exc:
                raise StreamInterrupted(
                    f"Sem dados do gateway por mais de {self._cfg.stream_read_timeout:.0f}s."
                ) from exc
            except httpx.TransportError as exc:
                raise StreamInterrupted(
                    f"Conexão interrompida durante o streaming ({type(exc).__name__})."
                ) from exc
        finally:
            resposta.close()

    def conversar(
        self,
        *,
        modelo: str,
        mensagens: Sequence[Mensagem],
        conversa_id: uuid.UUID | None = None,
    ) -> ResultadoChat:
        """Chat completo (consome o streaming e devolve o texto agregado).

        Raises:
            StreamError: o gateway enviou evento ``error``.
            (demais exceções de :meth:`transmitir_chat`)
        """
        id_conversa = conversa_id or uuid.uuid4()
        inicio = self._relogio()
        primeiro: float | None = None
        trechos: list[str] = []
        concluido: EventoConcluido | None = None
        request_id: str | None = None

        for evento in self.transmitir_chat(
            modelo=modelo, mensagens=mensagens, conversa_id=id_conversa
        ):
            if getattr(evento, "request_id", None):
                request_id = evento.request_id  # type: ignore[union-attr]
            if isinstance(evento, EventoDelta):
                if primeiro is None:
                    primeiro = self._relogio() - inicio
                trechos.append(evento.content)
            elif isinstance(evento, EventoErro):
                raise StreamError(
                    evento.mensagem or "O gateway reportou erro durante a geração.",
                    codigo=evento.codigo,
                    request_id=evento.request_id or request_id,
                )
            elif isinstance(evento, EventoConcluido):
                concluido = evento
        if concluido is None:  # pragma: no cover - iterar_eventos já garante terminal
            raise StreamInterrupted("Streaming encerrado sem 'completed'.")
        return ResultadoChat(
            texto="".join(trechos),
            request_id=request_id,
            model=concluido.model,
            conversation_id=id_conversa,
            usage=concluido.usage,
            tempo_total_s=self._relogio() - inicio,
            tempo_primeiro_trecho_s=primeiro,
            trechos=len(trechos),
        )

    # ------------------------------------------------------------- diagnóstico
    def sondar(
        self,
        metodo: str,
        caminho: str,
        *,
        json_corpo: Any | None = None,
        conteudo_bruto: bytes | None = None,
        cabecalhos: Mapping[str, str] | None = None,
        token: str | Literal["auto"] | None = "auto",  # noqa: S107
        limite_corpo: int = 1_000_000,
        timeout_s: float | None = None,
    ) -> RespostaSondagem:
        """Faz uma chamada e **descreve** o resultado, sem lançar exceção por status/rede.

        ``token``: ``"auto"`` usa o JWT válido; ``None`` não envia Authorization; qualquer outra
        string é enviada literalmente (ex.: token adulterado). Sem retentativas — é observação.
        """
        cab: dict[str, str] = dict(cabecalhos or {})
        if token == "auto":  # noqa: S105
            cab["Authorization"] = f"Bearer {self._token.obter()}"
        elif token is not None:
            cab["Authorization"] = f"Bearer {token}"

        timeout = (
            httpx.Timeout(timeout_s, connect=self._cfg.connect_timeout)
            if timeout_s is not None
            else httpx.Timeout(
                connect=self._cfg.connect_timeout,
                read=self._cfg.stream_read_timeout,
                write=self._cfg.request_timeout,
                pool=self._cfg.connect_timeout,
            )
        )
        inicio = self._relogio()
        try:
            requisicao = self._http.build_request(
                metodo,
                caminho,
                json=json_corpo if conteudo_bruto is None else None,
                content=conteudo_bruto,
                headers=cab,
                timeout=timeout,
            )
            resposta = self._http.send(requisicao, stream=True)
            try:
                bloco: list[bytes] = []
                lido = 0
                truncado = False
                for pedaco in resposta.iter_bytes():
                    lido += len(pedaco)
                    bloco.append(pedaco)
                    if lido >= limite_corpo:
                        truncado = True
                        break
                return RespostaSondagem(
                    status=resposta.status_code,
                    cabecalhos={k.lower(): v for k, v in resposta.headers.items()},
                    corpo=b"".join(bloco).decode("utf-8", errors="replace"),
                    tempo_ms=(self._relogio() - inicio) * 1000,
                    truncado=truncado,
                )
            finally:
                resposta.close()
        except httpx.HTTPError as exc:
            return RespostaSondagem(
                status=None,
                tempo_ms=(self._relogio() - inicio) * 1000,
                erro_rede=f"{type(exc).__name__}: {exc}",
            )
