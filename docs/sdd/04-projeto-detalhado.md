# 04 — Projeto detalhado

Descreve, módulo a módulo, **o que o código faz e por quê**: API pública, invariantes, algoritmos
e limitações. Os nomes são os do código (`itsa_agente/…`).

## 1. `config.py` — configuração

**Responsabilidade:** produzir um objeto `Settings` imutável e **validado** a partir de, em ordem
crescente de precedência: padrões → arquivo `.env` na raiz → variáveis de ambiente `ITSA_*`.

- `Settings.from_env(ambiente=None, *, arquivo_env=None)`: com `ambiente` injetado (testes), não
  toca `os.environ` nem o `.env`.
- `ler_arquivo_env(caminho)`: parser mínimo (sem dependência externa): ignora comentários e linhas
  inválidas; aceita `export`, aspas simples/duplas e comentário inline em valores sem aspas.
- Validação em `__post_init__`: URL `http(s)://…` (barra final removida), cabeçalhos de versão ≤ 50
  caracteres, `installation_id` GUID, `log_level` conhecido. Números aceitam vírgula decimal.
- `token_id_dev` (de `ITSA_TOKEN_ID`) existe só como conveniência de desenvolvimento e é
  `repr=False`. **Não** é lido por padrão em produção (ver [05](05-seguranca-e-guardrails.md)).

Todas as variáveis estão em [09 §2](09-operacao.md).

## 2. `gateway/errors.py` — erros

```
GatewayError(mensagem, codigo, status, request_id)
├── ConfigurationError        configuração local inválida
├── LocalValidationError      contrato violado ANTES de ir à rede
├── ConnectionFailed          DNS/TCP/TLS
├── RequestTimeout            sem resposta no prazo
├── BadRequest (400)  ├── Unauthorized (401)  ├── Forbidden (403)
├── RateLimited (429, retry_after)
├── ServiceUnavailable (503)  └── ServerError (demais 5xx)
├── ProtocolError             corpo/linha fora do contrato
├── StreamInterrupted         stream terminou sem 'completed'
└── StreamError               evento 'error' recebido
```

A UI captura **só** `GatewayError`. O texto ao usuário sai de `ui/estado.texto_erro`; o detalhe
técnico (`código`, `HTTP`, `requestId`) é mostrado em legenda separada.

## 3. `gateway/models.py` — contratos

| Tipo | Papel | Observações |
|---|---|---|
| `Credenciais` (dataclass congelada) | Agrupa CPF/CNPJ, Token ID, usuário | Normaliza/valida; `repr` mascara tudo; `payload()` é o único lugar que expõe o segredo |
| `TokenResponse` (pydantic) | Resposta do token | `accessToken` com `repr=False`; tolerante a campos extras |
| `ModeloInfo`, `ModelsResponse` | Lista de modelos | `models: null` → `[]` |
| `Mensagem` | `role` + `content` | `content` não vazio; **preserva** o texto original (não faz `strip`) |
| `ChatRequest` | Corpo do chat | `messages` 1–30; última `user`; `stream: Literal[True]`; `para_json()` usa *aliases* do swagger |
| `EventoIniciado/Delta/Concluido/Erro/Desconhecido` | Eventos do stream | Dataclasses imutáveis; `EventoErro.bruto` guarda o JSON para auditoria |
| `ResultadoChat` | Resultado agregado | Texto, `requestId`, uso, tempo total, tempo ao 1º trecho |

`normalizar_cpf_cnpj`: remove `.`, `-`, `/` e espaços, põe em maiúsculas; aceita `^\d{11}$`
(CPF) ou `^[0-9A-Z]{14}$` (CNPJ numérico ou alfanumérico). **Não** valida dígitos verificadores.

## 4. `gateway/ndjson.py` — decodificação do stream

```
iterar_eventos(linhas):
    para cada linha:
        e = evento_de_linha(linha)          # None para linha em branco
        se e é None: continue
        emite e
        se e é terminal (completed | error): return
    levanta StreamInterrupted               # acabou sem terminal
```

Propriedades:

- **Tolerância na leitura:** campos extras ignorados; `type` desconhecido vira
  `EventoDesconhecido` (não encerra); `usage` malformado vira `None`/zeros.
- **Dois formatos de `error`** aceitos (campos no topo ou `{"error":{…}}`), porque o real é
  desconhecido (L-02).
- **Linha inválida** → `ProtocolError` com no máximo 200 caracteres do trecho (pode conter dados).
- **Terminal encerra a leitura**: eventos posteriores são descartados (há teste).

## 5. `gateway/auth.py` — `GerenciadorToken`

Mantém `(jwt, vence_em)` sob `threading.Lock`.

| Operação | Comportamento |
|---|---|
| `obter()` | Retorna o JWT; emite um novo se não houver ou se `agora ≥ vence_em − skew` |
| `renovar()` | Emite sempre (usado por `autenticar()`) |
| `invalidar()` | Esquece o JWT (após `401` ou ao fechar) |
| `info()` | Validade restante e total, **sem** expor o JWT |

