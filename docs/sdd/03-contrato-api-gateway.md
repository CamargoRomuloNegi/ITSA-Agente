# 03 — Contrato da API IAitsaGateway

> **Fonte:** Swagger/OpenAPI v1 publicado em `https://suporteitsa2.ddns.net/swagger/index.html`
> (especificação em `/swagger/v1/swagger.json`), consultado em **07/10/2026**.
> Este documento consolida o contrato, avalia a qualidade da documentação e **lista as lacunas**
> que a suíte de diagnóstico (`D01`–`D19`) existe para fechar. Onde um comportamento ainda não foi
> medido no servidor real, isso está dito explicitamente.

## 1. Resumo

| Item | Valor |
|---|---|
| Título / versão | IAitsaGateway API · v1 |
| Finalidade | Intermediar recursos de IA para um ERP, com autenticação JWT e conversas em tempo real |
| Autenticação | `Bearer` (JWT) em todos os endpoints, exceto a emissão do token |
| Formato | JSON; o chat responde em **NDJSON** (uma linha = um objeto JSON completo) |
| Endpoints | `POST /api/auth/token` · `GET /api/models` · `POST /api/chat` |

Fluxo do cliente (descrito no swagger): (1) solicitar JWT; (2) autorizar com `Bearer`;
(3) consultar modelos; (4) enviar a conversa e consumir o NDJSON.

## 2. Endpoints

### 2.1 `POST /api/auth/token`

Emite um JWT para um cliente credenciado. O Token ID é usado só para autenticar e nunca é devolvido
nem gravado em texto puro. O JWT expira no **menor prazo entre 15 minutos e o vencimento do
cliente**.

| Corpo (`TokenRequest`) | Tipo | Regra |
|---|---|---|
| `cpfCnpj` | string | CPF com 11 dígitos ou CNPJ normalizado com 14 caracteres (exemplo alfanumérico: `12ABC34501DE35`) |
| `tokenId` | string | Credencial individual entregue pelo licenciamento |
| `erpUserName` | string | Usuário corrente do ERP, de 1 a 15 caracteres |

Resposta `200` (`TokenResponse`): `accessToken` (JWT), `tokenType` (`Bearer`), `expiresIn`
(segundos), `expiresAtUtc` (UTC). Erros: `400`, `401`, `403`, `429`.

### 2.2 `GET /api/models`

Lista os modelos **públicos** habilitados na configuração e instalados no serviço. Lista vazia é
resposta válida; identificadores internos nunca são expostos.

Resposta `200` (`ModelsResponse`): `{"models":[{"id":"iaitsa-geral","displayName":"IAitsa Geral"}]}`.
Erros: `401`, `403`, `503`. O servidor mantém cache da lista (`IAitsa:ModelsCacheSeconds`).

### 2.3 `POST /api/chat`

Processa uma conversa e transmite a resposta em NDJSON.

| Corpo (`ChatRequest`) | Tipo | Regra |
|---|---|---|
| `conversationId` | UUID | Estável durante toda a conversa |
| `model` | string | Identificador público obtido em `GET /api/models` |
| `messages` | `ChatMessage[]` | De **1 a 30** itens, em ordem cronológica |
| `stream` | boolean | **Obrigatoriamente `true`** |

`ChatMessage`: `role` (`system` \| `user` \| `assistant`) e `content` (não vazio; **não é
armazenado na auditoria**). A **última** mensagem deve ter `role = user`.

Resposta `200`: NDJSON com os eventos abaixo. Erros antes do streaming: `400`, `401`, `403`, `503`.

| Evento (`type`) | Campos documentados | Observações |
|---|---|---|
| `started` | `requestId`, `conversationId`, `model` | Início do streaming |
| `delta` | `requestId`, `content` | Trecho de texto |
| `completed` | `requestId`, `model`, `usage{promptTokens, completionTokens}` | Fim com sucesso |
| `error` | *(não exemplificado)* | Falha durante a interação — formato a medir (L-02) |

