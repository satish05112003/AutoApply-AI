# AutoApply AI — Platform Worker Launcher
# Spawns every Celery worker in its own visible PowerShell window.
# Usage: .\start-workers.ps1
# Run from D:\Predictions\AutoAiApply

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root       = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$CeleryExe  = "$BackendDir\venv\Scripts\celery.exe"
$PythonExe  = "$BackendDir\venv\Scripts\python.exe"

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   AutoApply AI — Platform Worker Launcher  " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# ── Preflight: verify venv ────────────────────────────────────────────────────
if (-not (Test-Path $CeleryExe)) {
    Write-Host "[ERROR] Celery not found at: $CeleryExe" -ForegroundColor Red
    Write-Host "  Fix: cd backend && venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

# ── Verify Celery imports cleanly ─────────────────────────────────────────────
Write-Host "[*] Verifying Celery module imports..." -ForegroundColor Yellow
$testResult = & $PythonExe -c "from app.celery_app import celery_app; from app.tasks.application_tasks import dispatch_application; print('OK')" 2>&1
if ($testResult -match "OK") {
    Write-Host "  [OK] Celery imports verified." -ForegroundColor Green
} else {
    Write-Host "  [ERROR] Celery import check failed:" -ForegroundColor Red
    Write-Host $testResult -ForegroundColor Red
    exit 1
}

Write-Host ""

# ── Worker definitions ────────────────────────────────────────────────────────
$workers = @(
    @{ Name="beat";              Label="Celery Beat (Scheduler)";  Queue="";              Args="-A app.celery_app.celery_app beat --loglevel=info" },
    @{ Name="discovery";         Label="Discovery Worker";         Queue="discovery";     Conc=2 },
    @{ Name="orchestrate";       Label="Orchestrate Worker";       Queue="orchestrate";   Conc=2 },
    @{ Name="applications";      Label="Generic App Worker";       Queue="applications";  Conc=2 },
    @{ Name="linkedin";          Label="LinkedIn Worker";          Queue="linkedin";      Conc=1 },
    @{ Name="indeed";            Label="Indeed Worker";            Queue="indeed";        Conc=1 },
    @{ Name="naukri";            Label="Naukri Worker";            Queue="naukri";        Conc=1 },
    @{ Name="unstop";            Label="Unstop Worker";            Queue="unstop";        Conc=1 },
    @{ Name="ats";               Label="ATS Worker";               Queue="ats";           Conc=2 },
    @{ Name="workday";           Label="Workday Worker";           Queue="workday";       Conc=1 },
    @{ Name="portal";            Label="Portal Worker";            Queue="portal";        Conc=1 },
    @{ Name="sheets";            Label="Sheets Worker";            Queue="sheets";        Conc=1 },
    @{ Name="email";             Label="Email Worker";             Queue="email";         Conc=1 }
)

# ── Launch each worker ────────────────────────────────────────────────────────
foreach ($w in $workers) {
    $name  = $w.Name
    $label = $w.Label

    if ($name -eq "beat") {
        $celeryArgs = $w.Args
    } else {
        $celeryArgs = "-A app.celery_app.celery_app worker --loglevel=info -P solo -Q $($w.Queue) -n worker_${name}@localhost --concurrency=$($w.Conc)"
    }

    $windowTitle = "AutoApply AI — $label"
    $cmd = "& { `$host.UI.RawUI.WindowTitle = '$windowTitle'; Set-Location '$BackendDir'; & '$CeleryExe' $celeryArgs }"
    
    Write-Host "  Starting: $label (Queue: $($w.Queue))..." -ForegroundColor Yellow
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $cmd `
        -WindowStyle Normal

    Start-Sleep -Milliseconds 400
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  All $($workers.Count) workers launched in separate windows " -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Workers started:" -ForegroundColor Cyan
foreach ($w in $workers) {
    Write-Host "    -> $($w.Label)" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "  To stop all workers: .\stop-all.ps1" -ForegroundColor DarkYellow
Write-Host ""
