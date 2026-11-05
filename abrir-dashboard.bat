@echo off
rem Abre o dashboard no navegador com um link de acesso de uso unico.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m sentinel dashboard
if errorlevel 1 pause
