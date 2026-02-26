# cleanup_json_files.ps1
# Script to cleanup identified non-essential JSON files with backup

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "$PSScriptRoot\backups\json_cleanup_$timestamp"
$reportFile = "$PSScriptRoot\JSON_ANALYSIS_REPORT.md"

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$filesToRemove = @(
    "menu_items.json",
    "daily_checklists.json",
    "checklist_settings.json",
    "checklist_items.json",
    "printer_audit_report.json",
    "tunnels.json",
    "tunnels_clean.json",
    "investigation_results.json",
    "restore_candidates.json",
    "products_contaminated_backup.json",
    "whatsapp_tags.json"
)

$foldersToClean = @(
    "testsprite_tests",
    "tests\backups"
)

$reportContent = @"
# Relatório de Análise e Limpeza de Arquivos JSON
**Data:** $(Get-Date -Format "dd/MM/yyyy HH:mm:ss")
**Backup:** $backupDir

## 1. Arquivos Essenciais (MANTIDOS)
Os seguintes arquivos foram identificados como essenciais para o funcionamento do sistema ou contêm dados de produção e **NÃO** foram removidos:

### Configuração e Metadados
- **system_config.json**: Configuração global de diretórios do sistema.
- **swagger.json**: Especificação da API (Documentação).
- **package.json / tsconfig.json**: (Se existirem) Configurações de ambiente Node/TypeScript.

### Dados de Produção (Pasta `data/`)
Todos os arquivos dentro de `data/` foram preservados, pois constituem o banco de dados da aplicação:
- `users.json`, `products.json`, `menu_items.json`, `cashier_sessions.json`, etc.

### Logs (Pasta `logs/`)
Arquivos de log foram mantidos para auditoria.

## 2. Arquivos Removidos (Com Backup)
Os seguintes arquivos foram identificados como redundantes, obsoletos ou lixo temporário e foram movidos para o backup antes da exclusão:

| Arquivo | Motivo da Remoção |
|---|---|
"@

# Process Root Files
foreach ($file in $filesToRemove) {
    $path = "$PSScriptRoot\$file"
    if (Test-Path $path) {
        Copy-Item -Path $path -Destination $backupDir
        Remove-Item -Path $path -Force
        $reportContent += "| `$file` | Redundante/Lixo (Versão antiga ou duplicada de `data/`) |`n"
        Write-Host "Removed $file"
    }
}

# Process Folders
foreach ($folderRel in $foldersToClean) {
    $folderPath = "$PSScriptRoot\$folderRel"
    if (Test-Path $folderPath) {
        $jsonFiles = Get-ChildItem -Path $folderPath -Recurse -Filter *.json
        foreach ($file in $jsonFiles) {
            $relPath = $file.FullName.Substring($PSScriptRoot.Length + 1)
            $backupPath = Join-Path $backupDir $relPath
            $backupDirFile = Split-Path $backupPath
            if (!(Test-Path $backupDirFile)) { New-Item -ItemType Directory -Force -Path $backupDirFile | Out-Null }
            
            Copy-Item -Path $file.FullName -Destination $backupPath
            Remove-Item -Path $file.FullName -Force
            $reportContent += "| `$relPath` | Arquivo temporário de teste ou backup obsoleto |`n"
            Write-Host "Removed $relPath"
        }
    }
}

$reportContent += @"

## 3. Conclusão
A estrutura de arquivos JSON foi limpa. Arquivos duplicados na raiz foram removidos em favor das versões oficiais na pasta `data/`.
"@

Set-Content -Path $reportFile -Value $reportContent
Write-Host "Cleanup finished. Report generated at $reportFile"
