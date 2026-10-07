@echo off
rem Executa testes, lint e checagem de tipos (ambiente isolado em .venv).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv 2>nul
  if not exist ".venv\Scripts\python.exe" python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
".venv\Scripts\python.exe" -m ruff check .
".venv\Scripts\python.exe" -m mypy
".venv\Scripts\python.exe" -m pytest %*
endlocal
