param(
    [string]$Source = "f:\Sistema Almareia Mirapraia",
    [string]$Dest = "C:\Users\Angelo Diamante\Documents\trae_projects\Back of the house",
    [switch]$AllowCustomDest,
    [switch]$SkipBackup,
    [switch]$RunSafeUpdater,
    [switch]$RunCompileCheck
)

$ProductionDest = "C:\Users\Angelo Diamante\Documents\trae_projects\Back of the house"
if (-not $AllowCustomDest -and $Dest -ne $ProductionDest) {
    Write-Warning "Destino informado ($Dest) ignorado. Usando destino de produção: $ProductionDest. Use -AllowCustomDest para sobrescrever."
    $Dest = $ProductionDest
}

Write-Host "Updating production system from $Source to $Dest"

function Ensure-Dir([string]$Path) {
    if (!(Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Patch-PortsTo5000([string]$Content) {
    if ($null -eq $Content) { return $Content }

    $Content = $Content.Replace("port=5001", "port=5000")
    $Content = $Content.Replace("port = 5001", "port = 5000")
    $Content = $Content.Replace("connect(5001", "connect(5000")
    $Content = $Content.Replace("http://{local_ip}:5001", "http://{local_ip}:5000")
    $Content = $Content.Replace("http://localhost:5001", "http://localhost:5000")
    $Content = $Content.Replace("http://127.0.0.1:5001", "http://127.0.0.1:5000")
    $Content = $Content.Replace("DEV MODE (Port 5001)", "PRODUCTION MODE (Port 5000)")
    return $Content
}

Ensure-Dir $Dest
Ensure-Dir (Join-Path $Dest "templates")

if (-not $SkipBackup) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupDir = Join-Path (Join-Path $Dest "backups") ("pre_update_" + $timestamp)
    Ensure-Dir $backupDir

    $backupTargets = @(
        "app.py",
        "wsgi.py",
        "share.py",
        "printing_service.py",
        "system_config_manager.py",
        "whatsapp_service.py",
        "waiting_list_service.py",
        "whatsapp_chat_service.py",
        "templates",
        "services",
        "scripts",
        "static"
    )

    foreach ($t in $backupTargets) {
        $tSrc = Join-Path $Dest $t
        $tDst = Join-Path $backupDir $t
        if (Test-Path $tSrc) {
            try {
                Copy-Item -Path $tSrc -Destination $tDst -Recurse -Force -ErrorAction Stop
            } catch {
                Write-Warning "Backup failed for $t : $_"
            }
        }
    }
}

$files = @(
    "waiting_list_service.py",
    "whatsapp_chat_service.py",
    "templates\whatsapp_chat.html",
    "system_config_manager.py",
    "whatsapp_service.py",
    "app.py",
    "printing_service.py",
    "templates\menu_management.html",
    "templates\restaurant_table_order.html",
    "wsgi.py",
    "share.py"
)

function Robocopy-Dir([string]$Src, [string]$Dst, [string[]]$ExcludeDirs = @()) {
    if (!(Test-Path $Src)) { return }
    Ensure-Dir $Dst

    $args = @($Src, $Dst, "/E", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    foreach ($xd in $ExcludeDirs) {
        if ($xd) {
            $args += "/XD"
            $args += (Join-Path $Src $xd)
        }
    }

    & robocopy @args | Out-Null
}

Robocopy-Dir (Join-Path $Source "templates") (Join-Path $Dest "templates")
Write-Host "Copied templates directory" -ForegroundColor Green

Robocopy-Dir (Join-Path $Source "services") (Join-Path $Dest "services")
Write-Host "Copied services directory" -ForegroundColor Green

Robocopy-Dir (Join-Path $Source "scripts") (Join-Path $Dest "scripts")
Write-Host "Copied scripts directory" -ForegroundColor Green

Robocopy-Dir (Join-Path $Source "static") (Join-Path $Dest "static") @("Produtos\\Fotos")
Write-Host "Copied static directory" -ForegroundColor Green

foreach ($file in $files) {
    $srcPath = Join-Path $Source $file
    $dstPath = Join-Path $Dest $file
    
    if (Test-Path $srcPath) {
        try {
            if ($file -match "app.py|wsgi.py|share.py") {
                $content = Get-Content -Path $srcPath -Raw -Encoding UTF8
                $content = Patch-PortsTo5000 $content
                Set-Content -Path $dstPath -Value $content -Encoding UTF8
                Write-Host "Copied and Configured (Port 5000): $file" -ForegroundColor Green
            } else {
                Ensure-Dir (Split-Path -Parent $dstPath)
                Copy-Item -Path $srcPath -Destination $dstPath -Force -ErrorAction Stop
                Write-Host "Copied: $file" -ForegroundColor Green
            }
        } catch {
            Write-Error "Failed to copy $file : $_"
        }
    } else {
        Write-Warning "Source file not found: $file"
    }
}

if ($RunSafeUpdater) {
    try {
        $safeUpdater = Join-Path $Dest "scripts\safe_updater.py"
        if (Test-Path $safeUpdater) {
            & python $safeUpdater | Out-Host
        }
    } catch {
        Write-Warning "safe_updater failed: $_"
    }
}

if ($RunCompileCheck) {
    try {
        Push-Location $Dest
        & python -m compileall -q . | Out-Null
        Pop-Location
        Write-Host "Python compile check OK" -ForegroundColor Green
    } catch {
        Write-Warning "Python compile check failed: $_"
    }
}

Write-Host "Update complete." -ForegroundColor Cyan
