# 01 — Requisitos

Legenda de prioridade: **M** = Must (obrigatório), **S** = Should (desejável).
Situação: ✅ implementado e testado · 🔶 parcial · ⏳ planejado (fase futura).

## 1. Requisitos funcionais (Fase 1)

| ID | Requisito | Pri. | Situação | Critério de aceite | Código | Testes |
|---|---|---|---|---|---|---|
| RF-01 | Autenticar com CPF/CNPJ, Token ID e usuário do ERP e obter JWT | M | ✅ | Credenciais válidas → JWT; inválidas → `Unauthorized` sem expor o Token ID | `gateway/auth.py`, `client.autenticar` | `test_cliente::TestAutenticacao` |
| RF-02 | Renovar o JWT automaticamente antes de vencer e após 401 (uma vez) | M | ✅ | Sem 401 visível ao usuário em conversa longa; sem laço de reautenticação | `GerenciadorToken`, `_enviar_autenticado` | `test_renova_antes_de_vencer`, `test_401_*` |
| RF-03 | Listar modelos habilitados, com cache curto e atualização forçada | M | ✅ | Lista vazia tratada; cache respeita `ITSA_MODELS_CACHE_SECONDS` | `client.listar_modelos` | `TestModelos` |
| RF-04 | Conversar com streaming NDJSON, expondo eventos tipados | M | ✅ | Sequência `started → delta* → completed`; eventos após o terminal ignorados | `gateway/ndjson.py`, `client.transmitir_chat` | `test_ndjson.py`, `TestChat` |
| RF-05 | Incorporar ao histórico **somente** interações com `completed` | M | ✅ | `error`, queda, cancelamento e fim sem `completed` não alteram o histórico | `conversation.Conversa.perguntar` | `test_conversa::TestConfirmacaoNoHistorico` |
| RF-06 | Manter janela de contexto ≤ 30 mensagens e ≤ orçamento de caracteres, preservando sistema e pergunta atual | M | ✅ | Nunca viola o contrato; poda em pares; sem resposta órfã no início | `Conversa.montar_janela` | `test_conversa::TestJanela` |
| RF-07 | Validar localmente o contrato do swagger antes de enviar | M | ✅ | 31 mensagens, última ≠ user, conteúdo vazio, modelo vazio → `LocalValidationError` sem rede | `gateway/models.py` | `test_models.py`, `test_validacao_local_*` |
| RF-08 | Converter erros HTTP/rede/stream em exceções tipadas e mensagens amigáveis em pt-BR | M | ✅ | 400/401/403/429/503/5xx mapeados; `Retry-After` exposto; mensagens ao usuário sem detalhes internos | `gateway/errors.py`, `client.erro_de_resposta`, `ui/estado.texto_erro` | `test_mapeamento_de_status`, `test_texto_erro_*` |
| RF-09 | Oferecer telas: Conexão, Modelos, Chat de teste, Diagnóstico | M | ✅ | Fluxo completo em `AppTest`; telas protegidas exigem conexão | `app.py`, `ui/` | `test_ui.py` |
| RF-10 | Executar bateria de diagnóstico (D01–D19) e gerar relatório Markdown/JSON com **catálogo de erros** | M | ✅ | Uma verificação nunca derruba as outras; gateway fora do ar → relatório com FALHA, sem exceção | `diagnostics/` | `test_diagnostico.py` |
| RF-11 | Executar o diagnóstico por linha de comando com código de saída | S | ✅ | `0` sem falhas, `1` com falhas, `2` uso inválido; Token ID nunca em argumento | `diagnostics/__main__.py` | `test_cli.py` |
| RF-12 | Enviar cabeçalhos de telemetria opcionais (`X-Erp-Version`, `X-Chat-Module-Version`, `X-Installation-Id`) | S | ✅ | Validação local dos limites (50 caracteres; GUID) | `config.py`, `client._cabecalhos_base` | `test_cabecalhos_de_telemetria`, `test_config.py` |
| RF-13 | Configurar por `.env` e variáveis `ITSA_*`, com validação e mensagens claras | M | ✅ | Valores inválidos → `ConfigurationError` | `config.py` | `test_config.py` |
| RF-14 | Executar direto da pasta sem instalar nada no sistema | M | ✅ | Scripts criam `.venv` local | `iniciar.*`, `testar.*`, `diagnostico.*` | (manual; ver [09](09-operacao.md)) |
| RF-15 | Conectar, na mesma tela, a provedores externos (NVIDIA e OpenRouter) por chave de API, de forma **opcional** e sem alterar o fluxo do gateway ITSA | M | ✅ | Chave em campo mascarado; conexão só com o provedor informado; falha de um provedor não derruba os demais | `providers/`, `ui/pagina_conexao.py` | `test_provedores.py`, `test_ui_provedores.py` |
| RF-16 | Rotear cada chamada pelo identificador qualificado `provedor::modelo` (sem `::` = gateway ITSA), com a mesma interface de streaming | M | ✅ | Origem desconectada → erro de validação local | `providers/roteador.py` | `test_provedores.py` |
| RF-17 | Decodificar SSE no padrão OpenAI-compatível, emitindo os mesmos eventos do gateway, com raciocínio separado e motivo de término | M | ✅ | Corte sem `finish_reason` → `StreamInterrupted`; raciocínio nunca entra no histórico | `providers/sse.py`, `conversation.py` | `test_provedores.py` |
| RF-18 | Listar modelos de todas as origens em catálogo único (gratuitos primeiro no OpenRouter) | S | ✅ | Falha de listagem de um provedor vira aviso | `providers/openrouter.py`, `ui/pagina_modelos.py` | `test_provedores.py`, `test_ui_provedores.py` |
| RF-19 | Controlar raciocínio (padrão/ligado/desligado) por chamada, quando suportado | S | ✅ | Desligado por padrão no NVIDIA Nemotron 3 | `providers/nvidia.py`, `ui/pagina_chat.py` | `test_provedores.py` |
| RF-20 | Diagnóstico de provedor (P01–P09) com relatório redigido | S | ✅ | Chave nunca aparece no relatório | `diagnostics/provedores.py` | `test_diagnostico_provedores.py` |