Regra de histórico (swagger): o cliente **só** incorpora a resposta ao histórico depois do
`completed`. Em cancelamento ou `error`, a interação fica incompleta e não deve entrar no histórico
(→ [ADR-0005](../adr/0005-historico-confirmado-apos-completed.md)).

### 2.4 Cabeçalhos opcionais (todos os endpoints)

| Cabeçalho | Regra documentada |
|---|---|
| `X-Erp-Version` | Até 50 caracteres |
| `X-Chat-Module-Version` | Até 50 caracteres |
| `X-Installation-Id` | GUID |
| `User-Agent` | Até 255 caracteres (registrado pelo servidor) |

O cliente envia `User-Agent: ITSA-Agente/<versão>` e os `X-*` configurados em `.env`.

### 2.5 Formato de erro

```json
{ "error": { "code": "<código estável>", "message": "<mensagem segura em português>" } }
```

`code` é descrito como "código estável para tratamento pelo ERP". **O catálogo de códigos não está
publicado** (L-01).

### 2.6 Configurações do servidor mencionadas

`IAitsa:ChatStartTimeoutSeconds`, `IAitsa:RequestTimeoutSeconds`, `IAitsa:ModelsCacheSeconds` —
os **valores** não são documentados (L-05).

## 3. Como o cliente aplica o contrato

| Regra do contrato | Validação local | Teste |
|---|---|---|
| 1 ≤ mensagens ≤ 30 | `ChatRequest.messages` (`min_length=1`, `max_length=30`) e janela em `Conversa` | `test_chat_request_limites_de_mensagens` |
| Última mensagem `user` | `ChatRequest._ultima_e_usuario` | `test_chat_request_ultima_deve_ser_usuario` |
| `stream = true` | `Literal[True]` | `test_chat_request_stream_deve_ser_true` |
| `content` não vazio | `Mensagem._nao_vazio` | `test_mensagem_vazia_e_rejeitada` |
| `erpUserName` 1–15 | `Credenciais.__post_init__` | `test_usuario_erp_fora_de_1_a_15` |
| CPF/CNPJ | `normalizar_cpf_cnpj` | `test_normaliza_cpf_cnpj`, `test_cpf_cnpj_invalido` |
| Cabeçalhos ≤ 50 / GUID | `Settings.__post_init__` | `test_valores_invalidos_sao_rejeitados` |
| Histórico só após `completed` | `Conversa.perguntar` | `TestConfirmacaoNoHistorico` |
| `conversationId` estável | `Conversa.id` | `test_conversation_id_estavel_e_historico_enviado` |

Validar localmente evita latência e consumo de cota para erros previsíveis e **não depende** de o
servidor repetir as mesmas regras.

## 4. Avaliação da documentação

**Aderência e qualidade: 7,5/10 — adequada para integrar o caminho feliz; incompleta para operar
em produção.**

| Critério | Nota | Comentário |
|---|---|---|
| Completude do caminho feliz | 9 | Fluxo em 4 passos, exemplos de requisição/resposta e eventos NDJSON |
| Rigor dos schemas | 8 | `additionalProperties: false`, tipos e formatos; limites de `erpUserName` e `messages` explícitos |
| Semântica de erros | 5 | Formato único e código "estável", mas **sem catálogo**; formato do evento `error` ausente |
| Limites operacionais | 3 | Sem limite de tamanho de conteúdo, janela de contexto, taxa (`429`) ou tempos |
| Segurança | 8 | Boas práticas declaradas (Token ID não devolvido, conteúdo fora da auditoria) |
| Clareza do contrato de histórico | 9 | Regra do `completed` é explícita e correta |
| Descoberta de capacidades | 4 | Nada sobre parâmetros de geração, `system`, módulos licenciados, versões |

