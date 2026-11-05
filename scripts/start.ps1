#Requires -Version 5.1
<#
.SYNOPSIS
    Executa o Sentinel em primeiro plano (útil para depuração). Ctrl+C encerra.
    Se a tarefa agendada já estiver rodando, esta cópia será recusada pela trava de instância.
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) { throw "Ambiente virtual não encontrado. Execute scripts\install.ps1 primeiro." }

Push-Location $Root
try {
    & $VenvPython -m sentinel run
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
