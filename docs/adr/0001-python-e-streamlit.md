# ADR-0001 — Python + Streamlit executados direto da pasta

- **Status:** Aceita · **Data:** 07/10/2026

## Contexto
O produto precisa de uma interface de chat com *streaming*, desenvolvida rápido, por uma equipe
que prefere Python, e **executável sem instalar dependências no sistema** (requisito P4).
Cada agente terá uma tela própria.

## Decisão
Usar **Python 3.10+** e **Streamlit**. A pasta é autossuficiente: `iniciar.bat`/`iniciar.sh` criam
um ambiente virtual em `.venv/` e instalam `requirements.txt` ali. `app.py` é o ponto de entrada
(`st.navigation`, uma página por tela/agente).

## Consequências
- (+) Entrega rápida; `st.chat_message`, `st.chat_input` e `st.write_stream` cobrem o chat.
- (+) Nada é instalado globalmente; o ambiente é descartável (apagar `.venv/`).
- (+) Testes de interface com `streamlit.testing.v1.AppTest`, sem navegador.
- (−) Streamlit re-executa o script a cada interação: estado precisa viver em `st.session_state`.
- (−) Não há autenticação própria: produção exige proxy reverso (ver [09](../sdd/09-operacao.md)).
- (−) Uma *thread* por sessão durante o streaming: limite de escala (ver [02 §8](../sdd/02-arquitetura.md)).

## Alternativas consideradas
- **FastAPI + front-end SPA:** mais flexível e escalável, porém mais código e outra *stack*; adiado —
  o núcleo já é independente de UI, permitindo migrar depois.
- **Gradio/Chainlit:** bons para chat, menos flexíveis para telas de negócio por módulo.
