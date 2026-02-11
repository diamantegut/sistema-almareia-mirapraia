@echo off
echo ==========================================
echo Instalador de Atualizacao - Mirapraia
echo ==========================================
echo.
echo ESTA PASTA (Update_Package_20260202) DEVE ESTAR DENTRO DA RAIZ DO PROJETO.
echo Exemplo: F:\Sistema Almareia Mirapraia\Update_Package_20260202
echo.
echo O script ira copiar os arquivos para a pasta anterior (..)
echo e executar a migracao do banco de dados.
echo.
pause

echo.
echo [1/3] Copiando arquivos...
copy /Y "%~dp0app.py" "..\app.py"
copy /Y "%~dp0templates\menu_management.html" "..\templates\menu_management.html"

if not exist "..\scripts" mkdir "..\scripts"
copy /Y "%~dp0scripts\safe_updater.py" "..\scripts\safe_updater.py"

echo.
echo [2/3] Executando migracao de dados (menu_items.json)...
cd ..
python scripts/safe_updater.py
cd %~dp0

echo.
echo [3/3] Finalizado.
echo ==========================================
echo ATUALIZACAO CONCLUIDA COM SUCESSO!
echo Por favor, reinicie o servidor (feche a janela do python/app e abra novamente).
echo ==========================================
pause
