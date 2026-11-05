@echo off
rem Mostra o estado do agente e os eventos recentes.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m sentinel status
echo.
pause
