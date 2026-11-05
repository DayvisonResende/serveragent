#Requires -Version 5.1
<#
.SYNOPSIS
    Verifica a instalação do Sentinel no Windows e gera um relatório.

.DESCRIPTION
    Executa automaticamente:
      1. Estado do agente, da tarefa agendada e dos processos
      2. Testes automáticos (pytest)
      3. Recusa de uma segunda instância
      4. Detecção de encerramento forçado (para e reinicia a tarefa)
      5. Consumo de memória e CPU do processo real do agente
    O relatório é salvo em logs\verificacao-AAAAMMDD-HHMMSS.txt e aberto no Bloco de Notas.
    A verificação de reinício do computador continua manual.
#>
[CmdletBinding()]
param([string]$TaskName = "Sentinel Agent")

$ErrorActionPreference = "Continue"
# Python e PowerShell passam a trocar texto em UTF-8 (evita "execuþÒo").
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
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

function Get-Status {
    $raw = & $Py -m sentinel status --json 2>$null | Out-String
    try { return $raw | ConvertFrom-Json } catch { return $null }
}

function Get-SentinelProcesses {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*-m sentinel run*" } |
        ForEach-Object {
            [pscustomobject]@{
                PID      = $_.ProcessId
                PaiPID   = $_.ParentProcessId
                Nome     = $_.Name
                MemoriaMB = [math]::Round($_.WorkingSetSize / 1MB, 1)
                Caminho  = $_.ExecutablePath
            }
        }
}

function Write-Processes([string]$Title) {
    Write-Report $Title
    $procs = @(Get-SentinelProcesses)
    if ($procs.Count -eq 0) { Write-Report "  (nenhum processo 'sentinel run')"; return }
    foreach ($p in $procs) {
        Write-Report ("  PID {0,-6} pai {1,-6} {2,-12} {3,7} MB  {4}" -f $p.PID, $p.PaiPID, $p.Nome, $p.MemoriaMB, $p.Caminho)
    }
}

function Wait-Until([int]$Seconds, [scriptblock]$Condition) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $value = & $Condition
        if ($value) { return $value }
        Start-Sleep -Seconds 2
    }
    return $null
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
    Write-Report (& $Py -m sentinel status 2>&1 | Out-String).TrimEnd()
    $status = Get-Status
    $isRunning = ($null -ne $status -and $null -ne $status.latest_run -and $status.latest_run.state -eq "running")
    Add-Result "Agente em execução" $isRunning ("execução #{0}, PID {1}" -f $status.latest_run.id, $status.latest_run.pid)
    Write-Processes "Processos do Sentinel:"
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
    if ($isRunning) {
        $errFile = Join-Path $env:TEMP "sentinel-second.txt"
        $proc = Start-Process -FilePath $Py -ArgumentList "-m", "sentinel", "run" -WorkingDirectory $Root `
            -NoNewWindow -PassThru -RedirectStandardError $errFile
        $null = $proc.Handle  # sem isto o PowerShell 5.1 perde o ExitCode
        if ($proc.WaitForExit(20000)) {
            $msg = "$(Get-Content $errFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue)".Trim()
            Add-Result "Segunda instância recusada" ($proc.ExitCode -eq 3) "código $($proc.ExitCode): $msg"
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
    if ($null -ne $task -and $isRunning) {
        $oldRun = [int]$status.latest_run.id
        $oldPid = [int]$status.latest_run.pid
        $uncleanBefore = [int]$status.unclean_shutdown_events

        Stop-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 3
        $survivor = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        Add-Result "Stop-ScheduledTask encerrou o agente" ($null -eq $survivor) "PID $oldPid"
        if ($null -ne $survivor) {
            Write-Processes "Processos que sobreviveram à parada da tarefa:"
            Stop-Process -Id $oldPid -Force
            Write-Report "  PID $oldPid encerrado à força para continuar o teste."
        }

        Start-ScheduledTask -TaskName $TaskName
        $newStatus = Wait-Until 60 {
            $s = Get-Status
            if ($null -ne $s -and $s.latest_run.id -gt $oldRun -and $s.latest_run.state -eq "running") { $s }
        }
        Add-Result "Nova execução iniciada pela tarefa" ($null -ne $newStatus) $(if ($newStatus) { "execução #$($newStatus.latest_run.id), PID $($newStatus.latest_run.pid)" } else { "nenhuma nova execução em 60 s" })

        $afterStatus = Wait-Until 20 {
            $s = Get-Status
            if ($null -ne $s -and [int]$s.unclean_shutdown_events -gt $uncleanBefore) { $s }
        }
        $uncleanAfter = if ($afterStatus) { $afterStatus.unclean_shutdown_events } else { (Get-Status).unclean_shutdown_events }
        Add-Result "Encerramento inesperado registrado" ($null -ne $afterStatus) "eventos antes: $uncleanBefore, depois: $uncleanAfter"
        Write-Processes "Processos após o reinício:"
    } else {
        Add-Result "Encerramento forçado" $false "Pulado: tarefa inexistente ou agente parado."
    }
    Write-Report ""

    # 5. Recursos --------------------------------------------------------------
    Write-Report "== 5. Consumo de recursos (amostra de 30 s) =="
    $current = Get-Status
    $agentPid = if ($current -and $current.latest_run) { [int]$current.latest_run.pid } else { 0 }
    $p = if ($agentPid) { Get-Process -Id $agentPid -ErrorAction SilentlyContinue } else { $null }
    if ($null -eq $p) {
        Add-Result "Processo do agente" $false "PID $agentPid não encontrado."
    } else {
        $cpu0 = $p.TotalProcessorTime.TotalSeconds
        Start-Sleep -Seconds 30
        $p.Refresh()
        $cpuPct = (($p.TotalProcessorTime.TotalSeconds - $cpu0) / 30 / [Environment]::ProcessorCount) * 100
        $memMb = [math]::Round($p.WorkingSet64 / 1MB, 1)
        Add-Result "Memória do agente (PID $agentPid)" ($memMb -le 200) "$memMb MB (meta: até 200 MB)"
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
