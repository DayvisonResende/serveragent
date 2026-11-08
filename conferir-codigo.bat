@echo off
rem Lista o hash de cada arquivo do codigo instalado (para conferir uma copia incompleta).
rem Relatorio em logs\codigo-AAAAMMDD-HHMMSS.txt
cd /d "%~dp0"
if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set STAMP=%%i
set REPORT=logs\codigo-%STAMP%.txt
".venv\Scripts\python.exe" -m sentinel code-check --files > "%REPORT%" 2>&1
echo Relatorio salvo em %REPORT%
start notepad "%REPORT%"
