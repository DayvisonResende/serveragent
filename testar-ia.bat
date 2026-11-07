@echo off
rem Teste de viabilidade da IA local (Fase 5). Precisa do Ollama instalado e aberto: https://ollama.com/download
rem Compara LFM3 1.7B, Qwen3 1.7B e Llama 3.2 3B neste computador e salva o relatorio em logs\ia-teste-*.txt
cd /d "%~dp0"
echo.
echo Este teste baixa ate 3 modelos de IA (cerca de 4 GB no total) e ocupa a CPU por alguns minutos.
echo Os servidores podem ficar mais lentos enquanto ele roda.
echo.
choice /c SN /m "Baixar os modelos que faltarem"
if errorlevel 2 (
  ".venv\Scripts\python.exe" -m sentinel ai-bench
) else (
  ".venv\Scripts\python.exe" -m sentinel ai-bench --pull
)
echo.
pause
