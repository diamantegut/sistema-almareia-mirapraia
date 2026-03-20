@echo off
setlocal
cd /d "%~dp0"
set "BASE_DIR=%CD%"

set "DEV_PORT=5001"
set "DEV_DOMAIN=syrupy-jaliyah-intracranial.ngrok-free.dev"
set "PROD_PORT=5000"
set "PROD_DOMAIN=hospedes.almareia.mirapraia.ngrok.app"

if /I "%~1"=="__RUN_APP" goto RUN_APP
if /I "%~1"=="__RUN_NGROK" goto RUN_NGROK
if /I "%~1"=="--print" goto PRINT_ONLY
if /I "%~1"=="DEV" goto PRESET_DEV
if /I "%~1"=="PRODUCAO" goto PRESET_PROD
if /I "%~1"=="PROD" goto PRESET_PROD

call :CHECK_PREREQS || goto END

echo.
echo ===================================================
echo     SISTEMA ALMAREIA - EXECUCAO WINDOWS
echo ===================================================
echo.
echo [1] DEV       - Porta %DEV_PORT% - %DEV_DOMAIN%
echo [2] PRODUCAO  - Porta %PROD_PORT% - %PROD_DOMAIN%
echo.
set /p "ENV_CHOICE=Escolha o ambiente [1/2]: "

if "%ENV_CHOICE%"=="1" goto PRESET_DEV
if "%ENV_CHOICE%"=="2" goto PRESET_PROD
echo [ERRO] Opcao invalida.
goto END

:PRESET_DEV
set "ENV_LABEL=DEV"
set "ALMAREIA_ENV=development"
set "TARGET_PORT=%DEV_PORT%"
set "TARGET_DOMAIN=%DEV_DOMAIN%"
goto START_ALL

:PRESET_PROD
set "ENV_LABEL=PRODUCAO"
set "ALMAREIA_ENV=production"
set "TARGET_PORT=%PROD_PORT%"
set "TARGET_DOMAIN=%PROD_DOMAIN%"
goto START_ALL

:START_ALL
echo.
echo [INFO] Ambiente escolhido: %ENV_LABEL%
echo [INFO] Porta usada: %TARGET_PORT%
echo [INFO] Dominio ngrok: %TARGET_DOMAIN%
echo.

start "ALMAREIA APP - %ENV_LABEL%" cmd /k ""%~f0" __RUN_APP "%ENV_LABEL%" "%TARGET_PORT%" "%ALMAREIA_ENV%""
start "ALMAREIA NGROK - %ENV_LABEL%" cmd /k ""%~f0" __RUN_NGROK "%ENV_LABEL%" "%TARGET_PORT%" "%TARGET_DOMAIN%""

echo [OK] Janelas iniciadas para APP e NGROK.
goto END

:RUN_APP
set "ENV_LABEL=%~2"
set "TARGET_PORT=%~3"
set "ALMAREIA_ENV=%~4"
cd /d "%BASE_DIR%"
echo.
echo ===============================================
echo   ALMAREIA APP - %ENV_LABEL%
echo ===============================================
echo [INFO] Ambiente: %ALMAREIA_ENV%
echo [INFO] Porta: %TARGET_PORT%
echo.
set "ALMAREIA_PORT=%TARGET_PORT%"
set "PORT=%TARGET_PORT%"
python "%BASE_DIR%\run.py"
echo.
echo [ERRO] Aplicacao finalizada com codigo %ERRORLEVEL%.
pause
goto END

:RUN_NGROK
set "ENV_LABEL=%~2"
set "TARGET_PORT=%~3"
set "TARGET_DOMAIN=%~4"
cd /d "%BASE_DIR%"
echo.
echo ===============================================
echo   ALMAREIA NGROK - %ENV_LABEL%
echo ===============================================
echo [INFO] Porta: %TARGET_PORT%
echo [INFO] Dominio: %TARGET_DOMAIN%
echo.
where ngrok >nul 2>&1
if errorlevel 1 (
    echo [ERRO] ngrok nao encontrado no PATH.
    echo [ACAO] Instale/configure ngrok e rode novamente.
    pause
    goto END
)
ngrok http --domain=%TARGET_DOMAIN% %TARGET_PORT%
echo.
echo [ERRO] ngrok finalizado com codigo %ERRORLEVEL%.
pause
goto END

:PRINT_ONLY
if "%~2"=="" (
    echo Uso: run.bat --print DEV ^| PRODUCAO
    goto END
)
if /I "%~2"=="DEV" (
    set "ENV_LABEL=DEV"
    set "ALMAREIA_ENV=development"
    set "TARGET_PORT=%DEV_PORT%"
    set "TARGET_DOMAIN=%DEV_DOMAIN%"
    goto SHOW_PRINT
)
if /I "%~2"=="PRODUCAO" (
    set "ENV_LABEL=PRODUCAO"
    set "ALMAREIA_ENV=production"
    set "TARGET_PORT=%PROD_PORT%"
    set "TARGET_DOMAIN=%PROD_DOMAIN%"
    goto SHOW_PRINT
)
if /I "%~2"=="PROD" (
    set "ENV_LABEL=PRODUCAO"
    set "ALMAREIA_ENV=production"
    set "TARGET_PORT=%PROD_PORT%"
    set "TARGET_DOMAIN=%PROD_DOMAIN%"
    goto SHOW_PRINT
)
echo Uso: run.bat --print DEV ^| PRODUCAO
goto END

:SHOW_PRINT
echo [PRINT] Ambiente: %ENV_LABEL%
echo [PRINT] APP: set ALMAREIA_ENV=%ALMAREIA_ENV%^&^& set ALMAREIA_PORT=%TARGET_PORT%^&^& set PORT=%TARGET_PORT%^&^& python "%BASE_DIR%\run.py"
echo [PRINT] NGROK: ngrok http --domain=%TARGET_DOMAIN% %TARGET_PORT%
goto END

:CHECK_PREREQS
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH.
    exit /b 1
)
if not exist "%BASE_DIR%\run.py" (
    echo [ERRO] run.py nao encontrado em "%BASE_DIR%".
    exit /b 1
)
where ngrok >nul 2>&1
if errorlevel 1 (
    echo [AVISO] ngrok nao encontrado no PATH neste momento.
    echo [AVISO] A janela de APP sera iniciada normalmente e a janela de NGROK exibira erro orientativo.
)
exit /b 0

:END
endlocal
