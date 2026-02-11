@echo off
echo Verificando status do servidor...
echo.

curl -s http://localhost:5001/health | findstr "ok" >nul
if %errorlevel% equ 0 (
    echo [OK] O servidor esta ONLINE e respondendo.
    curl -s http://localhost:5001/health
) else (
    echo [ERRO] O servidor parece estar OFFLINE ou nao respondendo.
    echo Verifique se a janela do servidor esta aberta.
)

echo.
pause
