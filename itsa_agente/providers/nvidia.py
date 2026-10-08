"""Provedor NVIDIA (build.nvidia.com): endpoint gratuito compatível com a API da OpenAI.

Fonte: página do modelo ``nvidia/nemotron-3-ultra-550b-a55b`` em build.nvidia.com (base
``https://integrate.api.nvidia.com/v1``). O raciocínio do Nemotron 3 é controlado por
``chat_template_kwargs.enable_thinking`` e chega separado, em ``delta.reasoning_content``.

O catálogo da NVIDIA tem centenas de modelos; oferecemos uma lista curta (``ITSA_NVIDIA_MODELS``)
e a tela aceita qualquer outro ID. Limites de taxa e termos do endpoint gratuito **não** são
documentados na página do modelo — consulte a NVIDIA antes de qualquer uso além de testes.
"""

from __future__ import annotations

from typing import Any

import httpx

from itsa_agente.config import Settings
from itsa_agente.providers.base import (
    PROVEDOR_NVIDIA,
    ModeloCatalogo,
    OpcoesGeracao,
    qualificar,
)
from itsa_agente.providers.erros import erro_de_resposta
from itsa_agente.providers.openai_compat import ClienteOpenAICompat

_ROTULOS = {
    "nvidia/nemotron-3-ultra-550b-a55b": "Nemotron 3 Ultra 550B (A55B)",
}


class ProvedorNvidia(ClienteOpenAICompat):
    id_provedor = PROVEDOR_NVIDIA
    rotulo = "NVIDIA"

    def __init__(self, api_key: str, configuracao: Settings, **kwargs: Any) -> None:
        super().__init__(
            api_key=api_key,
            base_url=configuracao.nvidia_base_url,
            configuracao=configuracao,
            **kwargs,
        )

    def verificar(self) -> None:
        """Valida a chave com uma conversa mínima (1 token).

        ``GET /v1/models`` da NVIDIA é **público** (responde sem chave), portanto não serve para
        validar. Só 401/403 indicam chave recusada; 400/404/422 (ex.: modelo fora do plano) e 429
        provam que a chave foi reconhecida e são aceitos.
        """
        modelo = self._cfg.nvidia_models[0]
        resposta = self._enviar(
            "POST",
            "/chat/completions",
            json_corpo={
                "model": modelo,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "stream": False,
            },
            timeout=httpx.Timeout(self._cfg.request_timeout, connect=10),
        )
        try:
            resposta.read()
            if resposta.status_code in (401, 403) or resposta.status_code >= 500:
                raise erro_de_resposta(resposta, self.id_provedor)
        finally:
            resposta.close()

    def listar_modelos(self, *, forcar: bool = False) -> list[ModeloCatalogo]:
        return [
            ModeloCatalogo(
                id=qualificar(PROVEDOR_NVIDIA, m),
                rotulo=_ROTULOS.get(m, m),
                provedor=PROVEDOR_NVIDIA,
                externo=True,
            )
            for m in self._cfg.nvidia_models
        ]

    def _extras(self, modelo: str, opcoes: OpcoesGeracao) -> dict[str, Any]:
        # Só a linha Nemotron 3 documenta `enable_thinking`; outros modelos não recebem o campo
        # para não correr o risco de uma validação estrita do NIM recusá-lo.
        if "nemotron-3" not in modelo.lower():
            return {}
        if opcoes.raciocinio:
            return {"chat_template_kwargs": {"enable_thinking": True}}
        # Padrão do ITSA-Agente: raciocínio desligado (resposta direta, menos tokens e latência).
        return {"chat_template_kwargs": {"enable_thinking": False, "force_nonempty_content": True}}
