@echo off
setlocal
title LotRadar FULL LAUNCH test (optional, downloads packages)
cd /d "%~dp0"
echo OPTIONAL TEST. Run this only AFTER RUN_WINDOWS11_TESTS.cmd finished and only if asked.
echo It needs internet and downloads Python packages and a browser into a TEMPORARY test folder.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Run-QAKit.ps1" -FullLaunch -Yes
set "RC=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RC%. Your results are in the RESULTS folder next to this file.
pause
exit /b %RC%
