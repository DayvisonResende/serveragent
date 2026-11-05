#Requires -Version 5.1
<#
.SYNOPSIS
    Instala o Sentinel para o usuário atual e registra a inicialização automática.

.DESCRIPTION
    1. Recusa execução em PowerShell elevado (o Sentinel roda sem privilégios — PRD 17.1).
    2. Verifica Python 3.12+.
    3. Cria o ambiente virtual .venv e instala as dependências.
    4. Executa "sentinel init" (configuração, diretórios, banco).
    5. Registra uma tarefa no Agendador de Tarefas que inicia o agente no logon,
       com privilégios limitados e reinício automático em caso de falha.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$TaskName = "Sentinel Agent",
    [switch]$NoTask
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments, [string]$What)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What falhou (código $LASTEXITCODE)." }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Execute este script em um PowerShell SEM 'Executar como administrador'. O Sentinel deve rodar com privilégios limitados."
}

$version = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($LASTEXITCODE -ne 0) { throw "Python não encontrado ('$Python'). Instale o Python 3.12+ ou informe -Python <caminho>." }
if ([version]$version -lt [version]"3.12") { throw "Python 3.12+ é necessário (encontrado $version)." }
Write-Host "Python $version encontrado."

$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$VenvPythonW = Join-Path $Venv "Scripts\pythonw.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Criando ambiente virtual em $Venv ..."
    Invoke-Checked $Python @("-m", "venv", $Venv) "Criação do ambiente virtual"
}

# Atualização: o agente em execução precisa parar antes, senão o pip não consegue
# substituir arquivos em uso e o processo antigo continuaria com o código anterior.
# Uma versão antiga do agente pode não reconhecer o pedido de parada: nesse caso
# "sentinel stop" retorna erro e seguimos para o plano B (parar a tarefa).
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (Test-Path $VenvPython) {
    Push-Location $Root
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"  # erro de um programa externo não pode abortar a instalação
    try {
        & $VenvPython -m sentinel stop --timeout 15
    } finally {
        $ErrorActionPreference = $previousPreference
        Pop-Location
    }
}
if ($null -ne $existingTask -and (Get-ScheduledTask -TaskName $TaskName).State -eq "Running") {
    Write-Host "O agente não parou pelo comando; encerrando a tarefa agendada."
    Stop-ScheduledTask -TaskName $TaskName
}
# Aguarda o processo do agente sair de fato (arquivos em uso impedem a atualização).
for ($i = 0; $i -lt 20; $i++) {
    $running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*-m sentinel run*" })
    if ($running.Count -eq 0) { break }
    Start-Sleep -Milliseconds 500
}
if ($running.Count -gt 0) {
    throw "O agente ainda está em execução (PID $($running[0].ProcessId)). Feche-o pelo Gerenciador de Tarefas e rode instalar.bat de novo."
}

Write-Host "Instalando dependências ..."
Invoke-Checked $VenvPython @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", (Join-Path $Root "requirements.txt")) "Instalação de dependências"

Push-Location $Root
try {
    Invoke-Checked $VenvPython @("-m", "sentinel", "init") "sentinel init"
} finally {
    Pop-Location
}

if ($NoTask) {
    Write-Host "Instalação concluída sem tarefa agendada. Inicie manualmente com scripts\start.ps1."
    return
}

$userId = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $VenvPythonW -Argument "-m sentinel run" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $taskPrincipal `
    -Settings $settings -Description "Sentinel - agente de monitoramento e administração local" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Tarefa '$TaskName' registrada e iniciada."
Write-Host "Verifique com:  .venv\Scripts\python.exe -m sentinel status"
