# 09 — Operação

## 1. Requisitos

| Item | Requisito |
|---|---|
| Python | 3.10 ou superior (`python --version`) |
| Rede | Saída HTTPS até o gateway (padrão: `https://suporteitsa2.ddns.net`) |
| Sistema | Windows, Linux ou macOS |
| Disco | ~300 MB para o `.venv` (Streamlit e dependências) |
| Instalação no sistema | **Nenhuma**: tudo fica em `.venv/` dentro da pasta do projeto |

## 2. Configuração

Ordem de precedência (maior vence): **variável de ambiente** > arquivo `.env` > padrão.
Copie `.env.example` para `.env`. Valores inválidos impedem o início com mensagem clara.

| Variável | Padrão | Descrição |
|---|---|---|
| `ITSA_BASE_URL` | `https://suporteitsa2.ddns.net` | URL base do gateway (`http://` ou `https://`) |
| `ITSA_VERIFY_TLS` | `true` | Verificar o certificado TLS. **Só desligar em teste**, nunca em produção |
| `ITSA_CONNECT_TIMEOUT` | `10` | Segundos para conectar |
| `ITSA_REQUEST_TIMEOUT` | `30` | Segundos de leitura/escrita em chamadas não-streaming |
| `ITSA_STREAM_READ_TIMEOUT` | `120` | **Silêncio máximo** (s) entre trechos do streaming; cubra o 1º token do modelo local |
| `ITSA_MAX_RETRIES` | `2` | Retentativas de conexão e de `503` (ver ADR-0004) |
| `ITSA_TOKEN_SKEW_SECONDS` | `60` | Renova o JWT este tempo antes de vencer |
| `ITSA_MODELS_CACHE_SECONDS` | `60` | Cache da lista de modelos |
| `ITSA_MAX_HISTORY_CHARS` | `24000` | Orçamento de caracteres do histórico enviado (calibrar com o D19) |
| `ITSA_ERP_VERSION` | *(vazio)* | Cabeçalho `X-Erp-Version` (≤ 50 caracteres) |
| `ITSA_CHAT_MODULE_VERSION` | *(vazio)* | Cabeçalho `X-Chat-Module-Version` (≤ 50 caracteres) |
| `ITSA_INSTALLATION_ID` | *(vazio)* | Cabeçalho `X-Installation-Id` (GUID) |
| `ITSA_CPF_CNPJ`, `ITSA_ERP_USER` | *(vazio)* | Pré-preenchem a tela de conexão e a CLI |
| `ITSA_TOKEN_ID` | *(vazio)* | **Somente desenvolvimento.** Preenche o Token ID; evite — prefira digitar |
| `ITSA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

Constantes não configuráveis: espera de retentativa `0,5 s × 2ⁿ`; teto de `Retry-After` 10 s;
`User-Agent: ITSA-Agente/<versão>`.

## 3. Execução

| Objetivo | Comando |
|---|---|
| Abrir a aplicação | `iniciar.bat` · `./iniciar.sh` |
| Outra porta | `iniciar.bat --server.port 8600` (argumentos vão ao Streamlit) |
| Testes + lint + tipos | `testar.bat` · `./testar.sh` |
| Diagnóstico (CLI) | `diagnostico.bat --cpf-cnpj <doc> --usuario <user> [--modelo <id>] [--com-carga] [--com-credencial-invalida]` |

O diagnóstico por CLI pede o Token ID **sem eco** (ou lê `ITSA_TOKEN_ID`) e grava relatórios
`.md` e `.json` em `relatorios/` (ignorado pelo Git). Código de saída: `0` sem falhas, `1` com
falhas, `2` uso inválido.

### Dica: executar sem os scripts
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        (Linux: .venv/bin/pip …)
.venv\Scripts\streamlit run app.py
```

## 4. Segurança operacional

1. **Nunca** versionar `.env`, relatórios ou capturas de tela com tokens (o `.gitignore` já cobre).
2. Use credenciais de **teste revogáveis** em desenvolvimento; revogue as que forem coladas em
   chats, tickets ou terminais compartilhados.
3. Relatórios de diagnóstico são redigidos, mas revise antes de enviá-los a terceiros.
4. Mantenha `ITSA_VERIFY_TLS=true`. Se o certificado do gateway não for confiável, instale a
   cadeia correta em vez de desligar a verificação.
