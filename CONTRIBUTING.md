# Guia de contribuição

## Fluxo

1. Crie um *branch* a partir de `main`: `feat/<assunto>`, `fix/<assunto>` ou `docs/<assunto>`.
2. Faça mudanças pequenas e coesas, **com testes**.
3. Rode `testar.bat` (ou `./testar.sh`): `ruff`, `mypy --strict` e `pytest` devem passar.
4. Atualize a documentação afetada (SDD/ADR/CHANGELOG) **na mesma mudança**.
5. Abra um *pull request* descrevendo o *porquê*, os requisitos (`RF-nn`) e os riscos.

## Mensagens de *commit* (pt-BR, imperativo)

`tipo(escopo): resumo` — tipos: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.
Exemplos: `feat(cliente): reemite o token após 401`, `docs(sdd): registra resultados do D19`.

## Convenções de código

- Python 3.10+ (não usar recursos 3.11+, como `datetime.UTC`); tipagem completa (`mypy --strict`).
- Identificadores de domínio em português; termos do protocolo (`role`, `stream`, `delta`) como no contrato.
- Docstrings em português explicando o **porquê** e as invariantes, não o óbvio.
- Funções puras sempre que possível; I/O (rede, relógio, espera) **injetável** para testar.
- Erros: levantar subclasses de `GatewayError`; a interface é quem traduz para o usuário.
- **Nunca** logar, imprimir ou serializar segredos ou conteúdo de conversa. Use `Redator` em saídas
  que possam sair do processo (relatórios, logs).
- Sem `print` fora da CLI; sem `except Exception` silencioso (exceção: isolamento de verificações do diagnóstico).

## Testes

- Todo comportamento novo tem teste; todo *bug* corrigido ganha teste de regressão.
- Use `tests/gateway_falso.py` e acrescente "botões" de falha ali, em vez de *mocks* ad hoc.
- Se o gateway real divergir do simulador, corrija **o simulador e `docs/sdd/03`**.
- Testes não podem depender de rede, relógio real ou ordem de execução.

## Segurança

- Não versione `.env`, relatórios ou capturas com credenciais (`.gitignore` já cobre).
- Se um segredo vazar (commit, chat, ticket), **revogue-o** imediatamente; reescrever o histórico do
  Git não basta.
- Mudanças em `security.py`, `auth.py` ou nos guardrails exigem revisão de outra pessoa.

## Adicionando um agente (quando a Fase 4 iniciar)

Siga [docs/sdd/06-agentes-e-modulos.md](docs/sdd/06-agentes-e-modulos.md): pacote
`itsa_agente/agentes/<id>/`, prompts versionados, catálogo de views, guardrails próprios, página
Streamlit, perguntas de ouro e testes adversariais. Registre decisões relevantes em um novo ADR.
