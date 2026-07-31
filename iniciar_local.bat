@echo off
cd /d "%~dp0"
if not exist data mkdir data
python -m streamlit run app.py
pause
