@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (echo Execute instalar.bat primeiro. & pause & exit /b 1)
call .venv\Scripts\activate.bat
rem Para liberar acesso por outros computadores da rede, remova o "rem" da linha abaixo:
rem set LOJA_HOST=0.0.0.0
python run.py
pause
