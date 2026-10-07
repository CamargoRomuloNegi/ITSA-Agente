@echo off
rem Inicia o ITSA-Agente (Streamlit) com um ambiente virtual ISOLADO nesta pasta (.venv).
rem Nada e instalado no sistema. Requer Python 3.10+.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente isolado em .venv ...
  py -3 -m venv .venv 2>nul
  if not exist ".venv\Scripts\python.exe" python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo [ERRO] Python 3.10+ nao encontrado. Instale em https://www.python.org/downloads/
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [ERRO] Falha ao instalar dependencias. Verifique a conexao com a internet.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py %*
endlocal
