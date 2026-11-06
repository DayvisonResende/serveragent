"""Reconhece quais processos pertencem a um servidor cadastrado."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import psutil

from sentinel.modules.monitor.processes import ProcessInfo
from sentinel.modules.servers.models import ProcessMatch
from sentinel.oslayer.process_control import normalize_path

# Um critério que reconhece processos demais (ex.: só "svchost.exe") é amplo demais para operar.
MAX_MATCHED_PROCESSES = 30


@dataclass(frozen=True, slots=True)
class MatchResult:
    pids: list[int]
    main_pid: int | None
    processes: list[ProcessInfo]

    @property
    def alive(self) -> bool:
        return bool(self.pids)

    @property
    def too_broad(self) -> bool:
        return len(self.pids) > MAX_MATCHED_PROCESSES


def _matches(proc: ProcessInfo, match: ProcessMatch, exe_norm: str | None) -> bool:
    if match.exe_path:
        if normalize_path(proc.exe) != exe_norm:
            return False
    if match.name and (proc.name or "").lower() != match.name.lower():
        return False
    if match.cmdline_contains:
        if not proc.cmdline:
            return False
        joined = "\x00".join(proc.cmdline).lower()
        if not all(part.lower() in joined for part in match.cmdline_contains):
            return False
    return True


def find_server_processes(
    processes: Iterable[ProcessInfo],
    match: ProcessMatch,
    port: int | None,
    listeners: dict[int, set[int | None]],
) -> MatchResult:
    procs = [p for p in processes if p.status != "zombie"]  # zumbi = processo já encerrado
    port_pids = {p for p in listeners.get(port, set()) if p is not None} if port else set()
    has_process_criteria = bool(match.exe_path or match.name or match.cmdline_contains)

    if has_process_criteria:
        exe_norm = normalize_path(match.exe_path)
        candidates = [p for p in procs if _matches(p, match, exe_norm)]
        # Exigir o dono da porta só quando o SO informa os PIDs (no Linux sem root eles vêm vazios).
        if match.port_owner and port_pids:
            candidates = [p for p in candidates if p.pid in port_pids]
    elif match.port_owner:
        candidates = [p for p in procs if p.pid in port_pids]
    else:
        candidates = []

    by_pid = {p.pid: p for p in candidates}
    # Processo principal: o que não tem pai entre os reconhecidos (raiz); empate → o mais antigo.
    roots = [p for p in candidates if p.ppid not in by_pid]
    roots.sort(key=lambda p: p.create_time if p.create_time is not None else float("inf"))
    main = roots[0].pid if roots else None

    # Descendentes entram na conta (ex.: java.exe iniciado pelo .bat, workers do node).
    children: dict[int, list[ProcessInfo]] = {}
    for p in procs:
        if p.ppid is not None:
            children.setdefault(p.ppid, []).append(p)
    stack = list(by_pid)
    while stack and len(by_pid) <= MAX_MATCHED_PROCESSES * 2:
        for child in children.get(stack.pop(), []):
            if child.pid not in by_pid:
                by_pid[child.pid] = child
                stack.append(child.pid)
    return MatchResult(sorted(by_pid), main, list(by_pid.values()))


def _still_running(proc: ProcessInfo) -> bool:
    try:
        live = psutil.Process(proc.pid)
        if proc.create_time is not None and abs(live.create_time() - proc.create_time) > 1:
            return False  # PID reutilizado por outro processo
        return live.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True  # existe, só não podemos inspecionar


def confirm_alive(result: MatchResult) -> MatchResult:
    """Descarta processos da lista (que pode ter até 15 s) que já terminaram."""
    alive = [p for p in result.processes if _still_running(p)]
    if len(alive) == len(result.processes):
        return result
    by_pid = {p.pid: p for p in alive}
    roots = sorted((p for p in alive if p.ppid not in by_pid), key=lambda p: p.create_time or float("inf"))
    return MatchResult(sorted(by_pid), roots[0].pid if roots else None, alive)
