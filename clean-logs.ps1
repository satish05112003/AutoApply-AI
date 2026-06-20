# AutoApply AI - Clean Log Files
Set-StrictMode -Version Latest

$Root = $PSScriptRoot

Write-Host "Stopping all AutoApply AI services to release file locks..." -ForegroundColor Cyan
& (Join-Path $Root "stop-all.ps1")

Write-Host "Cleaning log files under logs/..." -ForegroundColor Cyan
if (Test-Path "$Root\logs") {
    Remove-Item "$Root\logs\*" -Recurse -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Path "$Root\logs" | Out-Null
}

Write-Host "Logs cleaned successfully." -ForegroundColor Green
