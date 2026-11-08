@echo off
rem Aplica uma atualizacao do Sentinel: copie o arquivo sentinel-*.zip para esta pasta e de dois cliques aqui.
rem Extrai o pacote mais recente por cima do codigo (dados, logs e .venv nao estao no pacote e ficam intactos),
rem reinstala e mostra o codigo instalado. Este arquivo nao vem dentro do pacote (nunca e sobrescrito enquanto roda).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$z = Get-ChildItem -Path . -Filter 'sentinel-*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if (-not $z) { Write-Host 'Nenhum arquivo sentinel-*.zip nesta pasta. Copie o pacote para ca e tente de novo.'; exit 1 }; Write-Host ('Aplicando ' + $z.Name + ' ...'); Expand-Archive -Path $z.FullName -DestinationPath . -Force; Write-Host 'Arquivos atualizados.'"
if errorlevel 1 goto fim
echo.
echo Reinstalando (o agente e reiniciado)...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\install.ps1"
echo.
".venv\Scripts\python.exe" -m sentinel code-check
echo Compare o codigo acima com o informado pelo desenvolvedor.
:fim
echo.
pause
