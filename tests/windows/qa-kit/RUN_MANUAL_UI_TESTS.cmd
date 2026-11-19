@echo off
setlocal
title LotRadar guided real-start test (temporary TEST folder only)
cd /d "%~dp0"
echo GUIDED REAL-START TEST. Read the MANUAL section of START_HERE.txt first. Close LotRadar before starting.
echo It installs LotRadar into a temporary TEST folder and puts a "LotRadar TEST (sandbox)" shortcut on your Desktop.
echo You double-click that shortcut when asked and answer Y/N. Your real LotRadar, data, photos, drafts and real
echo shortcut are not changed (checked before and after). No Python is installed: without one the test reports BLOCKED.
echo Double-clicking this file is your OK. It shows what it will do, waits 10 seconds (close the window to cancel), then runs.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Run-QAKit.ps1" -ManualUI -Yes
set "RC=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RC%. A results folder was opened for you (it is on this PC, not in OneDrive).
pause
exit /b %RC%
