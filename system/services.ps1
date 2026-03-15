#Requires -RunAsAdministrator
<#
.SYNOPSIS
    OsteoTwin service manager — install/start/stop/restart Planning + Simulation servers as Windows services.
.USAGE
    .\services.ps1 install|uninstall|start|stop|restart|status|logs
#>

param(
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("install", "uninstall", "start", "stop", "restart", "status", "logs")]
    [string]$Action
)

$ErrorActionPreference = "Continue"

$ProjectRoot = "C:\Users\ahnch\Documents\OsteoTwin"
$VenvPython = "$ProjectRoot\.venv\Scripts\python.exe"
$LogDir = "$ProjectRoot\logs"
$EnvFile = "$ProjectRoot\.env"

$Services = @(
    @{
        Name        = "OsteoTwin-Planning"
        DisplayName = "OsteoTwin Planning Server"
        Description = "OsteoTwin Planning Server (FastAPI, port 8200)"
        Python      = $VenvPython
        Args        = "-m uvicorn planning_server.app.main:app --host 0.0.0.0 --port 8200"
        LogPrefix   = "planning"
    },
    @{
        Name        = "OsteoTwin-Simulation"
        DisplayName = "OsteoTwin Simulation Server"
        Description = "OsteoTwin Simulation Server (FastAPI, port 8300)"
        Python      = $VenvPython
        Args        = "-m uvicorn simulation_server.app.main:app --host 0.0.0.0 --port 8300"
        LogPrefix   = "simulation"
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Parse-EnvFile {
    if (-not (Test-Path $EnvFile)) {
        Write-Warning ".env file not found at $EnvFile"
        return @()
    }

    $envVars = @()
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        if ($trimmed -match '^([^=]+)=(.*)$') {
            $key = $Matches[1].Trim()
            $val = $Matches[2].Trim().Trim('"').Trim("'")
            $envVars += "$key=$val"
        }
    }
    return $envVars
}

$NssmExe = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe"

function Ensure-NssmAvailable {
    if (-not (Test-Path $NssmExe)) {
        if (Get-Command nssm -ErrorAction SilentlyContinue) {
            $script:NssmExe = (Get-Command nssm).Source
        } else {
            Write-Error "NSSM not found. Install it with: winget install nssm"
            exit 1
        }
    }
    Set-Alias -Name nssm -Value $NssmExe -Scope Script
}

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

function Do-Install {
    Ensure-NssmAvailable

    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        Write-Host "Created log directory: $LogDir"
    }

    $envVars = Parse-EnvFile

    foreach ($svc in $Services) {
        $name = $svc.Name

        $existing = nssm status $name 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Warning "Service '$name' is already installed (status: $existing). Skipping."
            continue
        }

        Write-Host "Installing service: $name ..." -ForegroundColor Cyan

        nssm install $name $svc.Python
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to install $name"; return }

        nssm set $name AppParameters $svc.Args
        nssm set $name AppDirectory $ProjectRoot
        nssm set $name DisplayName $svc.DisplayName
        nssm set $name Description $svc.Description

        # Auto-start on boot
        nssm set $name Start SERVICE_AUTO_START

        # Log files
        $stdoutLog = "$LogDir\$($svc.LogPrefix)_stdout.log"
        $stderrLog = "$LogDir\$($svc.LogPrefix)_stderr.log"
        nssm set $name AppStdout $stdoutLog
        nssm set $name AppStderr $stderrLog
        nssm set $name AppStdoutCreationDisposition 4
        nssm set $name AppStderrCreationDisposition 4

        # Log rotation: 10 MB
        nssm set $name AppRotateFiles 1
        nssm set $name AppRotateOnline 1
        nssm set $name AppRotateBytes 10485760

        # Environment variables
        if ($envVars.Count -gt 0) {
            nssm set $name AppEnvironmentExtra $envVars
        }

        Write-Host "  Installed $name" -ForegroundColor Green
        Write-Host "    Executable : $($svc.Python)"
        Write-Host "    Parameters : $($svc.Args)"
        Write-Host "    WorkDir    : $ProjectRoot"
        Write-Host "    Stdout log : $stdoutLog"
        Write-Host "    Stderr log : $stderrLog"
    }

    Write-Host "`nAll services installed. Run '.\services.ps1 start' to start them." -ForegroundColor Green
}

