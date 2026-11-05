#Requires -Version 5.1
<#
.SYNOPSIS
    Investiga um executável suspeito e gera um relatório. SOMENTE LEITURA.

.DESCRIPTION
    Coleta, sem alterar nada no sistema:
      1. Processos em execução com esse nome: PID, pai, linha de comando, dono, conexões de rede
      2. O arquivo: tamanho, datas, atributos, informações de versão, assinatura digital, SHA-256
      3. Cópias com o mesmo nome em pastas de usuário (AppData, Temp, ProgramData)
      4. Inicialização automática: chaves Run/RunOnce, pastas Inicializar, tarefas agendadas, serviços
      5. Tarefas agendadas e itens de inicialização que executam de pastas graváveis pelo usuário
      6. Estado e detecções do Microsoft Defender

    Nenhum processo é encerrado, nenhum arquivo é apagado ou executado e nada é
    enviado para a internet. O hash pode ser consultado manualmente no VirusTotal.
    O relatório é salvo em logs\investigacao-AAAAMMDD-HHMMSS.txt.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\investigate-process.ps1 -Name "programa.exe"
#>
[CmdletBinding()]
param([string]$Name = "Windows Driver Foundation (WDM).exe")

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Report = Join-Path $LogDir ("investigacao-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$Suspicious = New-Object System.Collections.Generic.List[string]

function Write-Report([string]$Text) {
    Write-Host $Text
    Add-Content -Path $Report -Value $Text -Encoding UTF8
}

function Contains-Text([string]$Haystack, [string]$Needle) {
    # IndexOf em vez de -like: nomes com [ ] ( ) não viram curingas.
    return ($Haystack -and $Needle -and $Haystack.IndexOf($Needle, [StringComparison]::OrdinalIgnoreCase) -ge 0)
}

$UserWritable = @($env:LOCALAPPDATA, $env:APPDATA, $env:TEMP, $env:ProgramData, "C:\Users\Public") | Where-Object { $_ }
function Test-UserWritable([string]$Text) {
    foreach ($dir in $UserWritable) { if (Contains-Text $Text $dir) { return $true } }
    return $false
}

$Targets = New-Object System.Collections.Generic.List[string]  # caminhos e pastas a procurar na inicialização
$Targets.Add($Name)

Write-Report "Investigação de processo suspeito - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Report "Alvo: $Name"
Write-Report "Modo: somente leitura (nada é encerrado, apagado, executado ou enviado)"
Write-Report ""

# 1. Processos ------------------------------------------------------------------
Write-Report "== 1. Processos em execução =="
$escaped = $Name.Replace("'", "''")
$procs = @(Get-CimInstance Win32_Process -Filter "Name='$escaped'" -ErrorAction SilentlyContinue)
if ($procs.Count -eq 0) {
    Write-Report "  Nenhum processo com esse nome em execução agora."
}
foreach ($p in $procs) {
    Write-Report "  PID $($p.ProcessId) - iniciado em $($p.CreationDate)"
    Write-Report "    Caminho        : $($p.ExecutablePath)"
    Write-Report "    Linha de comando: $($p.CommandLine)"
    try {
        $owner = Invoke-CimMethod -InputObject $p -MethodName GetOwner -ErrorAction Stop
        Write-Report "    Usuário        : $($owner.Domain)\$($owner.User)"
    } catch { Write-Report "    Usuário        : (sem acesso)" }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)" -ErrorAction SilentlyContinue
    if ($parent) {
        Write-Report "    Processo pai   : PID $($parent.ProcessId) $($parent.Name) - $($parent.ExecutablePath)"
        Write-Report "                     $($parent.CommandLine)"
    } else {
        Write-Report "    Processo pai   : PID $($p.ParentProcessId) (já encerrado)"
    }
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.ProcessId)" -ErrorAction SilentlyContinue)
    foreach ($c in $children) { Write-Report "    Processo filho : PID $($c.ProcessId) $($c.Name) - $($c.ExecutablePath)" }
    $tcp = @(Get-NetTCPConnection -OwningProcess $p.ProcessId -ErrorAction SilentlyContinue)
    if ($tcp.Count -eq 0) { Write-Report "    Conexões TCP   : nenhuma no momento" }
    foreach ($t in $tcp) {
        Write-Report ("    Conexão TCP    : {0}:{1} -> {2}:{3} ({4})" -f $t.LocalAddress, $t.LocalPort, $t.RemoteAddress, $t.RemotePort, $t.State)
    }
    $udp = @(Get-NetUDPEndpoint -OwningProcess $p.ProcessId -ErrorAction SilentlyContinue)
    foreach ($u in $udp) { Write-Report ("    Porta UDP      : {0}:{1}" -f $u.LocalAddress, $u.LocalPort) }
    if ($p.ExecutablePath) {
        $Targets.Add($p.ExecutablePath)
        $Targets.Add((Split-Path -Parent $p.ExecutablePath))
    }
    if ($p.ExecutablePath -and (Test-UserWritable $p.ExecutablePath) -and ($Name -match "Windows|Microsoft|svchost|Driver")) {
        $Suspicious.Add("Processo com nome de componente do sistema executando de pasta do usuário: $($p.ExecutablePath)")
    }
    Write-Report ""
}

