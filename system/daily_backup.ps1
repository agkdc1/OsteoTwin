#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Register/unregister a daily backup scheduled task for OsteoTwin.
.USAGE
    .\daily_backup.ps1 install     # Create daily 2 AM backup task
    .\daily_backup.ps1 uninstall   # Remove the scheduled task
    .\daily_backup.ps1 status      # Check task status
    .\daily_backup.ps1 run         # Run backup now (manual trigger)
#>

param(
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("install", "uninstall", "status", "run")]
    [string]$Action
)

$ErrorActionPreference = "Continue"

$TaskName = "OsteoTwin-DailyBackup"
$ProjectRoot = "C:\Users\ahnch\Documents\OsteoTwin"
$BackupScript = "$ProjectRoot\system\backup.sh"
$LogDir = "$ProjectRoot\logs"
$BashExe = "C:\Program Files\Git\bin\bash.exe"

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Do-Install {
    # Check if bash is available
    if (-not (Test-Path $BashExe)) {
        # Try to find bash in PATH
        $bashCmd = Get-Command bash -ErrorAction SilentlyContinue
        if ($bashCmd) {
            $script:BashExe = $bashCmd.Source
        } else {
            Write-Error "Git Bash not found. Install Git for Windows first."
            exit 1
        }
    }

    # Remove existing task if present
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Warning "Task '$TaskName' already exists. Removing and reinstalling."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    # Create the action: run backup.sh via bash
    $action = New-ScheduledTaskAction `
        -Execute $BashExe `
        -Argument "-c 'cd /c/Users/ahnch/Documents/OsteoTwin && source .venv/Scripts/activate && bash system/backup.sh daily-$(date +%Y%m%d) >> logs/backup.log 2>&1'" `
        -WorkingDirectory $ProjectRoot

    # Trigger: daily at 2:00 AM
    $trigger = New-ScheduledTaskTrigger -Daily -At "2:00AM"

    # Settings
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -RestartCount 2 `
        -RestartInterval (New-TimeSpan -Minutes 10)

    # Register the task (runs as SYSTEM so it works even if not logged in)
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "OsteoTwin daily backup to GCS (DB, cases, mesh cache)" `
        -User "SYSTEM" `
        -RunLevel Highest

    Write-Host "Scheduled task '$TaskName' installed." -ForegroundColor Green
    Write-Host "  Schedule  : Daily at 2:00 AM"
    Write-Host "  Script    : $BackupScript"
    Write-Host "  Log       : $LogDir\backup.log"
    Write-Host "  Runs as   : SYSTEM"
    Write-Host ""
    Write-Host "Test with: .\daily_backup.ps1 run" -ForegroundColor DarkGray
}

function Do-Uninstall {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Scheduled task '$TaskName' removed." -ForegroundColor Green
    } else {
        Write-Warning "Task '$TaskName' is not installed."
    }
}

function Do-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Task '$TaskName': NOT INSTALLED" -ForegroundColor Red
        return
    }

    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    $state = $task.State

    $color = switch ($state) {
        "Ready"   { "Green" }
        "Running" { "Cyan" }
        default   { "Yellow" }
    }

    Write-Host "`nOsteoTwin Daily Backup" -ForegroundColor Cyan
    Write-Host ("-" * 40)
    Write-Host ("  Status       : {0}" -f $state) -ForegroundColor $color
    Write-Host ("  Last Run     : {0}" -f $info.LastRunTime)
    Write-Host ("  Last Result  : {0}" -f $info.LastTaskResult)
    Write-Host ("  Next Run     : {0}" -f $info.NextRunTime)

    # Show backup log tail
    $logFile = "$LogDir\backup.log"
    if (Test-Path $logFile) {
        $size = [math]::Round((Get-Item $logFile).Length / 1KB, 1)
        Write-Host ("  Log File     : {0} ({1} KB)" -f $logFile, $size)
        Write-Host "`n  Last 5 log lines:" -ForegroundColor DarkGray
        Get-Content $logFile -Tail 5 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    Write-Host ""
}

function Do-Run {
    Write-Host "Running backup now..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

    if ($LASTEXITCODE -ne 0 -and -not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
        # Task not installed — run directly
        Write-Host "Task not installed. Running backup script directly..." -ForegroundColor Yellow
        & $BashExe -c "cd /c/Users/ahnch/Documents/OsteoTwin && source .venv/Scripts/activate && bash system/backup.sh manual-$(date +%Y%m%d-%H%M%S)"
    } else {
        Write-Host "Backup task triggered. Check status with: .\daily_backup.ps1 status" -ForegroundColor Green
    }
}

# Dispatch
switch ($Action) {
    "install"   { Do-Install }
    "uninstall" { Do-Uninstall }
    "status"    { Do-Status }
    "run"       { Do-Run }
}
