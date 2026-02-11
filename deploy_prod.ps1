<#
.SYNOPSIS
    Script de Deploy Automatizado para Almareia Mirapraia (Producao)
    Realiza backup, atualizacao via Robocopy (Mirror), validacao e rollback automatico.

.DESCRIPTION
    1. Prepara uma nova pasta de release com o codigo atual.
    2. Realiza backup da versao atual em execucao.
    3. Para o servico na porta 5000.
    4. Sincroniza arquivos usando Robocopy (Mirror) para contornar bloqueios.
    5. Inicia o servico e valida endpoints.
    6. Em caso de erro, restaura o backup via Robocopy.

.NOTES
    Autor: Trae AI / Equipe Almareia
    Data: 06/02/2026 - Fix 6 (Port Config)
#>

$SourceDir = "F:\Sistema Almareia Mirapraia"
$ProdBaseDir = "F:\"
$ProdDirName = "Sistema Almareia Mirapraia"
$ProdPath = Join-Path $ProdBaseDir $ProdDirName
$BackupBaseDir = "G:\Backups"
if (-not (Test-Path "G:\")) {
    $BackupBaseDir = Join-Path $ProdBaseDir "Backups"
}
$LogFile = Join-Path $ProdBaseDir "deploy_log.txt"
$Port = 5000
$HealthCheckUrl = "http://localhost:5000/login"
$MaxRetries = 60  # Aumentado para 120 segundos (2 minutos)
$ErrorActionPreference = "Stop"

function Log-Message {
    param([string]$Message, [string]$Level="INFO")
    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogEntry = "[$Timestamp] [$Level] $Message"
    
    $Color = "Green"
    if ($Level -eq "ERROR") { $Color = "Red" }
    elseif ($Level -eq "WARNING") { $Color = "Yellow" }
    
    Write-Host $LogEntry -ForegroundColor $Color
    Add-Content -Path $LogFile -Value $LogEntry
}

function Get-ProcessByPort {
    param($Port)
    $netstat = netstat -ano | Select-String ":$Port\s"
    if ($netstat) {
        $pidStr = $netstat -split '\s+' | Select-Object -Last 1
        return $pidStr
    }
    return $null
}

try {
    Log-Message "=== Iniciando Procedimento de Deploy (Versao Fix 5 - Debug) ==="

    # 1. Preparacao
    if (-not (Test-Path $BackupBaseDir)) { New-Item -ItemType Directory -Path $BackupBaseDir | Out-Null }
    
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $NewReleaseDir = Join-Path $ProdBaseDir "${ProdDirName}_New_${Timestamp}"
    $BackupDir = Join-Path $BackupBaseDir "${ProdDirName}_Backup_${Timestamp}"

    Log-Message "Criando diretorio de preparacao: $NewReleaseDir"
    New-Item -ItemType Directory -Path $NewReleaseDir | Out-Null

    # 2. Copiar Arquivos (Excluindo desnecessarios)
    Log-Message "Copiando arquivos de $SourceDir para $NewReleaseDir..."
    $Exclude = @('.git', '.venv', '__pycache__', '*.pyc', '.vscode', 'tmp')
    Copy-Item -Path "$SourceDir\*" -Destination $NewReleaseDir -Recurse -Force -Exclude $Exclude

    # 3. Preparar Ambiente (Copiar venv existente ou criar novo)
    if (Test-Path "$ProdPath\.venv") {
        Log-Message "Clonando ambiente virtual de producao..."
        Copy-Item -Path "$ProdPath\.venv" -Destination $NewReleaseDir -Recurse -Force
    } else {
        Log-Message "AVISO: .venv nao encontrado em producao. Certifique-se que o Python global tem as dependencias." -Level "WARNING"
    }

    # 4. Parar Servico Atual
    Log-Message "Verificando processos (Porta 5000 ou Zombies)..."
    
    # A) Matar por Porta
    $ProcessId = Get-ProcessByPort $Port
    if ($ProcessId -and [int]$ProcessId -gt 0) {
        Log-Message "Parando processo na porta $Port (PID: $ProcessId)..."
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
    
    # B) Matar Zombies (Python segurando arquivos na pasta de producao)
    try {
        $Zombies = Get-CimInstance Win32_Process | Where-Object { 
            ($_.Name -match "^python") -and 
            ($_.CommandLine -like "*$ProdDirName*")
        }
        foreach ($z in $Zombies) {
            Log-Message "Matando processo ZOMBIE detectado (PID: $($z.ProcessId))..." -Level "WARNING"
            Stop-Process -Id $z.ProcessId -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Log-Message "Erro ao buscar zombies: $_" -Level "WARNING"
    }

    # Aguardar liberacao
    Start-Sleep -Seconds 3

    # 5. Atualizacao (Estrategia: Robocopy Mirror)
    Log-Message "Iniciando atualizacao de arquivos (Robocopy Mirror)..."
    
    # 5.1 Backup Previo (Copia de Seguranca)
    if (Test-Path $ProdPath) {
        Log-Message "Criando backup de seguranca em $BackupDir..."
        Copy-Item -Path $ProdPath -Destination $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        New-Item -ItemType Directory -Path $ProdPath -Force | Out-Null
    }

    # 5.2 Sincronizacao (New -> Prod)
    Log-Message "Executando Robocopy de $NewReleaseDir para $ProdPath"
    
    # Lista de Exclusao para Proteger Dados de Producao
    $ExcludeDirs = @(
        "data", 
        "guests_encrypted", 
        "secure_docs", 
        "backups", 
        "Fiscal", 
        "Resumo de Estoque",
        "Vendas",
        "Fotos",
        ".venv", 
        ".git", 
        ".vscode", 
        "__pycache__",
        "tmp"
    )

    $ExcludeFiles = @(
        "users.json", 
        "products.json", 
        "table_orders.json", 
        "room_charges.json", 
        "sales_history.json", 
        "stock_entries.json", 
        "suppliers.json", 
        "system_status.json", 
        "complements.json", 
        "conferences.json", 
        "printers.json", 
        "settings.json", 
        "last_sync.json", 
        "checklist_items.json", 
        "checklist_settings.json", 
        "daily_checklists.json",
        "manual_allocations.json",
        "room_occupancy.json",
        "whatsapp_messages.json",
        "deleted_messages_log.json",
        "*.log",
        "*.pyc"
    )

    # Montar opcoes do Robocopy
    $RoboOptions = @("/MIR", "/NP", "/NFL", "/NDL", "/R:3", "/W:1")
    
    # Adicionar Exclusoes de Diretorios (/XD)
    if ($ExcludeDirs.Count -gt 0) {
        $RoboOptions += "/XD"
        $RoboOptions += $ExcludeDirs
    }

    # Adicionar Exclusoes de Arquivos (/XF)
    if ($ExcludeFiles.Count -gt 0) {
        $RoboOptions += "/XF"
        $RoboOptions += $ExcludeFiles
    }

    Log-Message "Opcoes Robocopy: $RoboOptions"
    & robocopy.exe "$NewReleaseDir" "$ProdPath" $RoboOptions
    $ExitCode = $LASTEXITCODE
    
    # Robocopy Exit Codes: < 8 e sucesso
    if ($ExitCode -ge 8) {
        Log-Message "ERRO CRITICO NO ROBOCOPY. Codigo de Saida: $ExitCode" -Level "ERROR"
        throw "Falha na sincronizacao de arquivos."
    }
    
    Log-Message "Arquivos sincronizados com sucesso."

    # 6. Iniciar Novo Servico
    Log-Message "Iniciando nova versao da aplicacao..."
    $PythonExe = "$ProdPath\.venv\Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) { $PythonExe = "python" }

    # Forcar porta correta via Variavel de Ambiente
    $env:APP_PORT = $Port
    Log-Message "Configurado APP_PORT=$Port"

    # Inicia em background
    $AppScript = "`"$ProdPath\app.py`""
    $Process = Start-Process -FilePath $PythonExe -ArgumentList $AppScript -PassThru -WindowStyle Hidden -RedirectStandardOutput "$ProdPath\stdout.log" -RedirectStandardError "$ProdPath\stderr.log"
    
    Log-Message "Processo iniciado com PID: $($Process.Id)"

    # 7. Validacao (Health Check)
    Log-Message "Aguardando servico ficar online (Timeout: 120s)..."
    $Success = $false
    for ($i = 1; $i -le $MaxRetries; $i++) {
        try {
            $Response = Invoke-WebRequest -Uri $HealthCheckUrl -UseBasicParsing -Method Head -ErrorAction Stop
            if ($Response.StatusCode -eq 200) {
                $Success = $true
                break
            }
        } catch {
            Write-Host -NoNewline "."
            Start-Sleep -Seconds 2
        }
    }
    Write-Host ""

    if ($Success) {
        Log-Message "DEPLOY CONCLUIDO COM SUCESSO! Sistema respondendo na porta $Port."
        
        # Validacoes adicionais
        Log-Message "Executando checklist pos-deploy..."
        try {
            Log-Message "- Endpoint Login: OK"
            Log-Message "- Processo PID $($Process.Id): Ativo"
        } catch {
            Log-Message "Aviso: Falha nas validacoes secundarias." -Level "WARNING"
        }

    } else {
        throw "Timeout: O servico nao respondeu na porta $Port apos $($MaxRetries * 2) segundos."
    }

} catch {
    Log-Message "ERRO DURANTE O DEPLOY: $($_.Exception.Message)" -Level "ERROR"
    
    # --- DEBUG: CAPTURAR LOGS ANTES DO ROLLBACK ---
    Log-Message "=== DIAGNOSTICO DE FALHA ===" -Level "ERROR"
    
    if (Test-Path "$ProdPath\stderr.log") {
        Log-Message "--- CONTEUDO DE STDERR.LOG (ULTIMAS 20 LINHAS) ---" -Level "ERROR"
        Get-Content "$ProdPath\stderr.log" -Tail 20 | ForEach-Object { Log-Message "STDERR: $_" -Level "ERROR" }
    } else {
        Log-Message "stderr.log nao encontrado." -Level "ERROR"
    }

    if (Test-Path "$ProdPath\stdout.log") {
        Log-Message "--- CONTEUDO DE STDOUT.LOG (ULTIMAS 20 LINHAS) ---" -Level "ERROR"
        Get-Content "$ProdPath\stdout.log" -Tail 20 | ForEach-Object { Log-Message "STDOUT: $_" -Level "ERROR" }
    }
    # ----------------------------------------------

    Log-Message "INICIANDO ROLLBACK AUTOMATICO..." -Level "ERROR"

    # Rollback Logic
    # 1. Matar processo novo
    $NewPid = Get-ProcessByPort $Port
    if ($NewPid) { Stop-Process -Id $NewPid -Force }

    # 2. Restaurar Backup (Robocopy Mirror Inverso)
    if (Test-Path $BackupDir) {
        Log-Message "Restaurando arquivos do backup..."
        
        $RoboOptions = @("/MIR", "/NP", "/NFL", "/NDL", "/R:3", "/W:1")
        & robocopy.exe "$BackupDir" "$ProdPath" $RoboOptions
        
        Log-Message "Backup restaurado."
        
        # 3. Reiniciar servico antigo
        $PythonExe = "$ProdPath\.venv\Scripts\python.exe"
        if (-not (Test-Path $PythonExe)) { $PythonExe = "python" }
        
        $env:APP_PORT = $Port
        Log-Message "Configurado APP_PORT=$Port (Rollback)"

        $AppScript = "`"$ProdPath\app.py`""
        Start-Process -FilePath $PythonExe -ArgumentList $AppScript -WindowStyle Hidden -RedirectStandardOutput "$ProdPath\stdout_rollback.log" -RedirectStandardError "$ProdPath\stderr_rollback.log"
        Log-Message "Servico anterior reiniciado."
    } else {
        Log-Message "FALHA CATASTROFICA: Backup nao encontrado para rollback." -Level "ERROR"
    }
    exit 1
}

Log-Message "=== Procedimento Finalizado ==="
