# cleanup_system.ps1
# Automated System Cleanup Script
# Removes identified junk files while preserving critical system data.

$logFile = "$PSScriptRoot\CLEANUP_LOG.txt"
$reportFile = "$PSScriptRoot\CLEANUP_REPORT.md"
$trashPath = "$PSScriptRoot\_trash"
$pycachePattern = "__pycache__"
$tmpPattern = "*.tmp"
$logPattern = "*.log"
$bakPattern = "*.bak"

function Log-Message {
    param ([string]$message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] $message"
    Write-Host $logEntry
    Add-Content -Path $logFile -Value $logEntry
}

function Get-FolderSize {
    param ($path)
    $size = 0
    if (Test-Path $path) {
        Get-ChildItem -Path $path -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $size += $_.Length }
    }
    return $size
}

function Format-Size {
    param ($bytes)
    if ($bytes -gt 1GB) { return "{0:N2} GB" -f ($bytes / 1GB) }
    if ($bytes -gt 1MB) { return "{0:N2} MB" -f ($bytes / 1MB) }
    if ($bytes -gt 1KB) { return "{0:N2} KB" -f ($bytes / 1KB) }
    return "$bytes B"
}

Log-Message "Starting system cleanup..."

# 1. Analyze _trash folder
if (Test-Path $trashPath) {
    $trashSize = Get-FolderSize -path $trashPath
    Log-Message "Found _trash folder. Size: $(Format-Size $trashSize)"
} else {
    $trashSize = 0
    Log-Message "_trash folder not found."
}

# 2. Analyze __pycache__ folders
$pycacheFolders = Get-ChildItem -Path $PSScriptRoot -Recurse -Directory -Filter $pycachePattern -ErrorAction SilentlyContinue
$pycacheSize = 0
foreach ($folder in $pycacheFolders) {
    $pycacheSize += Get-FolderSize -path $folder.FullName
}
Log-Message "Found $($pycacheFolders.Count) __pycache__ folders. Total Size: $(Format-Size $pycacheSize)"

# 3. Analyze Temp/Log files (excluding current logs if any)
# We will be careful not to delete the log file we are writing to
$junkFiles = Get-ChildItem -Path $PSScriptRoot -Recurse -File -Include $tmpPattern, $bakPattern, "*.old", "*.swp" -ErrorAction SilentlyContinue
$junkSize = 0
foreach ($file in $junkFiles) {
    $junkSize += $file.Length
}
Log-Message "Found $($junkFiles.Count) temporary/junk files. Total Size: $(Format-Size $junkSize)"

$totalFreed = $trashSize + $pycacheSize + $junkSize
Log-Message "Estimated space to be freed: $(Format-Size $totalFreed)"

# 4. Perform Cleanup
Log-Message "Initiating deletion..."

# Delete _trash
if (Test-Path $trashPath) {
    try {
        Remove-Item -Path $trashPath -Recurse -Force -ErrorAction Stop
        Log-Message "Deleted _trash folder."
    } catch {
        Log-Message "Error deleting _trash: $_"
    }
}

# Delete __pycache__
foreach ($folder in $pycacheFolders) {
    try {
        Remove-Item -Path $folder.FullName -Recurse -Force -ErrorAction SilentlyContinue
        Log-Message "Deleted $($folder.FullName)"
    } catch {
        Log-Message "Error deleting $($folder.FullName): $_"
    }
}

# Delete junk files
foreach ($file in $junkFiles) {
    try {
        Remove-Item -Path $file.FullName -Force -ErrorAction SilentlyContinue
        Log-Message "Deleted $($file.FullName)"
    } catch {
        Log-Message "Error deleting $($file.FullName): $_"
    }
}

Log-Message "Cleanup completed."

# 5. Generate Report
$reportContent = @"
# System Cleanup Report
**Date:** $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

## Summary
- **Total Space Freed:** $(Format-Size $totalFreed)
- **_trash Folder:** $(if ($trashSize -gt 0) { "Removed ($(Format-Size $trashSize))" } else { "Not found" })
- **__pycache__ Folders:** Removed $($pycacheFolders.Count) folders ($(Format-Size $pycacheSize))
- **Junk Files:** Removed $($junkFiles.Count) files ($(Format-Size $junkSize))

## Details
See CLEANUP_LOG.txt for detailed operation logs.
"@

Set-Content -Path $reportFile -Value $reportContent
Log-Message "Report generated at $reportFile"
