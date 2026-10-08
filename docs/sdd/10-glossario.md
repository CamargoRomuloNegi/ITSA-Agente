# 10 — Glossário

| Termo | Significado |
|---|---|
| **Agente** | Especialista estreito (vendas, fiscal, contábil…) definido por escopo, prompt, dados e guardrails, executado sobre o núcleo comum |
| **Auditoria (sem conteúdo)** | Registro de metadados do turno (quem, quando, agente, tokens, vereditos) sem o texto das conversas |
| **Canary (token-canário)** | Texto aleatório colocado no prompt de sistema; se aparecer na saída, indica extração do prompt |
| **Catálogo de erros** | Tabela de respostas de erro observadas (endpoint, cenário, HTTP, `error.code`, mensagem) gerada pelo diagnóstico |
| **Catálogo de views** | Lista das *views* do banco que cada agente pode consultar, com colunas, filtros e mascaramento |
| **`completed`** | Evento final do streaming que sinaliza sucesso; só então a interação entra no histórico |
| **Conversa (`Conversa`)** | Objeto que guarda `conversationId`, prompt de sistema e histórico **confirmado** |
| **`conversationId`** | GUID estável durante toda a conversa |
| **CNPJ alfanumérico** | Novo formato de CNPJ com 14 caracteres que podem incluir letras (ex.: `12ABC34501DE35`) |
| **Credenciais** | CPF/CNPJ + Token ID + usuário do ERP |
| **`delta`** | Evento do streaming com um trecho de texto |
| **Diagnóstico** | Bateria D01–D19 que mede o comportamento real do gateway |
| **ERP** | Sistema de gestão da ITSA, que hospeda as telas dos agentes |
| **`error` (evento)** | Falha durante a geração; a interação é descartada |
| **Few-shot** | Exemplos curtos incluídos no prompt para orientar o formato da resposta |
| **Gateway (IAitsaGateway)** | API que autentica clientes e intermedia o acesso aos modelos locais |
| **Guardrail** | Controle que limita entrada, escopo, dados ou saída de um agente |
| **Injeção de prompt** | Tentativa de fazer o modelo seguir instruções do atacante (direta, pelo usuário; indireta, escondida nos dados) |
| **Janela de contexto** | Parte do histórico efetivamente enviada ao modelo (≤ 30 mensagens e ≤ orçamento de caracteres) |
| **JWT** | Token de acesso de curta duração emitido por `POST /api/auth/token` |
| **LGPD** | Lei Geral de Proteção de Dados (Lei 13.709/2018) |
| **Módulo** | Unidade licenciável: agente + tela |
| **Modelo qualificado** | Identificador `provedor::modelo`; sem `::` indica o gateway ITSA |
| **NDJSON** | *Newline-delimited JSON*: um objeto JSON completo por linha |
| **`requestId`** | Identificador de uma requisição de chat, presente nos eventos; use-o ao reportar problemas |
| **Provedor externo** | Serviço de modelos de terceiros acessado por chave de API (NVIDIA, OpenRouter) |
| **Raciocínio** | Trecho de "pensamento" do modelo, exibido à parte e nunca guardado no histórico |
| **Redator** | Componente que remove segredos e dados sensíveis de textos e logs |
| **Roteador** | Componente que direciona cada chamada de chat à origem indicada pelo modelo qualificado |
| **SDD** | *Software Design Document* (esta documentação) |
| **SSE** | *Server-Sent Events*: formato de streaming usado pelos provedores externos |
| **`started`** | Primeiro evento do streaming |
| **Token ID** | Credencial individual do cliente, fornecida pelo licenciamento; segredo |
| **TTFB / 1º trecho** | Tempo até o primeiro `delta` |
| **View** | Visão do banco do cliente, somente leitura, usada para alimentar um agente |
