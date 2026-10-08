"""Provedor OpenRouter (openrouter.ai): agregador de modelos compatível com a API da OpenAI.

Particularidades tratadas (documentação do OpenRouter):

- ``HTTP-Referer`` e ``X-Title`` identificam o aplicativo (opcionais);
- o stream pode conter comentários SSE (``: OPENROUTER PROCESSING``) — ignorados pelo decodificador;
- erros podem chegar **no meio do stream** como ``data: {"error": {...}}``;
- ``usage`` vem em um único objeto ao final, com ``choices`` vazio;
- ``provider.data_collection = "deny"`` restringe o roteamento a provedores que não coletam dados
  (opcional: ``ITSA_OPENROUTER_DATA_COLLECTION``);
- ``reasoning.enabled`` liga/desliga o raciocínio em modelos que o suportam; só é enviado quando o
  usuário escolhe explicitamente (``OpcoesGeracao.raciocinio`` diferente de ``None``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from itsa_agente.config import Settings
from itsa_agente.gateway.errors import ProtocolError
from itsa_agente.providers.base import (
    PROVEDOR_OPENROUTER,
    ModeloCatalogo,
    OpcoesGeracao,
    qualificar,
)
from itsa_agente.providers.erros import erro_de_resposta
from itsa_agente.providers.openai_compat import ClienteOpenAICompat
from itsa_agente.security import redator_global

_CACHE_CATALOGO_S = 600.0


@dataclass(frozen=True, slots=True)
class InfoChave:
    """Dados seguros de ``GET /key`` (a chave em si nunca é devolvida pelo provedor)."""

    rotulo: str | None = None
    creditos_restantes: float | None = None  # ``None`` = sem limite de créditos na chave
    gratuitos_usados: int | None = None  # requisições a modelos ``:free`` hoje
    gratuitos_limite: int | None = None


def _numero(valor: Any) -> float | None:
    return float(valor) if isinstance(valor, int | float) and not isinstance(valor, bool) else None


def info_de_resposta(corpo: Any) -> InfoChave:
    dados = corpo.get("data") if isinstance(corpo, dict) else None
    if not isinstance(dados, dict):
        raise ProtocolError(
            "A resposta de GET /key do OpenRouter veio fora do formato esperado.",
            provedor=PROVEDOR_OPENROUTER,
        )
    gratis = dados.get("free_model_daily_requests")
    gratis = gratis if isinstance(gratis, dict) else {}
    usados, limite = _numero(gratis.get("used")), _numero(gratis.get("limit"))
    rotulo = dados.get("label")
    # Sem rótulo dado pelo usuário, o OpenRouter devolve um trecho da própria chave
    # ("sk-or-v1-abc…xyz"): descartamos para não exibir nem guardar fragmentos de segredo.
    if not isinstance(rotulo, str) or rotulo.lower().startswith("sk-or"):
        rotulo = None
    return InfoChave(
        rotulo=redator_global().aplicar(rotulo)[:60] if rotulo else None,
        creditos_restantes=_numero(dados.get("limit_remaining")),
        gratuitos_usados=None if usados is None else int(usados),
        gratuitos_limite=None if limite is None else int(limite),
    )


def _preco_zero(valor: Any) -> bool | None:
    try:
        return float(valor) == 0.0
    except (TypeError, ValueError):
        return None


def modelos_de_resposta(corpo: Any) -> list[ModeloCatalogo]:
    """Converte a resposta de ``GET /models`` do OpenRouter em :class:`ModeloCatalogo`."""
    dados = corpo.get("data") if isinstance(corpo, dict) else None
    if not isinstance(dados, list):
        raise ProtocolError(
            "A lista de modelos do OpenRouter veio fora do formato esperado.",
            provedor=PROVEDOR_OPENROUTER,
        )
    modelos: list[ModeloCatalogo] = []
    for item in dados:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        arquitetura = item.get("architecture")
        saidas: Any = (
            arquitetura.get("output_modalities") if isinstance(arquitetura, dict) else None
        )
        if isinstance(saidas, list) and "text" not in saidas:
            continue  # modelos que não geram texto (imagem, áudio) não servem ao chat
        bruto_precos = item.get("pricing")
        precos: dict[str, Any] = bruto_precos if isinstance(bruto_precos, dict) else {}
        p, c = _preco_zero(precos.get("prompt")), _preco_zero(precos.get("completion"))
        contexto = item.get("context_length")
        modelos.append(
            ModeloCatalogo(
                id=qualificar(PROVEDOR_OPENROUTER, item["id"]),
                rotulo=str(item.get("name") or item["id"]),
                provedor=PROVEDOR_OPENROUTER,
                externo=True,
                contexto=contexto if isinstance(contexto, int) else None,
                gratuito=None if p is None or c is None else (p and c),
            )
        )
    modelos.sort(key=lambda m: (not m.gratuito, m.rotulo.lower()))
    return modelos


class ProvedorOpenRouter(ClienteOpenAICompat):
    id_provedor = PROVEDOR_OPENROUTER
    rotulo = "OpenRouter"

    def __init__(self, api_key: str, configuracao: Settings, **kwargs: Any) -> None:
        cabecalhos = {"X-Title": configuracao.openrouter_title}
        if configuracao.openrouter_referer:
            cabecalhos["HTTP-Referer"] = configuracao.openrouter_referer
        super().__init__(
            api_key=api_key,
            base_url=configuracao.openrouter_base_url,
            configuracao=configuracao,
            cabecalhos=cabecalhos,
            **kwargs,
        )
        self._cache: tuple[float, list[ModeloCatalogo]] | None = None
        #: Preenchido por :meth:`verificar` (conta, créditos e cota diária de modelos ``:free``).
        self.info_chave: InfoChave | None = None

    def verificar(self) -> None:
        """Valida a chave com ``GET /key`` (exige a chave, ao contrário de ``GET /models``)."""
        resposta = self._enviar(
            "GET", "/key", timeout=httpx.Timeout(self._cfg.request_timeout, connect=10)
        )
        try:
            resposta.read()
            if resposta.status_code != 200:
                raise erro_de_resposta(resposta, self.id_provedor)
            try:
                self.info_chave = info_de_resposta(resposta.json())
            except ValueError as exc:
                raise ProtocolError(
                    "A resposta de GET /key do OpenRouter não é JSON válido.",
                    provedor=self.id_provedor,
                ) from exc
        finally:
            resposta.close()

    def listar_modelos(self, *, forcar: bool = False) -> list[ModeloCatalogo]:
        agora = time.monotonic()
        if not forcar and self._cache and agora - self._cache[0] < _CACHE_CATALOGO_S:
            return list(self._cache[1])
        resposta = self._enviar(
            "GET", "/models", timeout=httpx.Timeout(self._cfg.request_timeout, connect=10)
        )
        try:
            resposta.read()
            if resposta.status_code != 200:
                raise erro_de_resposta(resposta, self.id_provedor)
            try:
                corpo = resposta.json()
            except ValueError as exc:
                raise ProtocolError(
                    "A lista de modelos do OpenRouter não é JSON válido.",
                    provedor=self.id_provedor,
                ) from exc
        finally:
            resposta.close()
        modelos = modelos_de_resposta(corpo)
        self._cache = (agora, modelos)
        return list(modelos)

    def _extras(self, modelo: str, opcoes: OpcoesGeracao) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        if opcoes.raciocinio is not None:
            extras["reasoning"] = {"enabled": opcoes.raciocinio}
        if self._cfg.openrouter_data_collection:
            extras["provider"] = {"data_collection": self._cfg.openrouter_data_collection}
        return extras