`vence_em = agora_monotônico + expiresIn` (→ [ADR-0006](../adr/0006-validade-do-token-por-expiresin.md)).
A emissão é injetada (`emitir`), de modo que o gerenciador não conhece HTTP: `ClienteGateway`
fornece `_emitir_token`, que já converte respostas ≠ 200 em exceções tipadas. Falhas de rede na
emissão viram `ConnectionFailed`/`RequestTimeout`; corpo fora do contrato, `ProtocolError`.

## 6. `gateway/client.py` — `ClienteGateway`

### 6.1 API pública

| Método | Descrição |
|---|---|
| `autenticar() → InfoToken` | Força nova emissão |
| `listar_modelos(forcar=False)` | `GET /api/models`, cache de `ITSA_MODELS_CACHE_SECONDS` |
| `montar_requisicao_chat(...)` | Valida o contrato e devolve `ChatRequest` (levanta `LocalValidationError`; **não ecoa o conteúdo**) |
| `transmitir_chat(...) → Iterator[Evento]` | Valida, conecta e **levanta na chamada** erros anteriores ao stream; devolve gerador de eventos |
| `conversar(...) → ResultadoChat` | Consome o stream; `error` → `StreamError` |
| `sondar(...) → RespostaSondagem` | Chamada observacional sem exceções (diagnóstico) |
| `fechar()` | Descarta o token e fecha o pool HTTP |

### 6.2 Política de retentativa (ADR-0004)

| Situação | Repete? | Por quê |
|---|---|---|
| `ConnectError`, `ConnectTimeout` | Sim, até `ITSA_MAX_RETRIES` (padrão 2), espera `0,5·2ⁿ` s | A requisição não chegou ao servidor |
| HTTP `503` | Sim, respeitando `Retry-After` (limitado a 10 s) | O gateway declara que não processou |
| `ReadTimeout`/erro após enviar | **Não** | A geração pode ter ocorrido; repetir duplica custo/efeito |
| Erro no meio do stream | **Não** | Resposta parcial não é recuperável; vira `StreamInterrupted` |
| HTTP `401` autenticado | **1 vez**, após reemitir o token | Token pode ter sido revogado/rodado |
| HTTP `400`, `403`, `429` | Não | Não se resolvem repetindo (429: exibir espera) |

### 6.3 Abertura do chat (`transmitir_chat`)

1. `montar_requisicao_chat` valida o contrato (sem rede).
2. `_enviar_autenticado(... stream=True, timeout=…)` usa tempo de leitura longo
   (`ITSA_STREAM_READ_TIMEOUT`, é o **silêncio máximo entre trechos**).
3. Se o status ≠ 200: lê o corpo, fecha a resposta e levanta o erro tipado — **na chamada**.
4. Se 200: devolve `_consumir_stream`, um gerador que força UTF-8, itera `iter_lines()` →
   `iterar_eventos` e **sempre fecha a resposta** (`finally`), inclusive quando o consumidor
   interrompe (`GeneratorExit`).

Exceções de transporte durante a iteração viram `StreamInterrupted`.

### 6.4 `sondar`

Usado apenas pela suíte de diagnóstico. Aceita `token="auto"` (JWT válido), `None` (sem
Authorization) ou texto literal (token adulterado); `conteudo_bruto` para corpos malformados;
limita o corpo lido (`limite_corpo`). Nunca repete e nunca levanta por status ou rede — devolve
`RespostaSondagem(status, cabecalhos, corpo, tempo_ms, erro_rede, truncado)`.

## 7. `conversation.py` — histórico e janela

### 7.1 Invariantes de `Conversa`

1. `historico` contém apenas **pares** (usuário, assistente) **confirmados**; nunca começa por
   resposta órfã.
2. Só `confirmar()` altera `historico`, e só é chamado após `completed` com texto não vazio.
3. `id` (`conversationId`) é fixo até `reiniciar()`.

### 7.2 `montar_janela(pergunta)`

```
fixas   = [sistema] se houver prompt de sistema, senão []
atual   = Mensagem.usuario(pergunta)
orç_msg = max_mensagens − len(fixas) − 1
orç_chr = max_caracteres − chars(fixas) − chars(atual)

mantidos = []
percorre o histórico do par mais recente para o mais antigo:
    se len(mantidos)+2 > orç_msg   → para
    se chars_usados + custo(par) > orç_chr → para
    mantidos = par + mantidos
retorna fixas + mantidos + [atual], descartadas = len(historico) − len(mantidos)
```

Exemplo (padrões: 30 mensagens, 24 000 caracteres, com prompt de sistema): `orç_msg = 28` →
até **14 pares** mais sistema e pergunta atual = 30 mensagens. O **sistema** e a **pergunta atual**
nunca são cortados, mesmo que sozinhos excedam o orçamento (o gateway decidirá; D19 mede esse
limite).

