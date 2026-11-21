@echo off
setlocal
title LotRadar AUTOMATED real-start test (temporary TEST folder only)
cd /d "%~dp0"
echo AUTOMATED REAL-START TEST (no person needed). Close LotRadar before starting.
echo It installs LotRadar into a temporary TEST folder, then the kit itself double-clicks the TEST shortcut and presses
echo F5, Alt+C, Tab and clicks Retry with real keyboard and mouse input. Do NOT use the keyboard or mouse while it runs.
echo The first start downloads packages INTO THE TEST FOLDER only. Your real LotRadar, data, photos, drafts and real
echo shortcut are not changed (checked before and after). No Python is installed: without one the test reports BLOCKED.
echo Double-clicking this file is your OK. It shows what it will do, waits 10 seconds (close the window to cancel), then runs.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0tools\Run-QAKit.ps1" -ManualUI -AutoInput -Yes
set "RC=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RC%. A results folder was opened for you (it is on this PC, not in OneDrive).
pause
exit /b %RC%
