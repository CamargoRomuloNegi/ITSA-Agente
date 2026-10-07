# ADR-0004 — Política de retentativa conservadora

- **Status:** Aceita · **Data:** 07/10/2026

## Contexto
Inferência é cara e potencialmente não idempotente (consome GPU/CPU e pode ser contabilizada).
Falhas transitórias existem (rede, 503 com modelo carregando), mas repetir às cegas duplica custo e
pode entregar respostas duplicadas.

## Decisão
Repetir **somente**: (a) falha de **conexão** (`ConnectError`, `ConnectTimeout`) — a requisição não
foi enviada; (b) HTTP **503** — o gateway declara que não processou. Espera `0,5 s × 2ⁿ` ou
`Retry-After` (teto 10 s), até `ITSA_MAX_RETRIES` (2). **Nunca** repetir após *timeout de leitura*
nem no meio do streaming. Em **401** autenticado: reemitir o token e repetir **uma** vez.
400, 403 e 429 não são repetidos.

## Consequências
- (+) Sem inferência duplicada; sem laços; comportamento previsível e testado.
- (−) Quedas no meio da resposta exigem que o usuário reenvie a pergunta (a interação é descartada).
- (−) Um 429 vira erro visível em vez de espera automática (decisão revisável após L-04).
