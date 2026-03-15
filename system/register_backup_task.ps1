# Register daily backup task — run this script as Administrator
# Usage: Right-click PowerShell → Run as Admin → .\system\register_backup_task.ps1

$TaskName = "OsteoTwin-DailyBackup"
$BatFile = "C:\Users\ahnch\Documents\OsteoTwin\system\run_backup.bat"

# Remove if exists
schtasks /Delete /TN $TaskName /F 2>$null

# Create daily task at 2:00 AM
schtasks /Create /TN $TaskName /TR $BatFile /SC DAILY /ST 02:00 /RU SYSTEM /RL HIGHEST /F

if ($LASTEXITCODE -eq 0) {
    Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
    Write-Host "  Schedule : Daily at 2:00 AM"
    Write-Host "  Command  : $BatFile"
    Write-Host ""
    Write-Host "To test now: schtasks /Run /TN $TaskName" -ForegroundColor DarkGray
} else {
    Write-Host "Failed to register task. Are you running as Administrator?" -ForegroundColor Red
}
