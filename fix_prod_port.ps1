$ProdFile = "C:\Users\Angelo Diamante\Documents\trae_projects\Back of the house\app.py"

if (Test-Path $ProdFile) {
    Write-Host "Lendo arquivo de producao..."
    $content = Get-Content $ProdFile -Raw
    
    if ($content -match "port=5001") {
        Write-Host "Encontrado port=5001. Alterando para port=5000..."
        $newContent = $content -replace "port=5001", "port=5000"
        Set-Content -Path $ProdFile -Value $newContent -Encoding UTF8
        Write-Host "Arquivo atualizado com sucesso!" -ForegroundColor Green
    } else {
        Write-Host "O arquivo ja parece estar configurado corretamente ou nao contem port=5001." -ForegroundColor Yellow
    }
} else {
    Write-Error "Arquivo nao encontrado: $ProdFile"
}
