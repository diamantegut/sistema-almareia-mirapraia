# organize_docs.ps1
# Script para organizar arquivos de documentação e logs em "referencia-documentos"

$baseDir = "referencia-documentos"
$dirs = @(
    "$baseDir\tecnica",
    "$baseDir\manuais",
    "$baseDir\relatorios",
    "$baseDir\logs_arquivados",
    "$baseDir\legado"
)

# Criar estrutura de pastas
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        Write-Host "Criado diretório: $d"
    }
}

# Função auxiliar para mover arquivos
function Move-Doc {
    param($pattern, $destSubDir)
    $destPath = "$baseDir\$destSubDir"
    $files = Get-ChildItem -Path . -Filter $pattern -File
    foreach ($f in $files) {
        # Ignorar arquivos essenciais da raiz
        if ($f.Name -eq "README.md" -or $f.Name -eq "requirements.txt" -or $f.Name -eq "local_requirements.txt" -or $f.Name -eq "version.txt") {
            continue
        }
        
        Write-Host "Movendo $($f.Name) para $destSubDir..."
        Move-Item -Path $f.FullName -Destination $destPath -Force
    }
}

# 1. Documentação Técnica
Move-Doc "*STRUCTURE.md" "tecnica"
Move-Doc "DEPLOYMENT.md" "tecnica"
Move-Doc "DEVELOPMENT_ENVIRONMENT.md" "tecnica"
Move-Doc "*_INTEGRATION.md" "tecnica"
Move-Doc "*_DOCS.md" "tecnica"
Move-Doc "LOGGING_GUIDE.md" "tecnica"
Move-Doc "API_*.md" "tecnica"
Move-Doc "DOCS_*.md" "tecnica"

# 2. Manuais e Procedimentos
Move-Doc "*PROCEDURE.md" "manuais"
Move-Doc "*PROCESS.md" "manuais"
Move-Doc "*MANAGEMENT.md" "manuais"
Move-Doc "*DOCUMENTATION.md" "manuais"
Move-Doc "*NAVIGATION.md" "manuais"

# 3. Relatórios
Move-Doc "*REPORT.md" "relatorios"
Move-Doc "*ANALYSIS.md" "relatorios"
Move-Doc "incident_report*.md" "relatorios"
Move-Doc "*PLAN.md" "relatorios"
Move-Doc "*results.txt" "relatorios"

# 4. Logs e Arquivos Temporários
Move-Doc "*LOG.md" "logs_arquivados"
Move-Doc "*log*.txt" "logs_arquivados"
Move-Doc "debug*.txt" "logs_arquivados"
Move-Doc "line_count.txt" "logs_arquivados"
Move-Doc "python_works.txt" "logs_arquivados"
Move-Doc "valid_endpoints*.txt" "logs_arquivados"

# 5. Mover pasta docs antiga para tecnica (se existir)
if (Test-Path "docs") {
    Write-Host "Mesclando pasta 'docs' em 'referencia-documentos\tecnica'..."
    Get-ChildItem -Path "docs" -File | ForEach-Object {
        Move-Item -Path $_.FullName -Destination "$baseDir\tecnica" -Force
    }
    Remove-Item "docs" -Force -Recurse
}

Write-Host "Organização concluída."
