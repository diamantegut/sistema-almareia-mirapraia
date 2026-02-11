@echo off
cd /d "%~dp0"
echo --- INICIANDO AMBIENTE DE DESENVOLVIMENTO (run.py) ---
python run.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] O servidor parou com codigo %ERRORLEVEL%.
    pause
)
