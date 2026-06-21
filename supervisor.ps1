# AutoApply AI - Supervisor Daemon
# PowerShell 5.1 compatible. ASCII-safe output only.
# Manages all services and auto-restarts crashed processes.
# Do not run manually - launched by start-all.ps1

$ErrorActionPreference = "SilentlyContinue"

$Root           = $PSScriptRoot
$BackendDir     = Join-Path $Root "backend"
$FrontendDir    = Join-Path $Root "frontend"
$PythonExe      = Join-Path $BackendDir "venv\Scripts\python.exe"
$CeleryExe      = Join-Path $BackendDir "venv\Scripts\celery.exe"
$RunServicePath = Join-Path $Root "run-service.ps1"
$PidsDir        = Join-Path $Root "pids"
$LogsDir        = Join-Path $Root "logs"
$StopSignal     = Join-Path $Root "runtime\stop.signal"

# Save own PID
if (-not (Test-Path $PidsDir)) { New-Item -ItemType Directory -Path $PidsDir | Out-Null }
$PID | Out-File -FilePath (Join-Path $PidsDir "supervisor.pid") -Encoding utf8

function Write-Log {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Msg"
    Add-Content -Path (Join-Path $LogsDir "recovery.log") -Value $line -Encoding utf8
}

function Get-Base64Json {
    param([string]$JsonStr)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($JsonStr)
    return [Convert]::ToBase64String($bytes)
}

