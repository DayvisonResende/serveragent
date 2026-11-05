@echo off
rem Para o agente de forma limpa. A tarefa agendada o inicia de novo no proximo logon.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m sentinel stop
echo.
pause
