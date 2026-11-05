@echo off
rem Remove a tarefa agendada. Os dados sao mantidos.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall.ps1"
echo.
pause
