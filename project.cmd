@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0project.ps1" %*
set "PROJECT_EXIT=%ERRORLEVEL%"
if not "%PROJECT_EXIT%"=="0" pause
exit /b %PROJECT_EXIT%
