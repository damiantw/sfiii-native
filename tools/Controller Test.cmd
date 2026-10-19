@echo off
setlocal
cd /d "%~dp0"
set "SF3_CONTROLLER_DIR=%~dp0"
"controller-setup.exe" --test
if errorlevel 1 pause
