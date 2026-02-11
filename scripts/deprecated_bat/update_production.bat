@echo off
cd /d "F:\Sistema Almareia Mirapraia"
powershell -ExecutionPolicy Bypass -File ".\update_production.ps1"
echo.
echo Atualizacao concluida! Pressione qualquer tecla para sair...
pause
