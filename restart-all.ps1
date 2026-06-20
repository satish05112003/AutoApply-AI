# AutoApply AI - Platform Restart
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
Push-Location $Root
try {
    Write-Host "Triggering complete platform restart..." -ForegroundColor Cyan
    & (Join-Path $Root "stop-all.ps1")
    Start-Sleep -Seconds 2
    & (Join-Path $Root "start-all.ps1")
} finally {
    Pop-Location
}
