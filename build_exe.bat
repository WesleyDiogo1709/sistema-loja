@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m pip install -r requirements-build.txt
pyinstaller --noconfirm --onedir --name SistemaLoja --add-data "loja\static;loja\static" --add-data "loja\templates;loja\templates" --add-data "loja\schema.sql;loja" run.py
echo Pronto: dist\SistemaLoja\SistemaLoja.exe (os dados ficam em dist\SistemaLoja\dados ou conforme LOJA_DATA_DIR)
pause
