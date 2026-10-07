"""Execução do diagnóstico pela linha de comando.

Exemplo::

    python -m itsa_agente.diagnostics --cpf-cnpj 12ABC34501DE35 --usuario CARLOS

O Token ID é lido da variável ``ITSA_TOKEN_ID`` ou, se ausente, solicitado sem eco no terminal.
**Não existe parâmetro de linha de comando para o Token ID** (evita que fique no histórico do
shell). Código de saída: 0 = sem falhas; 1 = há falhas; 2 = erro de uso/configuração.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime
from pathlib import Path

from itsa_agente.config import RAIZ_PROJETO, Settings
from itsa_agente.diagnostics.modelos import Resultado
from itsa_agente.diagnostics.relatorio import relatorio_json, relatorio_markdown
from itsa_agente.diagnostics.suite import Diagnostico, OpcoesDiagnostico
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.errors import GatewayError
from itsa_agente.gateway.models import Credenciais
from itsa_agente.security import configurar_logging, redator_global


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m itsa_agente.diagnostics",
        description="Executa a bateria de diagnóstico contra o IAitsaGateway.",
    )
    cfg = Settings.from_env()
    p.add_argument("--cpf-cnpj", default=cfg.cpf_cnpj_padrao, help="CPF ou CNPJ do cliente")
    p.add_argument("--usuario", default=cfg.usuario_erp_padrao, help="Usuário do ERP (1–15 chars)")
    p.add_argument("--url", default=cfg.base_url, help="URL base do gateway")
    p.add_argument("--modelo", default=None, help="ID do modelo (padrão: o primeiro da lista)")
    p.add_argument(
        "--com-credencial-invalida",
        action="store_true",
        help="Inclui D18 (envia um Token ID inválido; pode acionar bloqueio/limite de taxa)",
    )
    p.add_argument(
        "--com-carga", action="store_true", help="Inclui D19 (tamanho máximo de contexto)"
    )
    p.add_argument(
        "--saida",
        type=Path,
        default=RAIZ_PROJETO / "relatorios",
        help="Pasta de saída dos relatórios (padrão: ./relatorios)",
    )
    return p.parse_args(argv)


def principal(argv: list[str] | None = None) -> int:
    args = _argumentos(argv)
    cfg = Settings.from_env().com(base_url=args.url)
    configurar_logging(cfg.log_level)

    if not args.cpf_cnpj or not args.usuario:
        print("Informe --cpf-cnpj e --usuario (ou ITSA_CPF_CNPJ / ITSA_ERP_USER).", file=sys.stderr)
        return 2
    token_id = cfg.token_id_dev or getpass.getpass("Token ID (não será exibido): ")

    try:
        credenciais = Credenciais(args.cpf_cnpj, token_id, args.usuario)
    except GatewayError as exc:
        print(f"Credenciais inválidas: {exc.mensagem}", file=sys.stderr)
        return 2
    redator_global().registrar(token_id)

    opcoes = OpcoesDiagnostico(
        modelo=args.modelo,
        incluir_credencial_invalida=args.com_credencial_invalida,
        incluir_carga=args.com_carga,
    )

    def progresso(r: Resultado) -> None:
        print(f"{r.status.icone} {r.id} {r.titulo} — {r.detalhe}")

    with ClienteGateway(credenciais, cfg) as cliente:
        relatorio = Diagnostico(cliente, opcoes, ao_concluir=progresso).executar()

    args.saida.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    md = args.saida / f"diagnostico-{carimbo}.md"
    js = args.saida / f"diagnostico-{carimbo}.json"
    md.write_text(relatorio_markdown(relatorio), encoding="utf-8")
    js.write_text(relatorio_json(relatorio), encoding="utf-8")
    print(f"\nRelatórios gravados em:\n  {md}\n  {js}")
    return 0 if relatorio.aprovado else 1


if __name__ == "__main__":
    raise SystemExit(principal())
