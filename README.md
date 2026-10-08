# ITSA-Agente

Chat estruturado com **agentes especialistas** (vendas, atendimento comercial, fiscal, contábil) para
o ERP, sobre a API **IAitsaGateway** — que gerencia modelos de linguagem executados localmente no
servidor da ITSA.

> **Estado atual — Fase 1 (Fundação) concluída.** O projeto contém o cliente completo da API, a
> gestão de conversa conforme o contrato do gateway, uma suíte de **diagnóstico** que mede o
> comportamento real do servidor, telas Streamlit de teste, testes automatizados e o SDD. Os
> agentes especialistas e os guardrails são as próximas fases (ver [roadmap](docs/sdd/08-roadmap.md)).

## Por que este projeto existe

Os modelos rodam **offline, em hardware próprio**, sem custo por chamada, mas são menores que os
grandes LLMs comerciais. A estratégia é compensar com **engenharia de prompt e de contexto**:
cada pergunta chega ao modelo já acompanhada de dados enriquecidos, extraídos de *views* do banco
do cliente, e de regras estritas de escopo. A API é única; cada agente ganha sua própria tela e
pode ser licenciado separadamente (ex.: cliente com módulo Comercial, outro com módulo Fiscal).

## Início rápido (sem instalar nada no sistema)

Requisito: **Python 3.10+** instalado. Os scripts criam um ambiente isolado em `.venv/`, dentro da
própria pasta, e instalam ali as dependências.

| Ação | Windows | Linux / macOS |
|---|---|---|
| Abrir a aplicação | `iniciar.bat` | `./iniciar.sh` |
| Rodar testes, lint e tipos | `testar.bat` | `./testar.sh` |
| Diagnóstico por linha de comando | `diagnostico.bat --cpf-cnpj ... --usuario ...` | `./diagnostico.sh --cpf-cnpj ... --usuario ...` |

Com as dependências já instaladas, também funciona: `streamlit run app.py`.

### Primeiro uso

1. Execute `iniciar.bat` (ou `./iniciar.sh`). O navegador abre em `http://localhost:8501`.
2. Na tela **Conexão**, informe CPF/CNPJ, **Token ID** e usuário do ERP. O Token ID fica só na
   memória da sessão (campo mascarado; nunca é gravado).
3. Em **Modelos**, confira a lista. Em **Chat de teste**, converse com o modelo.
4. Em **Diagnóstico**, execute a bateria e baixe o relatório (Markdown/JSON). **Esse relatório é o
   insumo para fechar as lacunas do contrato** — ver [03-contrato-api-gateway](docs/sdd/03-contrato-api-gateway.md).

5. **(Opcional, v0.2.0)** Na mesma tela **Conexão**, informe a chave da **NVIDIA** (`nvapi-…`) e/ou do
   **OpenRouter** (`sk-or-…`). Os modelos aparecem em **Modelos** e no **Chat** com o prefixo do
   provedor (`nvidia::…`, `openrouter::…`). Deixando o Token ID em branco, conecta só os provedores.
   As chaves ficam só na memória da sessão. Detalhes em [11-provedores-externos](docs/sdd/11-provedores-externos.md).

Configuração opcional: copie `.env.example` para `.env` (ignorado pelo Git). Todas as variáveis
`ITSA_*` estão descritas em [09-operacao](docs/sdd/09-operacao.md).

## O que há na pasta

```
app.py                    Ponto de entrada Streamlit (navegação entre telas)
itsa_agente/
  config.py               Configuração (.env + variáveis ITSA_*), validada
  conversation.py         Histórico confirmado + janela de contexto (30 msgs / orçamento de chars)
  security.py             Mascaramento de segredos em logs e relatórios
  gateway/                Cliente da API: contratos, NDJSON, token, HTTP, erros tipados
  providers/              Provedores externos (NVIDIA, OpenRouter): SSE, roteador, chaves
  diagnostics/            Bateria D01–D19 (gateway), P01–P09 (provedores), relatórios e CLI
  ui/                     Telas: conexão, modelos, chat de teste, diagnóstico
tests/                    Testes (gateway simulado em tests/gateway_falso.py)
.github/workflows/ci.yml  Integração contínua (lint, formatação, tipos e testes)
docs/sdd/                 Software Design Document (pt-BR)
docs/adr/                 Registros de decisões de arquitetura
```

## Documentação

Comece por [docs/README.md](docs/README.md). Em resumo:

| Documento | Para quê |
|---|---|
| [00 Visão geral](docs/sdd/00-visao-geral.md) | Contexto, objetivos, escopo, premissas, riscos |
| [01 Requisitos](docs/sdd/01-requisitos.md) | RF/RNF com critérios de aceite e rastreabilidade |
| [02 Arquitetura](docs/sdd/02-arquitetura.md) | Camadas, diagramas, fluxos e implantação |
| [03 Contrato da API](docs/sdd/03-contrato-api-gateway.md) | Swagger consolidado, **avaliação da documentação** e lacunas |
| [04 Projeto detalhado](docs/sdd/04-projeto-detalhado.md) | Módulos, algoritmos e invariantes do código |
| [05 Segurança e guardrails](docs/sdd/05-seguranca-e-guardrails.md) | Ameaças, controles atuais e **projeto dos guardrails** |
| [06 Agentes e módulos](docs/sdd/06-agentes-e-modulos.md) | Arquitetura dos especialistas e da camada de dados |
| [07 Plano de testes](docs/sdd/07-plano-de-testes.md) | Estratégia, matriz e roteiro com o gateway real |
| [08 Roadmap](docs/sdd/08-roadmap.md) | Fases, critérios de saída e decisões em aberto |
| [09 Operação](docs/sdd/09-operacao.md) | Configuração, execução, implantação e solução de problemas |

## Qualidade

- `ruff` (lint e formatação), `mypy --strict` e `pytest` devem passar antes de qualquer *commit*
  (`testar.bat` / `./testar.sh`).
- Os testes automatizados usam um **gateway simulado**. O comportamento do servidor real nos
  cenários-limite é medido pelo diagnóstico, não presumido.

## Licença

Software proprietário da ITSA. Todos os direitos reservados.
