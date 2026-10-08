# ADR-0003 — Engenharia de prompt e de contexto no cliente; `system` não é garantia

- **Status:** Aceita; atualizada com a medição do D10 · **Data:** 07/10/2026 (atualizada em 08/10/2026)

## Contexto
A API do gateway só expõe `messages`, `model` e `stream`: **não há** parâmetros de geração nem
*tools*, e o swagger não diz se `role=system` é aceito/obedecido por modelos locais pequenos
(L-06, L-07). A estratégia de negócio é compensar o tamanho do modelo com prompt e contexto.

## Decisão
1. Toda a engenharia de prompt, o enriquecimento de contexto, o roteamento e os cálculos ficam **no
   ITSA-Agente**, não no gateway.
2. `Conversa` aceita um `prompt_sistema` enviado como `role=system` **na primeira posição** — mas o
   desenho dos agentes **não depende** de que o modelo o obedeça: regras críticas serão também
   repetidas no início/fim da mensagem de usuário (estrutura "sanduíche") e garantidas por código.
3. O diagnóstico D10 mede aceitação e obediência; o resultado pode simplificar (ou obrigar) esse desenho.

### Atualização (08/10/2026) — medição no gateway real
O D10 mostrou que o `role=system` é **aceito e obedecido** (`iaitsa-geral`, tarefa trivial de uma
palavra). Consequência: o prompt de sistema passa a ser a camada **principal** de instruções de cada
agente. A decisão 2 permanece: a amostra é mínima e não prova obediência sob ataque, com contexto
grande ou regras múltiplas; por isso a estrutura "sanduíche" e as barreiras por código (Fase 2)
continuam obrigatórias. Em D17 o gateway aceitou `temperature`, mas sem efeito comprovado.

## Consequências
- (+) Independência do comportamento específico de cada modelo; troca de modelo é testável.
- (+) Segurança não depende da obediência do modelo (ver [05](../sdd/05-seguranca-e-guardrails.md)).
- (−) Prompts maiores (regras repetidas) consomem contexto — que é escasso.

## Alternativas
- Confiar em `system`: arriscado com modelos pequenos.
- Pedir ao gateway parâmetros/prompts por módulo: acopla o gateway aos agentes; reavaliar (D-09).
