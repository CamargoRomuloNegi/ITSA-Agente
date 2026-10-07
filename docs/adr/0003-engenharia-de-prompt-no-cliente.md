# ADR-0003 — Engenharia de prompt e de contexto no cliente; `system` não é garantia

- **Status:** Aceita (a revisar após o diagnóstico D10) · **Data:** 07/10/2026

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

## Consequências
- (+) Independência do comportamento específico de cada modelo; troca de modelo é testável.
- (+) Segurança não depende da obediência do modelo (ver [05](../sdd/05-seguranca-e-guardrails.md)).
- (−) Prompts maiores (regras repetidas) consomem contexto — que é escasso.

## Alternativas
- Confiar em `system`: arriscado com modelos pequenos.
- Pedir ao gateway parâmetros/prompts por módulo: acopla o gateway aos agentes; reavaliar (D-09).
