$TargetDir = "F:\Sistema Almareia Mirapraia"
Write-Host "Verificando processos rodando a partir de: $TargetDir" -ForegroundColor Cyan

# Buscar processos cujo executável esteja dentro da pasta alvo
$Processes = Get-CimInstance Win32_Process | Where-Object { 
    $_.ExecutablePath -like "$TargetDir*" 
}

if ($Processes) {
    Write-Host "ENCONTRADOS PROCESSOS BLOQUEANDO A PASTA:" -ForegroundColor Red
    foreach ($p in $Processes) {
        Write-Host "PID: $($p.ProcessId) | Name: $($p.Name)"
        Write-Host "   Path: $($p.ExecutablePath)"
        
        # Tentar matar
        Write-Host "   Tentando encerrar..." -NoNewline
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host " [OK]" -ForegroundColor Green
        } catch {
            Write-Host " [ERRO: $_]" -ForegroundColor Red
        }
    }
} else {
    Write-Host "Nenhum processo detectado rodando DENTRO da pasta." -ForegroundColor Green
}

# Verificar se há terminais do VS Code (Code.exe) com CWD na pasta (mais difícil via script puro sem ferramentas externas, mas vamos tentar via WMI commandline)
# Às vezes o próprio terminal do VS Code segura.
