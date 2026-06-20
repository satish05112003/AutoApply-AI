Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$supervisorPidFile = Join-Path $Root "pids\supervisor.pid"

# Save supervisor PID
if (-not (Test-Path "$Root\pids")) {
    New-Item -ItemType Directory -Path "$Root\pids" | Out-Null
}
$PID | Out-File -FilePath $supervisorPidFile -Encoding utf8

$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"

# Helper function to start a wrapper process in hidden mode
function Start-ServiceWrapper {
    param (
        [string]$Name,
        [string]$Label,
        [string]$Cwd,
        [string]$RunCmd,
        [string]$EnvVarsJsonBase64 = ""
    )
    $pidFile = "$Root\pids\$Name.pid"
    
    # Check if already running
    if (Test-Path $pidFile) {
        $wPid = (Get-Content $pidFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($wPid -match '^\d+$') {
            $proc = Get-Process -Id ([int]$wPid) -ErrorAction SilentlyContinue
            if ($proc -and -not $proc.HasExited) {
                return
            }
        } elseif ($wPid -eq "LAUNCHING") {
            # If it's launching, check the age of the file to allow recovery if it got stuck
            $fileAge = (Get-Date) - (Get-Item $pidFile).LastWriteTime
            if ($fileAge.TotalSeconds -lt 10) {
                return
            }
        }
    }
    
    # Write placeholder to prevent race condition
    "LAUNCHING" | Out-File -FilePath $pidFile -Encoding utf8
    
    $runServicePath = Join-Path $Root "run-service.ps1"
    
    # Escape double quotes and dollar signs for the PowerShell command string parser
    $escapedName = $Name -replace '"', '`"' -replace '\$', '`$'
    $escapedLabel = $Label -replace '"', '`"' -replace '\$', '`$'
    $escapedCwd = $Cwd -replace '"', '`"' -replace '\$', '`$'
    $escapedRunCmd = $RunCmd -replace '"', '`"' -replace '\$', '`$'
    $escapedEnvVars = $EnvVarsJsonBase64 -replace '"', '`"' -replace '\$', '`$'
    
    $cmdString = "& `"$runServicePath`" -Name `"$escapedName`" -Label `"$escapedLabel`" -Cwd `"$escapedCwd`" -RunCmd `"$escapedRunCmd`" -EnvVarsJsonBase64 `"$escapedEnvVars`""
    
    # Base64 encode the command string using UTF-16LE (Unicode) for -EncodedCommand
    $bytes = [System.Text.Encoding]::Unicode.GetBytes($cmdString)
    $encoded = [Convert]::ToBase64String($bytes)
    
    # Spawn the run-service wrapper in a hidden PowerShell window using -EncodedCommand
    Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy", "Bypass", "-NoExit", "-EncodedCommand", $encoded -WindowStyle Hidden
}

# Base64 encode JSON helper
function Get-Base64Json {
    param ([string]$JsonStr)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($JsonStr)
    return [Convert]::ToBase64String($bytes)
}

# Setup env variables
$backendEnvJson = '{"BACKEND_PORT":"8000","FRONTEND_URL":"http://localhost:3000","BACKEND_RELOAD":"false"}'
$backendEnvBase64 = Get-Base64Json $backendEnvJson

$frontendEnvJson = '{"PORT":"3000"}'
$frontendEnvBase64 = Get-Base64Json $frontendEnvJson

$queues = @("discovery", "orchestrate", "applications", "sheets", "email")

# Log supervisor startup
$dateStr = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"[$dateStr] Supervisor daemon started (PID: $PID)." | Out-File -FilePath "$Root\logs\recovery.log" -Append -Encoding utf8

$checkCounter = 0

while ($true) {
    # Check for stop signal
    if (Test-Path "$Root\runtime\stop.signal") {
        $dateStr = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        "[$dateStr] Supervisor stopping due to stop signal." | Out-File -FilePath "$Root\logs\recovery.log" -Append -Encoding utf8
        break
    }
    
    # 1. Maintain running status of all wrappers
    # Backend - use full absolute path to venv Python to prevent system Python 3.13 resolution
    $pythonExe = "$BackendDir\venv\Scripts\python.exe"
    $celeryExe = "$BackendDir\venv\Scripts\celery.exe"
    Start-ServiceWrapper "backend" "FastAPI Backend" $BackendDir "`"$pythonExe`" -u start.py" $backendEnvBase64
    
    # Celery Beat
    Start-ServiceWrapper "beat" "Celery Beat" $BackendDir "`"$celeryExe`" -A app.celery_app.celery_app beat --loglevel=info"
    
    # Workers
    foreach ($q in $queues) {
        Start-ServiceWrapper "worker_$q" "Celery Worker ($q)" $BackendDir "`"$celeryExe`" -A app.celery_app.celery_app worker --loglevel=info -P solo -Q $q -n worker_$q@localhost"
    }
    
    # Frontend (Use cmd.exe /c because npm is a cmd/bat script on Windows, not a binary exe)
    Start-ServiceWrapper "frontend" "Next.js Frontend" $FrontendDir "cmd.exe /c npm run dev -- -p 3000" $frontendEnvBase64
    
    # 2. Every 30 seconds, perform worker self-healing health check
    $checkCounter++
    if ($checkCounter -ge 30) {
        $checkCounter = 0
        
        # Verify worker health using platform_health.py
        Push-Location $BackendDir
        try {
            $healthOutput = & "$pythonExe" platform_health.py 2>$null
            if ($healthOutput) {
                $healthString = $healthOutput -join "`n"
                $jsonStart = $healthString.IndexOf('{')
                if ($jsonStart -ge 0) {
                    $jsonStr = $healthString.Substring($jsonStart)
                    $healthData = ConvertFrom-Json $jsonStr
                    
                    if ($healthData.workers) {
                        foreach ($w in $healthData.workers.psobject.properties) {
                            if ($w.Value -eq "OFFLINE") {
                                $wName = $w.Name
                                $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Worker queue '$wName' detected OFFLINE by supervisor. Killing stale process and restarting..."
                                Add-Content -Path "$Root\logs\recovery.log" -Value $msg
                                
                                # Kill stale worker process tree (wrapper process)
                                $wPidFile = "$Root\pids\worker_$wName.pid"
                                if (Test-Path $wPidFile) {
                                    $oldPidRaw = Get-Content $wPidFile -Raw -ErrorAction SilentlyContinue
                                    if ($oldPidRaw -and $oldPidRaw.Trim() -match '^\d+$') {
                                        $oldPid = $oldPidRaw.Trim()
                                        try {
                                            taskkill /F /T /PID $oldPid 2>$null *> $null
                                        } catch {}
                                    }
                                    Remove-Item $wPidFile -ErrorAction SilentlyContinue
                                }
                                
                                # Kill child process tree (Celery process)
                                $wChildPidFile = "$Root\pids\worker_${wName}_child.pid"
                                if (Test-Path $wChildPidFile) {
                                    $childPidRaw = Get-Content $wChildPidFile -Raw -ErrorAction SilentlyContinue
                                    if ($childPidRaw -and $childPidRaw.Trim() -match '^\d+$') {
                                        $childPid = $childPidRaw.Trim()
                                        try {
                                            taskkill /F /T /PID $childPid 2>$null *> $null
                                        } catch {}
                                    }
                                    Remove-Item $wChildPidFile -ErrorAction SilentlyContinue
                                }

                                # Kill by command line pattern to catch any duplicate/orphaned worker processes
                                try {
                                    Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%worker_$wName%'" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
                                } catch {}
                                
                                # Force immediate restart with absolute path
                                Start-ServiceWrapper "worker_$wName" "Celery Worker ($wName)" $BackendDir "`"$celeryExe`" -A app.celery_app.celery_app worker --loglevel=info -P solo -Q $wName -n worker_$wName@localhost"
                            }
                        }
                    }
                }
            }
        } catch {
            Add-Content -Path "$Root\logs\recovery.log" -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Supervisor check failed: $_"
        } finally {
            Pop-Location
        }
    }
    
    Start-Sleep -Seconds 1
}

# Cleanup supervisor PID file on clean stop
Remove-Item $supervisorPidFile -ErrorAction SilentlyContinue
