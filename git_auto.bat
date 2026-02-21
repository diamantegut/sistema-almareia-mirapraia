@echo off
TITLE Git Automation - Sistema Almareia Mirapraia
CLS
ECHO ========================================================
ECHO    GIT AUTOMATION MANAGER
ECHO ========================================================
ECHO.
ECHO  [System Code - Main Branch]
ECHO  1. Pull System Code (No Data)
ECHO  2. Push System Code (No Data)
ECHO.
ECHO  [Data Folder - Data Branch]
ECHO  3. Pull Data Only
ECHO  4. Push Data Only
ECHO.
ECHO  [Combined Operations]
ECHO  5. Pull Everything (System + Data)
ECHO  6. Push Everything (System + Data)
ECHO.
ECHO ========================================================
SET /P choice="Enter choice (1-6): "

IF "%choice%"=="1" GOTO PULL_SYS
IF "%choice%"=="2" GOTO PUSH_SYS
IF "%choice%"=="3" GOTO PULL_DATA
IF "%choice%"=="4" GOTO PUSH_DATA
IF "%choice%"=="5" GOTO PULL_ALL
IF "%choice%"=="6" GOTO PUSH_ALL
GOTO END

:PULL_SYS
ECHO.
ECHO [Pulling System Code...]
git pull origin main
GOTO END

:PUSH_SYS
ECHO.
ECHO [Pushing System Code...]
git push origin main
GOTO END

:PULL_DATA
ECHO.
ECHO [Pulling Data Folder...]
cd data
git pull origin data-branch
cd ..
GOTO END

:PUSH_DATA
ECHO.
ECHO [Pushing Data Folder...]
cd data
git push origin data-branch
cd ..
GOTO END

:PULL_ALL
ECHO.
ECHO [Pulling System Code...]
git pull origin main
ECHO.
ECHO [Pulling Data Folder...]
cd data
git pull origin data-branch
cd ..
GOTO END

:PUSH_ALL
ECHO.
ECHO [Pushing System Code...]
git push origin main
ECHO.
ECHO [Pushing Data Folder...]
cd data
git push origin data-branch
cd ..
GOTO END

:END
ECHO.
ECHO Operation Complete.
PAUSE
