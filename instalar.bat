@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Instalacao do Sistema da Loja ===
where python >nul 2>nul || (echo Python 3.10+ nao encontrado. Instale em python.org marcando "Add to PATH". & pause & exit /b 1)
python -m venv .venv || (echo Falha ao criar ambiente. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (echo Falha ao instalar dependencias. Verifique a internet. & pause & exit /b 1)
echo.
echo Instalacao concluida. Use iniciar.bat para abrir o sistema.
pause