### 7.3 `perguntar(cliente, modelo, pergunta)`

Gerador de `str`. Enquanto itera, repassa cada `delta`. Em `EventoErro` levanta `StreamError`.
Ao receber `completed` com texto, chama `confirmar`. Fechar o gerador (cancelar) ou qualquer
exceção deixa o histórico intacto.

## 8. `security.py` — higiene de segredos

`Redator` remove, nesta ordem: (1) segredos **registrados** (Token ID, ao conectar), (2) JWTs
(`eyJ…·…·…`), (3) `Bearer <token>`, (4) valores de campos `tokenId`/`accessToken`/`authorization`,
(5) números de 11–14 dígitos (CPF/CNPJ numéricos → `123******95`). `FiltroRedacao` aplica isso à
mensagem **já formatada** de cada registro de log e está instalado no *handler* (filtros de
*logger* não alcançam registros de loggers-filhos). `configurar_logging` é idempotente.

> O filtro é a última defesa. O código já evita logar segredos e conteúdo; o filtro cobre
> regressões e mensagens de bibliotecas.

## 9. `diagnostics/` — suíte de diagnóstico

| Verificação | O que mede | Resultados possíveis |
|---|---|---|
| D01 | Alcance + formato de erro sem token | OK / ALERTA (corpo fora de `{error:{code,message}}`) / FALHA |
| D02 | Emissão do JWT, validade, desvio de relógio | OK / ALERTA (>900 s ou desvio >120 s) |
| D03 | Lista de modelos; escolhe o modelo dos testes | OK / ALERTA (vazia) / FALHA (modelo pedido não existe) |
| D04–D05 | Token adulterado e chat sem token são rejeitados | OK / ALERTA |
| D06 | Cabeçalhos `X-*` válidos, 51 caracteres e GUID inválido | INFO / FALHA se os válidos forem recusados |
| D07 | Sequência `started→delta*→completed`, `requestId`, `usage`, TTFB, tokens/s | OK / ALERTA / FALHA |
| D08 | Acentuação (UTF-8) ponta a ponta | OK / ALERTA / FALHA (mojibake) |
| D09 | Memória multi-turno | OK / ALERTA |
| D10 | `role=system` aceito e obedecido | OK / ALERTA |
| D11–D16 | Rejeições: modelo inexistente, `stream=false`, 31 mensagens, última `assistant`, conteúdo vazio, JSON malformado, GUID inválido | OK / ALERTA (aceito indevidamente) / FALHA (5xx) |
| D17 | Campos extras (`temperature`) | INFO |
| D18 *(opcional)* | Token ID inválido → 401/403 | OK / ALERTA |
| D19 *(opcional)* | Maior conteúdo aceito e caracteres/token | OK / INFO / ALERTA |

Design: cada verificação retorna `(Status, detalhe, dados)`; `_rodar` captura qualquer exceção e a
converte em `FALHA` (uma verificação **nunca** derruba as demais). Toda resposta de erro
observada vira uma `Observacao` — o **catálogo de erros** do relatório. `relatorio_*` aplica o
`Redator` antes de serializar.

## 10. `ui/` — telas

| Arquivo | Responsabilidade |
|---|---|
| `estado.py` | Chaves de `st.session_state`, `conectar`/`desconectar`, `exigir_conexao`, `texto_erro`, `mostrar_erro`; fábrica de cliente injetável (testes) |
| `pagina_conexao.py` | Formulário com `clear_on_submit` (limpa o Token ID digitado); estado conectado |
| `pagina_modelos.py` | Lista e escolha do modelo padrão |
| `pagina_chat.py` | Chat com `st.write_stream`; barra lateral (modelo, sistema, nova conversa, uso) |
| `pagina_diagnostico.py` | Opções, progresso, tabelas e *downloads* |

Chaves de sessão: `itsa_cliente`, `itsa_conversa`, `itsa_modelo`, `itsa_relatorio`, `itsa_cfg`,
`itsa_fabrica` (só testes).

## 11. Limitações e dívidas técnicas conhecidas

| # | Item | Impacto | Plano |
|---|---|---|---|
| 1 | Se `transmitir_chat` for chamado e o gerador devolvido **nunca for iterado nem fechado**, a conexão só é liberada pelo coletor de lixo | Baixo (uso interno sempre itera) | Adotar *context manager* se surgir uso externo |
| 2 | `Retry-After` em formato data HTTP é ignorado | Baixo | Suportar se o gateway usar |
| 3 | O mascaramento de números de 11–14 dígitos é heurístico e pode mascarar outros números em logs | Aceitável (conservador) | — |
| 4 | Tokens (`promptTokens`) dependem do modelo; a relação caracteres/token é só medida em D19 | Médio | Calibrar na Fase 3 |
