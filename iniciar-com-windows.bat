@echo off
rem Faz o Sentinel iniciar junto com o Windows, mesmo sem logon.
rem Pede a senha da sua conta (janela do Windows) e permissao de administrador so para registrar a tarefa.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\enable-startup.ps1"
echo.
pause