5. Mantenha o ambiente atualizado (`pip install -U -r requirements.txt` periodicamente) e rode
   `testar` após atualizar.

## 5. Implantação como serviço (piloto)

O Streamlit **não possui autenticação própria**. Para uso além da máquina local:

1. Rode atrás de **proxy reverso** (nginx, Caddy, IIS/ARR) com **TLS** e autenticação (SSO do ERP,
   *basic auth* mínimo em piloto, ou restrição por rede/VPN).
2. Habilite *WebSocket* no proxy (o Streamlit depende dele) e *timeouts* ≥ `ITSA_STREAM_READ_TIMEOUT`.
3. Execute como serviço do sistema (systemd/NSSM) com usuário sem privilégios; logs em
   `journald`/arquivo com rotação.
4. Uma única instância atende várias sessões; cada sessão tem credenciais e histórico próprios.
5. Dimensione pela concorrência de **streams simultâneos** (cada um ocupa uma *thread*).

## 6. Observabilidade

| Fonte | Conteúdo | Cuidado |
|---|---|---|
| Logs (`itsa_agente.*`) | Eventos de token (usuário e validade), retentativas, 401, tempos por chamada (`DEBUG`) | Redação automática; nunca há conteúdo de conversa |
| Mensagens de erro na tela | Texto amigável + `código` + HTTP + `requestId` | Peça o `requestId` ao reportar problemas |
| Relatório de diagnóstico | Estado do gateway, latências, catálogo de erros | Anexável a chamados |

Para depurar, use `ITSA_LOG_LEVEL=DEBUG` (mostra método, caminho, status e tempo — sem corpos).

## 7. Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| "Python 3.10+ não encontrado" | Python ausente ou antigo | Instalar Python 3.10+; no Linux, definir `PYTHON=python3.11` |
| Falha ao instalar dependências | Sem internet/proxy | Configurar `pip` com o proxy corporativo; repetir |
| `iniciar` abre e a página não carrega | Porta 8501 ocupada | `iniciar.bat --server.port 8600` |
| "Não foi possível conectar ao servidor de IA" | DNS/rede/firewall; DDNS fora do ar; URL errada | Conferir `ITSA_BASE_URL`; testar o endereço no navegador; D01 no diagnóstico |
| Erro de certificado (TLS) | Certificado inválido/autoassinado ou proxy interceptando | Instalar a cadeia correta; **só em teste** usar `ITSA_VERIFY_TLS=false` |
| "Credenciais inválidas" (401) | CPF/CNPJ, Token ID ou usuário incorretos | Conferir com o licenciamento; cuidado com tentativas repetidas (L-10) |
| "Acesso negado" (403) | Licença vencida/bloqueada ou sem o recurso | Verificar com o licenciamento |
| "Muitas requisições" (429) | Limite de taxa | Aguardar o tempo informado |
| "Serviço de IA indisponível" (503) | Modelo carregando/indisponível | Aguardar; verificar o servidor de modelos; o cliente já tentou novamente |
| "A resposta foi interrompida" | Queda de rede ou corte do gateway | Repetir a pergunta; a interação **não** foi guardada |
| "O servidor demorou demais" | Modelo lento ou sobrecarregado | Ajustar `ITSA_STREAM_READ_TIMEOUT`; medir com D07 |
| Texto com acentos quebrados | Codificação | Rodar D08; conferir proxies intermediários |
| Lista de modelos vazia | Nenhum modelo habilitado/instalado para o cliente | Verificar configuração do gateway |
| "Dados inválidos: …" | Validação local do contrato | Ler a mensagem (campo e regra); ajustar a entrada |

## 8. Atualização e versionamento

- Versão em `itsa_agente/__init__.py` (SemVer); registrar mudanças em `CHANGELOG.md`.
- Atualizar: substituir os arquivos, executar `iniciar` (as dependências são reconciliadas
  automaticamente) e `testar`.
- Mudanças no swagger do gateway: seguir [03 §7](03-contrato-api-gateway.md).

## 9. Backup e recuperação

A aplicação **não guarda estado em disco** (nem histórico, nem credenciais). O que vale preservar:
o repositório Git, o `.env` local (fora do Git) e os relatórios de diagnóstico relevantes.
