# ADR-0010 — Provedores externos (NVIDIA, OpenRouter) ao lado do gateway, com roteamento por modelo

- **Status:** Aceita · **Data:** 08/10/2026

## Contexto
A premissa do projeto é usar **modelos locais** gerenciados pelo IAitsaGateway. Para ajustar
**tráfego, qualidade das respostas e sensibilidade dos dados**, a ITSA quer poder, no mesmo projeto,
chamar também modelos externos: a API gratuita da NVIDIA (`nvidia/nemotron-3-ultra-550b-a55b`,
build.nvidia.com) e o OpenRouter (agregador de modelos). Os dois modelos do gateway já são
equivalentes a modelos dessas famílias (Qwen e NVIDIA), e a intenção é **avaliar qual atende melhor
cada agente**. Em produção o modelo de cada agente será um **parâmetro fixo**, sem escolha do
usuário; na tela de teste a escolha é livre.

Restrição: **nada do que existe pode ser alterado em comportamento** — o gateway continua sendo a
origem padrão e seus testes, telas e contrato permanecem.

Os dois provedores usam a API de *chat completions* compatível com a da OpenAI, com streaming SSE,
e autenticam por chave de API (``Authorization: Bearer``), não por JWT.

## Decisão
1. **Pacote novo `itsa_agente/providers/`**, sem tocar na semântica de `gateway/`. Um cliente
   genérico compatível com a OpenAI (`ClienteOpenAICompat`, sobre `httpx`) e duas subclasses finas
   (`ProvedorNvidia`, `ProvedorOpenRouter`) com as particularidades de cada um.
2. **Mesmo vocabulário de eventos.** O decodificador SSE converte o stream nos eventos que
   `Conversa` já consome (`EventoIniciado/Delta/Concluido/Erro`). Duas adições compatíveis:
   `EventoRaciocinio` (raciocínio separado da resposta) e `EventoConcluido.motivo` (`stop`,
   `length`...). `Conversa` e o contrato `TransmissorChat` não mudam de forma incompatível.
3. **Identificador qualificado do modelo.** Modelos externos usam `provedor::id` (ex.:
   `nvidia::nvidia/nemotron-3-ultra-550b-a55b`); **todo id sem `::` pertence ao gateway**. Assim os
   ids do gateway ficam inalterados.
4. **`Roteador`** implementa `TransmissorChat` e escolhe o destino pelo prefixo. Também unifica o
   catálogo de modelos e isola falhas: uma origem fora do ar não esconde as outras.
5. **Chaves de API só em memória**, digitadas na mesma tela de Conexão (campos opcionais),
   registradas no redator global (ADR-0007) e cobertas por padrões de mascaramento
   (`nvapi-…`, `sk-or-…`). Não há variável de ambiente nem `.env` para chaves, por desenho.
6. **O gateway deixa de ser obrigatório na sessão**: pode-se conectar só a provedores externos
   (Token ID em branco). Com Token ID informado, o fluxo é o de antes.
7. **Retentativa** igual ao ADR-0004 (conexão e indisponibilidade antes do primeiro byte; nunca em
   timeout de leitura nem no meio do stream; `429` não é repetido), estendida a `502/503/504` por
   serem as indisponibilidades transitórias dos provedores externos.
8. **Verificação da chave sem custo relevante e sem falso positivo:** `GET /models` é **público**
   na NVIDIA e no OpenRouter (verificado em 08/10/2026), então não valida a chave. NVIDIA: conversa
   mínima de 1 token; OpenRouter: `GET /key`, que também informa a cota diária de modelos gratuitos.
9. **Raciocínio:** desligado por padrão no Nemotron 3 (resposta direta, menos tokens/latência) com
   interruptor na tela; o texto de raciocínio é exibido à parte e **nunca entra no histórico**.
10. **Política de dados (decisão do produto, 08/10/2026):** *sem restrição por ora.* A ITSA não
    proíbe o usuário de enviar o que quiser a um provedor externo — hoje ele já poderia fazê-lo por
    conta própria. O foco da proteção (Fase 2) é **uso malicioso** (injeção de prompt, extração do
    prompt, abuso), não uso indevido por usuário legítimo. A interface identifica a origem do modelo
    (provedor no seletor e nas listas). Se a política mudar, o ponto de controle natural é uma
    marca por agente no `Roteador`.
11. **Sem SDK de terceiros** (`openai`, LiteLLM): o contrato usado é pequeno, e manter `httpx`
    preserva controle de retentativa, tempos, redação de segredos e a ausência de dependências novas
    (ADR-0002).

## Consequências
- (+) Comparar modelos locais e externos com o mesmo código, o mesmo diagnóstico e a mesma conversa.
- (+) Base pronta para "um modelo fixo por agente" (basta configuração) e para medir tráfego/peso.
- (+) Nenhum teste anterior mudou de significado; ids e telas do gateway permanecem.
- (−) Passa a existir tráfego para terceiros quando o usuário escolhe um modelo externo (ver
  [05 §A.4](../sdd/05-seguranca-e-guardrails.md) e a nota de LGPD em B.9).
- (−) Os limites e termos do endpoint gratuito da NVIDIA **não estão documentados** na página do
  modelo; o OpenRouter publica limites para modelos `:free` (20 req/min; 50/dia, ou 1000/dia com ≥ 10
  créditos comprados). Dependência de serviços de terceiros: disponibilidade e preço podem mudar.
- (−) Superfície de teste maior; mitigada por provedor simulado e pelo diagnóstico P01–P09.

## Alternativas
- **SDK `openai` apontando para as URLs dos provedores:** menos código, mas retira o controle fino
  de retentativa/tempos/redação e adiciona dependência pesada. Rejeitada.
- **Rotear tudo pelo gateway (ele chamaria NVIDIA/OpenRouter):** centralizaria, mas acopla o gateway
  aos agentes, exige mudança no servidor e esconde custos/limites de cada provedor do projeto.
  Reavaliar quando o licenciamento por módulo estiver definido.
- **Bloquear dados sensíveis para provedores externos agora:** rejeitada pela decisão de produto
  acima; reversível via marca por agente.
