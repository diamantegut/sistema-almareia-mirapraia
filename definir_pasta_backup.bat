@echo off
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PARENT_DIR=%%~fI

set DEFAULT_BACKUP=%PARENT_DIR%\Backups-Sistema

if "%~1"=="" (
  set TARGET_DIR=%DEFAULT_BACKUP%
  echo Nenhum caminho informado. Usando pasta padrao: "%TARGET_DIR%"
) else (
  set TARGET_DIR=%~1
)

for %%I in ("%TARGET_DIR%") do set TARGET_DIR=%%~fI

if not exist "%TARGET_DIR%" (
  mkdir "%TARGET_DIR%"
  if errorlevel 1 (
    echo ERRO: Nao foi possivel criar a pasta "%TARGET_DIR%".
    exit /b 1
  )
)

set CONFIG_FILE=%SCRIPT_DIR%system_config.json

powershell -NoProfile -Command ^
  "$cfgPath = '%CONFIG_FILE%';" ^
  "$target = '%TARGET_DIR%';" ^
  "if (-not (Test-Path $cfgPath)) { $cfg = @{ data_dir='data'; logs_dir='logs'; backups_dir='backups'; fiscal_dir='fiscal_documents'; uploads_dir='static/uploads/maintenance'; sales_excel_path='' } } else { $cfg = Get-Content -Raw -Encoding UTF8 $cfgPath | ConvertFrom-Json }" ^
  "$cfg.backups_dir = $target;" ^
  "$json = $cfg | ConvertTo-Json -Depth 6;" ^
  "[IO.File]::WriteAllText($cfgPath, $json, (New-Object System.Text.UTF8Encoding $false))"

if errorlevel 1 (
  echo ERRO: Falha ao atualizar system_config.json.
  exit /b 1
)

echo Pasta de backup configurada em:
echo %TARGET_DIR%
echo Arquivo atualizado: %CONFIG_FILE%
exit /b 0
