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
set "NGROK_DOMAIN_5001=syrupy-jaliyah-intracranial.ngrok-free.dev"
set "NGROK_DOMAIN="
set "GUEST_DOMAIN=hospedes.almareia.mirapraia.ngrok.app"
set "NGROK_SCOPE_FLAG="

echo.
echo ===================================================
echo      SISTEMA MIRAPRAIA - INICIALIZACAO SERVIDOR
echo ===================================================
echo.

:ASK_PORT
echo.
set /p server_port="Digite a porta do servidor (Ex: 5000, 5001): "
if "%server_port%"=="" goto ASK_PORT

if "%server_port%"=="5000" (
    set "NGROK_ENV=production"
    set "NGROK_DOMAIN="
    echo [INFO] Modo de Producao detectado - Porta 5000.
) else (
    set "NGROK_ENV=development"
    set "NGROK_DOMAIN=%NGROK_DOMAIN_5001%"
    echo [INFO] Modo de Desenvolvimento detectado.
)

if "%server_port%"=="5001" (
    set "NGROK_SCOPE_FLAG=--staff-only"
    echo [INFO] Regra 5001 ativa: somente dominio %NGROK_DOMAIN% sera publicado externamente.
    echo [INFO] Regra 5001 ativa: configuracao ngrok sera automatica sem pergunta.
    goto CONFIG_NGROK
)

if "%server_port%"=="5000" goto ASK_NGROK
goto START_SERVER

:ASK_NGROK
echo.
echo Deseja configurar o ngrok para esta instancia?
echo S - Sim, configurar ngrok para a porta %server_port%
echo N - Nao, iniciar apenas o servidor local
set /p use_ngrok="Opcao (S/N): "

if /I "%use_ngrok%"=="S" goto ASK_DOMAIN_5000
if /I "%use_ngrok%"=="N" goto START_SERVER

echo Opcao invalida. Tente novamente.
goto ASK_NGROK

:ASK_DOMAIN_5000
echo.
set /p NGROK_DOMAIN="Digite o dominio reservado do ngrok para a porta 5000: "
if "%NGROK_DOMAIN%"=="" (
    echo [ERRO] Dominio do ngrok nao pode ficar vazio.
    goto ASK_DOMAIN_5000
)
goto CONFIG_NGROK

:CONFIG_NGROK
echo.
echo [INFO] Verificando instancias existentes do ngrok...
tasklist /FI "IMAGENAME eq ngrok.exe" | find /I "ngrok.exe" >nul 2>&1
if not errorlevel 1 (
    echo [AVISO] Uma instancia do ngrok esta em execucao.
    echo [INFO] Ela sera mantida. Esta instancia iniciara seu proprio gerenciador ngrok em "%BASE_DIR%".
)

echo.
echo [INFO] Atualizando configuracao do sistema e do ngrok para a porta %server_port%.
%PYTHON% "%BASE_DIR%\scripts\setup_env.py" --env %NGROK_ENV% --port %server_port% --domain %NGROK_DOMAIN% --guest-domain %GUEST_DOMAIN% %NGROK_SCOPE_FLAG%

echo.
echo [INFO] Verificando consistencia da configuracao do ngrok...
%PYTHON% "%BASE_DIR%\scripts\check_ngrok_config.py"

echo.
echo [INFO] Iniciando servico ngrok (tunnels)...
start "Ngrok Service %server_port%" /MIN %PYTHON% "%BASE_DIR%\scripts\manage_ngrok.py" %NGROK_ENV%

goto START_SERVER

:START_SERVER
echo.
echo --- INICIANDO SERVIDOR NA PORTA %server_port% ---
if "%server_port%"=="5001" (
    set "ALMAREIA_EXTERNAL_OPEN_MODE=1"
    echo [INFO] Regra 5001 ativa: login/senha/permissoes desativados para acesso externo.
) else (
    set "ALMAREIA_EXTERNAL_OPEN_MODE=0"
)
%PYTHON% "%BASE_DIR%\scripts\setup_env.py" --port %server_port% --no-ngrok
%PYTHON% "%BASE_DIR%\run.py"

if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] O servidor parou com codigo %ERRORLEVEL%.
    pause
)

:END
endlocal