**Conclusão:** a documentação é coerente, enxuta e confiável no que cobre. O risco está no que
não cobre — por isso o diagnóstico mede o servidor em vez de supor.

## 5. Lacunas e como fechá-las

| ID | O que não sabemos | Impacto | Verificação | Decisão provisória |
|---|---|---|---|---|
| L-01 | Catálogo de `error.code` (por endpoint/status) | Tratamento fino no ERP | D01, D04, D05, D11–D18 (catálogo no relatório) | Tratar por classe de status; exibir `código` no detalhe |
| L-02 | Formato do evento `error` no stream | Mensagem ao usuário, auditoria | Só reproduzível com falha real do modelo; D19 pode provocá-lo | Aceitar campos no topo **ou** `{"error":{...}}` (`ndjson.py`) |
| L-03 | Limite de tamanho de `content` e janela de contexto por modelo | Quanto contexto das views cabe | D19 (2k→96k caracteres; mede `promptTokens`) | `ITSA_MAX_HISTORY_CHARS=24000` (heurística) |
| L-04 | Limites de taxa e `Retry-After` do `429` | Experiência sob carga | Teste de carga dedicado (não coberto por D01–D19) | Não repetir 429; exibir tempo de espera |
| L-05 | Valores de timeout do servidor | Tempo limite do cliente | D07 (TTFB, total) | `ITSA_STREAM_READ_TIMEOUT=120` s |
| L-06 | Se `role=system` é aceito e **obedecido** | Desenho dos prompts | D10 | Não depender de `system` (ADR-0003) |
| L-07 | Se o gateway aceita campos extras (`temperature`...) | Controle de geração | D17 | Assumir que não há ajuste |
| L-08 | Se fechar a conexão cancela a geração no servidor | Custo de inferência | Medição manual (tempo de CPU/GPU) | Fechar a conexão; documentar |
| L-09 | Como o gateway informa **módulos licenciados** do cliente | Habilitar telas por agente | Inspeção do JWT/resposta (fora do escopo desta fase) | O ERP informará os módulos ativos |
| L-10 | Política de bloqueio por tentativas inválidas de credencial | Segurança vs. testes | D18 (opcional, com cuidado) | D18 desligado por padrão |
| L-11 | Concorrência máxima por cliente/modelo | Dimensionamento | Teste de carga dedicado | Uma requisição por sessão |
| L-12 | Comportamento do `Accept`/content negotiation e compressão | Compatibilidade | D01/D07 | `Accept: application/x-ndjson, application/json` |

## 6. Resultados medidos no gateway real

> **Pendente.** O ambiente de construção desta entrega **não alcança** o servidor (o acesso é
> bloqueado pelo proxy de saída), portanto nenhum dado abaixo foi medido. Execute o diagnóstico na
> rede da ITSA (`Diagnóstico` na aplicação, ou `diagnostico.bat`) e cole aqui as tabelas do relatório.

| Item | Valor medido | Data | Responsável |
|---|---|---|---|
| Validade real do JWT | _a medir (D02)_ | | |
| Modelos expostos | _a medir (D03)_ | | |
| 1º trecho / total / tokens por segundo | _a medir (D07)_ | | |
| `role=system` aceito e obedecido | _a medir (D10)_ | | |
| Campos extras aceitos | _a medir (D17)_ | | |
| Maior conteúdo aceito (caracteres) e caracteres/token | _a medir (D19)_ | | |
| Catálogo de `error.code` | _a medir (relatório §"Catálogo")_ | | |

## 7. Política de evolução do contrato

1. Toda mudança no swagger do gateway deve gerar um *diff* deste documento e do gateway simulado
   (`tests/gateway_falso.py`), e uma nova rodada do diagnóstico.
2. O cliente é **tolerante na leitura** (ignora campos novos, preserva eventos desconhecidos) e
   **estrito na escrita** (só envia campos documentados).
3. Mudança incompatível (`v2`) exige novo ADR.
