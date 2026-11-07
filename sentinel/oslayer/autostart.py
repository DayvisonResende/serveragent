"""Itens que iniciam automaticamente com o Windows — onde malware costuma se esconder.

Coleta somente leitura de: chaves Run/RunOnce (usuário, máquina, 32 bits),
políticas Run, Winlogon (Shell/Userinit), script de logon do usuário, AutoRun do
cmd, AppInit_DLLs, IFEO (Debugger), pastas Inicializar, tarefas agendadas e
serviços. ``assess`` aponta o que é suspeito. Fora do Windows coleta apenas as
pastas de autostart do usuário (desenvolvimento).
"""

from __future__ import annotations

import csv
import io
import logging
import ntpath
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AutostartEntry:
    location: str
    name: str
    value: str

    @property
    def key(self) -> str:
        return f"{self.location}|{self.name}"


SCRIPT_HOSTS = ("cmd.exe", "cmd ", "powershell", "pwsh", "wscript", "cscript", "mshta", "rundll32", "regsvr32", ".vbs", ".js ", ".bat", ".cmd", ".ps1")
# Nomes que imitam componentes do Windows ("update" ficou de fora: atualizadores legítimos vivem em AppData).
SYSTEM_LIKE = re.compile(r"windows|microsoft|driver|svchost|defender|system32|runtime ?broker|lsass|csrss|winlogon", re.IGNORECASE)
_USER_DIRS_PATTERN = re.compile(r"\\appdata\\|\\temp\\|\\programdata\\|\\users\\public\\|/tmp/|/\.local/", re.IGNORECASE)
# Para "nome de sistema fora do lugar": ProgramData fica de fora — o próprio Defender roda de lá.
_PERSONAL_DIRS_PATTERN = re.compile(r"\\appdata\\|\\temp\\|\\users\\public\\|/tmp/|/\.local/", re.IGNORECASE)


def assess(entry: AutostartEntry) -> list[str]:
    """Motivos para considerar o item suspeito (lista vazia = nada a apontar)."""
    reasons: list[str] = []
    value = entry.value.strip()
    low = value.lower()
    loc = entry.location.lower()
    if "winlogon" in loc and entry.name.lower() == "shell" and low not in ("explorer.exe", ""):
        reasons.append("o Shell do Winlogon deveria ser apenas explorer.exe: há outro programa iniciando junto com o Windows")
    if "winlogon" in loc and entry.name.lower() == "userinit" and low.rstrip(",") not in (r"c:\windows\system32\userinit.exe", "userinit.exe", ""):
        reasons.append("o Userinit do Winlogon foi alterado")
    if "ifeo" in loc:
        reasons.append("um Debugger em IFEO desvia a execução de outro programa")
    if "appinit" in loc and value:
        reasons.append("AppInit_DLLs injeta DLLs em todos os programas")
    if "autorun" in loc and value:
        reasons.append("o AutoRun do cmd executa algo sempre que um prompt abre")
    if "userinitmprlogonscript" in loc:
        reasons.append("script de logon do usuário configurado")
    in_user_dir = bool(_USER_DIRS_PATTERN.search(value))
    if in_user_dir and any(host in low for host in SCRIPT_HOSTS):
        reasons.append("executa um interpretador/script a partir de uma pasta do usuário")
    in_personal_dir = bool(_PERSONAL_DIRS_PATTERN.search(value))
    exe_name = ntpath.basename(value.strip('"').split('"')[0].split(" /")[0])
    if in_personal_dir and (SYSTEM_LIKE.search(entry.name) or SYSTEM_LIKE.search(exe_name)):
        reasons.append("nome de componente do sistema, mas o arquivo está numa pasta do usuário")
    return reasons



_SERVICE_VALUE = re.compile(r"^(?P<path>.*) \[início: (?P<start>[\w-]+)\]$", re.DOTALL)
_WINDOWS_BINARY = re.compile(r"^\"?[a-z]:\\windows\\(system32|syswow64)\\", re.IGNORECASE)
_ROUTINE_START_TYPES = {"automatic", "manual"}


