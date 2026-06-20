# AutoApply AI - Service Status Check
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot

Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host "                    AutoApply AI Service Status Dashboard                  " -ForegroundColor Cyan
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host ""

$services = @(
    @{ Name = "supervisor"; Label = "Supervisor Daemon" },
    @{ Name = "backend"; Label = "FastAPI Backend" },
    @{ Name = "beat"; Label = "Celery Beat Scheduler" },
    @{ Name = "worker_discovery"; Label = "Discovery Worker" },
    @{ Name = "worker_orchestrate"; Label = "Orchestration Worker" },
    @{ Name = "worker_applications"; Label = "Applications Worker" },
    @{ Name = "worker_sheets"; Label = "Sheets Sync Worker" },
    @{ Name = "worker_email"; Label = "Email Monitor Worker" },
    @{ Name = "frontend"; Label = "Next.js Frontend" }
)

$statusData = @()

foreach ($s in $services) {
    $name = $s.Name
    $label = $s.Label
    
    $pidFile = Join-Path $Root "pids\$name.pid"
    $childPidFile = Join-Path $Root "pids\$name`_child.pid"
    
    $status = "OFFLINE"
    $pidStr = "-"
    $childPidStr = "-"
    $memoryStr = "-"
    $uptimeStr = "-"
    
    if (Test-Path $pidFile) {
        $targetPidRaw = Get-Content $pidFile -Raw -ErrorAction SilentlyContinue
        if ($targetPidRaw -and $targetPidRaw.Trim() -match '^\d+$') {
            $targetPid = $targetPidRaw.Trim()
            $pidStr = $targetPid
            $proc = Get-Process -Id ([int]$targetPid) -ErrorAction SilentlyContinue
            if ($proc -and -not $proc.HasExited) {
                $status = "ONLINE"
                
                # Fetch child PID if exists
                if (Test-Path $childPidFile) {
                    $cpidRaw = Get-Content $childPidFile -Raw -ErrorAction SilentlyContinue
                    if ($cpidRaw -and $cpidRaw.Trim() -match '^\d+$') {
                        $cpid = $cpidRaw.Trim()
                        $childPidStr = $cpid
                        # Query child process instead for memory and uptime if it's the actual service
                        $cproc = Get-Process -Id ([int]$cpid) -ErrorAction SilentlyContinue
                        if ($cproc -and -not $cproc.HasExited) {
                            $proc = $cproc
                        }
                    }
                }
                
                # Get Memory in MB
                $memMb = [Math]::Round($proc.WorkingSet64 / 1MB, 1)
                $memoryStr = "$memMb MB"
                
                # Get Uptime
                try {
                    $startTime = $proc.StartTime
                    $span = (Get-Date) - $startTime
                    if ($span.TotalHours -ge 1) {
                        $uptimeStr = "{0:N1} hrs" -f $span.TotalHours
                    } elseif ($span.TotalMinutes -ge 1) {
                        $uptimeStr = "{0:N0} mins" -f $span.TotalMinutes
                    } else {
                        $uptimeStr = "{0:N0} secs" -f $span.TotalSeconds
                    }
                } catch {
                    $uptimeStr = "Access Denied"
                }
            }
        }
    }
    
    $statusData += [PSCustomObject]@{
        "Service Label" = $label
        "Wrapper PID"   = $pidStr
        "Child PID"     = $childPidStr
        "Status"        = $status
        "Memory"        = $memoryStr
        "Uptime"        = $uptimeStr
    }
}

$statusData | Format-Table -AutoSize

Write-Host "==========================================================================" -ForegroundColor Cyan
