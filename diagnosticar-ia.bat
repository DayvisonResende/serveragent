@echo off
rem Diagnostico rapido (1 a 2 min): o Ollama reaproveita a leitura das instrucoes da IA entre perguntas?
rem Relatorio em logs\ia-cache-*.txt
cd /d "%~dp0"
echo.
echo Medindo a leitura das instrucoes pela IA local. Leva 1 a 2 minutos e ocupa a CPU.
echo.
".venv\Scripts\python.exe" -m sentinel ai-bench --cache
echo.
pause