function Start-ManagedService {
    param(
        [string]$Name,
        [string]$Label,
        [string]$Cwd,
        [string]$RunCmd,
        [string]$EnvB64
    )

    $pidFile = Join-Path $PidsDir "$Name.pid"

    # Skip if already alive
    if (Test-Path $pidFile) {
        $raw = (Get-Content $pidFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($raw -eq "LAUNCHING") {
            $fileAge = (Get-Date) - (Get-Item $pidFile).LastWriteTime
            if ($fileAge.TotalSeconds -lt 15) { return }
        }
        if ($raw -match "^\d+$") {
            $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
            if ($proc -and (-not $proc.HasExited)) { return }
        }
    }

    "LAUNCHING" | Out-File -FilePath $pidFile -Encoding utf8

    # Build the inner command string for run-service.ps1
    $eName   = $Name    -replace "'", "''"
    $eLabel  = $Label   -replace "'", "''"
    $eCwd    = $Cwd     -replace "'", "''"
    $eRunCmd = $RunCmd  -replace "'", "''"
    $eEnvB64 = $EnvB64  -replace "'", "''"

    $inner = "& '$RunServicePath' -Name '$eName' -Label '$eLabel' -Cwd '$eCwd' -RunCmd '$eRunCmd' -EnvVarsJsonBase64 '$eEnvB64'"

    $bytes   = [System.Text.Encoding]::Unicode.GetBytes($inner)
    $encoded = [Convert]::ToBase64String($bytes)

    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-NoExit", "-EncodedCommand", $encoded `
        -WindowStyle Hidden
}

# --- Environment payloads ---------------------------------------------------
$backendEnvB64  = Get-Base64Json '{"BACKEND_PORT":"8000","FRONTEND_URL":"http://localhost:3000","BACKEND_RELOAD":"false"}'
$frontendEnvB64 = Get-Base64Json '{"PORT":"3000"}'

# --- Worker specs -----------------------------------------------------------
# Each entry: Name, Label, Queue, Concurrency
$workerSpecs = @(
    @("worker_discovery",    "Discovery Worker",    "discovery",    2),
    @("worker_orchestrate",  "Orchestrate Worker",  "orchestrate",  2),
    @("worker_applications", "Generic App Worker",  "applications", 2),
    @("worker_linkedin",     "LinkedIn Worker",     "linkedin",     1),
    @("worker_indeed",       "Indeed Worker",       "indeed",       1),
    @("worker_naukri",       "Naukri Worker",       "naukri",       1),
    @("worker_unstop",       "Unstop Worker",       "unstop",       1),
    @("worker_ats",          "ATS Worker",          "ats",          2),
    @("worker_workday",      "Workday Worker",      "workday",      1),
    @("worker_portal",       "Portal Worker",       "portal",       1),
    @("worker_sheets",       "Sheets Worker",       "sheets",       1),
    @("worker_email",        "Email Worker",        "email",        1)
)

Write-Log "Supervisor started (PID $PID). Managing $($workerSpecs.Count) workers."

$tick = 0

while ($true) {
    # Check stop signal
    if (Test-Path $StopSignal) {
        Write-Log "Stop signal detected. Supervisor shutting down."
        break
    }

    # --- Backend ---
    Start-ManagedService `
        -Name    "backend" `
        -Label   "FastAPI Backend" `
        -Cwd     $BackendDir `
        -RunCmd  "$PythonExe -u start.py" `
        -EnvB64  $backendEnvB64

    # --- Celery Beat ---
    Start-ManagedService `
        -Name   "beat" `
        -Label  "Celery Beat" `
        -Cwd    $BackendDir `
        -RunCmd "$CeleryExe -A app.celery_app.celery_app beat --loglevel=info" `
        -EnvB64 ""

    # --- Platform Workers ---
    foreach ($spec in $workerSpecs) {
        $wName  = $spec[0]
        $wLabel = $spec[1]
        $wQueue = $spec[2]
        $wConc  = $spec[3]
        $wCmd   = "$CeleryExe -A app.celery_app.celery_app worker --loglevel=info -P solo -Q $wQueue -n $wName@localhost --concurrency=$wConc"

        Start-ManagedService `
            -Name   $wName `
            -Label  $wLabel `
            -Cwd    $BackendDir `
            -RunCmd $wCmd `
            -EnvB64 ""
    }

    # --- Frontend ---
    Start-ManagedService `
        -Name   "frontend" `
        -Label  "Next.js Frontend" `
        -Cwd    $FrontendDir `
        -RunCmd "cmd.exe /c npm run dev -- -p 3000" `
        -EnvB64 $frontendEnvB64

    # --- Periodic health self-healing (every 60 ticks = ~60s) ---
    $tick++
    if ($tick -ge 60) {
        $tick = 0

        Push-Location $BackendDir
        try {
            $healthOut = & $PythonExe platform_health.py 2>$null
            if ($healthOut) {
                $healthStr = $healthOut -join "`n"
                $jsonIdx = $healthStr.IndexOf("{")
                if ($jsonIdx -ge 0) {
                    $healthJson = $healthStr.Substring($jsonIdx)
                    $healthData = ConvertFrom-Json $healthJson

                    if ($healthData.workers) {
                        foreach ($wprop in $healthData.workers.PSObject.Properties) {
                            if ($wprop.Value -eq "OFFLINE") {
                                $offlineQueue = $wprop.Name
                                Write-Log "Worker queue '$offlineQueue' is OFFLINE. Killing stale process and restarting."

                                # Kill wrapper PID
                                $wPidFile = Join-Path $PidsDir "worker_$offlineQueue.pid"
                                if (Test-Path $wPidFile) {
                                    $raw = (Get-Content $wPidFile -Raw -ErrorAction SilentlyContinue).Trim()
                                    if ($raw -match "^\d+$") {
                                        try { taskkill /F /T /PID $raw 2>$null } catch {}
                                    }
                                    Remove-Item $wPidFile -Force -ErrorAction SilentlyContinue
                                }

                                # Kill child PID
                                $childPidFile = Join-Path $PidsDir "worker_${offlineQueue}_child.pid"
                                if (Test-Path $childPidFile) {
                                    $raw = (Get-Content $childPidFile -Raw -ErrorAction SilentlyContinue).Trim()
                                    if ($raw -match "^\d+$") {
                                        try { taskkill /F /T /PID $raw 2>$null } catch {}
                                    }
                                    Remove-Item $childPidFile -Force -ErrorAction SilentlyContinue
                                }

                                # Restart matching spec
                                foreach ($spec in $workerSpecs) {
                                    if ($spec[2] -eq $offlineQueue) {
                                        $wCmd = "$CeleryExe -A app.celery_app.celery_app worker --loglevel=info -P solo -Q $($spec[2]) -n $($spec[0])@localhost --concurrency=$($spec[3])"
                                        Start-ManagedService -Name $spec[0] -Label $spec[1] -Cwd $BackendDir -RunCmd $wCmd -EnvB64 ""
                                        break
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } catch {
            Write-Log "Health check error: $_"
        } finally {
            Pop-Location
        }
    }

    Start-Sleep -Seconds 1
}

Remove-Item (Join-Path $PidsDir "supervisor.pid") -Force -ErrorAction SilentlyContinue
