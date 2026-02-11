@echo off
cd /d "%~dp0"
title Almareia Mirapraia Server (PROD)
echo --- INICIANDO SERVIDOR DE PRODUCAO (wsgi.py) ---
python wsgi.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] O servidor parou com codigo %ERRORLEVEL%.
    pause
)
