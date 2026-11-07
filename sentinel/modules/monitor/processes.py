"""Coleta de processos (PRD 5.7). Somente observação.

CPU por processo é normalizada para 0–100% da máquina inteira (como no
Gerenciador de Tarefas). Na primeira vez em que um processo é visto não há
base de comparação, então sua CPU é ``None`` — nunca um 0 inventado.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, TypeVar

import psutil

from sentinel.core.clock import to_iso
from sentinel.oslayer import winproc

log = logging.getLogger(__name__)

SortKey = Literal["cpu", "memory", "name", "runtime"]

_T = TypeVar("_T")
# nome, caminho, usuário, pai, linha de comando — fixos durante a vida do processo
_Static = tuple[str | None, str | None, str | None, int | None, tuple[str, ...] | None]


def _safe_any(getter: Callable[[], _T]) -> _T | None:
    """Como _safe, mas um processo que acabou de encerrar também vira None."""
    try:
        return getter()
    except psutil.Error:
        return None


def _safe(getter: Callable[[], _T]) -> _T | None:
    """Lê um atributo; sem permissão (processos de sistema) devolve None. Processo encerrado propaga."""
    try:
        return getter()
    except (psutil.AccessDenied, psutil.ZombieProcess):
        return None


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    name: str
    exe: str | None
    username: str | None
    status: str | None
    started_at: str | None
    create_time: float | None
    cpu_percent: float | None
    memory_bytes: int | None
    memory_percent: float | None
    # Uso interno (reconhecer servidores). A linha de comando pode conter senhas/tokens,
    # então NUNCA é exposta pela API.
    ppid: int | None = field(default=None, repr=False)
    cmdline: tuple[str, ...] | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("cmdline")
        return data


class ProcessCollector:
    """Nome, caminho e usuário não mudam durante a vida de um processo: são lidos
    uma única vez e guardados em cache por (pid, horário de criação). A cada coleta
    só memória, estado e CPU são consultados — consultar o dono de cada processo
    é a operação mais cara no Windows."""

    def __init__(self) -> None:
        self._cpu_count = psutil.cpu_count(logical=True) or 1
        self._seen: set[tuple[int, float | None]] = set()
        self._static: dict[tuple[int, float | None], _Static] = {}
        # Windows: lista completa numa chamada só (oslayer/winproc). Desligado se falhar.
        self._fast = sys.platform == "win32"
        self._cpu_prev: dict[tuple[int, float | None], float] = {}
        self._last_wall: float | None = None

    def collect(self) -> list[ProcessInfo]:
        if self._fast:
            try:
                return self._collect_windows()
            except Exception as exc:  # qualquer surpresa no formato: volta ao caminho do psutil
                self._fast = False
                log.warning("Leitura rápida de processos indisponível; usando psutil", extra={"error": f"{type(exc).__name__}: {exc}"})
        return self._collect_psutil()

    def _collect_windows(self) -> list[ProcessInfo]:
        raw = winproc.snapshot()
        me = os.getpid()
        if not any(r.pid == me for r in raw) or len(raw) < 5:
            raise OSError("verificação de sanidade falhou (o próprio Sentinel não está na lista)")
        now = time.monotonic()
        elapsed = now - self._last_wall if self._last_wall is not None else None
        total_memory = psutil.virtual_memory().total
        result: list[ProcessInfo] = []
        times: dict[tuple[int, float | None], float] = {}
        for r in raw:
            if r.pid == 0:
                continue
            identity = (r.pid, round(r.create_time, 1) if r.create_time else None)
            static = self._static.get(identity)
            if static is None:
                static = self._read_static(r.pid, r.name, r.ppid)
            self._static[identity] = static
            name, exe, username, ppid, cmdline = static
            previous = self._cpu_prev.get(identity)
            cpu = None
            if previous is not None and elapsed:
                cpu = round(max(r.cpu_seconds - previous, 0.0) / elapsed / self._cpu_count * 100, 1)
            times[identity] = r.cpu_seconds
            result.append(ProcessInfo(
                pid=r.pid, name=name or r.name or f"pid {r.pid}", exe=exe, username=username, status="running",
                started_at=to_iso(datetime.fromtimestamp(r.create_time, timezone.utc)) if r.create_time else None,
                create_time=r.create_time, cpu_percent=cpu, memory_bytes=r.rss,
                memory_percent=round(r.rss / total_memory * 100, 2) if total_memory else None,
                ppid=ppid, cmdline=cmdline,
            ))
        for gone in self._static.keys() - times.keys():
            del self._static[gone]
        self._cpu_prev, self._last_wall = times, now
        return result

    @staticmethod
    def _read_static(pid: int, name: str, ppid: int) -> _Static:
        """Atributos fixos de um processo novo. Sem oneshot: no Windows ele dispararia a varredura cara."""
        try:
            proc = psutil.Process(pid)
        except psutil.Error:
            return (name, None, None, ppid, None)
        cmd = _safe_any(proc.cmdline)
        return (
            name,
            _safe_any(proc.exe) or None,
            _safe_any(proc.username),
            ppid,
            tuple(a[:1000] for a in cmd[:100]) if cmd else None,
        )

    def _collect_psutil(self) -> list[ProcessInfo]:
        total_memory = psutil.virtual_memory().total
        result: list[ProcessInfo] = []
        current: set[tuple[int, float | None]] = set()
        # process_iter reaproveita os objetos Process entre chamadas, o que permite
        # cpu_percent(None) medir desde a coleta anterior.
        for proc in psutil.process_iter(["pid", "create_time"]):
            pid = proc.info["pid"]
            if pid == 0:  # "System Idle Process" (Windows) / swapper: não é um processo real
                continue
            created = proc.info.get("create_time")
            identity = (pid, created)
            try:
                with proc.oneshot():
                    static = self._static.get(identity)
                    if static is None:
                        cmd = _safe(proc.cmdline)
                        static = (
                            _safe(proc.name),
                            _safe(proc.exe),
                            _safe(proc.username),
                            _safe(proc.ppid),
                            tuple(a[:1000] for a in cmd[:100]) if cmd else None,
                        )
                    mem = _safe(proc.memory_info)
                    status = _safe(proc.status)
                    raw_cpu = _safe(lambda: proc.cpu_percent(None))
            except psutil.NoSuchProcess:
                continue  # encerrou durante a leitura: não aparece, em vez de aparecer com dados parciais
            current.add(identity)
            self._static[identity] = static
            name, exe, username, ppid, cmdline = static
            cpu = round(raw_cpu / self._cpu_count, 1) if raw_cpu is not None and identity in self._seen else None
            rss = mem.rss if mem is not None else None
            result.append(
                ProcessInfo(
                    pid=pid,
                    name=name or f"pid {pid}",
                    exe=exe or None,
                    username=username,
                    status=status,
                    started_at=to_iso(datetime.fromtimestamp(created, timezone.utc)) if created else None,
                    create_time=created,
                    cpu_percent=cpu,
                    memory_bytes=rss,
                    memory_percent=round(rss / total_memory * 100, 2) if rss is not None and total_memory else None,
                    ppid=ppid,
                    cmdline=cmdline,
                )
            )
        self._seen = current
        for gone in self._static.keys() - current:
            del self._static[gone]
        return result


def sort_processes(processes: list[ProcessInfo], key: SortKey, limit: int) -> list[ProcessInfo]:
    if key == "cpu":
        ordered = sorted(processes, key=lambda p: (p.cpu_percent is not None, p.cpu_percent or 0), reverse=True)
    elif key == "memory":
        ordered = sorted(processes, key=lambda p: p.memory_bytes or 0, reverse=True)
    elif key == "runtime":  # mais antigos primeiro (maior tempo de execução)
        ordered = sorted(processes, key=lambda p: p.create_time if p.create_time is not None else float("inf"))
    elif key == "name":
        ordered = sorted(processes, key=lambda p: p.name.lower())
    else:
        raise ValueError(f"Ordenação inválida: {key}")
    return ordered[:limit]
