@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (echo Execute instalar.bat primeiro. & pause & exit /b 1)
call .venv\Scripts\activate.bat
if not exist dados_demo\loja.db python tools\demo_data.py
set LOJA_DATA_DIR=%~dp0dados_demo
set LOJA_PORT=5001
echo MODO DEMONSTRACAO (dados ficticios separados). Login: admin / Demo@1234
python run.py
pause
