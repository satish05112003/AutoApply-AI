# AutoApply AI - Production-Grade Local Development Startup Script (Windows)
# Checks PostgreSQL, Redis, Qdrant; runs migrations; picks free ports; launches dev servers.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─── Helper: Find next free TCP port ────────────────────────────────────────
function Get-FreePort {
    param ([int]$StartPort = 8000)
    $props = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties()
    $activePorts  = @()
    $activePorts += ($props.GetActiveTcpListeners()   | ForEach-Object { $_.Port })
    $activePorts += ($props.GetActiveTcpConnections() | ForEach-Object { $_.LocalEndPoint.Port })
    $port = $StartPort
    while ($port -le 65535) {
        if ($activePorts -notcontains $port) { return $port }
        $port++
    }
    throw "No available ports found starting from $StartPort."
}

# ─── Helper: Test if a local TCP port is reachable ──────────────────────────
function Test-LocalPort {
    param ([int]$Port, [int]$TimeoutMs = 500)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $ar     = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok     = $ar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        $client.Close()
        return $ok
    } catch { return $false }
}

# ─── Banner ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       AutoApply AI  --  Dev Launcher     " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$Root       = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir= Join-Path $Root "frontend"

# ─── 1. PostgreSQL check ─────────────────────────────────────────────────────
Write-Host "[1/7] Checking PostgreSQL (port 5432)..." -ForegroundColor Yellow
if (-not (Test-LocalPort 5432)) {
    Write-Host ""
    Write-Host "  [ERROR] PostgreSQL is NOT running on port 5432." -ForegroundColor Red
    Write-Host "  Fix: Open Services (services.msc) and start 'postgresql-x64-*'," -ForegroundColor Red
    Write-Host "       or run:  net start postgresql-x64-14" -ForegroundColor Red
    Write-Host ""
    exit 1
}
Write-Host "  [OK] PostgreSQL is reachable." -ForegroundColor Green

# ─── 2. Redis check (optional — warn, don't abort) ──────────────────────────
Write-Host "[2/7] Checking Redis (port 6379)..." -ForegroundColor Yellow
if (-not (Test-LocalPort 6379)) {
    Write-Host "  [WARN] Redis is NOT running on port 6379." -ForegroundColor DarkYellow
    Write-Host "         Background job queues will be disabled until Redis is started." -ForegroundColor DarkYellow
    Write-Host "         To start Redis inside WSL: wsl -e bash -c 'sudo service redis-server start'" -ForegroundColor DarkYellow
} else {
    Write-Host "  [OK] Redis is reachable." -ForegroundColor Green
}

# ─── 3. Qdrant check (optional — warn, don't abort) ─────────────────────────
Write-Host "[3/7] Checking Qdrant (port 6333)..." -ForegroundColor Yellow
if (-not (Test-LocalPort 6333)) {
    Write-Host "  [WARN] Qdrant is NOT running on port 6333." -ForegroundColor DarkYellow
    Write-Host "         Vector search will be degraded until Qdrant is started." -ForegroundColor DarkYellow
    Write-Host "         To start Qdrant inside WSL: wsl -e bash -c 'qdrant &'" -ForegroundColor DarkYellow
} else {
    Write-Host "  [OK] Qdrant is reachable." -ForegroundColor Green
}

# ─── 4. Run Alembic migrations ───────────────────────────────────────────────
Write-Host "[4/7] Running database migrations (alembic upgrade head)..." -ForegroundColor Yellow
$PythonExe = Join-Path $BackendDir "venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "  [ERROR] Virtual environment not found at: $PythonExe" -ForegroundColor Red
    Write-Host "  Fix: cd backend && python -m venv venv && venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}
Push-Location $BackendDir
try {
    & $PythonExe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] Alembic migration failed (exit code $LASTEXITCODE)." -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Migrations applied." -ForegroundColor Green
} finally {
    Pop-Location
}

# ─── 5. Discover free ports ──────────────────────────────────────────────────
Write-Host "[5/7] Scanning for available ports..." -ForegroundColor Yellow
$BackendPort  = Get-FreePort -StartPort 8000
$FrontendPort = Get-FreePort -StartPort 3000
Write-Host "  Backend  port: $BackendPort" -ForegroundColor Green
Write-Host "  Frontend port: $FrontendPort" -ForegroundColor Green

# ─── 6. Write .env.local (BOM-free, deduplicated) ────────────────────────────
Write-Host "[6/7] Writing frontend environment (.env.local)..." -ForegroundColor Yellow
$EnvFile    = Join-Path $FrontendDir ".env.local"
$EnvContent = @(
    "NEXT_PUBLIC_API_URL=http://localhost:$BackendPort/api/v1",
    "NEXT_PUBLIC_WS_URL=ws://localhost:$BackendPort"
)
# Use .NET WriteAllLines to guarantee UTF-8 WITHOUT BOM
[System.IO.File]::WriteAllLines($EnvFile, $EnvContent, [System.Text.UTF8Encoding]::new($false))
Write-Host "  [OK] Written: $EnvFile" -ForegroundColor Green

# ─── 7. Launch backend & frontend ────────────────────────────────────────────
Write-Host "[7/7] Launching dev servers..." -ForegroundColor Yellow

# Backend: spawn in its own terminal window
$BackendCmd = "cd '$BackendDir'; `$env:BACKEND_PORT=$BackendPort; `$env:FRONTEND_URL='http://localhost:$FrontendPort'; .\venv\Scripts\python start.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $BackendCmd -WindowStyle Normal

# Celery Worker: spawn in its own terminal window
$WorkerCmd = "cd '$BackendDir'; .\venv\Scripts\celery -A app.celery_app.celery_app worker --loglevel=info -P solo"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $WorkerCmd -WindowStyle Normal

# Celery Beat: spawn in its own terminal window
$BeatCmd = "cd '$BackendDir'; .\venv\Scripts\celery -A app.celery_app.celery_app beat --loglevel=info"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $BeatCmd -WindowStyle Normal

# Give backend a moment to bind the socket
Start-Sleep -Seconds 3

# Open browser
Write-Host ""
Write-Host "  Opening browser at: http://localhost:$FrontendPort" -ForegroundColor Cyan
Start-Process "http://localhost:$FrontendPort"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Backend  -> http://localhost:$BackendPort" -ForegroundColor Cyan
Write-Host "  Frontend -> http://localhost:$FrontendPort" -ForegroundColor Cyan
Write-Host "  API Docs -> http://localhost:$BackendPort/docs" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Frontend: run in this terminal (blocking)
Set-Location $FrontendDir
$env:PORT = $FrontendPort
npm run dev -- -p $FrontendPort
