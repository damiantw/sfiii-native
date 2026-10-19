@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0import-saturn-save.ps1"
if errorlevel 1 pause
