@echo off
echo [DEPLOY] Killing existing Python processes...
taskkill /F /IM python.exe /T >nul 2>&1

echo [DEPLOY] Waiting for cleanup...
timeout /t 3 /nobreak >nul

echo [DEPLOY] Starting Deployment Script...
python scripts/deploy_to_production.py
if %ERRORLEVEL% NEQ 0 (
    echo [DEPLOY] Deployment Script Failed!
    exit /b %ERRORLEVEL%
)

echo [DEPLOY] Deployment Wrapper Completed.
