#Requires -Version 5.1
<#
.SYNOPSIS
    Atualiza o Sentinel a partir do GitHub (git pull) e reinstala.

.DESCRIPTION
    Registra o commit antes e depois, lista o que chegou e, se o pull falhar,
    mostra o motivo (ex.: arquivos alterados nesta pasta que impedem a
    atualização). Nada é descartado automaticamente. Depois reinstala (o agente
    é reiniciado) e mostra a impressão digital do código.
    Relatório em logs\atualizacao-AAAAMMDD-HHMMSS.txt, aberto no Bloco de Notas.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Report = Join-Path $LogDir ("atualizacao-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")

function Write-Report([string]$Text) {
    Write-Host $Text
    Add-Content -Path $Report -Value $Text -Encoding UTF8
}

function Invoke-Git([string[]]$Arguments) {
    # git escreve progresso em stderr: junta tudo como texto, sem tratar como erro.
    $out = & git -C $Root @Arguments 2>&1 | ForEach-Object { "$_" }
    return [pscustomobject]@{ Code = $LASTEXITCODE; Text = ($out -join "`n").Trim() }
}

Write-Report ("Atualização do Sentinel - " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Report "Pasta: $Root"
Write-Report ""
$ok = $false
try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Report "[FALHA] O comando git não foi encontrado neste PC."
        Write-Report "        Se você usa o GitHub Desktop, faça o pull por ele e rode instalar.bat."
        return
    }
    $before = (Invoke-Git @("rev-parse", "--short", "HEAD")).Text
    $branch = (Invoke-Git @("rev-parse", "--abbrev-ref", "HEAD")).Text
    Write-Report "Commit antes : $before (ramo $branch)"

    $dirty = Invoke-Git @("status", "--porcelain", "--untracked-files=no")
    if ($dirty.Text) {
        Write-Report ""
        Write-Report "[ATENÇÃO] Arquivos alterados nesta pasta (podem impedir o pull):"
        Write-Report $dirty.Text
    }

    Write-Report ""
    Write-Report "git pull --ff-only:"
    $pull = Invoke-Git @("pull", "--ff-only")
    Write-Report $pull.Text
    if ($pull.Code -ne 0) {
        Write-Report ""
        Write-Report "[FALHA] O pull não foi concluído (código $($pull.Code)). Nada foi alterado."
        Write-Report "        Mande este relatório para análise. Se a causa forem os arquivos alterados listados"
        Write-Report "        acima, eles precisam ser revertidos ou guardados antes de atualizar."
        return
    }
    $after = (Invoke-Git @("rev-parse", "--short", "HEAD")).Text
    Write-Report ""
    Write-Report "Commit depois: $after"
    if ($after -eq $before) {
        Write-Report "Nenhuma novidade no GitHub (já estava atualizado). Foi feito o push no outro computador?"
    } else {
        Write-Report "Chegaram:"
        Write-Report (Invoke-Git @("log", "--oneline", "$before..$after")).Text
    }

    Write-Report ""
    Write-Report "Reinstalando (o agente é reiniciado)..."
    $install = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install.ps1") 2>&1 | ForEach-Object { "$_" }
    Write-Report (($install -join "`n").Trim())
    Write-Report ""
    $code = (& $Py -m sentinel code-check 2>&1 | Out-String).Trim()
    Write-Report $code
    $ok = $true
} finally {
    Write-Report ""
    Write-Report $(if ($ok) { "Atualização concluída. Rode verificar.bat." } else { "Atualização NÃO concluída." })
    Write-Report "Relatório salvo em: $Report"
    Start-Process notepad.exe $Report
}