function Do-Uninstall {
    Ensure-NssmAvailable

    foreach ($svc in $Services) {
        $name = $svc.Name
        Write-Host "Stopping service: $name ..." -ForegroundColor Yellow
        nssm stop $name 2>&1 | Out-Null
        Write-Host "Removing service: $name ..." -ForegroundColor Cyan
        nssm remove $name confirm
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Removed $name" -ForegroundColor Green
        } else {
            Write-Warning "  Could not remove $name (may not be installed)."
        }
    }
    Write-Host "`nAll services removed." -ForegroundColor Green
}

function Do-Start {
    Ensure-NssmAvailable
    foreach ($svc in $Services) {
        $name = $svc.Name
        Write-Host "Starting service: $name ..." -ForegroundColor Cyan
        nssm start $name
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Started $name" -ForegroundColor Green
        } else {
            Write-Warning "  Failed to start $name. Check logs with: .\services.ps1 logs"
        }
    }
}

function Do-Stop {
    Ensure-NssmAvailable
    foreach ($svc in $Services) {
        $name = $svc.Name
        Write-Host "Stopping service: $name ..." -ForegroundColor Yellow
        nssm stop $name
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Stopped $name" -ForegroundColor Green
        } else {
            Write-Warning "  Failed to stop $name (may not be running)."
        }
    }
}

function Do-Restart {
    Ensure-NssmAvailable
    foreach ($svc in $Services) {
        $name = $svc.Name
        Write-Host "Restarting service: $name ..." -ForegroundColor Cyan
        nssm restart $name
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Restarted $name" -ForegroundColor Green
        } else {
            Write-Warning "  Failed to restart $name."
        }
    }
}

function Do-Status {
    Ensure-NssmAvailable

    Write-Host "`nOsteoTwin Service Status" -ForegroundColor Cyan
    Write-Host ("-" * 50)

    foreach ($svc in $Services) {
        $name = $svc.Name
        $status = nssm status $name 2>&1
        if ($LASTEXITCODE -ne 0) {
            $status = "NOT INSTALLED"
        }

        $color = switch ($status) {
            "SERVICE_RUNNING"  { "Green" }
            "SERVICE_STOPPED"  { "Yellow" }
            "SERVICE_PAUSED"   { "Yellow" }
            "NOT INSTALLED"    { "Red" }
            default            { "White" }
        }

        Write-Host ("  {0,-30} {1}" -f $name, $status) -ForegroundColor $color
    }
    Write-Host ""
}

function Do-Logs {
    Write-Host "`nOsteoTwin Log Files" -ForegroundColor Cyan
    Write-Host ("-" * 50)

    foreach ($svc in $Services) {
        $stdoutLog = "$LogDir\$($svc.LogPrefix)_stdout.log"
        $stderrLog = "$LogDir\$($svc.LogPrefix)_stderr.log"

        Write-Host "`n  $($svc.Name):" -ForegroundColor White

        if (Test-Path $stdoutLog) {
            $size = [math]::Round((Get-Item $stdoutLog).Length / 1KB, 1)
            Write-Host "    stdout: $stdoutLog ($size KB)"
        } else {
            Write-Host "    stdout: $stdoutLog (not yet created)" -ForegroundColor DarkGray
        }

        if (Test-Path $stderrLog) {
            $size = [math]::Round((Get-Item $stderrLog).Length / 1KB, 1)
            Write-Host "    stderr: $stderrLog ($size KB)"
        } else {
            Write-Host "    stderr: $stderrLog (not yet created)" -ForegroundColor DarkGray
        }
    }

    Write-Host "`nTip: To tail a log file in real time:" -ForegroundColor DarkGray
    Write-Host "  Get-Content '$LogDir\planning_stderr.log' -Wait -Tail 50" -ForegroundColor DarkGray
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

switch ($Action) {
    "install"   { Do-Install }
    "uninstall" { Do-Uninstall }
    "start"     { Do-Start }
    "stop"      { Do-Stop }
    "restart"   { Do-Restart }
    "status"    { Do-Status }
    "logs"      { Do-Logs }
}
