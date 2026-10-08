# 08 — Roadmap

Princípio: **um projeto de cada vez**, cada fase entregando algo utilizável e validado. Os agentes
só começam depois que a segurança e a camada de dados existirem.

```mermaid
flowchart LR
    F1["F1 Fundação ✅<br/>cliente · diagnóstico · SDD"] --> F2["F2 Guardrails"]
    F1 --> F3["F3 Camada de dados"]
    F2 --> F4["F4 Agente Comercial / Vendas"]
    F3 --> F4
    F4 --> F5["F5 Agente Fiscal"]
    F5 --> F6["F6 Agente Contábil"]
    F4 --> F7["F7 Produção<br/>licenciamento · ERP · observabilidade"]
    F6 --> F7
```

F2 e F3 podem andar em paralelo. A Fase 7 começa a ser preparada junto à Fase 4 (pilotos) e se
conclui depois dos agentes.

## Fases

### Fase 1 — Fundação ✅ *(esta entrega)*
**Entregáveis:** cliente da API; conversa/janela; segurança de segredos; diagnóstico D01–D19; telas;
188 testes (350 na v0.2.0); SDD e ADRs; scripts sem instalação.
**Saída:** critérios de [07 §4](07-plano-de-testes.md) atendidos.
**Validação com o gateway real:** diagnóstico executado em 08/10/2026 (aprovado, sem falhas); medições
em [03 §6](03-contrato-api-gateway.md). Restam as pendências de medição de §6.4 (teto de contexto,
vazão de geração, efeito de `temperature`, corpo bruto dos erros do framework).

### Fase 1.5 — Provedores externos ✅ *(v0.2.0)*
**Entregáveis:** integração nativa com NVIDIA (`nemotron-3-ultra-550b-a55b`) e OpenRouter; roteador por
modelo qualificado; raciocínio controlável; diagnóstico P01–P09; 350 testes; ADR-0010 e SDD 11.
**Pendente:** validação com chaves reais (L-13…L-18).

### Fase 2 — Guardrails
**Objetivo:** pacote `guardrails/` reutilizável (entrada, escopo, montagem de prompt com
delimitadores e *canary*, saída, limites, auditoria sem conteúdo).
**Entregáveis:** implementação de [05 §B](05-seguranca-e-guardrails.md); corpus adversarial inicial;
métricas de bloqueio/falso positivo; ADR dos limites.
**Saída:** metas de [05 §B.8](05-seguranca-e-guardrails.md) atingidas sobre o corpus.
**Dependências:** resultado do D10 (obediência a `system`) e D19 (limites de contexto).

### Fase 3 — Camada de dados
**Objetivo:** catálogo de views, executor somente leitura, mascaramento, representação compacta.
**Entregáveis:** [06 §4](06-agentes-e-modulos.md) implementado; testes de isolamento entre
empresas/usuários; medição de tamanho (caracteres/tokens) das representações.
**Saída:** nenhuma consulta fora do catálogo; nenhum dado sensível sem mascaramento; isolamento comprovado.
**Dependências:** decisão D-04 (acesso a banco) e levantamento das views reais com o cliente-piloto.
*Pode caminhar em paralelo à Fase 2.*

### Fase 4 — Agente Comercial / Vendas
**Entregáveis:** agente, tela própria, perguntas de ouro, prompts versionados, avaliação, guia do
usuário; piloto com um cliente.
**Saída:** meta de acerto numérico e de recusa definida e atingida; revisão de segurança aprovada.

### Fase 5 — Agente Fiscal
**Entregáveis adicionais:** base normativa versionada com vigência e fonte; revisão por especialista
fiscal; cálculos 100 % fora do modelo.

### Fase 6 — Agente Contábil
**Entregáveis adicionais:** conferência numérica reforçada; perfis por empresa/centro de custo.

### Fase 7 — Produção
**Entregáveis:** habilitação de módulos por cliente (L-09); integração com o ERP (identidade
assinada, Token ID no backend); implantação (proxy, TLS, autenticação); observabilidade
(métricas, alertas); teste de carga (L-04, L-11); política de retenção/LGPD; manual de operação.

## Decisões em aberto

| ID | Decisão | Responsável sugerido | Necessária antes de |
|---|---|---|---|
| D-01 | Resultados do diagnóstico no gateway real (D10, D17, D19, catálogo de erros) | Dev + infraestrutura | Fase 2 |
| D-02 | Como o gateway/ERP informa os **módulos licenciados** (L-09) | Licenciamento | Fase 7 (idealmente Fase 4) |
| D-03 | Lista de intenções, tom e recusas padrão por agente | Produto + especialistas | Fases 4–6 |
| D-04 | Tecnologia e local de acesso ao banco do cliente (SGBD, driver, onde roda a consulta) | Arquitetura + clientes | Fase 3 |
| D-05 | Quem fornece e atualiza a base normativa fiscal (fonte, periodicidade) | Fiscal | Fase 5 |
| D-06 | Persistência de conversas (sim/não, retenção, anonimização) | Jurídico + produto | Fase 7 |
| D-07 | Modelo de implantação (§7 de [02](02-arquitetura.md)): local, servidor interno ou integrado | Arquitetura | Fase 7 |
| D-08 | Metas numéricas de qualidade por agente | Produto | Fase 4 |
| D-09 | Possibilidade de o gateway expor parâmetros de geração (temperatura, limite de tokens) e papel `system` obedecido | Equipe do gateway | Fase 2 |

## Riscos de cronograma

1. **Qualidade do modelo local abaixo do necessário** para fiscal/contábil → mitigar com tarefas
   pequenas, números pré-computados e, se preciso, modelo maior no mesmo gateway.
2. **Views dos clientes heterogêneas** → começar com um cliente-piloto e padronizar um
   *contrato de dados* de views.
3. **Capacidade do servidor de modelos** sob uso simultâneo → medir (L-11) antes do piloto.
