@echo off
setlocal
title LotRadar Windows 11 / R3 test kit
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Run-QAKit.ps1"
set "RC=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RC%. Your results are in the RESULTS folder next to this file.
pause
exit /b %RC%
