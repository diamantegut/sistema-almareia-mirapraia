$BackupSource = "G:\Backups\Almareia Mirapraia Sistema Producao_Backup_20260206_233813"
$ProdDest = "F:\Sistema Almareia Mirapraia"
if (Test-Path "G:\Almareia Mirapraia Sistema Producao") {
    $ProdDest = "G:\Almareia Mirapraia Sistema Producao"
}

Write-Host "Restaurando dados de $BackupSource para $ProdDest..."

# 1. Restore data folder
if (Test-Path "$BackupSource\data") {
    Write-Host "Restaurando pasta 'data'..."
    if (-not (Test-Path "$ProdDest\data")) { New-Item -ItemType Directory -Path "$ProdDest\data" -Force | Out-Null }
    Copy-Item -Path "$BackupSource\data\*" -Destination "$ProdDest\data" -Recurse -Force
}

# 2. Restore root JSONs (users.json, products.json, etc if they exist in root)
# Note: users.json is usually in data/, but some config files might be in root.
$JsonFiles = Get-ChildItem -Path "$BackupSource" -Filter "*.json"
foreach ($file in $JsonFiles) {
    Write-Host "Restaurando $($file.Name)..."
    Copy-Item -Path $file.FullName -Destination "$ProdDest\$($file.Name)" -Force
}

# 3. Restore other potential data folders
$Folders = @("Produtos", "Vendas", "Fiscal", "Resumo de Estoque", "guests_encrypted", "secure_docs", "backups")
foreach ($folder in $Folders) {
    if (Test-Path "$BackupSource\$folder") {
        Write-Host "Restaurando pasta '$folder'..."
        if (-not (Test-Path "$ProdDest\$folder")) { New-Item -ItemType Directory -Path "$ProdDest\$folder" -Force | Out-Null }
        Copy-Item -Path "$BackupSource\$folder\*" -Destination "$ProdDest\$folder" -Recurse -Force
    }
}

Write-Host "Restauracao de dados concluida com sucesso."
