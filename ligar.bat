@echo off
rem Liga o Sentinel agora (pela tarefa agendada).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-ScheduledTask -TaskName 'Sentinel Agent' -ErrorAction SilentlyContinue) { Start-ScheduledTask -TaskName 'Sentinel Agent'; Write-Host 'Sentinel ligado. Confira com status.bat em alguns segundos.' } else { Write-Host 'Tarefa nao encontrada: execute instalar.bat primeiro.' }"
echo.
pause