def is_routine_change(location: str, old_value: str, new_value: str) -> bool:
    """Mudança que o próprio Windows faz sozinho e não merece alerta.

    Caso real (BITS): o Windows Update alterna o início do serviço entre
    automático e manual quase todo dia. Só vale quando o programa do serviço é o
    mesmo e fica em System32/SysWOW64; ativar um serviço desativado ("disabled")
    ou trocar o programa continua gerando alerta.
    """
    if location != "Serviço":
        return False
    old, new = _SERVICE_VALUE.match(old_value or ""), _SERVICE_VALUE.match(new_value or "")
    if not old or not new or old["path"] != new["path"] or not _WINDOWS_BINARY.match(new["path"].strip()):
        return False
    return {old["start"], new["start"]} <= _ROUTINE_START_TYPES

def source_of(location: str) -> str:
    """Fonte (para linha de base e falhas) a partir do local do item."""
    if location.startswith("HK"):
        return "registro"
    if location.startswith("Inicializar"):
        return "pastas Inicializar"
    if location == "Tarefa agendada":
        return "tarefas agendadas"
    if location == "Serviço":
        return "serviços"
    return "pastas de autostart"


@dataclass
class CollectResult:
    entries: list[AutostartEntry]
    failed_sources: set[str]          # fonte inteira indisponível: nada é concluído sobre ela
    warnings: list[str]               # leituras parciais (ex.: uma chave sem permissão)
    sources: set[str]                 # fontes consultadas

    @property
    def errors(self) -> list[str]:
        return [f"{s}: indisponível" for s in sorted(self.failed_sources)] + self.warnings


def collect() -> CollectResult:
    """Cada fonte é independente; dentro do registro, cada chave também."""
    result = CollectResult([], set(), [], set())
    sources = _windows_sources() if sys.platform == "win32" else [("pastas de autostart", _posix_autostart)]
    for label, source in sources:
        result.sources.add(label)
        try:
            found = source(result.warnings)
        except Exception as exc:  # a fonte inteira falhou; o motivo vai para o relatório
            result.failed_sources.add(label)
            result.warnings.append(f"{label}: {type(exc).__name__}: {exc}")
            log.warning("Fonte de inicialização automática falhou", extra={"source": label, "error": str(exc)})
            continue
        result.entries.extend(found)
    unique = {e.key: e for e in result.entries}
    result.entries = list(unique.values())
    return result


# --------------------------------------------------------------------- Windows

def _windows_sources() -> list[tuple[str, object]]:
    return [
        ("registro", _registry),
        ("pastas Inicializar", _startup_folders),
        ("tarefas agendadas", _scheduled_tasks),
        ("serviços", _services),
    ]


