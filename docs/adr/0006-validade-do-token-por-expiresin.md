# ADR-0006 — Validade do token por `expiresIn` em relógio monotônico

- **Status:** Aceita · **Data:** 07/10/2026

## Contexto
A resposta traz `expiresIn` (segundos) e `expiresAtUtc` (data/hora UTC). Comparar `expiresAtUtc` com
o relógio local falha se o relógio do cliente estiver adiantado/atrasado, e `datetime.now()` pode
saltar (ajuste de horário, NTP).

## Decisão
Calcular `vence_em = time.monotonic() + expiresIn` no instante do recebimento e renovar quando
`agora ≥ vence_em − ITSA_TOKEN_SKEW_SECONDS` (60 s). `expiresAtUtc` serve só para exibição e para o
diagnóstico D02 medir o desvio de relógio. O relógio é injetável (testes).

## Consequências
- (+) Imune a diferenças e saltos de relógio.
- (+) Renovação antes do vencimento evita 401 no meio da conversa.
- (−) A latência de rede entre a emissão e o recebimento é desprezada (coberta pela margem de 60 s).
