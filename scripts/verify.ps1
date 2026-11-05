#Requires -Version 5.1
<#
.SYNOPSIS
    Verifica a instalação do Sentinel no Windows e gera um relatório.

.DESCRIPTION
    Executa automaticamente:
      1. Estado do agente e da tarefa agendada
      2. Testes automáticos (pytest)
      3. Recusa de uma segunda instância
      4. Detecção de encerramento forçado (para e reinicia a tarefa)
      5. Consumo de memória e CPU
    O relatório é salvo em logs\verificacao-AAAAMMDD-HHMMSS.txt e aberto no Bloco de Notas.
    A verificação de reinício do computador continua manual.
#>
[CmdletBinding()]
param([string]$TaskName = "Sentinel Agent")

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Db = Join-Path $Root "data\sentinel.db"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Report = Join-Path $LogDir ("verificacao-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$Results = New-Object System.Collections.Generic.List[object]

function Write-Report([string]$Text) {
    Write-Host $Text
    Add-Content -Path $Report -Value $Text -Encoding UTF8
}

function Add-Result([string]$Name, [bool]$Ok, [string]$Detail) {
    $Results.Add([pscustomobject]@{ Nome = $Name; Ok = $Ok; Detalhe = $Detail })
    $mark = if ($Ok) { "[OK]   " } else { "[FALHA]" }
    Write-Report "$mark $Name - $Detail"
}

function Invoke-Sentinel([string[]]$Arguments) {
    $output = & $Py -m sentinel @Arguments 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Output = $output.TrimEnd() }
}

function Get-UncleanCount {
    $code = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('SELECT COUNT(*) FROM events WHERE event_type=?', ('agent.unclean_shutdown',)).fetchone()[0])"
    $value = & $Py -c $code $Db 2>&1 | Out-String
    $parsed = 0
    if ([int]::TryParse($value.Trim(), [ref]$parsed)) { return $parsed }
    return -1
}

function Wait-AgentRunning([int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $s = Invoke-Sentinel @("status")
        if ($s.Output -match "em execu") { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Get-AgentProcess {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*sentinel run*" } |
        Select-Object -First 1
}

Push-Location $Root
try {
    Write-Report "Verificação do Sentinel - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Report "Pasta: $Root"
    Write-Report ("Windows: " + (Get-CimInstance Win32_OperatingSystem).Caption)
    Write-Report ""

    if (-not (Test-Path $Py)) {
        Add-Result "Ambiente virtual" $false "Não encontrado em $Py. Execute instalar.bat primeiro."
        return
    }

    # 1. Estado ----------------------------------------------------------------
    Write-Report "== 1. Estado do agente =="
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Add-Result "Tarefa agendada" $false "Tarefa '$TaskName' não existe."
    } else {
        Add-Result "Tarefa agendada" ($task.State -eq "Running") "Estado: $($task.State)"
    }
    $status = Invoke-Sentinel @("status")
    Write-Report $status.Output
    Add-Result "Agente em execução" ($status.Output -match "em execu") "sentinel status (código $($status.Code))"
    Write-Report ""

    # 2. Testes ----------------------------------------------------------------
    Write-Report "== 2. Testes automáticos =="
    & $Py -m pip install --disable-pip-version-check -q -r (Join-Path $Root "requirements-dev.txt") 2>&1 | Out-Null
    $tests = & $Py -m pytest -q -p no:cacheprovider 2>&1 | Out-String
    $testCode = $LASTEXITCODE
    $summary = ($tests.Trim() -split "`r?`n")[-1]
    Add-Result "pytest" ($testCode -eq 0) $summary
    if ($testCode -ne 0) { Write-Report $tests }
    Write-Report ""

    # 3. Segunda instância -----------------------------------------------------
    Write-Report "== 3. Recusa de segunda instância =="
    if ($status.Output -match "em execu") {
        $errFile = Join-Path $env:TEMP "sentinel-second.txt"
        $proc = Start-Process -FilePath $Py -ArgumentList "-m", "sentinel", "run" -WorkingDirectory $Root `
            -NoNewWindow -PassThru -RedirectStandardError $errFile
        if ($proc.WaitForExit(20000)) {
            $msg = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue)
            $ok = ($proc.ExitCode -eq 3)
            Add-Result "Segunda instância recusada" $ok ("código $($proc.ExitCode): " + "$msg".Trim())
        } else {
            Stop-Process -Id $proc.Id -Force
            Add-Result "Segunda instância recusada" $false "A segunda cópia NÃO foi recusada (encerrada à força)."
        }
    } else {
        Add-Result "Segunda instância recusada" $false "Pulado: o agente não está em execução."
    }
    Write-Report ""

    # 4. Encerramento forçado --------------------------------------------------
    Write-Report "== 4. Detecção de encerramento forçado =="
    if ($null -ne $task) {
        $before = Get-UncleanCount
        Stop-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 3
        Start-ScheduledTask -TaskName $TaskName
        $running = Wait-AgentRunning 40
        $after = Get-UncleanCount
        Add-Result "Agente voltou após reinício da tarefa" $running ""
        Add-Result "Encerramento inesperado registrado" ($after -gt $before -and $before -ge 0) "eventos antes: $before, depois: $after"
    } else {
        Add-Result "Encerramento forçado" $false "Pulado: tarefa agendada inexistente."
    }
    Write-Report ""

    # 5. Recursos --------------------------------------------------------------
    Write-Report "== 5. Consumo de recursos (amostra de 30 s) =="
    $agent = Get-AgentProcess
    if ($null -eq $agent) {
        Add-Result "Processo do agente" $false "Processo 'sentinel run' não encontrado."
    } else {
        $p = Get-Process -Id $agent.ProcessId
        $cpu0 = $p.TotalProcessorTime.TotalSeconds
        Start-Sleep -Seconds 30
        $p.Refresh()
        $cpuPct = (($p.TotalProcessorTime.TotalSeconds - $cpu0) / 30 / [Environment]::ProcessorCount) * 100
        $memMb = [math]::Round($p.WorkingSet64 / 1MB, 1)
        Add-Result "Memória do agente" ($memMb -le 200) "$memMb MB (meta: até 200 MB)"
        Add-Result "CPU em repouso" ($cpuPct -le 3) ("{0:N2}% (meta: até 3%)" -f $cpuPct)
    }
    Write-Report ""
} finally {
    Pop-Location
    $failed = @($Results | Where-Object { -not $_.Ok }).Count
    Write-Report "== Resumo =="
    Write-Report ("{0} verificações, {1} falha(s)." -f $Results.Count, $failed)
    Write-Report "Verificação manual pendente: reinicie o PC, faça logon e execute status.bat."
    Write-Report "Relatório salvo em: $Report"
    Start-Process notepad.exe $Report
}
