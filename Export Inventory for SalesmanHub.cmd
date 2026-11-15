@echo off
setlocal EnableExtensions DisableDelayedExpansion
title LotRadar - Export Inventory for SalesmanHub
set "PY=%LOCALAPPDATA%\MarketplaceScanner\runtime\setup-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\MarketplaceScanner\runtime\venv\Scripts\python.exe"
if not exist "%PY%" (
 echo Private Scanner Python runtime missing. Start LotRadar first.
 pause
 exit /b 1
)
"%PY%" "%~dp0connector_export.py"
set "RESULT=%ERRORLEVEL%"
echo.
echo Pending export only; SalesmanHub does not automatically import this file yet.
pause
exit /b %RESULT%
