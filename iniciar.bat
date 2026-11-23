@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Preparando na primeira vez, aguarde...
  py -3 -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python -c "import qrcode" 2>nul || .venv\Scripts\python -m pip install -q -r requirements.txt

rem Sem argumentos: abre o painel (janela), sem console.
if "%~1"=="" (
  start "" .venv\Scripts\pythonw server.py
  exit /b
)
.venv\Scripts\python server.py %*
pause
