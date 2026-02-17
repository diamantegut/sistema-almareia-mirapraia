@echo off
:: ========================================================
::   AUTOMACAO GIT - ALMAREIA MIRAPRAIA
::   Agora com PULL e PUSH separados por categoria
:: ========================================================
:menu
cls
echo ========================================================
echo   AUTOMACAO GIT - ALMAREIA MIRAPRAIA
echo ========================================================
echo.
echo [1] PULL COMPLETO (Projeto inteiro)
echo [2] PUSH COMPLETO (Projeto inteiro)
echo [3] PULL DATA APENAS (Somente pasta data)
echo [4] PUSH DATA APENAS (Somente pasta data)
echo [5] PULL SISTEMA (Exceto pasta data)
echo [6] PUSH SISTEMA (Exceto pasta data)
echo [7] STATUS (Verificar alteracoes pendentes)
echo [8] SAIR
echo.
set /p opcao=Escolha uma opcao: 

if "%opcao%"=="1" goto pull_full
if "%opcao%"=="2" goto push_full
if "%opcao%"=="3" goto pull_data
if "%opcao%"=="4" goto push_data
if "%opcao%"=="5" goto pull_system
if "%opcao%"=="6" goto push_system
if "%opcao%"=="7" goto status
if "%opcao%"=="8" goto sair
goto menu

:pull_full
echo.
echo === PULL COMPLETO ===
git pull origin main
pause
goto menu

:push_full
echo.
echo === PREPARANDO PUSH COMPLETO ===
git add .
set msg=
set /p msg=Digite a mensagem do commit (Enter para "Atualizacao Completa"): 
if "%msg%"=="" set msg=Atualizacao Completa
git commit -m "%msg%"
echo.
echo === ENVIANDO (PUSH COMPLETO) ===
git push origin main
pause
goto menu

:pull_data
echo.
echo === PULL DATA APENAS ===
echo Sincronizando apenas a pasta ^'data^' com o remoto...
git fetch origin main
git checkout origin/main -- data
echo.
echo [OK] Pasta ^'data^' atualizada a partir de origin/main sem alterar outros arquivos.
pause
goto menu

:push_data
echo.
echo === PUSH DATA APENAS ===
git add data
set msg=
set /p msg=Mensagem do commit para DATA (Enter para "Atualizacao DATA"): 
if "%msg%"=="" set msg=Atualizacao DATA
git commit -m "%msg%"
echo.
echo === ENVIANDO ALTERACOES DE DATA ===
git push origin main
pause
goto menu

:pull_system
echo.
echo === PULL SISTEMA (EXCETO DATA) ===
echo Atualizando arquivos do sistema a partir do remoto, preservando ^'data^' local...
git fetch origin main
git checkout origin/main -- .
git checkout HEAD -- data
echo.
echo [OK] Sistema atualizado. Pasta ^'data^' preservada.
pause
goto menu

:push_system
echo.
echo === PUSH SISTEMA (EXCETO DATA) ===
git add .
git reset HEAD data
set msg=
set /p msg=Mensagem do commit para SISTEMA (Enter para "Atualizacao SISTEMA"): 
if "%msg%"=="" set msg=Atualizacao SISTEMA
git commit -m "%msg%"
echo.
echo === ENVIANDO ALTERACOES DO SISTEMA ===
git push origin main
pause
goto menu

:status
echo.
echo === Status atual ===
git status
echo.
pause
goto menu

:sair
exit
