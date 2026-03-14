@echo off
setlocal EnableExtensions
TITLE Git Automation - Sistema Almareia Mirapraia
cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Git nao encontrado no PATH.
    echo Instale o Git ou abra pelo Git Bash.
    goto END
)

:MENU
CLS
ECHO ========================================================
ECHO    GIT AUTOMATION MANAGER
ECHO ========================================================
ECHO.
ECHO  Diretorio atual: %CD%
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
ECHO  0. Exit
ECHO ========================================================
SET /P choice="Enter choice (0-6): "

IF "%choice%"=="1" GOTO PULL_SYS
IF "%choice%"=="2" GOTO PUSH_SYS
IF "%choice%"=="3" GOTO PULL_DATA
IF "%choice%"=="4" GOTO PUSH_DATA
IF "%choice%"=="5" GOTO PULL_ALL
IF "%choice%"=="6" GOTO PUSH_ALL
IF "%choice%"=="0" GOTO END
GOTO MENU

:PULL_SYS
ECHO.
ECHO [Pulling System Code...]
call :RUN_MAIN "pull --rebase origin main"
GOTO DONE

:PUSH_SYS
ECHO.
ECHO [Pushing System Code...]
call :RUN_MAIN "pull --rebase origin main"
if errorlevel 1 GOTO DONE
call :RUN_MAIN "push origin main"
GOTO DONE

:PULL_DATA
ECHO.
ECHO [Pulling Data Folder...]
call :RUN_DATA "pull --rebase origin data-branch"
GOTO DONE

:PUSH_DATA
ECHO.
ECHO [Pushing Data Folder...]
call :RUN_DATA "pull --rebase origin data-branch"
if errorlevel 1 GOTO DONE
call :RUN_DATA "push origin data-branch"
GOTO DONE

:PULL_ALL
ECHO.
ECHO [Pulling System Code...]
call :RUN_MAIN "pull --rebase origin main"
ECHO.
ECHO [Pulling Data Folder...]
call :RUN_DATA "pull --rebase origin data-branch"
GOTO DONE

:PUSH_ALL
ECHO.
ECHO [Pushing System Code...]
call :RUN_MAIN "pull --rebase origin main"
if errorlevel 1 GOTO DONE
call :RUN_MAIN "push origin main"
ECHO.
ECHO [Pushing Data Folder...]
call :RUN_DATA "pull --rebase origin data-branch"
if errorlevel 1 GOTO DONE
call :RUN_DATA "push origin data-branch"
GOTO DONE

:RUN_MAIN
git fetch origin --prune
git checkout main
git %~1
exit /b %errorlevel%

:RUN_DATA
if not exist "data\.git" (
    ECHO [ERRO] Pasta data nao eh repositorio Git separado: %CD%\data
    ECHO Verifique se o script esta na raiz correta do projeto.
    exit /b 1
)
pushd data
git fetch origin --prune
git checkout data-branch
git %~1
set ERR=%errorlevel%
popd
exit /b %ERR%

:DONE
ECHO.
IF ERRORLEVEL 1 (
    ECHO [FALHOU] Operacao finalizada com erro.
    ECHO Se houver conflito no rebase, resolva e execute novamente.
) ELSE (
    ECHO [OK] Operacao concluida.
)
ECHO.
PAUSE
GOTO MENU

:END
ECHO.
ECHO Encerrado.
PAUSE
