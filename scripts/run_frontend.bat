@echo off
title KON Assistant - Frontend Interface
echo ====================================================
echo  INICIANDO INTERFACE DO KON (React + Vite)
echo ====================================================
cd /d "%~dp0\..\frontend"

if not exist "node_modules" (
    echo [INFO] Instalando dependencias do frontend...
    call npm install
)

echo Iniciando servidor de desenvolvimento Vite...
call npm run dev
pause
