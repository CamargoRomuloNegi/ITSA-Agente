# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento
[SemVer](https://semver.org/lang/pt-BR/).

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
