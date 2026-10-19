@echo off
setlocal
cd /d "%~dp0"
set "SF3_CONTROLLER_DIR=%~dp0"
echo Close the native game before changing controller bindings.
"controller-setup.exe" --setup
pause
