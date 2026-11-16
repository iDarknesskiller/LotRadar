@echo off
setlocal
cd /d "%~dp0"
title Install LotRadar - Current Source
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-LotRadar.ps1"
set "result=%errorlevel%"
echo.
if not "%result%"=="0" (
 echo Installation did NOT complete. Read the error above.
) else (
 echo LotRadar is installed. Use your desktop LotRadar shortcut to open it.
)
pause
exit /b %result%
