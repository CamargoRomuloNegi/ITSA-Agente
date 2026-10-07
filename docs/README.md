# Documentação do ITSA-Agente

Esta pasta reúne o **SDD** (*Software Design Document*) e os **ADRs** (registros de decisão).

## Como ler

- **Quer entender o projeto?** `sdd/00-visao-geral.md` → `sdd/02-arquitetura.md`.
- **Vai integrar com o gateway ou depurar chamadas?** `sdd/03-contrato-api-gateway.md` e `sdd/04-projeto-detalhado.md`.
- **Vai desenhar um agente?** `sdd/05-seguranca-e-guardrails.md` e `sdd/06-agentes-e-modulos.md`.
- **Vai operar/implantar?** `sdd/09-operacao.md`.
- **Vai contribuir com código?** `../CONTRIBUTING.md` e `sdd/07-plano-de-testes.md`.

## Índice

### SDD (`docs/sdd/`)

| Nº | Documento |
|---|---|
| 00 | [Visão geral](sdd/00-visao-geral.md) |
| 01 | [Requisitos](sdd/01-requisitos.md) |
| 02 | [Arquitetura](sdd/02-arquitetura.md) |
| 03 | [Contrato da API do gateway](sdd/03-contrato-api-gateway.md) |
| 04 | [Projeto detalhado](sdd/04-projeto-detalhado.md) |
| 05 | [Segurança e guardrails](sdd/05-seguranca-e-guardrails.md) |
| 06 | [Agentes e módulos](sdd/06-agentes-e-modulos.md) |
| 07 | [Plano de testes](sdd/07-plano-de-testes.md) |
| 08 | [Roadmap](sdd/08-roadmap.md) |
| 09 | [Operação](sdd/09-operacao.md) |
| 10 | [Glossário](sdd/10-glossario.md) |

### ADRs (`docs/adr/`)

| ADR | Decisão |
|---|---|
| [0001](adr/0001-python-e-streamlit.md) | Python + Streamlit executados direto da pasta |
| [0002](adr/0002-cliente-http-sincrono-httpx.md) | Cliente HTTP síncrono com `httpx` |
| [0003](adr/0003-engenharia-de-prompt-no-cliente.md) | Engenharia de prompt e de contexto no cliente; `system` não é garantia |
| [0004](adr/0004-politica-de-retentativa.md) | Política de retentativa conservadora |
| [0005](adr/0005-historico-confirmado-apos-completed.md) | Histórico só recebe interações `completed` |
| [0006](adr/0006-validade-do-token-por-expiresin.md) | Validade do token por `expiresIn` em relógio monotônico |
| [0007](adr/0007-segredos-somente-em-memoria.md) | Segredos só em memória e sempre mascarados |
| [0008](adr/0008-diagnostico-como-produto.md) | Diagnóstico mede o gateway real em vez de supor |
| [0009](adr/0009-um-modulo-por-agente.md) | Um módulo e uma tela por agente, sobre um núcleo único |

## Convenções

- Idioma: **português do Brasil** (código de domínio, mensagens e documentação). Termos de
  protocolo (`role`, `stream`, `delta`, `completed`) permanecem como no contrato.
- Requisitos têm IDs estáveis (`RF-nn`, `RNF-nn`); lacunas do contrato, `L-nn`; verificações do
  diagnóstico, `Dnn`; decisões, `ADR-nnnn`. Use-os em *commits*, *issues* e revisões.
- Diagramas em **Mermaid** (renderizados pelo GitHub).
- O que é **proposta** (ainda não implementado) está sempre marcado como tal.
