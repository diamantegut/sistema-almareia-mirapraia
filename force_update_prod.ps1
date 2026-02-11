$SourceDir = "F:\Sistema Almareia Mirapraia"
$DestDir = "C:\Users\Angelo Diamante\Documents\trae_projects\Back of the house"

Write-Host "Iniciando atualizacao forcada do servidor de Producao..." -ForegroundColor Cyan

# Check if source exists
if (!(Test-Path $SourceDir)) {
    Write-Error "Diretorio fonte nao encontrado: $SourceDir"
    exit 1
}

# Check if dest exists
if (!(Test-Path $DestDir)) {
    Write-Error "Diretorio destino nao encontrado: $DestDir"
    exit 1
}

# Copy app.py
Write-Host "Copiando app.py..."
Copy-Item -Path "$SourceDir\app.py" -Destination "$DestDir\app.py" -Force

# Copy templates/menu_management.html
Write-Host "Copiando menu_management.html..."
Copy-Item -Path "$SourceDir\templates\menu_management.html" -Destination "$DestDir\templates\menu_management.html" -Force

# Copy safe_updater.py
Write-Host "Copiando safe_updater.py..."
if (!(Test-Path "$DestDir\scripts")) {
    New-Item -ItemType Directory -Path "$DestDir\scripts" | Out-Null
}
Copy-Item -Path "$SourceDir\scripts\safe_updater.py" -Destination "$DestDir\scripts\safe_updater.py" -Force

# Copy restored menu_items.json (Fiscal Data)
Write-Host "Copiando menu_items.json (Dados Fiscais Restaurados)..."
Copy-Item -Path "$SourceDir\data\menu_items.json" -Destination "$DestDir\data\menu_items.json" -Force

# Run updater
Write-Host "Executando migracao de dados (safe_updater.py)..."
Set-Location "$DestDir"
echo y | python scripts/safe_updater.py

# Fix port to 5000
Write-Host "Ajustando porta para 5000..."
$ProdApp = "$DestDir\app.py"
$content = Get-Content $ProdApp -Raw
if ($content -match "port=5001") {
    $newContent = $content -replace "port=5001", "port=5000"
    Set-Content -Path $ProdApp -Value $newContent -Encoding UTF8
    Write-Host "Porta corrigida para 5000." -ForegroundColor Cyan
}

Write-Host "========================================================" -ForegroundColor Green
Write-Host "ATUALIZACAO CONCLUIDA COM SUCESSO!" -ForegroundColor Green
Write-Host "Agora voce DEVE reiniciar o servidor 'Back of the house'." -ForegroundColor Yellow
Write-Host "1. Feche a janela preta/terminal onde o servidor (porta 5000) esta rodando." -ForegroundColor Yellow
Write-Host "2. Abra novamente e inicie o servidor." -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Green
