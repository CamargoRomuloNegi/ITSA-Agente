# 07 — Plano de testes

## 1. Estratégia

| Nível | O que cobre | Ferramenta | Onde |
|---|---|---|---|
| Unitário | Regras puras: validação, NDJSON, janela de contexto, redação, configuração | `pytest` | `test_models`, `test_ndjson`, `test_conversa`, `test_seguranca`, `test_config` |
| Integração (gateway simulado) | Cliente completo contra um servidor falso fiel ao swagger, com falhas injetáveis | `pytest` + `httpx.MockTransport` | `test_cliente`, `test_diagnostico`, `test_cli` |
| Interface | Fluxos das telas sem navegador | `streamlit.testing.v1.AppTest` | `test_ui` |
| Qualidade estática | Estilo, bugs comuns, segurança básica, tipos | `ruff`, `mypy --strict` | `testar.bat` / `testar.sh` |
| **Aceitação com o gateway real** | O que só o servidor real responde | Diagnóstico (D01–D19) + roteiro manual (§5) | Aplicação / CLI |
| *(Fase 2+)* Adversarial e de qualidade de agentes | Injeção, isolamento de dados, perguntas de ouro | corpus versionado | `tests/adversarial/`, `tests/agentes/` |

### Por que um gateway simulado

`tests/gateway_falso.py` implementa o contrato do swagger **inclusive as rejeições** (400/401),
o streaming NDJSON e "botões" de falha: `revogar_tokens()`, `indisponivel_n` (503), `erro_conexao_n`,
`timeout_leitura`, `modo_stream` (`corte`, `lixo`, `evento_erro`, `erro_aninhado`,
`sem_completed`), `aceita_system`, `respeita_system`, `max_chars_conteudo`. Isso permite testar
cenários que o servidor real raramente produz sob demanda.

> **Limite honesto:** o simulador reflete o que o swagger **diz**. Onde o swagger é silencioso
> (formato do evento `error`, códigos de erro, limites), o simulador usa suposições razoáveis. Só o
> diagnóstico contra o servidor real as confirma — e qualquer divergência deve atualizar
> [03](03-contrato-api-gateway.md) **e** o simulador.

## 2. Inventário (Fase 1)

| Arquivo | Testes | Foco |
|---|---|---|
| `test_config.py` | 17 | Padrões, sobrescrita por ambiente, valores inválidos, `.env`, segredo fora do `repr` |
| `test_models.py` | 28 | CPF/CNPJ (incl. alfanumérico), credenciais, limites do `ChatRequest`, `Mensagem`, tolerância a campos extras |
| `test_ndjson.py` | 17 | Exemplo do swagger, linhas em branco, terminal encerra, `error` (2 formatos), desconhecidos, corte, JSON inválido, Unicode |
| `test_cliente.py` | 55 | Token (emissão, cache, renovação, 401, 429), modelos (cache, vazio), resiliência (503, conexão, timeout, `Retry-After`), mapeamento de status, chat (sequência, erros, corte, linha inválida, UTF-8 dividido entre pacotes), validação local, cabeçalhos, `sondar`, logs |
| `test_conversa.py` | 22 | Confirmação transacional, cancelamento, janela (30 msgs/caracteres), `conversationId` estável, conversa longa de 40 turnos |
| `test_seguranca.py` | 8 | Redação de segredos, JWT, Bearer, CPF/CNPJ, estruturas aninhadas, filtro de log |
| `test_diagnostico.py` | 21 | Gateway saudável, catálogo de erros, alertas por divergência de contrato, gateway fora do ar, opções D18/D19, relatórios sem segredos |
| `test_cli.py` | 6 | Execução, relatórios gravados, códigos de saída 0/1/2, ausência de parâmetro de Token ID |
| `test_ui.py` | 14 | Conexão (sucesso, token errado, CNPJ inválido), desconectar, telas protegidas, chat (stream, erro, nova conversa, instrução de sistema), limpeza de widgets, mensagens de erro |
| `test_provedores.py` | 113 | Base/ids qualificados, erros OpenAI-compatíveis, SSE, cliente (retentativa, `stream_options`), NVIDIA, OpenRouter, roteador, redação de chaves |
| `test_ui_provedores.py` | 28 | Conexão com chaves, modo só-externo, avisos, remoção, catálogo unificado, chat com provedor e raciocínio |
| `test_diagnostico_provedores.py` | 21 | P01–P09, chave inválida, relatórios sem chave |
| **Total** | **350** | |

## 3. Matriz requisito → teste