def _registry(warnings: list[str]) -> list[AutostartEntry]:
    import winreg

    HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
    cv = r"Software\Microsoft\Windows\CurrentVersion"
    wow = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion"
    nt = r"Software\Microsoft\Windows NT\CurrentVersion"
    multi = [
        ("HKCU\\Run", HKCU, cv + r"\Run"), ("HKCU\\RunOnce", HKCU, cv + r"\RunOnce"),
        ("HKLM\\Run", HKLM, cv + r"\Run"), ("HKLM\\RunOnce", HKLM, cv + r"\RunOnce"),
        ("HKLM\\Run (32 bits)", HKLM, wow + r"\Run"), ("HKLM\\RunOnce (32 bits)", HKLM, wow + r"\RunOnce"),
        ("HKCU\\Policies\\Run", HKCU, cv + r"\Policies\Explorer\Run"), ("HKLM\\Policies\\Run", HKLM, cv + r"\Policies\Explorer\Run"),
    ]
    single = [
        ("HKLM\\Winlogon", HKLM, nt + r"\Winlogon", "Shell"), ("HKLM\\Winlogon", HKLM, nt + r"\Winlogon", "Userinit"),
        ("HKCU\\Winlogon", HKCU, nt + r"\Winlogon", "Shell"),
        ("HKCU\\Environment\\UserInitMprLogonScript", HKCU, "Environment", "UserInitMprLogonScript"),
        ("HKCU\\Command Processor\\AutoRun", HKCU, r"Software\Microsoft\Command Processor", "AutoRun"),
        ("HKLM\\Command Processor\\AutoRun", HKLM, r"Software\Microsoft\Command Processor", "AutoRun"),
        ("HKLM\\AppInit_DLLs", HKLM, nt + r"\Windows", "AppInit_DLLs"),
        ("HKCU\\Windows\\Load", HKCU, nt + r"\Windows", "Load"),
    ]
    out: list[AutostartEntry] = []
    def denied(label: str, exc: OSError) -> None:
        warnings.append(f"registro (parcial): {label}: {exc.strerror or exc}")

    for label, hive, path in multi:
        try:
            with winreg.OpenKey(hive, path) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    out.append(AutostartEntry(label, name or "(padrão)", str(value)))
                    i += 1
        except FileNotFoundError:
            continue
        except OSError as exc:  # ex.: chave protegida — as demais continuam
            denied(label, exc)
    for label, hive, path, name in single:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
                if str(value).strip():
                    out.append(AutostartEntry(label, name, str(value)))
        except FileNotFoundError:
            continue
        except OSError as exc:
            denied(f"{label}\\{name}", exc)
    try:
        with winreg.OpenKey(HKLM, nt + r"\Image File Execution Options") as ifeo:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(ifeo, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(ifeo, sub) as key:
                        debugger, _ = winreg.QueryValueEx(key, "Debugger")
                        out.append(AutostartEntry("HKLM\\IFEO", sub, str(debugger)))
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    denied(f"HKLM\\IFEO\\{sub}", exc)
    except FileNotFoundError:
        pass
    except OSError as exc:
        denied("HKLM\\IFEO", exc)
    return out


def _startup_folders(warnings: list[str]) -> list[AutostartEntry]:
    out = []
    for label, var, rel in (("Inicializar (usuário)", "APPDATA", r"Microsoft\Windows\Start Menu\Programs\Startup"),
                            ("Inicializar (todos)", "ProgramData", r"Microsoft\Windows\Start Menu\Programs\Startup")):
        base = os.environ.get(var)
        if not base:
            continue
        folder = Path(base) / rel
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            if item.name.lower() == "desktop.ini":
                continue
            st = item.stat()
            out.append(AutostartEntry(label, item.name, f"{item} ({st.st_size} bytes, modificado {int(st.st_mtime)})"))
    return out


def _scheduled_tasks(warnings: list[str]) -> list[AutostartEntry]:
    # Colunas do CSV verbose do schtasks (fixas, independentes do idioma): 1 = nome, 8 = ação.
    result = subprocess.run(
        ["schtasks", "/query", "/fo", "csv", "/v", "/nh"], capture_output=True, timeout=90,
        creationflags=0x08000000,  # CREATE_NO_WINDOW: sem janela de console
    )
    if result.returncode != 0:
        raise OSError(f"schtasks retornou {result.returncode}")
    text = result.stdout.decode("oem", errors="replace")
    out: dict[str, AutostartEntry] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) > 8 and row[1].startswith("\\"):
            out[row[1]] = AutostartEntry("Tarefa agendada", row[1], row[8])
    return list(out.values())


def _services(warnings: list[str]) -> list[AutostartEntry]:
    import psutil

    out = []
    for svc in psutil.win_service_iter():
        try:
            info = svc.as_dict()
        except (psutil.Error, OSError):
            continue
        out.append(AutostartEntry("Serviço", info["name"], f"{info.get('binpath') or ''} [início: {info.get('start_type')}]"))
    return out


# ----------------------------------------------------------------------- POSIX

def _posix_autostart(warnings: list[str]) -> list[AutostartEntry]:
    out = []
    for folder in (Path.home() / ".config" / "autostart", Path.home() / ".config" / "systemd" / "user"):
        if folder.is_dir():
            for item in folder.iterdir():
                if item.is_file():
                    out.append(AutostartEntry(f"autostart ({folder.name})", item.name, str(item)))
    return out
