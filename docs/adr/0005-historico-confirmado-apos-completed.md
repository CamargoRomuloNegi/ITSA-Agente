# ADR-0005 — Histórico só recebe interações `completed`

- **Status:** Aceita · **Data:** 07/10/2026

## Contexto
O swagger determina que o cliente "somente deve incorporar a resposta ao histórico depois do
evento `completed`"; em cancelamento ou `error`, "a interação fica incompleta e não deve entrar no
histórico". Respostas parciais no histórico envenenam as próximas rodadas do modelo.

## Decisão
`Conversa` mantém apenas pares (usuário, assistente) **confirmados**. `perguntar()` é um gerador que
só chama `confirmar()` ao receber `completed` com texto não vazio. Qualquer exceção, evento
`error`, fim sem `completed` ou fechamento do gerador pelo consumidor deixa o histórico intacto.
A janela de contexto poda em **pares** para nunca começar por resposta órfã.

## Consequências
- (+) Histórico sempre coerente e válido para o contrato (1–30 mensagens, última `user`).
- (+) Comportamento transacional, simples de testar (`TestConfirmacaoNoHistorico`).
- (−) Uma resposta quase completa interrompida é perdida (aceitável; pode-se oferecer "continuar" no futuro).
