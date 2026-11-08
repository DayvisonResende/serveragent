@echo off
rem Aplica uma atualizacao do Sentinel (pacote sentinel-*.zip). Fica na pasta do Sentinel; de dois cliques.
rem Procura o pacote nesta pasta, em Downloads, na Area de Trabalho e em Documentos (o mais recente vence).
rem Dados, logs e .venv nao estao no pacote e ficam intactos. Este arquivo nao vem dentro do pacote.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$here = (Get-Location).Path; if (-not (Test-Path 'scripts\install.ps1')) { Write-Host ('Este atualizar.bat esta em: ' + $here); Write-Host 'Ele precisa ficar na pasta do Sentinel (a que tem instalar.bat e a pasta sentinel).'; exit 1 }; $places = @($here, (Join-Path $env:USERPROFILE 'Downloads'), (Join-Path $env:USERPROFILE 'Desktop'), (Join-Path $env:USERPROFILE 'OneDrive\Desktop'), (Join-Path $env:USERPROFILE 'Documents')) | Where-Object { Test-Path $_ }; $z = $places | ForEach-Object { Get-ChildItem -Path $_ -Filter 'sentinel-*.zip' -File -ErrorAction SilentlyContinue } | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if (-not $z) { Write-Host 'Nenhum pacote sentinel-*.zip encontrado. Procurei em:'; $places | ForEach-Object { Write-Host ('  ' + $_) }; $other = Get-ChildItem -Path $here -Filter '*.zip' -File -ErrorAction SilentlyContinue; if ($other) { Write-Host 'Arquivos .zip nesta pasta:'; $other | ForEach-Object { Write-Host ('  ' + $_.Name) } }; exit 1 }; Write-Host ('Pacote: ' + $z.FullName + '  (' + $z.LastWriteTime + ')'); Expand-Archive -Path $z.FullName -DestinationPath $here -Force; Write-Host ('Arquivos atualizados em ' + $here)"
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
