@echo off
title KON Assistant - Backend Server
echo ====================================================
echo  INICIANDO SERVIDOR BACKEND DO KON (Python/FastAPI)
echo ====================================================
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual .venv nao encontrado!
    echo Execute: uv venv --python 3.12 .venv
    echo E depois: uv pip install -r requirements.txt
    pause
    exit /b 1
)

echo Ativando ambiente virtual...
call .venv\Scripts\activate.bat

echo Iniciando backend KON...
python -m backend.main
pause
