# cleanup_backups.ps1
# Script para remover arquivos de backup obsoletos recursivamente

$extensions = @("*.bak", "*.backup", "*.old", "*.tmp", "*.swp", "*.swo")
$logFile = "cleanup_backups_log.txt"
$reportFile = "CLEANUP_REPORT.md"

# Inicializa logs
"--- Log de Limpeza de Backups ---" | Out-File -FilePath $logFile -Encoding utf8
"# Relatório de Limpeza de Backups e Arquivos Temporários" | Out-File -FilePath $reportFile -Encoding utf8
"" | Out-File -FilePath $reportFile -Append -Encoding utf8
"Data: $(Get-Date)" | Out-File -FilePath $reportFile -Append -Encoding utf8
"" | Out-File -FilePath $reportFile -Append -Encoding utf8
"| Arquivo | Tamanho | Status |" | Out-File -FilePath $reportFile -Append -Encoding utf8
"|---|---|---|" | Out-File -FilePath $reportFile -Append -Encoding utf8

$totalSize = 0
$count = 0

Write-Host "Iniciando varredura..."

# Procura arquivos (excluindo node_modules, venv, .git se existirem, e a própria pasta _trash)
Get-ChildItem -Path . -Include $extensions -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { 
    $_.FullName -notmatch "\\node_modules\\" -and 
    $_.FullName -notmatch "\\venv\\" -and 
    $_.FullName -notmatch "\\.git\\" -and
    $_.FullName -notmatch "\\_trash\\" 
} | ForEach-Object {
    $file = $_
    $sizeKB = [math]::Round($file.Length / 1KB, 2)
    $path = $file.FullName
    
    try {
        Remove-Item -Path $path -Force
        "Removido: $path" | Out-File -FilePath $logFile -Append -Encoding utf8
        "| `$($file.Name) | $sizeKB KB | Removido |" | Out-File -FilePath $reportFile -Append -Encoding utf8
        $totalSize += $file.Length
        $count++
        Write-Host "Removido: $($file.Name)"
    }
    catch {
        "Erro ao remover: $path - $_" | Out-File -FilePath $logFile -Append -Encoding utf8
        "| `$($file.Name) | $sizeKB KB | Erro |" | Out-File -FilePath $reportFile -Append -Encoding utf8
        Write-Host "Erro ao remover: $($file.Name)" -ForegroundColor Red
    }
}

$totalSizeMB = [math]::Round($totalSize / 1MB, 2)

"" | Out-File -FilePath $reportFile -Append -Encoding utf8
"**Total Removido:** $count arquivos ($totalSizeMB MB)" | Out-File -FilePath $reportFile -Append -Encoding utf8

Write-Host "Limpeza concluída. Verifique $reportFile."
