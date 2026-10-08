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
| L-03 | Limite de tamanho de `content` e janela de contexto por modelo | Quanto contexto das views cabe | D19 (2k→192k caracteres; mede `promptTokens`) | `ITSA_MAX_HISTORY_CHARS=24000` (heurística); medido: aceita ≥ 96k ([§6](#6-resultados-medidos-no-gateway-real)) |
| L-04 | Limites de taxa e `Retry-After` do `429` | Experiência sob carga | Teste de carga dedicado (não coberto por D01–D19) | Não repetir 429; exibir tempo de espera |
| L-05 | Valores de timeout do servidor | Tempo limite do cliente | D07 (TTFB, total) | `ITSA_STREAM_READ_TIMEOUT=120` s |
| L-06 | Se `role=system` é aceito e **obedecido** | Desenho dos prompts | D10 | **Medido: aceito e obedecido** (§6); desenho segue sem depender só dele (ADR-0003) |
| L-07 | Se o gateway aceita campos extras (`temperature`...) | Controle de geração | D17 | **Medido: aceito**; efeito não comprovado — assumir que não há ajuste |
| L-08 | Se fechar a conexão cancela a geração no servidor | Custo de inferência | Medição manual (tempo de CPU/GPU) | Fechar a conexão; documentar |
| L-09 | Como o gateway informa **módulos licenciados** do cliente | Habilitar telas por agente | Inspeção do JWT/resposta (fora do escopo desta fase) | O ERP informará os módulos ativos |
| L-10 | Política de bloqueio por tentativas inválidas de credencial | Segurança vs. testes | D18 (opcional, com cuidado) | D18 desligado por padrão |
| L-11 | Concorrência máxima por cliente/modelo | Dimensionamento | Teste de carga dedicado | Uma requisição por sessão |
| L-12 | Comportamento do `Accept`/content negotiation e compressão | Compatibilidade | D01/D07 | `Accept: application/x-ndjson, application/json` |

## 6. Resultados medidos no gateway real

Medição de **08/10/2026**, diagnóstico D01–D19 (com D18 e D19) executado a partir do ITSA-Agente
0.1.1 contra `https://suporteitsa2.ddns.net`, com credencial de teste (usuário ERP `RicardoTeste`).
Resultado: **aprovado** — 12 OK, 5 alertas, 0 falhas, 2 informativos; duração total 16 s.

### 6.1 Valores medidos

| Item | Valor medido | Verificação |
|---|---|---|
| Validade do JWT | **900 s** (15 min), igual ao documentado; desvio de relógio −1 s | D02 |
| Modelos expostos | `iaitsa-geral` ("IAitsa Geral") e `iaitsa-suporte` ("IAitsa Suporte") | D03 |
| Sequência do *stream* | `started → delta → completed`, um único `requestId`; `completed` traz `promptTokens`/`completionTokens` | D07 |
| 1º trecho / total (resposta de 2 tokens) | **0,44 s / 0,46 s** | D07 |
| Vazão de leitura do *prompt* | ≈ **2.600–3.000 tokens/s** (429 tokens em 0,37 s; 18.623 em 6,6 s) | D19 |
| Tokens por segundo de **geração** | **Não medido**: a resposta de teste tem 2 tokens (o valor de 4,4 tok/s do relatório não é representativo) | D07 |
| Acentuação (UTF-8) | Íntegra de ponta a ponta | D08 |
| Memória multi-turno | O modelo usou o histórico enviado (respondeu o código combinado) | D09 |
| `role=system` | **Aceito e obedecido** (amostra única, tarefa trivial) | D10 |
| Campos extras (`temperature`) | **Aceitos** (HTTP 200); **efeito não medido** — pode ser ignorado | D17 |
| Cabeçalhos `X-*` inválidos (51 caracteres, GUID inválido) | **Aceitos** (HTTP 200): o servidor não valida; a validação local do cliente é mantida | D06 |
| Maior conteúdo aceito | **96.000 caracteres** (18.623 tokens) sem erro; limite superior ainda não encontrado | D19 |
| Caracteres por token | ≈ **5,0** (texto repetitivo de teste; para dados reais de ERP, com números e códigos, assumir **3,5**) | D19 |
| Tempo por tamanho de entrada | 2 mil: 0,37 s · 8 mil: 0,60 s · 32 mil: 2,05 s · 96 mil: 6,60 s (≈ linear) | D19 |
| Credencial inválida | Token ID de formato inválido → **400** `INVALID_REQUEST` (não 401); credencial bem formada porém errada → 401 (observado na conexão) | D18 |
| Bloqueio por tentativas | Não observado com 1 tentativa inválida (política completa segue desconhecida) | D18 |

### 6.2 Catálogo de erros observados

| Cenário | HTTP | `error.code` | Mensagem do servidor |
|---|---|---|---|
| Modelo inexistente | 400 | `MODEL_NOT_AVAILABLE` | O modelo informado não está disponível. |
| `stream=false` | 400 | `STREAM_REQUIRED` | Esta operação exige streaming. |
| 31 mensagens | 400 | `INVALID_MESSAGES_COUNT` | Informe entre 1 e 30 mensagens. |
| Última mensagem `assistant` | 400 | `LAST_MESSAGE_MUST_BE_USER` | A última mensagem deve ser do usuário. |
| `content` vazio | 400 | `INVALID_MESSAGE` | Todas as mensagens devem possuir função válida e conteúdo. |
| Dados de autenticação inválidos | 400 | `INVALID_REQUEST` | Os dados informados são inválidos. |
| Sem token / token adulterado / expirado | 401 | *(ausente)* | *(corpo fora do formato; ver abaixo)* |
| JSON malformado / `conversationId` inválido | 400 | *(ausente)* | *(corpo fora do formato; ver abaixo)* |

**Conclusões:**

1. Os erros de **regra de negócio** do `/api/chat` e do `/api/auth/token` seguem
   `{"error":{"code","message"}}` com códigos estáveis em maiúsculas — adequados para tratamento
   programático (o cliente já os expõe em `GatewayError.codigo`).
2. Os erros emitidos **pelo framework antes da aplicação** (401 de JWT ausente/inválido; 400 de
   JSON ou GUID malformado) **não** seguem esse formato. O cliente trata esses casos pela classe do
   status HTTP e usa mensagens padrão em pt-BR (`extrair_erro_api`). Os alertas D01/D04/D05/D16 do
   relatório de 0.1.1 refletem isso e são **comportamento esperado**: a partir da versão 0.1.2
   passam a INFO.
3. O corpo bruto desses erros **não foi capturado** no relatório de 0.1.1 (a coluna de mensagem do
   catálogo mostrou o texto padrão do próprio cliente, não o do servidor). A versão 0.1.2 inclui a
   coluna *Corpo bruto (resumo)*; reexecute o diagnóstico para registrá-lo aqui.
4. Distinção importante para a interface: **400 `INVALID_REQUEST`** na autenticação indica dado mal
   formado; **401** indica credencial bem formada, porém não reconhecida.

### 6.3 Decisões e consequências

| Achado | Decisão |
|---|---|
| Entrada de 96 mil caracteres aceita e processada a ≈ 2.800 tokens/s | Contexto **não** é o gargalo imediato. Manter `ITSA_MAX_HISTORY_CHARS=24000` (≈ 7 mil tokens com 3,5 car./token; ≈ 2,5 s de leitura) — o limite prático será a **qualidade** do modelo pequeno e a latência, não o servidor. Reavaliar com os dados reais das *views* (Fase 3). |
| `role=system` obedecido | ADR-0003 atualizada: pode-se usar `system` como camada principal de instruções; a estrutura "sanduíche" e as barreiras por código **continuam**, porque o teste foi trivial e a obediência sob ataque é medida na Fase 2. |
| `temperature` aceito sem efeito comprovado | Tratar como **sem controle de geração** até medir (mesmo *prompt*, `0` vs `1.5`, repetido). Item aberto L-07. |
| Validade 900 s e relógio sincronizado | Política de renovação do ADR-0006 confirmada. |
| 5,0 caracteres/token em texto de teste | Não usar como orçamento real; adotar 3,5 para dimensionar contexto de dados. |
| Modelo `iaitsa-suporte` | Finalidade a confirmar com a ITSA (suporte técnico?) antes de associá-lo a algum agente. Os agentes de ERP partem de `iaitsa-geral`. |

### 6.4 Pendências de medição

- Teto de entrada (D19 agora também testa **192.000** caracteres) e comportamento sob 2–3 conversas
  simultâneas (L-11).
- Vazão de **geração** com resposta longa (≥ 200 tokens) — acrescentar uma verificação ao
  diagnóstico na Fase 2.
- Efeito real de `temperature` e corpo bruto dos erros do framework (reexecutar o diagnóstico).
- Política de limite de taxa (`429`) e de bloqueio por tentativas inválidas (L-04, L-10).

## 7. Política de evolução do contrato

1. Toda mudança no swagger do gateway deve gerar um *diff* deste documento e do gateway simulado
   (`tests/gateway_falso.py`), e uma nova rodada do diagnóstico.
2. O cliente é **tolerante na leitura** (ignora campos novos, preserva eventos desconhecidos) e
   **estrito na escrita** (só envia campos documentados).
3. Mudança incompatível (`v2`) exige novo ADR.
