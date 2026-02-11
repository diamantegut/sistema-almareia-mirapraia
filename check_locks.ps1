$TargetDir = "F:\Sistema Almareia Mirapraia"
Write-Host "Procurando processos usando: $TargetDir" -ForegroundColor Cyan

$Processes = Get-CimInstance Win32_Process | Where-Object { 
    ($_.CommandLine -like "*$TargetDir*") -or 
    ($_.ExecutablePath -like "*$TargetDir*")
}

if ($Processes) {
    Write-Host "PROCESSOS ENCONTRADOS BLOQUEANDO A PASTA:" -ForegroundColor Red
    foreach ($p in $Processes) {
        Write-Host "PID: $($p.ProcessId) | Name: $($p.Name)"
        Write-Host "   Path: $($p.ExecutablePath)"
        Write-Host "   Cmd:  $($p.CommandLine)"
        Write-Host "---------------------------------------------------"
    }
} else {
    Write-Host "Nenhum processo óbvio encontrado via WMI (ExecutablePath/CommandLine)." -ForegroundColor Green
    Write-Host "Se o erro persistir, pode ser um terminal aberto ou Windows Explorer." -ForegroundColor Yellow
}
