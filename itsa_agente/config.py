"""Configuração da aplicação.

A configuração vem, em ordem de precedência crescente, de: valores padrão, arquivo ``.env``
na raiz do projeto e variáveis de ambiente ``ITSA_*``. Nenhuma dependência externa é usada
para ler o ``.env`` (parser mínimo abaixo), mantendo a pasta executável sem instalações extras.

O **Token ID nunca é lido de arquivo por padrão** — ver ``docs/sdd/05-seguranca-e-guardrails.md``.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from itsa_agente.gateway.errors import ConfigurationError

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
URL_PADRAO = "https://suporteitsa2.ddns.net"
URL_NVIDIA_PADRAO = "https://integrate.api.nvidia.com/v1"
URL_OPENROUTER_PADRAO = "https://openrouter.ai/api/v1"
#: Modelos NVIDIA oferecidos por padrão (o catálogo da NVIDIA tem centenas; o usuário pode
#: informar outro ID na tela ou em ``ITSA_NVIDIA_MODELS``).
MODELOS_NVIDIA_PADRAO = ("nvidia/nemotron-3-ultra-550b-a55b",)

#: Limite documentado para os cabeçalhos de versão (swagger do gateway).
LIMITE_CABECALHO_VERSAO = 50

_LINHA_ENV = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_VERDADEIROS = {"1", "true", "t", "yes", "y", "sim", "s", "on"}
_FALSOS = {"0", "false", "f", "no", "n", "nao", "não", "off"}


def ler_arquivo_env(caminho: Path) -> dict[str, str]:
    """Lê um arquivo ``.env`` simples (``CHAVE=valor``, comentários com ``#``).

    Aceita aspas simples/duplas ao redor do valor. Retorna ``{}`` se o arquivo não existir.
    """
    if not caminho.is_file():
        return {}
    valores: dict[str, str] = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        casou = _LINHA_ENV.match(linha)
        if not casou:
            continue
        chave, valor = casou.groups()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        elif " #" in valor:  # comentário inline em valor sem aspas
            valor = valor.split(" #", 1)[0].rstrip()
        valores[chave] = valor
    return valores


def _texto(ambiente: Mapping[str, str], chave: str, padrao: str = "") -> str:
    return ambiente.get(chave, padrao).strip()


def _numero(ambiente: Mapping[str, str], chave: str, padrao: float, minimo: float) -> float:
    bruto = _texto(ambiente, chave)
    if not bruto:
        return padrao
    try:
        valor = float(bruto.replace(",", "."))
    except ValueError as exc:
        raise ConfigurationError(f"{chave} deve ser numérico (recebido: {bruto!r}).") from exc
    if valor < minimo:
        raise ConfigurationError(f"{chave} deve ser >= {minimo} (recebido: {valor}).")
    return valor


def _inteiro(ambiente: Mapping[str, str], chave: str, padrao: int, minimo: int) -> int:
    return int(_numero(ambiente, chave, float(padrao), float(minimo)))


def _lista(ambiente: Mapping[str, str], chave: str, padrao: tuple[str, ...]) -> tuple[str, ...]:
    """Lista separada por vírgula (ou ponto e vírgula); vazio mantém o padrão."""
    itens = tuple(i.strip() for i in re.split(r"[,;]", _texto(ambiente, chave)) if i.strip())
    return itens or padrao


def _booleano(ambiente: Mapping[str, str], chave: str, padrao: bool) -> bool:
    bruto = _texto(ambiente, chave).lower()
    if not bruto:
        return padrao
    if bruto in _VERDADEIROS:
        return True
    if bruto in _FALSOS:
        return False
    raise ConfigurationError(f"{chave} deve ser booleano (recebido: {bruto!r}).")


@dataclass(frozen=True, slots=True)
class Settings:
    """Parâmetros de execução, imutáveis. Use :meth:`Settings.from_env` para carregar."""

    base_url: str = URL_PADRAO
    verify_tls: bool = True

    connect_timeout: float = 10.0
    request_timeout: float = 30.0
    stream_read_timeout: float = 120.0

    max_retries: int = 2
    retry_backoff_base: float = 0.5
    token_skew_seconds: int = 60
    models_cache_seconds: int = 60

    max_history_chars: int = 24_000

    erp_version: str | None = None
    chat_module_version: str | None = None
    installation_id: str | None = None

    # Valores de conveniência para pré-preencher a tela de conexão (nunca o Token ID).
    cpf_cnpj_padrao: str = ""
    usuario_erp_padrao: str = ""
    token_id_dev: str = field(default="", repr=False)

    log_level: str = "INFO"

    # Provedores externos (opcionais). As chaves de API NUNCA ficam aqui: são digitadas na tela.
    nvidia_base_url: str = URL_NVIDIA_PADRAO
    nvidia_models: tuple[str, ...] = MODELOS_NVIDIA_PADRAO
    openrouter_base_url: str = URL_OPENROUTER_PADRAO
    openrouter_referer: str | None = None
    openrouter_title: str = "ITSA-Agente"
    #: ``deny`` pede ao OpenRouter só provedores que não coletam dados; ``None`` não envia nada.
    openrouter_data_collection: str | None = None
    #: Teto de tokens de saída enviado aos provedores externos (inclui o raciocínio).
    provider_max_tokens: int = 8192

    def __post_init__(self) -> None:
        url = self.base_url.strip().rstrip("/")
        if not re.match(r"^https?://[^\s/]+", url):
            raise ConfigurationError(f"ITSA_BASE_URL inválida: {self.base_url!r}.")
        object.__setattr__(self, "base_url", url)

        for nome, valor in (
            ("ITSA_ERP_VERSION", self.erp_version),
            ("ITSA_CHAT_MODULE_VERSION", self.chat_module_version),
        ):
            if valor is not None and len(valor) > LIMITE_CABECALHO_VERSAO:
                raise ConfigurationError(
                    f"{nome} excede {LIMITE_CABECALHO_VERSAO} caracteres (limite do gateway)."
                )
        if self.installation_id is not None:
            try:
                uuid.UUID(self.installation_id)
            except ValueError as exc:
                raise ConfigurationError("ITSA_INSTALLATION_ID deve ser um GUID válido.") from exc

        for nome, valor in (
            ("ITSA_NVIDIA_BASE_URL", self.nvidia_base_url),
            ("ITSA_OPENROUTER_BASE_URL", self.openrouter_base_url),
        ):
            if not re.match(r"^https?://[^\s/]+", valor.strip()):
                raise ConfigurationError(f"{nome} inválida: {valor!r}.")
        object.__setattr__(self, "nvidia_base_url", self.nvidia_base_url.strip().rstrip("/"))
        object.__setattr__(
            self, "openrouter_base_url", self.openrouter_base_url.strip().rstrip("/")
        )
        if self.openrouter_data_collection not in (None, "allow", "deny"):
            raise ConfigurationError(
                "ITSA_OPENROUTER_DATA_COLLECTION deve ser 'allow' ou 'deny' "
                f"(recebido: {self.openrouter_data_collection!r})."
            )
        if self.provider_max_tokens < 16:
            raise ConfigurationError("ITSA_PROVIDER_MAX_TOKENS deve ser >= 16.")

        nivel = self.log_level.upper()
        if nivel not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError(f"ITSA_LOG_LEVEL inválido: {self.log_level!r}.")
        object.__setattr__(self, "log_level", nivel)

    @property
    def url_token(self) -> str:
        return f"{self.base_url}/api/auth/token"

    def com(self, **alteracoes: object) -> Settings:
        """Cópia com campos alterados (a classe é imutável)."""
        return replace(self, **alteracoes)  # type: ignore[arg-type]

    @classmethod
    def from_env(
        cls,
        ambiente: Mapping[str, str] | None = None,
        *,
        arquivo_env: Path | None = None,
    ) -> Settings:
        """Carrega a configuração.

        ``ambiente`` permite injetar um mapa (testes). Se ``None``, usa ``os.environ`` mesclado
        sobre o ``.env`` da raiz do projeto.
        """
        if ambiente is None:
            base = ler_arquivo_env(arquivo_env or (RAIZ_PROJETO / ".env"))
            base.update(os.environ)
            ambiente = base

        def opcional(chave: str) -> str | None:
            return _texto(ambiente, chave) or None

        return cls(
            base_url=_texto(ambiente, "ITSA_BASE_URL", URL_PADRAO) or URL_PADRAO,
            verify_tls=_booleano(ambiente, "ITSA_VERIFY_TLS", True),
            connect_timeout=_numero(ambiente, "ITSA_CONNECT_TIMEOUT", 10.0, 0.1),
            request_timeout=_numero(ambiente, "ITSA_REQUEST_TIMEOUT", 30.0, 0.1),
            stream_read_timeout=_numero(ambiente, "ITSA_STREAM_READ_TIMEOUT", 120.0, 1.0),
            max_retries=_inteiro(ambiente, "ITSA_MAX_RETRIES", 2, 0),
            token_skew_seconds=_inteiro(ambiente, "ITSA_TOKEN_SKEW_SECONDS", 60, 0),
            models_cache_seconds=_inteiro(ambiente, "ITSA_MODELS_CACHE_SECONDS", 60, 0),
            max_history_chars=_inteiro(ambiente, "ITSA_MAX_HISTORY_CHARS", 24_000, 500),
            erp_version=opcional("ITSA_ERP_VERSION"),
            chat_module_version=opcional("ITSA_CHAT_MODULE_VERSION"),
            installation_id=opcional("ITSA_INSTALLATION_ID"),
            cpf_cnpj_padrao=_texto(ambiente, "ITSA_CPF_CNPJ"),
            usuario_erp_padrao=_texto(ambiente, "ITSA_ERP_USER"),
            token_id_dev=_texto(ambiente, "ITSA_TOKEN_ID"),
            log_level=_texto(ambiente, "ITSA_LOG_LEVEL", "INFO") or "INFO",
            nvidia_base_url=_texto(ambiente, "ITSA_NVIDIA_BASE_URL", URL_NVIDIA_PADRAO)
            or URL_NVIDIA_PADRAO,
            nvidia_models=_lista(ambiente, "ITSA_NVIDIA_MODELS", MODELOS_NVIDIA_PADRAO),
            openrouter_base_url=_texto(ambiente, "ITSA_OPENROUTER_BASE_URL", URL_OPENROUTER_PADRAO)
            or URL_OPENROUTER_PADRAO,
            openrouter_referer=opcional("ITSA_OPENROUTER_REFERER"),
            openrouter_title=_texto(ambiente, "ITSA_OPENROUTER_TITLE", "ITSA-Agente")
            or "ITSA-Agente",
            openrouter_data_collection=(opcional("ITSA_OPENROUTER_DATA_COLLECTION") or "").lower()
            or None,
            provider_max_tokens=_inteiro(ambiente, "ITSA_PROVIDER_MAX_TOKENS", 8192, 16),
        )
