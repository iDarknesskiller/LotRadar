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
rem Interactive double-click: show the native startup window (startup\Show-LotRadarStartup.ps1). It only displays
rem progress and runs this same launcher again with LOTRADAR_STARTUP_GUI=0, so the bootstrap below stays the only owner of
rem the launch lock, the server and the browser window. Scripts and tests keep this console path unchanged:
rem   LOTRADAR_STARTUP_GUI=0 (documented opt-out), LOTRADAR_NO_PAUSE=1 (automation), or the window file missing.
rem Window exit codes: 0 opened/closed while starting, 91 failure shown (returned as 1), anything else (90 = cannot be
rem shown here, or the window script failed to run) falls back to the console start below.
set "STARTUPGUI=%~dp0startup\Show-LotRadarStartup.ps1"
if "%LOTRADAR_STARTUP_GUI%"=="0" goto :console
if defined LOTRADAR_NO_PAUSE goto :console
if not exist "%STARTUPGUI%" goto :console
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -STA -File "%STARTUPGUI%"
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" exit /b 0
if "%RC%"=="91" exit /b 1
if not "%RC%"=="90" echo The LotRadar startup window could not run ^(code %RC%^). Starting in this window instead.
:console
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
