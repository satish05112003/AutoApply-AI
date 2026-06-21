# AutoApply AI - One-Command Platform Launcher
# PowerShell 5.1 compatible. ASCII-safe output only.
# Usage:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\start-all.ps1

$ErrorActionPreference = "Stop"

# ---- Helper: test TCP port ------------------------------------------------
function Test-Port {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $ar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne(800, $false)
        try { $client.Close() } catch {}
        return $ok
    } catch {
        return $false
    }
}

# ---- Helper: write a status line ------------------------------------------
function Write-OK   { param([string]$Msg) Write-Host "  [OK]   $Msg" -ForegroundColor Green  }
function Write-FAIL { param([string]$Msg) Write-Host "  [FAIL] $Msg" -ForegroundColor Red    }
function Write-WARN { param([string]$Msg) Write-Host "  [WARN] $Msg" -ForegroundColor Yellow }
function Write-INFO { param([string]$Msg) Write-Host "  [....] $Msg" -ForegroundColor Cyan   }

# ---- Paths ----------------------------------------------------------------
$Root        = $PSScriptRoot
$BackendDir  = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$PythonExe   = Join-Path $BackendDir "venv\Scripts\python.exe"
$CeleryExe   = Join-Path $BackendDir "venv\Scripts\celery.exe"
$EnvFile     = Join-Path $BackendDir ".env"

# ---- Banner ---------------------------------------------------------------
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "       AutoApply AI - Platform Launcher         " -ForegroundColor Cyan
Write-Host "   True Autonomous Multi-Agent Job Platform     " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ==========================================================================
# STEP 1 - PREFLIGHT CHECKS
# ==========================================================================
Write-Host "STEP 1/5 - PREFLIGHT CHECKS" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray

