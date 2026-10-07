# 00 — Visão geral

| | |
|---|---|
| **Projeto** | ITSA-Agente |
| **Versão do documento** | 0.1.0 (Fase 1 — Fundação) |
| **Status** | Em vigor para a Fase 1; Fases 2+ marcadas como *proposta* |
| **Responsável técnico** | ITSA |
| **Idioma** | pt-BR |

## 1. Contexto

O ERP da ITSA atende clientes de segmentos distintos. Cada cliente tem dados próprios (vendas,
estoque, obrigações fiscais, contabilidade) em seu banco. O objetivo é oferecer, dentro do ERP,
**assistentes conversacionais especialistas** que respondam com base nesses dados.

A ITSA mantém um servidor com **modelos de linguagem executados localmente** (offline), expostos
por uma API própria, o **IAitsaGateway**. O gateway autentica o cliente (JWT), lista os modelos
disponíveis e processa conversas com resposta em *streaming*. A gestão financeira do consumo
fica do lado da ITSA: não há custo por chamada a LLMs de terceiros.

## 2. Problema

1. Modelos locais são **menores** do que os LLMs comerciais: têm menos conhecimento, seguem
   instruções com menos fidelidade e são **mais vulneráveis a injeção de prompt**.
2. Perguntas de negócio exigem **dados do cliente**, que o modelo não possui.
3. Áreas como fiscal e contábil têm **risco de resposta errada** (multas, retrabalho) e exigem
   rastreabilidade.
4. A oferta deve ser **modular**: cada cliente contrata os agentes que quiser.

## 3. Estratégia

> **Compensar o tamanho do modelo com engenharia de prompt e de contexto, e com controles
> determinísticos fora do modelo.**

- O modelo recebe **pouco texto, muito bem estruturado e já enriquecido** com dados reais.
- Decisões de acesso, escopo e cálculo **nunca ficam a cargo do modelo**: são código.
- Os agentes são **estreitos** (uma especialidade cada) e compartilham um núcleo único.
- Medir antes de supor: o comportamento real do gateway é verificado por uma suíte de diagnóstico.

## 4. Objetivos

| # | Objetivo | Fase |
|---|---|---|
| O1 | Cliente confiável e seguro da API do gateway (auth, modelos, chat em streaming) | 1 ✅ |
| O2 | Validar credenciamento, acesso aos modelos e limites reais do gateway | 1 ✅ (ferramenta) |
| O3 | Guardrails severos e proteção contra injeção de prompt, reutilizáveis por todos os agentes | 2 |
| O4 | Camada de dados: acesso somente leitura a *views* do cliente, com escopo e mascaramento | 3 |
| O5 | Agentes especialistas (comercial/vendas, fiscal, contábil), cada um com sua tela e licença | 4–6 |
| O6 | Operação em produção (licenciamento por módulo, observabilidade, implantação) | 7 |

## 5. Escopo da Fase 1 (esta entrega)

**Dentro:** cliente da API; gestão de histórico e janela de contexto; mascaramento de segredos;
suíte de diagnóstico (19 verificações) com relatório; telas de conexão, modelos, chat de teste e
diagnóstico; testes automatizados; scripts de execução sem instalação; SDD e ADRs.

**Fora (próximas fases):** agentes especialistas; guardrails (projetados em
[05](05-seguranca-e-guardrails.md), não implementados); acesso ao banco do cliente; licenciamento
por módulo; integração incorporada ao ERP.

> O chat de teste é **deliberadamente cru** (sem guardrails nem agente): serve para validar o
> encanamento. Ele **não deve ser exposto a usuários finais**.

## 6. Premissas e restrições

| ID | Premissa / restrição | Consequência |
|---|---|---|
| P1 | Os modelos rodam offline no servidor da ITSA e são "mais simples" | Prompt curto e estruturado; cálculos fora do modelo; guardrails em código |
| P2 | Em produção o **Token ID fica trancado no banco do cliente**; só o cliente que contata o serviço o utiliza; o cadastro é feito externamente | O ITSA-Agente não armazena nem cadastra credenciais; recebe-as por sessão |
| P3 | Em desenvolvimento, o Token ID é digitado numa janela | Campo mascarado, só em memória (ADR-0007) |
| P4 | Streamlit direto da pasta, sem instalar dependências no sistema | Scripts criam `.venv` local (ADR-0001) |
| P5 | Um único acesso à API; módulos por agente | Núcleo comum + um módulo/tela por agente (ADR-0009) |
| P6 | O gateway não informa, nos contratos conhecidos, quais módulos o cliente licenciou | Lacuna L-09: o ERP deverá informar os módulos ativos (ver [06](06-agentes-e-modulos.md)) |

## 7. Partes interessadas

| Parte | Interesse |
|---|---|
| Usuário final do ERP | Respostas úteis, rápidas e corretas, na tela do próprio ERP |
| Cliente (empresa) | Privacidade dos dados, custo previsível, módulos sob medida |
| ITSA — produto | Demanda por módulos, MVP incremental |
| ITSA — infraestrutura | Capacidade do servidor de modelos, estabilidade do gateway |
| ITSA — licenciamento | Controle de vigência e de módulos por cliente |

## 8. Riscos principais

| ID | Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|---|
| R1 | Injeção de prompt contornar regras em modelo pequeno | Alta | Alto | Defesa em camadas, controles determinísticos, testes adversariais ([05](05-seguranca-e-guardrails.md)) |
| R2 | Resposta fiscal/contábil incorreta | Média | Alto | Números vêm das views; modelo apenas explica; citação de fonte; revisão humana; escopo estrito |
| R3 | Contexto do modelo local insuficiente para as views | Alta | Médio | Compactação, recuperação seletiva, medir limites (D19) |
| R4 | Gateway sem limites/erros documentados | Média | Médio | Diagnóstico + catálogo de erros; tratamento genérico seguro |
| R5 | Vazamento de dados entre clientes/usuários | Baixa | Crítico | Escopo obrigatório por empresa/usuário na camada de dados; auditoria; testes de isolamento |
| R6 | Latência alta de modelos locais | Média | Médio | Streaming, indicador de progresso, tempo limite por trecho, medir TTFB/tokens por segundo |
| R7 | Exposição acidental do chat de teste | Baixa | Médio | Documentado como interno; telas de produção separadas |

## 9. Critérios de sucesso da Fase 1

1. `iniciar.bat`/`iniciar.sh` abre a aplicação sem instalar nada no sistema.
2. Com credenciais válidas, o usuário autentica, lista modelos e conversa em streaming.
3. A suíte de diagnóstico roda contra o gateway real e produz relatório com catálogo de erros.
4. `ruff`, `mypy --strict` e todos os testes passam.
5. Nenhum segredo aparece em log, relatório ou tela.

## 10. Documentos relacionados

[01 Requisitos](01-requisitos.md) · [02 Arquitetura](02-arquitetura.md) ·
[03 Contrato](03-contrato-api-gateway.md) · [08 Roadmap](08-roadmap.md)
