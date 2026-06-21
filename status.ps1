# AutoApply AI - System Status Monitor
# PowerShell 5.1 compatible. ASCII-safe output only.
# Usage: .\status.ps1

$ErrorActionPreference = "SilentlyContinue"

function Test-Port {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $ar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne(600, $false)
        try { $client.Close() } catch {}
        return $ok
    } catch {
        return $false
    }
}

function Write-Row {
    param([string]$Label, [bool]$Ok, [string]$Detail)
    $padded = $Label.PadRight(28)
    if ($Ok) {
        Write-Host "  [OK]   $padded $Detail" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $padded $Detail" -ForegroundColor Red
    }
}

function Get-PidAlive {
    param(
        [string]$PidFile,
        [string]$ExpectedProcessName
    )
    if (-not (Test-Path $PidFile)) { return $false }
    $raw = Get-Content $PidFile -Raw -ErrorAction SilentlyContinue
    if ($null -eq $raw) { return $false }
    $raw = $raw.Trim()
    if ($raw -notmatch "^\d+$") { return $false }
    $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    if ($proc.HasExited) { return $false }
    if ($ExpectedProcessName) {
        if ($proc.ProcessName -notlike "*$ExpectedProcessName*") { return $false }
    }
    return $true
}

$Root    = $PSScriptRoot
$PidsDir = Join-Path $Root "pids"

Clear-Host
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "       AutoApply AI - System Status             " -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')                        " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Infrastructure -------------------------------------------------------
Write-Host "INFRASTRUCTURE" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray
Write-Row "PostgreSQL (5432)"  (Test-Port 5432)  ""
Write-Row "Redis (6379)"       (Test-Port 6379)  ""
Write-Row "Qdrant (6333)"      (Test-Port 6333)  "(optional)"
Write-Host ""

# ---- Application services -------------------------------------------------
Write-Host "SERVICES" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray

$backendOk = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($r.StatusCode -eq 200) { $backendOk = $true }
} catch {}
Write-Row "Backend API" $backendOk "http://localhost:8000"

$frontendOk = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($r.StatusCode -eq 200) { $frontendOk = $true }
} catch {}
Write-Row "Frontend" $frontendOk "http://localhost:3000"
Write-Host ""

# ---- Celery processes -----------------------------------------------------
Write-Host "CELERY WORKERS" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray

$processes = @(
    @{ Name="beat";              Label="Celery Beat";         Queue="scheduler"    },
    @{ Name="worker_discovery";  Label="Discovery Worker";    Queue="discovery"    },
    @{ Name="worker_orchestrate";Label="Orchestrate Worker";  Queue="orchestrate"  },
    @{ Name="worker_applications";Label="Generic App Worker"; Queue="applications" },
    @{ Name="worker_linkedin";   Label="LinkedIn Worker";     Queue="linkedin"     },
    @{ Name="worker_indeed";     Label="Indeed Worker";       Queue="indeed"       },
    @{ Name="worker_naukri";     Label="Naukri Worker";       Queue="naukri"       },
    @{ Name="worker_unstop";     Label="Unstop Worker";       Queue="unstop"       },
    @{ Name="worker_ats";        Label="ATS Worker";          Queue="ats"          },
    @{ Name="worker_workday";    Label="Workday Worker";      Queue="workday"      },
    @{ Name="worker_portal";     Label="Portal Worker";       Queue="portal"       },
    @{ Name="worker_sheets";     Label="Sheets Worker";       Queue="sheets"       },
    @{ Name="worker_email";      Label="Email Worker";        Queue="email"        }
)

$onlineCount = 0
foreach ($p in $processes) {
    $pName = $p.Name
    $alive = $false

    # Check if a child PID file exists
    $childPidFile = Join-Path $PidsDir "${pName}_child.pid"
    if (Test-Path $childPidFile) {
        $expectedName = "python"
        if ($pName -eq "frontend") { $expectedName = "node" }
        $alive = Get-PidAlive -PidFile $childPidFile -ExpectedProcessName $expectedName
    }

    # Fallback to checking the wrapper process if no child check was active/successful
    if (-not $alive) {
        $pidFile = Join-Path $PidsDir "$pName.pid"
        $expectedWrapper = "powershell"
        if ($pName -eq "frontend") { $expectedWrapper = "powershell" }
        $alive = Get-PidAlive -PidFile $pidFile -ExpectedProcessName $expectedWrapper
    }

    if ($alive) { $onlineCount++ }
    Write-Row $p.Label $alive "queue: $($p.Queue)"
}
Write-Host ""

# ---- Supervisor -----------------------------------------------------------
Write-Host "SUPERVISOR" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray
$supAlive = Get-PidAlive -PidFile (Join-Path $PidsDir "supervisor.pid") -ExpectedProcessName "powershell"
Write-Row "Supervisor Daemon" $supAlive "auto-restart daemon"
Write-Host ""

# ---- Summary --------------------------------------------------------------
$total      = $processes.Count
$allOk      = ($backendOk -and $frontendOk -and ($onlineCount -ge ($total - 2)))
$workerLine = "Workers Online: $onlineCount / $total"

Write-Host "SUMMARY" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor DarkGray
if ($onlineCount -ge ($total - 2)) {
    Write-Host "  [OK]   $workerLine" -ForegroundColor Green
} else {
    Write-Host "  [WARN] $workerLine" -ForegroundColor Yellow
}
Write-Host ""

if ($allOk) {
    Write-Host "================================================" -ForegroundColor Green
    Write-Host "  SYSTEM STATUS: ONLINE                         " -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Green
} else {
    Write-Host "================================================" -ForegroundColor Yellow
    Write-Host "  SYSTEM STATUS: PARTIAL                        " -ForegroundColor Yellow
    Write-Host "  Run .\start-all.ps1 to start all services     " -ForegroundColor Yellow
    Write-Host "  Check logs\ for details                       " -ForegroundColor Yellow
    Write-Host "================================================" -ForegroundColor Yellow
}
Write-Host ""
