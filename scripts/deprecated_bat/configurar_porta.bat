@echo off
setlocal enabledelayedexpansion

echo.
echo === INICIANDO CONFIGURADOR DE PORTA ===
echo.

REM Tenta encontrar o executavel do Python
set PYTHON_CMD=

REM Tenta 'python'
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto FOUND
)

REM Tenta 'py' (Python Launcher)
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    goto FOUND
)

REM Tenta 'python3'
python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python3
    goto FOUND
)

:NOT_FOUND
echo [ERRO] Python nao encontrado.
echo Por favor, instale o Python em https://www.python.org/downloads/
echo e marque a opcao "Add Python to PATH" durante a instalacao.
echo.
pause
exit /b 1

:FOUND
echo Python encontrado: !PYTHON_CMD!
echo.

REM Executa o script de configuracao
!PYTHON_CMD! configure_port.py

echo.
pause