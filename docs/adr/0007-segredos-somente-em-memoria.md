# ADR-0007 — Segredos só em memória e sempre mascarados

- **Status:** Aceita · **Data:** 07/10/2026

## Contexto
O Token ID é a credencial do cliente. Em produção fica trancado no banco do cliente (P2); em
desenvolvimento é digitado. Relatórios e logs circulam entre pessoas (chamados, e-mails).

## Decisão
1. O Token ID vive apenas em `Credenciais` (memória do processo), dentro do `ClienteGateway` da
   sessão. Nunca em disco, cookie, URL ou `st.query_params`.
2. `repr`/`str` mascarados; o segredo só sai em `payload()` para o `POST` do token.
3. Redator global registra o Token ID ao conectar; **filtro no *handler* de log** e aplicação
   obrigatória na geração de relatórios.
4. A CLI **não** tem parâmetro para o Token ID (evita histórico do shell): lê `ITSA_TOKEN_ID` ou pede sem eco.
5. O formulário limpa o campo após o envio (`clear_on_submit`).
6. `ITSA_TOKEN_ID` existe apenas como conveniência de desenvolvimento e é `repr=False`.

## Consequências
- (+) Superfície de vazamento mínima e testada.
- (−) O usuário digita o token a cada sessão em desenvolvimento (aceitável).
- (−) A redação por padrões é heurística (ver limitações em [04 §11](../sdd/04-projeto-detalhado.md)).
