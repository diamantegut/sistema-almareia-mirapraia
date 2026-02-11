# analyze_disk_usage.ps1
$root = Get-Location
$reportFile = "DISK_USAGE_REPORT.md"

function Get-FolderSize {
    param ($path)
    $size = 0
    Get-ChildItem -Path $path -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $size += $_.Length }
    return $size
}

function Format-Size {
    param ($bytes)
    if ($bytes -gt 1GB) { return "{0:N2} GB" -f ($bytes / 1GB) }
    if ($bytes -gt 1MB) { return "{0:N2} MB" -f ($bytes / 1MB) }
    if ($bytes -gt 1KB) { return "{0:N2} KB" -f ($bytes / 1KB) }
    return "$bytes B"
}

"--- Relatório de Uso de Disco ---" | Out-File -FilePath $reportFile -Encoding utf8
"Data: $(Get-Date)" | Out-File -FilePath $reportFile -Append -Encoding utf8
"" | Out-File -FilePath $reportFile -Append -Encoding utf8

# 1. Top 20 Largest Files
"## Top 20 Arquivos Mais Pesados" | Out-File -FilePath $reportFile -Append -Encoding utf8
"| Arquivo | Caminho | Tamanho |" | Out-File -FilePath $reportFile -Append -Encoding utf8
"|---|---|---|" | Out-File -FilePath $reportFile -Append -Encoding utf8

$files = Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue 
$files | Sort-Object Length -Descending | Select-Object -First 20 | ForEach-Object {
    $relPath = $_.FullName.Replace($root.Path, "")
    "| $($_.Name) | $relPath | $(Format-Size $_.Length) |" | Out-File -FilePath $reportFile -Append -Encoding utf8
}

# 2. Folder Sizes (Depth 1 and 2)
"" | Out-File -FilePath $reportFile -Append -Encoding utf8
"## Tamanho das Pastas (Nível 1 e 2)" | Out-File -FilePath $reportFile -Append -Encoding utf8
"| Pasta | Tamanho |" | Out-File -FilePath $reportFile -Append -Encoding utf8
"|---|---|" | Out-File -FilePath $reportFile -Append -Encoding utf8

$folders = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue
foreach ($folder in $folders) {
    $size = Get-FolderSize $folder.FullName
    "| **$($folder.Name)** | **$(Format-Size $size)** |" | Out-File -FilePath $reportFile -Append -Encoding utf8
    
    # Subfolders
    Get-ChildItem -Path $folder.FullName -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $subSize = Get-FolderSize $_.FullName
        "| &nbsp;&nbsp;&nbsp;&nbsp; $($_.Name) | $(Format-Size $subSize) |" | Out-File -FilePath $reportFile -Append -Encoding utf8
    }
}

# 3. File Type Analysis
"" | Out-File -FilePath $reportFile -Append -Encoding utf8
"## Análise por Tipo de Arquivo" | Out-File -FilePath $reportFile -Append -Encoding utf8
"| Extensão | Contagem | Tamanho Total |" | Out-File -FilePath $reportFile -Append -Encoding utf8
"|---|---|---|" | Out-File -FilePath $reportFile -Append -Encoding utf8

$files | Group-Object Extension | Sort-Object @{Expression={($_.Group | Measure-Object -Property Length -Sum).Sum}} -Descending | ForEach-Object {
    $ext = if ($_.Name) { $_.Name } else { "(sem extensão)" }
    $sum = ($_.Group | Measure-Object -Property Length -Sum).Sum
    "| $ext | $($_.Count) | $(Format-Size $sum) |" | Out-File -FilePath $reportFile -Append -Encoding utf8
}

Write-Host "Análise concluída. Verifique $reportFile"