## 2. Requisitos não funcionais

| ID | Categoria | Requisito | Verificação |
|---|---|---|---|
| RNF-01 | Segurança | O Token ID e o JWT **nunca** são gravados em disco, log, relatório, URL ou tela; ficam só na memória da sessão | `test_token_id_nao_vai_para_nenhum_log`, `test_relatorios_nao_vazam_segredos`, `test_conexao_com_sucesso` |
| RNF-02 | Privacidade | O **conteúdo** das conversas não é registrado em log nem relatório; mensagens de validação não ecoam o conteúdo | `test_mensagem_de_validacao_nao_ecoa_o_conteudo` |
| RNF-03 | Resiliência | Retentativa só quando seguro (conexão e 503); nunca após timeout de leitura nem no meio do streaming (ADR-0004) | `TestResiliencia`, `test_corte_no_meio_do_streaming` |
| RNF-04 | Desempenho percebido | Resposta exibida à medida que chega; tempo limite por silêncio no streaming configurável (padrão 120 s) | `test_chat_*` (UI); D07 mede 1º trecho e tokens/s |
| RNF-05 | Portabilidade | Python 3.10+; Windows, Linux e macOS | Código sem recursos 3.11+ (checado por `mypy` com alvo 3.10) |
| RNF-06 | Qualidade | `ruff` limpo, `mypy --strict` limpo, todos os testes verdes | `testar.bat`/`testar.sh` |
| RNF-07 | Observabilidade | Logs com nível configurável e **redação automática**; `requestId` preservado nos erros de stream | `test_logging_com_redacao_nao_vaza_token` |
| RNF-08 | Idioma | Mensagens, documentação e identificadores de domínio em pt-BR | Revisão |
| RNF-09 | Manutenibilidade | Núcleo sem dependência de UI; UI sem lógica de protocolo; sem ciclos de importação | Estrutura de pacotes ([02](02-arquitetura.md)) |
| RNF-10 | Testabilidade | Todo I/O injetável (transporte HTTP, relógio, espera) | Fixtures de `tests/conftest.py` |
| RNF-11 | Concorrência | Estado de token protegido por `Lock`; uma instância de cliente por sessão de usuário | `GerenciadorToken` |
| RNF-12 | Segredos de provedores | Chaves `nvapi-`/`sk-or-` só em memória, redigidas de logs e relatórios; sem variável de ambiente para chaves (ADR-0007, ADR-0010) | `test_provedores.py`, `test_diagnostico_provedores.py` |

