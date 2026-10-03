@echo off
title KON - Inicializador Completo
echo ====================================================
echo             INICIANDO SISTEMA KON
echo ====================================================

cd /d "%~dp0"

echo [1/3] Liberando porta 8000 e iniciando Servidor Backend Python com Voz Real...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
start "KON - Backend Server" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe main.py"

echo [2/3] Aguardando backend inicializar...
timeout /t 3 /nobreak >nul

echo [3/3] Iniciando Frontend React e abrindo navegador...
start "KON - Frontend Vite" cmd /k "cd /d "%~dp0frontend" && npm run dev"

timeout /t 2 /nobreak >nul
start http://127.0.0.1:5173

echo ====================================================
echo  KON INICIADO COM SUCESSO!
echo  Voce pode fechar esta janela caso queira.
echo ====================================================
pause
