@echo off
cd /d "%~dp0"
echo Iniciando ARC+ Enterprise v8...
python -m streamlit run app.py
pause
