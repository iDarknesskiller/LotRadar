@echo off
setlocal
if not exist "%~dp0LotRadar.exe" (
 echo LotRadar is missing. Run LotRadar_Setup.exe to repair it.
 exit /b 1
)
start "" "%~dp0LotRadar.exe"
exit /b %ERRORLEVEL%