# 2 e 3. Arquivos ---------------------------------------------------------------
Write-Report "== 2. Arquivos com esse nome em pastas de usuário =="
$files = New-Object System.Collections.Generic.List[string]
foreach ($p in $procs) { if ($p.ExecutablePath -and (Test-Path -LiteralPath $p.ExecutablePath)) { $files.Add($p.ExecutablePath) } }
foreach ($dir in $UserWritable) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    Get-ChildItem -LiteralPath $dir -Recurse -Depth 6 -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $Name } |
        ForEach-Object { if (-not $files.Contains($_.FullName)) { $files.Add($_.FullName) } }
}
if ($files.Count -eq 0) { Write-Report "  Nenhum arquivo encontrado." }
foreach ($path in $files) {
    $item = Get-Item -LiteralPath $path -Force
    Write-Report "  Arquivo: $path"
    Write-Report ("    Tamanho     : {0:N0} bytes" -f $item.Length)
    Write-Report "    Criado em   : $($item.CreationTime)"
    Write-Report "    Modificado  : $($item.LastWriteTime)"
    Write-Report "    Atributos   : $($item.Attributes)"
    $v = $item.VersionInfo
    Write-Report "    Empresa     : $($v.CompanyName)"
    Write-Report "    Produto     : $($v.ProductName) $($v.ProductVersion)"
    Write-Report "    Descrição   : $($v.FileDescription)"
    Write-Report "    Nome original: $($v.OriginalFilename)"
    $sig = Get-AuthenticodeSignature -LiteralPath $path
    $signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "(nenhum)" }
    Write-Report "    Assinatura  : $($sig.Status) - $signer"
    if ($sig.Status -ne "Valid") { $Suspicious.Add("Arquivo sem assinatura digital válida: $path ($($sig.Status))") }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    Write-Report "    SHA-256     : $hash"
    Write-Report "    Consulta manual: https://www.virustotal.com/gui/file/$hash"
    $folder = Split-Path -Parent $path
    if (-not $Targets.Contains($folder)) { $Targets.Add($folder) }
    Write-Report "    Executáveis/scripts na mesma pasta (somente esta pasta):"
    Get-ChildItem -LiteralPath $folder -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in ".exe", ".dll", ".js", ".vbs", ".ps1", ".bat", ".cmd", ".scr", ".lnk" } |
        ForEach-Object { Write-Report ("      {0,-50} {1,12:N0} bytes  {2}" -f $_.Name, $_.Length, $_.LastWriteTime) }
    Write-Report ""
}

# 4. Inicialização automática ---------------------------------------------------
Write-Report "== 3. Inicialização automática que aponta para o alvo =="
$found = $false
function Test-Target([string]$Text) {
    foreach ($t in $Targets) { if (Contains-Text $Text $t) { return $true } }
    return $false
}

$runKeys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce"
)
$allRun = New-Object System.Collections.Generic.List[string]
foreach ($key in $runKeys) {
    $props = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
    if (-not $props) { continue }
    foreach ($prop in $props.PSObject.Properties) {
        if ($prop.Name -like "PS*") { continue }
        $line = "$key -> $($prop.Name) = $($prop.Value)"
        $allRun.Add($line)
        if (Test-Target "$($prop.Value)") { Write-Report "  [REGISTRO] $line"; $found = $true }
    }
}

