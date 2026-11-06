#Requires -Version 5.1
<#
.SYNOPSIS
    Faz o Sentinel iniciar junto com o Windows, mesmo sem ninguém fazer logon.

.DESCRIPTION
    Reconfigura a tarefa agendada "Sentinel Agent" para "executar estando o usuário
    conectado ou não", com gatilho na inicialização do Windows.

    - O Windows exige a senha da sua conta para isso: ela é pedida numa janela do
      próprio Windows e guardada pelo Agendador de Tarefas (não pelo Sentinel).
    - Registrar uma tarefa de inicialização exige administrador (aparece o aviso do
      UAC). O Sentinel continua rodando com privilégios LIMITADOS na sua conta.
    - Se você trocar a senha do Windows, rode este script de novo.
    - Para voltar ao modo anterior (iniciar no logon), rode instalar.bat com -ModoLogon:
      powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -ModoLogon
#>
[CmdletBinding()]
param(
    [string]$TaskName = "Sentinel Agent",
    [string]$TargetUser = "$env:USERDOMAIN\$env:USERNAME"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Pedindo permissão de administrador apenas para registrar a tarefa..."
    # O usuário-alvo é decidido ANTES da elevação: se a elevação usar outra conta, a tarefa
    # continua sendo da sua conta.
    $elevateArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-TaskName", "`"$TaskName`"", "-TargetUser", "`"$TargetUser`"")
    $proc = Start-Process powershell.exe -Verb RunAs -ArgumentList $elevateArgs -Wait -PassThru
    exit $proc.ExitCode
}

$VenvPythonW = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $VenvPythonW)) { throw "Sentinel não instalado. Execute instalar.bat primeiro." }

$credential = Get-Credential -UserName $TargetUser -Message "Senha da conta $TargetUser (necessária para o Sentinel iniciar sem logon; fica com o Agendador de Tarefas)"
if ($null -eq $credential) { throw "Operação cancelada." }
$password = $credential.GetNetworkCredential().Password

$action = New-ScheduledTaskAction -Execute $VenvPythonW -Argument "-m sentinel run" -WorkingDirectory $Root
$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = "PT30S"  # aguarda a rede subir
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $boot -Settings $settings `
        -User $TargetUser -Password $password -RunLevel Limited `
        -Description "Sentinel - inicia com o Windows, sem logon (privilégios limitados)" -Force | Out-Null
} catch {
    throw "Não foi possível registrar a tarefa: $($_.Exception.Message). Confira a senha da conta $TargetUser."
} finally {
    $password = $null
    $credential = $null
}

Write-Host "Pronto: o Sentinel agora inicia junto com o Windows, sem precisar de logon."
Write-Host "A tarefa roda como $TargetUser, com privilégios limitados."
Write-Host "Ele passa a valer a partir do próximo reinício (ou use ligar.bat agora)."
