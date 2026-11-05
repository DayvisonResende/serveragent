#Requires -Version 5.1
<#
.SYNOPSIS
    Remove a tarefa agendada do Sentinel. Dados (data\, logs\, config\) são preservados.

.DESCRIPTION
    Parar a tarefa encerra apenas o processo do Sentinel. Servidores monitorados
    não são afetados.
#>
[CmdletBinding()]
param([string]$TaskName = "Sentinel Agent")

$ErrorActionPreference = "Stop"

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
