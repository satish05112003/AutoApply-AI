param (
    [string]$Name,
    [string]$Label,
    [string]$Cwd,
    [string]$RunCmd,
    [string]$EnvVarsJson = "{}",
    [string]$EnvVarsJsonBase64 = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$pidFile   = Join-Path $Root "pids\$Name.pid"
$wrapperLog = Join-Path $Root "logs\$Name.wrapper.log"

try {
    # Set window title
    try { $host.UI.RawUI.WindowTitle = "AutoApply AI - $Label" } catch {}

    # Ensure directories exist
    foreach ($dir in @("$Root\pids","$Root\logs")) {
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    }

    # Save wrapper PID so supervisor can check liveness
    $PID | Out-File -FilePath $pidFile -Encoding utf8

    # ---------- Environment Variables ----------
    $json = $EnvVarsJson
    if ($EnvVarsJsonBase64 -and $EnvVarsJsonBase64.Trim() -ne "" `
            -and $EnvVarsJsonBase64 -ne '""' -and $EnvVarsJsonBase64 -ne "''") {
        $bytes = [Convert]::FromBase64String($EnvVarsJsonBase64.Trim())
        $json  = [System.Text.Encoding]::UTF8.GetString($bytes)
    }
    $EnvVars = ConvertFrom-Json $json
    if ($EnvVars -ne $null) {
        foreach ($prop in $EnvVars.psobject.properties) {
            [System.Environment]::SetEnvironmentVariable($prop.Name, $prop.Value, "Process")
        }
    }

    # ---------- Parse RunCmd into Executable + Args ----------
    # RunCmd can be: `"C:\...\python.exe" -u start.py`  OR  `npm run dev -- -p 3000`
    # Strategy: if it starts with a quoted path, extract it; otherwise first token is the exe.
    $exePath = $null
    $exeArgs = @()

    if ($RunCmd.TrimStart().StartsWith('"')) {
        # Quoted executable path
        $closingQuote = $RunCmd.IndexOf('"', 1)
        if ($closingQuote -gt 1) {
            $exePath = $RunCmd.Substring(1, $closingQuote - 1)
            $rest    = $RunCmd.Substring($closingQuote + 1).Trim()
            if ($rest -ne "") {
                # Split remaining args respecting quotes
                $exeArgs = $rest -split '\s+(?=(?:[^"]*"[^"]*")*[^"]*$)' | Where-Object { $_ -ne "" }
            }
        }
    } else {
        # Unquoted: split on whitespace; first token is the command
        $parts   = $RunCmd -split '\s+' | Where-Object { $_ -ne "" }
        $exePath = $parts[0]
        if ($parts.Count -gt 1) { $exeArgs = $parts[1..($parts.Count-1)] }
    }

    if (-not $exePath) {
        throw "Could not parse executable from RunCmd: $RunCmd"
    }

    $dateStr = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "[$dateStr] Starting supervision for '$Label' | exe='$exePath' args=$($exeArgs -join ' ')" |
        Out-File -FilePath $wrapperLog -Append -Encoding utf8

    # ---------- Supervisor Restart Loop ----------
    while ($true) {
        if (Test-Path "$Root\runtime\stop.signal") { break }

        $dateStr = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        "[$dateStr] Launching: $exePath $($exeArgs -join ' ')" |
            Out-File -FilePath $wrapperLog -Append -Encoding utf8

        try {
            $stdoutLog = Join-Path $Root "logs\$Name.stdout.log"
            $stderrLog = Join-Path $Root "logs\$Name.stderr.log"

            if ($exeArgs.Count -gt 0) {
                $proc = Start-Process -FilePath $exePath -ArgumentList $exeArgs `
                            -WorkingDirectory $Cwd -PassThru -NoNewWindow `
                            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
            } else {
                $proc = Start-Process -FilePath $exePath `
                            -WorkingDirectory $Cwd -PassThru -NoNewWindow `
                            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
            }

            # Write child PID
            $proc.Id | Out-File -FilePath "$Root\pids\$Name`_child.pid" -Encoding utf8

            $proc.WaitForExit()
            $exitCode = $proc.ExitCode
        } catch {
            $exitCode = -1
            "[$dateStr] Launch error: $_" | Out-File -FilePath $wrapperLog -Append -Encoding utf8
        }

        Remove-Item "$Root\pids\$Name`_child.pid" -ErrorAction SilentlyContinue

        if (Test-Path "$Root\runtime\stop.signal") { break }

        $date = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $msg  = "[$date] $Label exited (code $exitCode). Auto-restarting in 3s..."
        $msg | Out-File -FilePath $wrapperLog -Append -Encoding utf8
        Add-Content -Path "$Root\logs\recovery.log" -Value $msg -Encoding utf8

        Start-Sleep -Seconds 3
    }

} catch {
    $date = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "[$date] FATAL ERROR in run-service.ps1 for '$Label': $_`n$($_.ScriptStackTrace)" |
        Add-Content -Path "$Root\logs\recovery.log" -Encoding utf8
} finally {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Remove-Item "$Root\pids\$Name`_child.pid" -ErrorAction SilentlyContinue
}
