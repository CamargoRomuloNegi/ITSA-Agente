# ADR-0002 — Cliente HTTP síncrono com `httpx`

- **Status:** Aceita · **Data:** 07/10/2026

## Contexto
O Streamlit executa o script de forma síncrona por sessão. O gateway usa HTTPS e NDJSON em
*streaming*. Precisamos de tempos limite granulares (conexão vs. silêncio no stream), `MockTransport`
para testes e API de *streaming* limpa.

## Decisão
Usar `httpx.Client` **síncrono**, uma instância por sessão (`ClienteGateway`), com
`httpx.Timeout(connect, read, write, pool)` distintos; no chat, `read` = silêncio máximo entre
trechos (`ITSA_STREAM_READ_TIMEOUT`). Redirecionamentos desativados.

## Consequências
- (+) Código simples, legível e diretamente compatível com `st.write_stream`.
- (+) `httpx.MockTransport` permite um gateway simulado fiel, sem rede.
- (+) Pool de conexões reaproveitado (menos latência).
- (−) Não aproveita `asyncio`; para alta concorrência, migrar para `httpx.AsyncClient` num serviço
  FastAPI (o contrato `TransmissorChat` já isola o consumidor).

## Alternativas
- `requests`: sem *timeouts* granulares nem `MockTransport`; menos adequado a *streaming*.
- `aiohttp`/`AsyncClient`: desnecessário para o modelo de execução atual.
