#Requires -Version 5.1
<#
.SYNOPSIS
    Para o agente e remove a tarefa agendada. Dados (data\, logs\, config\) são preservados.

.DESCRIPTION
    Parar o Sentinel encerra apenas o processo do Sentinel. Servidores monitorados
    não são afetados.
#>
[CmdletBinding()]
param([string]$TaskName = "Sentinel Agent")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    Push-Location $Root
    try {
        & $VenvPython -m sentinel stop 2>&1 | Write-Host
    } finally {
        Pop-Location
    }
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Tarefa '$TaskName' não encontrada; nada a remover."
    return
}

if ($task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
    Write-Host "Tarefa parada."
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Tarefa '$TaskName' removida. Os dados em data\, logs\ e config\ foram mantidos."
