@echo off
REM OsteoTwin Daily Backup — called by Windows Task Scheduler
REM Runs backup.sh via Git Bash and logs output

set PROJECT_ROOT=C:\Users\ahnch\Documents\OsteoTwin
set BASH_EXE=C:\Program Files\Git\bin\bash.exe
set LOG_FILE=%PROJECT_ROOT%\logs\backup.log

if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"

echo ========================================== >> "%LOG_FILE%"
echo Backup started: %DATE% %TIME% >> "%LOG_FILE%"
echo ========================================== >> "%LOG_FILE%"

"%BASH_EXE%" -c "cd /c/Users/ahnch/Documents/OsteoTwin && source .venv/Scripts/activate && bash system/backup.sh daily-$(date +%%Y%%m%%d)" >> "%LOG_FILE%" 2>&1

echo Backup finished: %DATE% %TIME% >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
