@echo off
echo Starting Server Watchdog...
echo This script ensures the server (app.py) runs continuously.
echo If the server crashes, it will be automatically restarted.
echo Logs are saved to server_watchdog.log and server_app.log.
echo.
python server_watchdog.py
pause
