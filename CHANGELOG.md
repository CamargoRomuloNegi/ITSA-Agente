# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento
[SemVer](https://semver.org/lang/pt-BR/).

## [0.2.0] — 2026-10-08

Integração nativa com **provedores externos**, sem alterar o fluxo do gateway ITSA (ADR-0010).

### Adicionado
- Pacote `itsa_agente/providers/`: cliente OpenAI-compatível com SSE, NVIDIA (`nemotron-3-ultra-550b-a55b`),
  OpenRouter (catálogo dinâmico, gratuitos primeiro), fábrica e `Roteador` por modelo qualificado `provedor::modelo`.
- Tela **Conexão** com campos (mascarados) para as chaves NVIDIA e OpenRouter; modo só-externo; avisos por provedor.
- **Raciocínio** controlável (padrão/ligado/desligado), exibido à parte e nunca guardado no histórico.
- Diagnóstico de provedor **P01–P09** (catálogo, chat mínimo, UTF-8, `system`, streaming longo, raciocínio, chave inválida, modelo inexistente, contexto longo opcional).
- Erro `CreditoInsuficiente` (402); redação de chaves `nvapi-`/`sk-or-`.
- Configuração `ITSA_NVIDIA_*`, `ITSA_OPENROUTER_*`, `ITSA_PROVIDER_MAX_TOKENS`.
- 162 testes (350 no total); ADR-0010 e SDD 11.

### Observação
- Os endpoints reais não puderam ser exercitados do ambiente de desenvolvimento; confirmar com o diagnóstico P01–P09 (lacunas L-13…L-18).

## [0.1.2] — 2026-10-08

Primeira versão ajustada com **medições do gateway real** (ver `docs/sdd/03` §6).

### Alterado
- Diagnóstico: rejeições do *framework* (401 de JWT; 400 de JSON/GUID malformado) fora do formato
  `{error:{code,message}}` passam de ALERTA para INFO (D01, D04, D05, D16): é o comportamento real.
- D18 aceita 400 (validação de entrada, `INVALID_REQUEST`), além de 401/403.
- D19 testa também 192.000 caracteres.

### Adicionado
- Catálogo de erros do relatório ganha a coluna **Corpo bruto (resumo)** (já redigido), para mostrar o
  formato real dos erros sem `error.code`.
- 2 testes (188 no total).

### Documentação
- `docs/sdd/03` §6 preenchido com as medições (validade do JWT, modelos, latência, `system`,
  `temperature`, tamanho de contexto, catálogo de erros) e decisões decorrentes; ADR-0003 atualizada.

## [0.1.1] — 2026-10-07

### Corrigido
- `app.py` insere a própria pasta no `sys.path`, evitando `ModuleNotFoundError: itsa_agente` em
  ambientes onde o diretório do script não é importável (ex.: Streamlit Cloud).

### Documentação
- `docs/sdd/09-operacao.md` §5.1: passo a passo e solução de problemas para o Streamlit Community Cloud.

## [0.1.0] — 2026-10-07 — Fase 1: Fundação

### Adicionado
- Cliente do IAitsaGateway: autenticação com renovação automática, listagem de modelos com cache,
  chat com *streaming* NDJSON, validação local do contrato, erros tipados, política de retentativa
  conservadora (ADR-0004).
- Gestão de conversa: histórico confirmado apenas após `completed`; janela de contexto por número
  de mensagens (30) e orçamento de caracteres (ADR-0005).
- Segurança de segredos: `Credenciais` mascaradas, redator de logs e relatórios (ADR-0007).
- Suíte de diagnóstico D01–D19 com relatório Markdown/JSON e catálogo de erros; CLI
  `python -m itsa_agente.diagnostics` (ADR-0008).
- Telas Streamlit: Conexão, Modelos, Chat de teste e Diagnóstico.
- 186 testes automatizados (gateway simulado, CLI e interface via `AppTest`); `ruff` e
  `mypy --strict` limpos.
- Scripts `iniciar`, `testar` e `diagnostico` para Windows e Linux/macOS, com ambiente isolado em `.venv`.
- SDD completo (00–10) e ADRs 0001–0009 em português.

### Pendente
- Executar o diagnóstico no gateway real e registrar os resultados em
  `docs/sdd/03-contrato-api-gateway.md` §6.