| Requisito | Testes principais |
|---|---|
| RF-01 | `TestAutenticacao::test_emite_token_e_informa_validade`, `test_credencial_invalida_vira_unauthorized` |
| RF-02 | `test_renova_antes_de_vencer`, `test_401_reemite_token_e_repete_uma_vez`, `test_401_persistente_nao_entra_em_laco`, `test_401_no_chat_reemite_e_repete` |
| RF-03 | `TestModelos` (lista, vazia, cache, forçar) |
| RF-04 | `test_sequencia_de_eventos`, `test_eventos_apos_completed_sao_ignorados`, `test_conversar_agrega_*` |
| RF-05 | `TestConfirmacaoNoHistorico` (error, queda, sem `completed`, cancelamento, recuperação) |
| RF-06 | `TestJanela` e `test_conversa_longa_de_ponta_a_ponta_nunca_viola_o_contrato` |
| RF-07 | `test_validacao_local_nao_toca_a_rede`, `test_models.py` |
| RF-08 | `test_mapeamento_de_status`, `test_corpo_de_erro_sem_formato_usa_mensagem_padrao`, `test_texto_erro_cobre_os_tipos_principais` |
| RF-09 | `test_ui.py` |
| RF-10 | `test_diagnostico.py` |
| RF-11 | `test_cli.py` |
| RF-12 | `test_cabecalhos_de_telemetria`, `test_valores_invalidos_sao_rejeitados` |
| RF-13 | `test_config.py` |
| RF-14 | Manual (§5.1) |
| RNF-01/02 | `test_token_id_nao_vai_para_nenhum_log`, `test_relatorios_nao_vazam_segredos`, `test_mensagem_de_validacao_nao_ecoa_o_conteudo`, `test_conexao_com_sucesso` |
| RNF-03 | `TestResiliencia`, `test_corte_no_meio_do_streaming` |
| RNF-07 | `test_logging_com_redacao_nao_vaza_token` |

## 4. Como executar

```
Windows:      testar.bat            Linux/macOS:  ./testar.sh
Só testes:    .venv\Scripts\python -m pytest        (ou .venv/bin/python -m pytest)
Um arquivo:   testar.bat tests\test_conversa.py -v
```

A mesma verificação roda no GitHub a cada *push*/*pull request* (`.github/workflows/ci.yml`:
Ubuntu e Windows, Python 3.10 e 3.12; inclui `ruff format --check`).

A execução local roda, nesta ordem: `ruff check .` → `mypy` → `pytest`. **Os três precisam passar** antes
de qualquer *commit*.

Critérios de aceite da Fase 1 (todos atendidos no momento da entrega): 350 testes verdes;
`ruff` e `mypy --strict` sem alertas; fluxo de UI completo em `AppTest`; relatórios sem segredos.

## 5. Roteiro de aceitação com o gateway real (manual)

Executar na rede da ITSA, com credenciais de **teste** revogáveis.

### 5.1 Instalação e inicialização
1. Em máquina **sem** as dependências instaladas, executar `iniciar.bat` (ou `./iniciar.sh`).
2. Verificar: `.venv/` criado na pasta; nada instalado globalmente; o navegador abre em `:8501`.

### 5.2 Conexão
1. Credenciais corretas → "Conectado como…" e validade do token (≈ 15 min ou menos).
2. Token ID errado → mensagem amigável; nenhum segredo na tela/terminal.
3. Aguardar o token vencer (ou usar validade curta) e conversar → renovação transparente.

### 5.3 Modelos e chat
1. Tela **Modelos** lista o esperado (inclusive "lista vazia", se aplicável).
2. **Chat de teste**: pergunta curta; ver o texto chegando aos poucos; barra lateral mostra tokens.
3. Fechar a aba no meio de uma resposta → no servidor, verificar se a geração parou (L-08).
4. Derrubar a rede no meio → mensagem de "resposta interrompida"; o histórico não ganha a interação.

### 5.4 Diagnóstico
1. Executar **sem** opcionais; salvar o relatório `.md`/`.json`.
2. Executar com **D19** (carga) em horário de baixo uso; anotar o maior conteúdo aceito.
3. Executar **D18** apenas com autorização (pode acionar bloqueio) e com credencial de teste.
4. Copiar as tabelas para [03 §6](03-contrato-api-gateway.md) e abrir *issues* para cada ALERTA.

### 5.5 Verificação de higiene
Procurar o Token ID e o JWT em: saída do terminal, relatórios, arquivos da pasta
(`grep -r "<token>" .`), e histórico do shell. **Nenhuma ocorrência é aceitável.**

## 6. O que os testes atuais **não** cobrem

- **Provedores reais:** os endpoints da NVIDIA e do OpenRouter foram simulados (`tests/provedor_falso.py`) a partir dos formatos documentados; o comportamento real só é confirmado executando o diagnóstico P01–P09 com chaves reais.

| Lacuna | Motivo | Mitigação |
|---|---|---|
| Comportamento real do gateway/modelos | Ambiente de construção sem acesso ao servidor | Diagnóstico + roteiro §5 |
| Carga e concorrência | Fora do escopo da Fase 1 | Teste de carga dedicado (L-04, L-11) na Fase 7 |
| Qualidade das respostas do modelo | Sem agentes ainda | Perguntas de ouro (Fase 4+) |
| Navegadores reais / acessibilidade | `AppTest` não renderiza | Verificação manual; Playwright se necessário |
| Guardrails | Não implementados | Corpus adversarial (Fase 2) |
| Sistemas operacionais além de Linux (scripts `.bat`) | CI/ambiente Linux | Execução manual no Windows (§5.1) |
