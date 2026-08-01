@echo off
cd /d "%~dp0"
echo Iniciando ARC+ Enterprise v9...
python -m streamlit run app.py
pause
