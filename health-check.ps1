# AutoApply AI - Platform Health Monitor
Set-StrictMode -Version Latest

# Helper: Test if a local TCP port is reachable
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

# Check Backend
$backendStatus = "OFFLINE"
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/docs" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($resp.StatusCode -eq 200) { $backendStatus = "ONLINE" }
} catch {}

# Check Frontend
$frontendStatus = "OFFLINE"
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($resp.StatusCode -eq 200) { $frontendStatus = "ONLINE" }
} catch {}

# Check Redis Port
$redisPortOk = Test-LocalPort 6379
$redisStatus = if ($redisPortOk) { "ONLINE" } else { "OFFLINE" }

# Check Postgres Port
$postgresPortOk = Test-LocalPort 5432
$postgresStatus = if ($postgresPortOk) { "ONLINE" } else { "OFFLINE" }

# Check Beat Process Status
$beatStatus = "OFFLINE"
$beatPidFile = "$Root\pids\beat.pid"
if (-not (Test-Path $beatPidFile)) {
    $beatPidFile = "$Root\logs\beat.pid"
}
if (Test-Path $beatPidFile) {
    $targetPidRaw = Get-Content -Path $beatPidFile -Raw -ErrorAction SilentlyContinue
    if ($targetPidRaw -and $targetPidRaw.Trim() -match '^\d+$') {
        $proc = Get-Process -Id ([int]($targetPidRaw.Trim())) -ErrorAction SilentlyContinue
        if ($proc) { $beatStatus = "ONLINE" }
    }
}

# Default metrics values
$dbJobs = 0
$dbApps = 0
$dbSubmitted = 0
$dbPending = 0

$workerDiscovery = "OFFLINE"
$workerOrchestrate = "OFFLINE"
$workerApplications = "OFFLINE"
$workerSheets = "OFFLINE"
$workerEmail = "OFFLINE"

$qDiscovery = 0
$qOrchestrate = 0
$qApplications = 0
$qSheets = 0
$qEmail = 0

# Run python platform_health.py to retrieve live metrics
Push-Location "$Root\backend"
try {
    $output = & ".\venv\Scripts\python.exe" platform_health.py 2>$null
    if ($output) {
        $outputString = $output -join "`n"
        $jsonStart = $outputString.IndexOf('{')
        if ($jsonStart -ge 0) {
            $jsonStr = $outputString.Substring($jsonStart)
            $data = ConvertFrom-Json $jsonStr
            
            if ($data.db) {
                $dbJobs = $data.db.total_jobs
                $dbApps = $data.db.total_applications
                $dbSubmitted = $data.db.submitted_count
                $dbPending = $data.db.pending_count
            }
            if ($data.workers) {
                $workerDiscovery = $data.workers.discovery
                $workerOrchestrate = $data.workers.orchestrate
                $workerApplications = $data.workers.applications
                $workerSheets = $data.workers.sheets
                $workerEmail = $data.workers.email
            }
            if ($data.redis -and $data.redis.queue_sizes) {
                $qDiscovery = $data.redis.queue_sizes.discovery
                $qOrchestrate = $data.redis.queue_sizes.orchestrate
                $qApplications = $data.redis.queue_sizes.applications
                $qSheets = $data.redis.queue_sizes.sheets
                $qEmail = $data.redis.queue_sizes.email
            }
        }
    }
} catch {}
finally {
    Pop-Location
}

# Print exact output format requested by user
Write-Host "Backend: $backendStatus"
Write-Host "Frontend: $frontendStatus"
Write-Host "Redis: $redisStatus"
Write-Host "Postgres: $postgresStatus"
Write-Host "Beat: $beatStatus"
Write-Host ""
Write-Host "Workers:"
Write-Host "  * discovery: $workerDiscovery"
Write-Host "  * orchestrate: $workerOrchestrate"
Write-Host "  * applications: $workerApplications"
Write-Host "  * sheets: $workerSheets"
Write-Host "  * email: $workerEmail"
Write-Host ""
Write-Host "Queue sizes:"
Write-Host "  * discovery: $qDiscovery"
Write-Host "  * orchestrate: $qOrchestrate"
Write-Host "  * applications: $qApplications"
Write-Host "  * sheets: $qSheets"
Write-Host "  * email: $qEmail"
Write-Host ""
Write-Host "Total jobs discovered: $dbJobs"
Write-Host "Total applications: $dbApps"
Write-Host "Submitted count: $dbSubmitted"
Write-Host "Pending count: $dbPending"
