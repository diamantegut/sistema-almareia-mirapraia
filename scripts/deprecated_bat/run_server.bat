@echo off
cd /d "%~dp0"
title Almareia Mirapraia Server
echo Iniciando servidor Almareia Mirapraia...
python wsgi.py
if %ERRORLEVEL% NEQ 0 (
    echo Erro ao iniciar o servidor.
    pause
)
