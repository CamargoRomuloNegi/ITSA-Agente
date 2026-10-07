"""Geração do relatório de diagnóstico (Markdown e JSON), sempre com segredos mascarados."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from itsa_agente.diagnostics.modelos import Relatorio, Status
from itsa_agente.security import Redator, redator_global


def relatorio_dict(relatorio: Relatorio, redator: Redator | None = None) -> dict[str, Any]:
    """Representação serializável e **redigida** do relatório."""
    red = redator or redator_global()
    bruto = asdict(relatorio)
    for resultado in bruto["resultados"]:
        resultado["status"] = Status(resultado["status"]).value
    bruto["contagem"] = relatorio.contagem()
    bruto["aprovado"] = relatorio.aprovado
    return red.aplicar_em(bruto)  # type: ignore[no-any-return]


def relatorio_json(relatorio: Relatorio, redator: Redator | None = None) -> str:
    return json.dumps(relatorio_dict(relatorio, redator), ensure_ascii=False, indent=2, default=str)


def _celula(valor: Any) -> str:
    texto = "" if valor is None else str(valor)
    return texto.replace("|", "\\|").replace("\n", " ")


def relatorio_markdown(relatorio: Relatorio, redator: Redator | None = None) -> str:
    """Relatório legível, no formato usado para atualizar ``docs/sdd/03``."""
    d = relatorio_dict(relatorio, redator)
    c = d["contagem"]
    linhas = [
        "# Relatório de diagnóstico — IAitsaGateway",
        "",
        f"- **Início:** {d['iniciado_em']} (UTC)",
        f"- **Gateway:** {d['base_url']}",
        f"- **Cliente (mascarado):** {d['cpf_cnpj_mascarado']} · usuário ERP `{d['usuario_erp']}`",
        f"- **Versão do ITSA-Agente:** {d['versao_app']}",
        f"- **Duração total:** {d['duracao_total_s']} s",
        f"- **Resumo:** ✅ {c['OK']} · ⚠️ {c['ALERTA']} · ❌ {c['FALHA']} · "
        f"ℹ️ {c['INFO']} · ⏭️ {c['PULADO']}",
        f"- **Veredito:** {'APROVADO' if d['aprovado'] else 'REPROVADO (há falhas)'}",
        "",
        "## Resultados",
        "",
        "| ID | Verificação | Status | Detalhe | Tempo (ms) |",
        "|---|---|---|---|---|",
    ]
    for r in d["resultados"]:
        linhas.append(
            f"| {r['id']} | {_celula(r['titulo'])} | {Status(r['status']).icone} {r['status']} | "
            f"{_celula(r['detalhe'])} | {r['duracao_ms']:.0f} |"
        )

    linhas += ["", "## Catálogo de respostas de erro observadas", ""]
    if d["observacoes"]:
        linhas += [
            "| Endpoint | Cenário | HTTP | `error.code` | Mensagem | Tempo (ms) |",
            "|---|---|---|---|---|---|",
        ]
        for o in d["observacoes"]:
            http = o["status_http"] if o["status_http"] is not None else f"rede: {o['erro_rede']}"
            linhas.append(
                f"| {_celula(o['endpoint'])} | {_celula(o['cenario'])} | {_celula(http)} | "
                f"{_celula(o['codigo'])} | {_celula(o['mensagem'])} | {o['tempo_ms']} |"
            )
    else:
        linhas.append("_Nenhuma resposta de erro observada._")

    linhas += ["", "## Dados medidos", ""]
    for r in d["resultados"]:
        if r["dados"] and r["status"] != Status.PULADO.value:
            linhas += [
                f"### {r['id']} — {r['titulo']}",
                "",
                "```json",
                json.dumps(r["dados"], ensure_ascii=False, indent=2, default=str),
                "```",
                "",
            ]
    linhas += [
        "---",
        "_Relatório gerado automaticamente. Tokens, JWT e documentos foram mascarados; "
        "nenhum conteúdo de conversa de cliente é registrado, apenas amostras curtas de testes._",
    ]
    return "\n".join(linhas) + "\n"
