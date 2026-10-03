@echo off
title KON - Teste Direto de Voz
cd /d "%~dp0"

echo ====================================================
echo         KON — TESTE DIRETO DE VOZ REAL
echo ====================================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual .venv nao encontrado!
    echo Execute 'uv sync' ou instale os pacotes no .venv.
    pause
    exit /b 1
)

.venv\Scripts\python.exe testar_voz.py
pause
