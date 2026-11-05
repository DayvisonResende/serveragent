@echo off
rem Instala o Sentinel e registra a tarefa agendada. NAO execute como administrador.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
echo.
pause
