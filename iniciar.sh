#!/usr/bin/env bash
# Inicia o ITSA-Agente (Streamlit) usando um ambiente virtual ISOLADO dentro desta pasta (.venv).
# Nada é instalado no sistema. Requer Python 3.10+.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[ERRO] Python 3.10+ não encontrado. Instale-o ou defina a variável PYTHON." >&2
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "[ERRO] É necessário Python 3.10 ou superior (encontrado: $("$PY" -V))." >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Criando ambiente isolado em .venv ..."
  "$PY" -m venv .venv
fi

.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
exec .venv/bin/python -m streamlit run app.py "$@"
