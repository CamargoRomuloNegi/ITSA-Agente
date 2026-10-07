@echo off
rem Diagnostico do gateway pela linha de comando.
rem Exemplo: diagnostico.bat --cpf-cnpj 12ABC34501DE35 --usuario CARLOS --com-carga
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv 2>nul
  if not exist ".venv\Scripts\python.exe" python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
".venv\Scripts\python.exe" -m itsa_agente.diagnostics %*
endlocal
