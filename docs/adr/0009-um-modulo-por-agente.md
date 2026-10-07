# ADR-0009 — Um módulo e uma tela por agente, sobre um núcleo único

- **Status:** Aceita (arquitetura-alvo; implementação nas Fases 4–6) · **Data:** 07/10/2026

## Contexto
O acesso ao gateway é único, mas a venda é modular: um cliente pode contratar só o Comercial,
outro só o Fiscal. Os agentes serão escritos um de cada vez e criam demanda pelo produto (MVP).

## Decisão
Estrutura `itsa_agente/agentes/<id>/` (agente, prompts, views, guardrails, página) sobre o núcleo
(`gateway`, `conversation`, `guardrails`, `dados`, `security`). Cada agente é uma **página
Streamlit própria**; `app.py` monta a navegação apenas com os módulos ativos do cliente. A
habilitação é verificada também no servidor, não só escondendo telas. Não haverá chat genérico em
produção.

## Consequências
- (+) Entrega e validação incrementais; falha de um agente não afeta os demais.
- (+) Segurança evolui uma vez, no núcleo, e beneficia todos.
- (−) Exige um mecanismo confiável de licenciamento por módulo (L-09, D-02).
- (−) Código compartilhado entre agentes deve ficar no núcleo, evitando duplicação.
