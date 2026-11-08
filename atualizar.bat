@echo off
rem Atualiza o Sentinel pelo GitHub (git pull), reinstala e mostra o que mudou.
rem Relatorio em logs\atualizacao-AAAAMMDD-HHMMSS.txt (abre no Bloco de Notas).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update.ps1"
echo.
pause
