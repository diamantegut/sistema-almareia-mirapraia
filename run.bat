@echo off
cd /d "%~dp0"
setlocal
set "BASE_DIR=%CD%"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH. Instale o Python 3.x e tente novamente.
    goto END
)

if not exist "%BASE_DIR%\run.py" (
    echo [ERRO] Arquivo run.py nao encontrado em "%BASE_DIR%".
    goto END
)

if not exist "%BASE_DIR%\scripts" (
    echo [ERRO] Pasta scripts nao encontrada em "%BASE_DIR%".
    goto END
)

if not exist "%BASE_DIR%\scripts\setup_env.py" (
    echo [ERRO] Arquivo scripts\setup_env.py nao encontrado em "%BASE_DIR%\scripts".
    goto END
)

if not exist "%BASE_DIR%\scripts\check_ngrok_config.py" (
    echo [ERRO] Arquivo scripts\check_ngrok_config.py nao encontrado em "%BASE_DIR%\scripts".
    goto END
)

set "PYTHON=python"
set "NGROK_ENV=development"
set "NGROK_DOMAIN=syrupy-jaliyah-intracranial.ngrok-free.dev"

echo.
echo ===================================================
echo      SISTEMA MIRAPRAIA - INICIALIZACAO SERVIDOR
echo ===================================================
echo.

:ASK_PORT
echo.
set /p server_port="Digite a porta do servidor (Ex: 5000, 5001): "
if "%server_port%"=="" goto ASK_PORT

:ASK_NGROK
echo.
echo Deseja configurar o ngrok para esta instancia?
echo S - Sim, configurar ngrok para a porta %server_port%
echo N - Nao, iniciar apenas o servidor local
set /p use_ngrok="Opcao (S/N): "

if /I "%use_ngrok%"=="S" goto CONFIG_NGROK
if /I "%use_ngrok%"=="N" goto START_SERVER

echo Opcao invalida. Tente novamente.
goto ASK_NGROK

:CONFIG_NGROK
echo.
echo [INFO] Verificando instancias existentes do ngrok...
tasklist /FI "IMAGENAME eq ngrok.exe" | find /I "ngrok.exe" >nul 2>&1
if not errorlevel 1 (
    echo [AVISO] Uma instancia do ngrok esta em execucao.
    echo [AVISO] Ela sera encerrada e reconfigurada para a porta %server_port% em "%BASE_DIR%".
    taskkill /F /IM ngrok.exe >nul 2>&1
)

echo.
echo [INFO] Atualizando configuracao do sistema e do ngrok para a porta %server_port%.
%PYTHON% "%BASE_DIR%\scripts\setup_env.py" --env %NGROK_ENV% --port %server_port% --domain %NGROK_DOMAIN%

echo.
echo [INFO] Verificando consistencia da configuracao do ngrok...
%PYTHON% "%BASE_DIR%\scripts\check_ngrok_config.py"

goto START_SERVER

:START_SERVER
echo.
echo --- INICIANDO SERVIDOR NA PORTA %server_port% ---
%PYTHON% "%BASE_DIR%\scripts\setup_env.py" --port %server_port% --no-ngrok
%PYTHON% "%BASE_DIR%\run.py"

if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] O servidor parou com codigo %ERRORLEVEL%.
    pause
)

:END
endlocal
