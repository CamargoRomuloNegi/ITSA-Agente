#!/usr/bin/env bash
# Executa os testes automatizados, o lint e a checagem de tipos (ambiente isolado em .venv).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
[ -x ".venv/bin/python" ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest "$@"
