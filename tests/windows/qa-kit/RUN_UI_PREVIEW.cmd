@echo off
setlocal
title LotRadar startup window PREVIEW (example steps only)
cd /d "%~dp0"
echo STARTUP WINDOW PREVIEW. It shows the real LotRadar startup window with EXAMPLE steps.
echo Nothing is installed or started. You try the keys, then answer two Y/N questions.
echo Run it once at your normal display scaling and once at 150%% (Settings, Display, Scale).
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Run-QAKit.ps1" -UiPreview -Yes
set "RC=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RC%. A results folder was opened for you. Look at the screenshots before sharing them.
pause
exit /b %RC%
