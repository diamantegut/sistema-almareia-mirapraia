@echo off
setlocal
cd /d "%~dp0"
title Almareia-Mirapraia Server Monitor

:loop
cls
echo ========================================================
echo   Iniciando Servidor Almareia-Mirapraia...
echo   Data/Hora: %date% %time%
echo ========================================================
echo.

:: Append start time to log
echo [START] %date% %time% >> server_monitor.log

:: Run the server
python app.py

:: If we get here, the server crashed or stopped
echo.
echo ========================================================
echo   ALERTA: O servidor parou!
echo   Reiniciando em 5 segundos...
echo ========================================================
echo [CRASH] %date% %time% - Exit Code: %errorlevel% >> server_monitor.log

:: Wait 5 seconds before restarting
timeout /t 5 >nul
goto loop
