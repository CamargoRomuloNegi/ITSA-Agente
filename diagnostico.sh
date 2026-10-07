#!/usr/bin/env bash
# Executa o diagnóstico do gateway pela linha de comando. Veja: python -m itsa_agente.diagnostics --help
# Exemplo: ./diagnostico.sh --cpf-cnpj 12ABC34501DE35 --usuario CARLOS --com-carga
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
[ -x ".venv/bin/python" ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
exec .venv/bin/python -m itsa_agente.diagnostics "$@"