$shell = New-Object -ComObject WScript.Shell
$startupDirs = @([Environment]::GetFolderPath("Startup"), [Environment]::GetFolderPath("CommonStartup"))
$allStartup = New-Object System.Collections.Generic.List[string]
foreach ($dir in $startupDirs) {
    Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $target = ""
        if ($_.Extension -eq ".lnk") {
            $lnk = $shell.CreateShortcut($_.FullName)  # apenas leitura do atalho; nada é salvo
            $target = "$($lnk.TargetPath) $($lnk.Arguments)"
        }
        $line = "$($_.FullName) -> $target"
        $allStartup.Add($line)
        if ((Test-Target $line)) { Write-Report "  [INICIALIZAR] $line"; $found = $true }
    }
}

$taskLines = New-Object System.Collections.Generic.List[string]
foreach ($task in @(Get-ScheduledTask -ErrorAction SilentlyContinue)) {
    foreach ($action in @($task.Actions)) {
        $cmd = "$($action.Execute) $($action.Arguments)"
        if (-not $action.Execute) { continue }
        $line = "$($task.TaskPath)$($task.TaskName) [$($task.State)] -> $cmd"
        if (Test-Target $cmd) { Write-Report "  [TAREFA] $line"; $found = $true }
        elseif (Test-UserWritable $cmd) { $taskLines.Add($line) }
    }
}

foreach ($svc in @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue)) {
    if (Test-Target "$($svc.PathName)") {
        Write-Report "  [SERVIÇO] $($svc.Name) ($($svc.State), $($svc.StartMode)) -> $($svc.PathName)"
        $found = $true
    }
}

try {
    $consumers = @(Get-CimInstance -Namespace root\subscription -ClassName CommandLineEventConsumer -ErrorAction Stop)
    foreach ($c in $consumers) {
        if (Test-Target "$($c.CommandLineTemplate) $($c.ExecutablePath)") {
            Write-Report "  [WMI] $($c.Name) -> $($c.CommandLineTemplate)"
            $found = $true
        }
    }
} catch {
    Write-Report "  (Assinaturas WMI não puderam ser lidas sem administrador.)"
}
if (-not $found) { Write-Report "  Nenhuma entrada de inicialização visível aponta para o alvo." }
else { $Suspicious.Add("O alvo é iniciado automaticamente (veja a seção 3).") }
Write-Report ""

Write-Report "== 4. Contexto: tudo que inicia automaticamente =="
Write-Report "  Chaves Run/RunOnce:"
if ($allRun.Count -eq 0) { Write-Report "    (nenhuma)" }
foreach ($l in $allRun) { Write-Report "    $l" }
Write-Report "  Pastas Inicializar:"
if ($allStartup.Count -eq 0) { Write-Report "    (vazias)" }
foreach ($l in $allStartup) { Write-Report "    $l" }
Write-Report "  Tarefas agendadas que executam de pastas graváveis pelo usuário:"
if ($taskLines.Count -eq 0) { Write-Report "    (nenhuma)" }
foreach ($l in $taskLines) { Write-Report "    $l" }
Write-Report ""

# 6. Defender -------------------------------------------------------------------
Write-Report "== 5. Microsoft Defender =="
try {
    $mp = Get-MpComputerStatus -ErrorAction Stop
    Write-Report "  Proteção em tempo real : $($mp.RealTimeProtectionEnabled)"
    Write-Report "  Assinaturas atualizadas: $($mp.AntivirusSignatureLastUpdated)"
    Write-Report "  Última verificação completa: $($mp.FullScanEndTime)"
} catch { Write-Report "  Estado indisponível: $($_.Exception.Message)" }
try {
    $detections = @(Get-MpThreatDetection -ErrorAction Stop)
    if ($detections.Count -eq 0) { Write-Report "  Nenhuma detecção registrada." }
    foreach ($d in $detections) {
        Write-Report "  Detecção em $($d.InitialDetectionTime): ThreatID $($d.ThreatID) - $($d.Resources -join '; ')"
    }
} catch { Write-Report "  Histórico de detecções indisponível sem administrador." }
Write-Report ""

Write-Report "== Resumo =="
if ($Suspicious.Count -eq 0) { Write-Report "  Nenhum indicador forte encontrado pelas verificações acima." }
foreach ($s in $Suspicious) { Write-Report "  [!] $s" }
Write-Report ""
Write-Report "Nada foi alterado. Próximo passo recomendado: Segurança do Windows > Proteção contra"
Write-Report "vírus e ameaças > Opções de verificação > Verificação offline do Microsoft Defender."
Write-Report "Relatório salvo em: $Report"
Start-Process notepad.exe $Report
