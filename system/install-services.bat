@echo off
:: OsteoTwin Service Installer — auto-elevates to Admin
:: Double-click this file or run from cmd

:: Check for admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: We are elevated
echo ============================================
echo  OsteoTwin Service Installer
echo ============================================
echo.

set NSSM=C:\Users\ahnch\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win64\nssm.exe
set PYTHON=C:\Users\ahnch\Documents\OsteoTwin\.venv\Scripts\python.exe
set ROOT=C:\Users\ahnch\Documents\OsteoTwin
set LOGDIR=%ROOT%\logs

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [1/6] Installing OsteoTwin-Planning...
"%NSSM%" install OsteoTwin-Planning "%PYTHON%"
"%NSSM%" set OsteoTwin-Planning AppParameters "-m uvicorn planning_server.app.main:app --host 0.0.0.0 --port 8200"
"%NSSM%" set OsteoTwin-Planning AppDirectory "%ROOT%"
"%NSSM%" set OsteoTwin-Planning DisplayName "OsteoTwin Planning Server"
"%NSSM%" set OsteoTwin-Planning Description "OsteoTwin Planning Server (FastAPI, port 8200)"
"%NSSM%" set OsteoTwin-Planning Start SERVICE_AUTO_START
"%NSSM%" set OsteoTwin-Planning AppStdout "%LOGDIR%\planning_stdout.log"
"%NSSM%" set OsteoTwin-Planning AppStderr "%LOGDIR%\planning_stderr.log"
"%NSSM%" set OsteoTwin-Planning AppStdoutCreationDisposition 4
"%NSSM%" set OsteoTwin-Planning AppStderrCreationDisposition 4
"%NSSM%" set OsteoTwin-Planning AppRotateFiles 1
"%NSSM%" set OsteoTwin-Planning AppRotateOnline 1
"%NSSM%" set OsteoTwin-Planning AppRotateBytes 10485760
echo    Done.

echo [2/6] Installing OsteoTwin-Simulation...
"%NSSM%" install OsteoTwin-Simulation "%PYTHON%"
"%NSSM%" set OsteoTwin-Simulation AppParameters "-m uvicorn simulation_server.app.main:app --host 0.0.0.0 --port 8300"
"%NSSM%" set OsteoTwin-Simulation AppDirectory "%ROOT%"
"%NSSM%" set OsteoTwin-Simulation DisplayName "OsteoTwin Simulation Server"
"%NSSM%" set OsteoTwin-Simulation Description "OsteoTwin Simulation Server (FastAPI, port 8300)"
"%NSSM%" set OsteoTwin-Simulation Start SERVICE_AUTO_START
"%NSSM%" set OsteoTwin-Simulation AppStdout "%LOGDIR%\simulation_stdout.log"
"%NSSM%" set OsteoTwin-Simulation AppStderr "%LOGDIR%\simulation_stderr.log"
"%NSSM%" set OsteoTwin-Simulation AppStdoutCreationDisposition 4
"%NSSM%" set OsteoTwin-Simulation AppStderrCreationDisposition 4
"%NSSM%" set OsteoTwin-Simulation AppRotateFiles 1
"%NSSM%" set OsteoTwin-Simulation AppRotateOnline 1
"%NSSM%" set OsteoTwin-Simulation AppRotateBytes 10485760
echo    Done.

echo [3/6] Starting OsteoTwin-Simulation...
"%NSSM%" start OsteoTwin-Simulation
echo [4/6] Waiting 3 seconds for Simulation Server...
timeout /t 3 /nobreak >nul

echo [5/6] Starting OsteoTwin-Planning...
"%NSSM%" start OsteoTwin-Planning
echo [6/6] Waiting 3 seconds for Planning Server...
timeout /t 3 /nobreak >nul

echo.
echo ============================================
echo  Service Status:
echo ============================================
"%NSSM%" status OsteoTwin-Planning
"%NSSM%" status OsteoTwin-Simulation
echo.
echo Services installed and started.
echo Planning Server: http://localhost:8200
echo Simulation Server: http://localhost:8300
echo.
pause