## 3. Regras de negócio e de contrato

| ID | Regra | Origem |
|---|---|---|
| RN-01 | Histórico enviado: de 1 a 30 mensagens, em ordem cronológica | Swagger |
| RN-02 | A última mensagem tem `role = user` | Swagger |
| RN-03 | `stream` é obrigatoriamente `true` | Swagger |
| RN-04 | `conversationId` é estável durante a conversa | Swagger |
| RN-05 | Incorporar a resposta ao histórico só após `completed`; em `error`/cancelamento a interação é descartada | Swagger |
| RN-06 | `erpUserName` tem de 1 a 15 caracteres | Swagger |
| RN-07 | CPF: 11 dígitos; CNPJ: 14 caracteres normalizados (numérico ou alfanumérico) | Swagger |
| RN-08 | O conteúdo das mensagens não é armazenado na auditoria do gateway (MVP) | Swagger |
| RN-09 | O JWT expira no menor prazo entre 15 minutos e o vencimento do cliente | Swagger |
| RN-10 | Cabeçalhos de versão: até 50 caracteres; `X-Installation-Id`: GUID | Swagger |

## 4. Requisitos planejados (fases futuras)

Detalhados nos documentos indicados; **ainda não implementados**.

| ID | Requisito | Fase | Detalhe |
|---|---|---|---|
| RF-G1 | Filtro de entrada (limites, normalização, detecção de injeção) | 2 | [05 §5](05-seguranca-e-guardrails.md) |
| RF-G2 | Estrutura de prompt com delimitação de dados e *canary* | 2 | [05 §5](05-seguranca-e-guardrails.md) |
| RF-G3 | Validação de saída (formato, vazamento de prompt, coerência numérica) | 2 | [05 §5](05-seguranca-e-guardrails.md) |
| RF-G4 | Limites de uso por usuário/módulo | 2 | [05 §5](05-seguranca-e-guardrails.md) |
| RF-G5 | Auditoria sem conteúdo (metadados) | 2 | [05 §6](05-seguranca-e-guardrails.md) |
| RF-D1 | Catálogo de *views* permitidas por agente, com filtros obrigatórios | 3 | [06 §4](06-agentes-e-modulos.md) |
| RF-D2 | Execução somente leitura, parametrizada, com limite de linhas e mascaramento | 3 | [06 §4](06-agentes-e-modulos.md) |
| RF-A1…A4 | Agentes Comercial/Vendas, Fiscal e Contábil, cada um com tela e licença | 4–6 | [06](06-agentes-e-modulos.md) |
| RF-L1 | Habilitação de módulos por cliente | 7 | [06 §7](06-agentes-e-modulos.md) |

## 5. Matriz de rastreabilidade (resumo)

| Objetivo (00) | Requisitos |
|---|---|
| O1 Cliente confiável | RF-01…RF-08, RF-12, RNF-01…RNF-03 |
| O2 Validar gateway | RF-10, RF-11 |
| O2b Comparar modelos/provedores | RF-15…RF-20 |
| O3 Guardrails | RF-G1…RF-G5 |
| O4 Camada de dados | RF-D1, RF-D2 |
| O5 Agentes | RF-A1…A4 |
| O6 Produção | RF-L1, RNF-07 |