# 1a. venv
Write-INFO "Checking Python venv..."
if (-not (Test-Path $PythonExe)) {
    Write-FAIL "venv not found at: $PythonExe"
    Write-Host ""
    Write-Host "  Fix: cd backend" -ForegroundColor Yellow
    Write-Host "       python -m venv venv" -ForegroundColor Yellow
    Write-Host "       venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}
Write-OK "Python venv found"

# 1b. .env
Write-INFO "Checking .env file..."
if (-not (Test-Path $EnvFile)) {
    Write-FAIL ".env not found: $EnvFile"
    Write-Host "  Fix: Copy backend\.env.example to backend\.env" -ForegroundColor Yellow
    exit 1
}
Write-OK ".env file found"

# 1c. PostgreSQL
Write-INFO "Checking PostgreSQL (port 5432)..."
if (-not (Test-Port 5432)) {
    Write-FAIL "PostgreSQL is NOT running on port 5432"
    Write-Host "  Fix: net start postgresql-x64-16" -ForegroundColor Yellow
    Write-Host "       or open Services and start PostgreSQL" -ForegroundColor Yellow
    exit 1
}
Write-OK "PostgreSQL is reachable"

# 1d. Redis
Write-INFO "Checking Redis (port 6379)..."
if (-not (Test-Port 6379)) {
    Write-FAIL "Redis is NOT running on port 6379"
    Write-Host "  Fix (WSL): wsl -e bash -c 'sudo service redis-server start'" -ForegroundColor Yellow
    exit 1
}
Write-OK "Redis is reachable"

# 1e. Qdrant (optional)
Write-INFO "Checking Qdrant (port 6333)..."
if (Test-Port 6333) {
    Write-OK "Qdrant is reachable"
} else {
    Write-WARN "Qdrant not found on port 6333 (vector search optional)"
}

# 1f. Celery import check
Write-INFO "Verifying Celery module imports..."
$importScript = "from app.celery_app import celery_app; from app.tasks.application_tasks import dispatch_application; print('CELERY OK')"
$importOut = ""
Push-Location $BackendDir
try {
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $importOut = & $PythonExe -c $importScript 2>&1
} catch {
    $importOut = "ERROR: $_"
} finally {
    $ErrorActionPreference = $oldEap
    Pop-Location
}
$importStr = "$importOut"
if ($importStr -match "CELERY OK") {
    Write-OK "Celery imports verified"
} else {
    Write-FAIL "Celery import failed"
    Write-Host "  Output: $importStr" -ForegroundColor Red
    exit 1
}

# 1g. Alembic migrations
Write-INFO "Running database migrations..."
Push-Location $BackendDir
try {
    $migrOut = & $PythonExe -m alembic upgrade head 2>&1
    Write-OK "Migrations applied"
} catch {
    Write-WARN "Migration step failed (tables may already exist): $_"
} finally {
    Pop-Location
}

Write-Host ""

# ==========================================================================
# STEP 2 - SETUP DIRECTORIES
# ==========================================================================
Write-Host "STEP 2/5 - SETUP DIRECTORIES" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray

foreach ($dirName in @("logs", "runtime", "pids")) {
    $dirPath = Join-Path $Root $dirName
    if (-not (Test-Path $dirPath)) {
        New-Item -ItemType Directory -Path $dirPath | Out-Null
    }
}
$stopSignal = Join-Path $Root "runtime\stop.signal"
if (Test-Path $stopSignal) { Remove-Item $stopSignal -Force }

$envLocal = Join-Path $FrontendDir ".env.local"
$envLines = @(
    "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1",
    "NEXT_PUBLIC_WS_URL=ws://localhost:8000"
)
[System.IO.File]::WriteAllLines($envLocal, $envLines, [System.Text.UTF8Encoding]::new($false))
Write-OK "Directories ready, .env.local written"
Write-Host ""

# ==========================================================================
# STEP 3 - STOP STALE SERVICES
# ==========================================================================
Write-Host "STEP 3/5 - CLEARING STALE PROCESSES" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray

$stopScript = Join-Path $Root "stop-all.ps1"
if (Test-Path $stopScript) {
    try {
        & $stopScript 2>$null
    } catch {}
}
Start-Sleep -Seconds 2
Write-OK "Stale processes cleared"
Write-Host ""

# ==========================================================================
# STEP 4 - LAUNCH SUPERVISOR
# ==========================================================================
Write-Host "STEP 4/5 - LAUNCHING SUPERVISOR" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray

$supervisorScript = Join-Path $Root "supervisor.ps1"
if (-not (Test-Path $supervisorScript)) {
    Write-FAIL "supervisor.ps1 not found at: $supervisorScript"
    exit 1
}

Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-ExecutionPolicy", "Bypass", "-File", $supervisorScript `
    -WindowStyle Hidden

Write-OK "Supervisor daemon launched (manages all services)"
Write-Host ""
Write-Host "  Services being managed:" -ForegroundColor DarkGray
$serviceList = @(
    "    FastAPI Backend       -> http://localhost:8000",
    "    Next.js Frontend      -> http://localhost:3000",
    "    Celery Beat           -> periodic scheduler",
    "    Discovery Worker      -> queue: discovery",
    "    Orchestrate Worker    -> queue: orchestrate",
    "    Generic App Worker    -> queue: applications",
    "    LinkedIn Worker       -> queue: linkedin",
    "    Indeed Worker         -> queue: indeed",
    "    Naukri Worker         -> queue: naukri",
    "    Unstop Worker         -> queue: unstop",
    "    ATS Worker            -> queue: ats",
    "    Workday Worker        -> queue: workday",
    "    Portal Worker         -> queue: portal",
    "    Sheets Worker         -> queue: sheets",
    "    Email Monitor         -> queue: email"
)
foreach ($svc in $serviceList) {
    Write-Host $svc -ForegroundColor DarkCyan
}
Write-Host ""
Write-INFO "Waiting 10 seconds for services to initialize..."
Start-Sleep -Seconds 10
Write-Host ""

# ==========================================================================
# STEP 5 - HEALTH VALIDATION
# ==========================================================================
Write-Host "STEP 5/5 - VALIDATING SYSTEM HEALTH" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray

$success      = $false
$maxAttempts  = 18
$minWorkers   = 3

for ($i = 1; $i -le $maxAttempts; $i++) {
    Write-Host ""
    Write-Host "  Attempt $i / $maxAttempts" -ForegroundColor DarkGray

    # Backend
    $backendOk = $false
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $backendOk = $true }
    } catch {}

    # Frontend
    $frontendOk = $false
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $frontendOk = $true }
    } catch {}

    # Beat
    $beatOk = $false
    $beatPidFile = Join-Path $Root "pids\beat.pid"
    if (Test-Path $beatPidFile) {
        $raw = (Get-Content $beatPidFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($raw -match "^\d+$") {
            $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
            if ($proc) { $beatOk = $true }
        }
    }

    # Workers
    $workerCount = 0
    $pidsFolder = Join-Path $Root "pids"
    $workerPids = Get-ChildItem "$pidsFolder\worker_*.pid" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*_child.pid" }
    if ($workerPids) {
        foreach ($wf in $workerPids) {
            $raw = (Get-Content $wf.FullName -Raw -ErrorAction SilentlyContinue).Trim()
            if ($raw -match "^\d+$") {
                $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
                if ($proc) { $workerCount++ }
            }
        }
    }

    # Display
    if ($backendOk)  { Write-OK "Backend API" } else { Write-WARN "Backend API (starting...)" }
    if ($frontendOk) { Write-OK "Frontend"    } else { Write-WARN "Frontend (starting...)"    }
    if ($beatOk)     { Write-OK "Celery Beat" } else { Write-WARN "Celery Beat (starting...)" }

    $workerStatus = "Workers: $workerCount / 12 alive"
    if ($workerCount -ge $minWorkers) {
        Write-OK $workerStatus
    } else {
        Write-WARN $workerStatus
    }

    if ($backendOk -and $frontendOk -and $beatOk -and ($workerCount -ge $minWorkers)) {
        $success = $true
        break
    }

    Start-Sleep -Seconds 5
}

# ==========================================================================
# FINAL STATUS
# ==========================================================================
Write-Host ""
Write-Host "================================================" -ForegroundColor White

if ($success) {
    Write-Host "  SYSTEM STATUS: ONLINE" -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor White
    Write-Host ""
    Write-Host "  Dashboard  -> http://localhost:3000" -ForegroundColor Cyan
    Write-Host "  API Docs   -> http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host "  Health     -> http://localhost:8000/health" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Opening dashboard in Microsoft Edge..." -ForegroundColor Yellow
    try {
        Start-Process "msedge" "http://localhost:3000"
    } catch {
        Start-Process "http://localhost:3000"
    }
} else {
    Write-Host "  SYSTEM STATUS: PARTIAL - Some services still starting" -ForegroundColor Yellow
    Write-Host "================================================" -ForegroundColor White
    Write-Host ""
    Write-Host "  Run .\status.ps1 to check current state" -ForegroundColor Yellow
    Write-Host "  Check logs\ folder for error details" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Log files:" -ForegroundColor DarkGray
    Write-Host "    logs\backend.stdout.log" -ForegroundColor DarkGray
    Write-Host "    logs\worker_linkedin.stdout.log" -ForegroundColor DarkGray
    Write-Host "    logs\recovery.log" -ForegroundColor DarkGray
}
Write-Host ""
