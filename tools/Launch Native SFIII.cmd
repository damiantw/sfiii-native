@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-native.ps1" -Work "%~dp0."
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
