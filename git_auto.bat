@echo off
:menu
cls
echo ========================================================
echo   AUTOMACAO GIT - ALMAREIA MIRAPRAIA
echo ========================================================
echo.
echo [1] PULL (Atualizar projeto)
echo [2] PUSH (Salvar e Enviar alteracoes)
echo [3] STATUS (Verificar alteracoes pendentes)
echo [4] SAIR
echo.
set /p opcao=Escolha uma opcao: 

if "%opcao%"=="1" goto pull
if "%opcao%"=="2" goto push
if "%opcao%"=="3" goto status
if "%opcao%"=="4" goto sair

:pull
echo.
echo === Atualizando repositorio... ===
git pull origin main
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Falha ao atualizar. Verifique conflitos.
) else (
    echo.
    echo [SUCESSO] Repositorio atualizado!
)
pause
goto menu

:push
echo.
echo === Preparando envio... ===
git status
echo.
set /p confirm=Deseja adicionar TODOS os arquivos listados acima? (S/N): 
if /i "%confirm%" neq "S" goto menu

set /p msg=Digite a mensagem do commit: 
if "%msg%"=="" (
    echo [ERRO] Mensagem obrigatoria!
    pause
    goto menu
)

git add .
git commit -m "%msg%"
echo.
echo === Enviando para o GitHub... ===
git push origin main
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Falha no envio. Verifique sua conexao ou permissoes.
) else (
    echo.
    echo [SUCESSO] Alteracoes enviadas com sucesso!
)
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
