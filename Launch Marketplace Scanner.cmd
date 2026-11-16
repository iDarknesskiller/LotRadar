@echo off
setlocal EnableExtensions
rem LotRadar launcher. Runs the canonical Python bootstrap; LotRadar.exe is NOT required.
cd /d "%~dp0"
set "BOOTSTRAP=%~dp0Marketplace Bootstrap.ps1"
if not exist "%BOOTSTRAP%" (
 echo LOTRADAR ERROR: "Marketplace Bootstrap.ps1" was not found next to this launcher.
 echo Reinstall LotRadar or run the launcher from the program folder.
 set "RC=2"
 goto :finish
)
where powershell.exe >nul 2>&1
if errorlevel 1 (
 echo LOTRADAR ERROR: Windows PowerShell 5.1+ ^(powershell.exe^) was not found.
 set "RC=3"
 goto :finish
)
rem Execution policy is relaxed for this single process only; machine/user policy is not changed.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%"
set "RC=%ERRORLEVEL%"
:finish
if not "%RC%"=="0" (
 echo.
 echo LotRadar exited with error code %RC%. See the messages above.
 rem Keep the window open so the message can be read (e.g. after a double-click). Scripts set LOTRADAR_NO_PAUSE=1.
 if not defined LOTRADAR_NO_PAUSE pause
)
exit /b %RC%
