# AutoApply AI - Platform Launcher
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Helper: Test if a local TCP port is reachable (IPv4 check)
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

$Root = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       AutoApply AI Launcher System       " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verify Postgres & Redis are reachable
Write-Host "[1/5] Checking Postgres (5432)..." -ForegroundColor Yellow
if (-not (Test-LocalPort 5432)) {
    Write-Host "  [ERROR] PostgreSQL is NOT running on port 5432." -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] PostgreSQL is reachable." -ForegroundColor Green

Write-Host "[2/5] Checking Redis (6379)..." -ForegroundColor Yellow
if (-not (Test-LocalPort 6379)) {
    Write-Host "  [ERROR] Redis is NOT running on port 6379." -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Redis is reachable." -ForegroundColor Green

# 2. Setup directory structure
Write-Host "[3/5] Setting up directories..." -ForegroundColor Yellow
foreach ($dirName in @("logs", "runtime", "pids")) {
    $dirPath = Join-Path $Root $dirName
    if (-not (Test-Path $dirPath)) {
        New-Item -ItemType Directory -Path $dirPath | Out-Null
    }
}
# Clear stop signal if left over
Remove-Item "$Root\runtime\stop.signal" -ErrorAction SilentlyContinue
Write-Host "  [OK] logs/, runtime/, pids/ folders ready." -ForegroundColor Green

# 3. Stop any prior running platform processes
Write-Host "[4/5] Stopping any stale services..." -ForegroundColor Yellow
& (Join-Path $Root "stop-all.ps1")
Write-Host "  [OK] Stale processes cleared." -ForegroundColor Green

# 4. Generate frontend environment (.env.local)
Write-Host "[5/5] Writing frontend environment (.env.local)..." -ForegroundColor Yellow
$EnvFile = Join-Path $FrontendDir ".env.local"
$EnvContent = @(
    "NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1",
    "NEXT_PUBLIC_WS_URL=ws://localhost:8000"
)
[System.IO.File]::WriteAllLines($EnvFile, $EnvContent, [System.Text.UTF8Encoding]::new($false))
Write-Host "  [OK] Written: $EnvFile" -ForegroundColor Green

# 5. Launch supervisor daemon in hidden background window
Write-Host "Spawning supervisor process..." -ForegroundColor Yellow
$supervisorPath = Join-Path $Root "supervisor.ps1"
Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy", "Bypass", "-File", $supervisorPath -WindowStyle Hidden

Write-Host "Supervisor spawned. Verifying platform startup..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

$success = $false
for ($attempt = 1; $attempt -le 15; $attempt++) {
    Write-Host "Validating system status (Attempt $attempt/15)..." -ForegroundColor Yellow
    
    $backendOnline = $false
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $backendOnline = $true }
    } catch {}
    
    $frontendOnline = $false
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $frontendOnline = $true }
    } catch {}
    
    $redisOnline = $false
    $dbOnline = $false
    $workersOnlineCount = 0
    $beatOnline = $false
    
    # Celery Beat PID check
    $beatPidFile = "$Root\pids\beat.pid"
    if (Test-Path $beatPidFile) {
        $targetPidRaw = Get-Content -Path $beatPidFile -Raw -ErrorAction SilentlyContinue
        if ($targetPidRaw -and $targetPidRaw.Trim() -match '^\d+$') {
            $proc = Get-Process -Id ([int]($targetPidRaw.Trim())) -ErrorAction SilentlyContinue
            if ($proc) { $beatOnline = $true }
        }
    }
    
    # Retrieve metrics from platform_health.py
    Push-Location "$Root\backend"
    try {
        $output = & ".\venv\Scripts\python.exe" platform_health.py 2>$null
        if ($output) {
            $outputString = $output -join "`n"
            $jsonStart = $outputString.IndexOf('{')
            if ($jsonStart -ge 0) {
                $jsonStr = $outputString.Substring($jsonStart)
                $data = ConvertFrom-Json $jsonStr
                
                if ($data.redis -and $data.redis.redis_online -eq "ONLINE") {
                    $redisOnline = $true
                }
                if ($data.db -and -not $data.db.error) {
                    $dbOnline = $true
                }
                if ($data.workers) {
                    $onlineWorkers = @()
                    foreach ($w in $data.workers.psobject.properties) {
                        if ($w.Value -eq "ONLINE") {
                            $onlineWorkers += $w.Name
                        }
                    }
                    $workersOnlineCount = $onlineWorkers.Count
                }
            }
        }
    } catch {}
    finally {
        Pop-Location
    }
    
    Write-Host "  * Backend: " -NoNewline
    if ($backendOnline) { Write-Host "ONLINE" -ForegroundColor Green } else { Write-Host "OFFLINE" -ForegroundColor Red }
    
    Write-Host "  * Frontend: " -NoNewline
    if ($frontendOnline) { Write-Host "ONLINE" -ForegroundColor Green } else { Write-Host "OFFLINE" -ForegroundColor Red }
    
    Write-Host "  * Redis: " -NoNewline
    if ($redisOnline) { Write-Host "ONLINE" -ForegroundColor Green } else { Write-Host "OFFLINE" -ForegroundColor Red }
    
    Write-Host "  * Database: " -NoNewline
    if ($dbOnline) { Write-Host "ONLINE" -ForegroundColor Green } else { Write-Host "OFFLINE" -ForegroundColor Red }
    
    Write-Host "  * Celery Beat: " -NoNewline
    if ($beatOnline) { Write-Host "ONLINE" -ForegroundColor Green } else { Write-Host "OFFLINE" -ForegroundColor Red }
    
    $workerColor = if ($workersOnlineCount -eq 5) { "Green" } else { "Yellow" }
    Write-Host "  * Workers Online: $workersOnlineCount/5" -ForegroundColor $workerColor
    
    if ($backendOnline -and $frontendOnline -and $redisOnline -and $dbOnline -and $beatOnline -and $workersOnlineCount -eq 5) {
        $success = $true
        break
    }
    
    Start-Sleep -Seconds 2
}

if ($success) {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host "  ALL SERVICES VALIDATED AND ONLINE!      " -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host ""
    
    Write-Host "Opening browser at http://localhost:3000..." -ForegroundColor Cyan
    Start-Process -FilePath "http://localhost:3000"
} else {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Red
    Write-Host "  WARNING: SOME SERVICES FAILED TO START! " -ForegroundColor Red
    Write-Host "  Please check logs under logs/           " -ForegroundColor Red
    Write-Host "==========================================" -ForegroundColor Red
    exit 1
}
