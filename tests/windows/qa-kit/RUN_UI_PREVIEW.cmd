@echo off
setlocal
title LotRadar startup window PREVIEW (example steps only)
cd /d "%~dp0"
echo STARTUP WINDOW PREVIEW. It shows the real LotRadar startup window with EXAMPLE steps.
echo Nothing is installed or started. Five previews: 16 individual P observations with notes, plus E4 and E0.
echo Use the current display settings for LR-010.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Run-QAKit.ps1" -UiPreview -Yes
set "RC=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RC%. A results folder was opened for you. Look at the screenshots before sharing them.
pause
exit /b %RC%
