@echo off
rem Gera dist\SomDoPC.exe (roda sem Python instalado).
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name SomDoPC --icon icone.ico ^
  --add-data "static;static" --add-data "icone.ico;." ^
  --collect-all aiortc --collect-all av --collect-binaries pyaudiowpatch ^
  server.py
echo.
echo Pronto: dist\SomDoPC.exe
pause
