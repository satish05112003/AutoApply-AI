# AutoApply AI - Platform Shutdown
Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

$Root = $PSScriptRoot

if (-not (Test-Path "$Root\runtime")) {
    New-Item -ItemType Directory -Path "$Root\runtime" | Out-Null
}

# Create stop signal so wrappers exit
"stop" | Out-File -FilePath "$Root\runtime\stop.signal" -Encoding utf8

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       AutoApply AI Shutdown System       " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Kill supervisor first so it doesn't try to restart anything
$supervisorPidFile = "$Root\pids\supervisor.pid"
if (Test-Path $supervisorPidFile) {
    $targetPidRaw = Get-Content -Path $supervisorPidFile -Raw -ErrorAction SilentlyContinue
    if ($targetPidRaw -and $targetPidRaw.Trim() -match '^\d+$') {
        $pidInt = [int]($targetPidRaw.Trim())
        Write-Host "Terminating supervisor process PID $pidInt..." -ForegroundColor Yellow
        taskkill /F /PID $pidInt *> $null
    }
    Remove-Item $supervisorPidFile -ErrorAction SilentlyContinue
}

# 2. Kill all wrapper and child processes saved in pids/
if (Test-Path "$Root\pids") {
    $pidFiles = Get-ChildItem -Path "$Root\pids\*.pid" -ErrorAction SilentlyContinue
    # Sort child PIDs first so we kill the actual services before their wrapper shells
    $sortedPidFiles = $pidFiles | Sort-Object { $_.Name -like "*_child.pid" } -Descending
    
    foreach ($file in $sortedPidFiles) {
        if (Test-Path $file.FullName) {
            $targetPidRaw = Get-Content -Path $file.FullName -Raw -ErrorAction SilentlyContinue
            if ($targetPidRaw -and $targetPidRaw.Trim() -match '^\d+$') {
                $pidInt = [int]($targetPidRaw.Trim())
                Write-Host "Terminating process tree for PID $pidInt ($($file.BaseName))..." -ForegroundColor Yellow
                taskkill /F /T /PID $pidInt *> $null
            }
            Remove-Item $file.FullName -ErrorAction SilentlyContinue
        }
    }
}

# 3. Clean up ports 8000 and 3000 just in case anything leaked
$ports = @(8000, 3000)
foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        foreach ($c in $conn) {
            if ($c.OwningProcess -gt 0) {
                Write-Host "Cleaning up orphaned process $($c.OwningProcess) on port $port..." -ForegroundColor Yellow
                taskkill /F /T /PID $c.OwningProcess *> $null
            }
        }
    }
}

# Remove stop signal
Remove-Item "$Root\runtime\stop.signal" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "All AutoApply AI services stopped successfully." -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
