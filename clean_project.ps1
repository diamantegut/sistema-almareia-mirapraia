# clean_project.ps1
$trash = "_trash"
if (-not (Test-Path $trash)) { New-Item -ItemType Directory -Force -Path $trash }

function Move-Safe {
    param($path, $dest)
    if (Test-Path $path) {
        Write-Host "Movendo $path para $dest..."
        Move-Item -Path $path -Destination $dest -Force
    }
}

# 1. Mover pasta de backups antigos
Move-Safe "backups" "$trash\backups"

# 2. Mover arquivos Monolíticos da raiz
Move-Safe "app.py" "$trash\app_monolithic.py"
Move-Safe "wsgi.py" "$trash\wsgi_old.py"

# 3. Mover pastas duplicadas (a versão correta está dentro de app/)
Move-Safe "templates" "$trash\templates_legacy"
Move-Safe "static" "$trash\static_legacy"
Move-Safe "services" "$trash\services_legacy"

# 4. Mover scripts soltos da raiz (exceto os essenciais)
$keep = @("run.py", "clean_project.ps1", "production_run.py", "wsgi.py", "requirements.txt", "README.md", "checklist_items.json", "daily_checklists.json", "menu_items.json", "products.json", "users.json")
$scripts = Get-ChildItem -Path . -Filter "*.py"
foreach ($s in $scripts) {
    if ($keep -notcontains $s.Name) {
         $dest = "$trash\root_scripts"
         if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Force -Path $dest }
         Move-Safe $s.FullName "$dest\$($s.Name)"
    }
}

Write-Host "Limpeza concluída! Arquivos movidos para _trash."
