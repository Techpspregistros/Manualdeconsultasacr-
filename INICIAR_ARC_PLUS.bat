@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo Iniciando ARC+ Enterprise v5.1
echo ==============================================

python --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python no esta instalado o no esta en PATH.
  echo Ejecute primero instalar_v5_1.bat.
  pause
  exit /b 1
)

python launcher.py

if errorlevel 1 (
  echo.
  echo La aplicacion se detuvo con un error.
  echo Revise el mensaje mostrado arriba.
  pause
)
