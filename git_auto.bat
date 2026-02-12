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

echo Salvando alteracoes locais automaticamente...
git add .
git commit -m "Auto-backup local changes before pull"

echo.
echo Buscando atualizacoes...
git pull origin main --strategy-option=theirs

if %errorlevel% neq 0 (
    echo.
    echo [ALERTA] Houve conflitos no merge automatico.
    echo Tentando resolver usando versao remota para arquivos conflitantes...
    git checkout --theirs .
    git add .
    git commit -m "Auto-resolved merge conflicts using remote version"
    
    echo Verificando se restaram pendencias...
    git status
) else (
    echo.
    echo [SUCESSO] Repositorio atualizado!
)
pause
goto menu

:push
echo.
echo === Preparando envio... ===
echo Adicionando todos os arquivos automaticamente...
git add .

echo.
set msg=
set /p msg=Digite a mensagem do commit (Enter para "Atualizacao Automatica"): 
if "%msg%"=="" set msg=Atualizacao Automatica

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
