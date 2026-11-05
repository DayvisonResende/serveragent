"""Coleta de processos (PRD 5.7). Somente observação.

CPU por processo é normalizada para 0–100% da máquina inteira (como no
Gerenciador de Tarefas). Na primeira vez em que um processo é visto não há
base de comparação, então sua CPU é ``None`` — nunca um 0 inventado.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import psutil

from sentinel.core.clock import to_iso

SortKey = Literal["cpu", "memory", "name", "runtime"]

_ATTRS = ["pid", "name", "exe", "username", "status", "create_time", "memory_info"]


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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProcessCollector:
    def __init__(self) -> None:
        self._cpu_count = psutil.cpu_count(logical=True) or 1
        self._seen: set[tuple[int, float | None]] = set()

    def collect(self) -> list[ProcessInfo]:
        total_memory = psutil.virtual_memory().total
        result: list[ProcessInfo] = []
        current: set[tuple[int, float | None]] = set()
        # process_iter reaproveita os objetos Process entre chamadas, o que permite
        # cpu_percent(None) medir desde a coleta anterior.
        for proc in psutil.process_iter(_ATTRS):
            info = proc.info
            pid = info["pid"]
            if pid == 0:  # "System Idle Process" (Windows) / swapper: não é um processo real
                continue
            identity = (pid, info.get("create_time"))
            current.add(identity)
            try:
                raw_cpu = proc.cpu_percent(None)
                cpu = round(raw_cpu / self._cpu_count, 1) if identity in self._seen else None
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                cpu = None
            mem = info.get("memory_info")
            rss = mem.rss if mem is not None else None
            created = info.get("create_time")
            result.append(
                ProcessInfo(
                    pid=pid,
                    name=info.get("name") or f"pid {pid}",
                    exe=info.get("exe") or None,
                    username=info.get("username"),
                    status=info.get("status"),
                    started_at=to_iso(datetime.fromtimestamp(created, timezone.utc)) if created else None,
                    create_time=created,
                    cpu_percent=cpu,
                    memory_bytes=rss,
                    memory_percent=round(rss / total_memory * 100, 2) if rss is not None and total_memory else None,
                )
            )
        self._seen = current
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
