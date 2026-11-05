@echo off
rem Executa o agente nesta janela (depuracao). Feche a janela ou Ctrl+C para parar.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
echo.
pause
