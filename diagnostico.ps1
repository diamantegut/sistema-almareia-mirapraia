# Script de Diagnóstico Rápido
$ProdPath = "F:\Sistema Almareia Mirapraia"

Write-Host "=== Diagnóstico de Ambiente ===" -ForegroundColor Cyan

# 1. Verificar F:
if (Test-Path "F:\") {
    Write-Host "[OK] Unidade F: detectada." -ForegroundColor Green
} else {
    Write-Host "[ERRO] Unidade F: NÃO encontrada!" -ForegroundColor Red
}

# 2. Verificar Pasta de Produção
if (Test-Path $ProdPath) {
    Write-Host "[OK] Diretório de produção encontrado: $ProdPath" -ForegroundColor Green
    
    # Testar permissão de escrita
    try {
        $TestFile = Join-Path $ProdPath "write_test.tmp"
        "test" | Out-File $TestFile
        Remove-Item $TestFile
        Write-Host "[OK] Permissão de escrita confirmada." -ForegroundColor Green
    } catch {
        Write-Host "[ERRO] Sem permissão de escrita em $ProdPath" -ForegroundColor Red
    }
} else {
    Write-Host "[ERRO] Diretório de produção NÃO encontrado!" -ForegroundColor Red
}

# 3. Verificar Porta 5000
$PortProcess = netstat -ano | Select-String ":5000\s"
if ($PortProcess) {
    Write-Host "[INFO] Porta 5000 está em uso (Aplicação rodando?)." -ForegroundColor Yellow
} else {
    Write-Host "[INFO] Porta 5000 está livre." -ForegroundColor Gray
}

# 4. Verificar Python
try {
    $PyVer = python --version 2>&1
    Write-Host "[OK] Python detectado: $PyVer" -ForegroundColor Green
} catch {
    Write-Host "[ERRO] Python não encontrado no PATH." -ForegroundColor Red
}

Write-Host "`nPressione Enter para sair..."
Read-Host
