@echo off
setlocal
title LotRadar cleanup safety self-test (synthetic folders only)
cd /d "%~dp0"
echo CLEANUP SAFETY SELF-TEST. Read the CLEANUP section of START_HERE.txt first.
echo It checks, on SYNTHETIC test folders and a fake Desktop, that the kit only ever deletes folders it can prove it created.
echo Your real shortcut, photos and data are not used.
echo Double-clicking this file is your OK for the LOCAL checks only. It shows what it will do, waits 10 seconds (close the window to cancel), then runs.
echo If OneDrive is present you are asked SEPARATELY whether to include two OneDrive cases (one temporary test folder there).
echo Just press Enter to skip them - that is the default. Only Y includes them.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Run-QAKit.ps1" -CleanupSelfTest -Yes
set "RC=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RC%. A results folder was opened for you (it is on this PC, not in OneDrive).
pause
exit /b %RC%
