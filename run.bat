@echo off
cd /d "%~dp0"
echo.
echo ===================================================
echo      SISTEMA MIRAPRAIA - CONFIGURACAO INICIAL
echo ===================================================
echo.

:ASK_ENV
echo Escolha o ambiente:
echo 1 - Desenvolvimento (syrupy-jaliyah-intracranial.ngrok-free.dev)
echo 2 - Producao (almareia.mirapraia.ngrok.app)
set /p env_choice="Opcao (1 ou 2): "

if "%env_choice%"=="1" (
    set TARGET_ENV=development
    set TARGET_DOMAIN=syrupy-jaliyah-intracranial.ngrok-free.dev
    goto ASK_PORT
)
if "%env_choice%"=="2" (
    set TARGET_ENV=production
    set TARGET_DOMAIN=almareia.mirapraia.ngrok.app
    goto ASK_PORT
)
echo Opcao invalida. Tente novamente.
goto ASK_ENV

:ASK_PORT
echo.
set /p server_port="Digite a porta do servidor (Ex: 5000, 5001): "
if "%server_port%"=="" goto ASK_PORT

echo.
echo Configurando ambiente...
python scripts/setup_env.py --env %TARGET_ENV% --port %server_port% --domain %TARGET_DOMAIN%

echo.
echo --- VERIFICANDO CONFIGURACAO NGROK (Check Adicional) ---
python scripts/check_ngrok_config.py

echo.
echo --- INICIANDO SERVIDOR (%TARGET_ENV% na porta %server_port%) ---
python run.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] O servidor parou com codigo %ERRORLEVEL%.
    pause
)
