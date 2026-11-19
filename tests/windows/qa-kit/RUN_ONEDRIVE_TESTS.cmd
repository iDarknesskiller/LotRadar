@echo off
setlocal
title LotRadar OneDrive test (optional, asks before writing to OneDrive)
cd /d "%~dp0"
echo OPTIONAL ONEDRIVE TEST. Read the ONEDRIVE section of START_HERE.txt first.
echo LotRadar vehicle photos and Facebook photo exports stay local; only the disposable installer-compatibility test fixture is placed in OneDrive.
echo Double-clicking this file is your OK. It shows what it will do, waits 10 seconds (close the window to cancel), then runs.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Run-QAKit.ps1" -OneDrive -Yes
set "RC=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RC%. A results folder was opened for you (it is on this PC, not in OneDrive).
pause
exit /b %RC%
