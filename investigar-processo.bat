@echo off
rem Investiga o processo suspeito 'Windows Driver Foundation (WDM).exe'. SOMENTE LEITURA:
rem nada e encerrado, apagado, executado ou enviado para a internet.
rem Outro alvo: investigar-processo.bat "nome.exe"
cd /d "%~dp0"
if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\investigate-process.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\investigate-process.ps1" -Name "%~1"
)
echo.
pause
