@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo Instalando ARC+ Enterprise v5.1
echo ==============================================

python --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python no esta instalado o no esta en PATH.
  pause
  exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
  echo.
  echo ERROR: No se pudieron instalar todas las dependencias.
  pause
  exit /b 1
)

echo.
echo Instalacion completada.
echo Ahora ejecute INICIAR_ARC_PLUS.bat
pause
