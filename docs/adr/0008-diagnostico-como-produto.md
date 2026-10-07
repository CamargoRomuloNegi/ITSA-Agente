# ADR-0008 — Diagnóstico mede o gateway real em vez de supor

- **Status:** Aceita · **Data:** 07/10/2026

## Contexto
A documentação do gateway é boa no caminho feliz, mas omite catálogo de erros, limites e vários
comportamentos (ver [03 §5](../sdd/03-contrato-api-gateway.md)). Decisões de desenho dos agentes
dependem desses fatos.

## Decisão
Tratar o diagnóstico como **funcionalidade do produto**: bateria D01–D19 com relatório que inclui
o **catálogo de respostas de erro observadas**, disponível na interface e na CLI. Cenários
negativos usam credenciais válidas e *payloads* inválidos; o único que envia credencial inválida
(D18) e o de carga (D19) são **opcionais**. Uma verificação nunca derruba as demais.

## Consequências
- (+) Fecha as lacunas com dados, alimenta o SDD e o simulador de testes, serve ao suporte.
- (+) Detecta regressões/divergências do servidor após atualizações.
- (−) Consome algumas inferências; D19 pode ser demorado.
- (−) D18 pode acionar bloqueio de credencial (daí o padrão desligado).
