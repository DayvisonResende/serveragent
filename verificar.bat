@echo off
rem Verifica a instalacao e gera um relatorio em logs\verificacao-*.txt
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify.ps1"
echo.
pause
