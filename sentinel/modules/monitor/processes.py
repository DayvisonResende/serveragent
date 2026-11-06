"""Coleta de processos (PRD 5.7). Somente observação.

CPU por processo é normalizada para 0–100% da máquina inteira (como no
Gerenciador de Tarefas). Na primeira vez em que um processo é visto não há
base de comparação, então sua CPU é ``None`` — nunca um 0 inventado.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, TypeVar

import psutil

from sentinel.core.clock import to_iso

SortKey = Literal["cpu", "memory", "name", "runtime"]

_T = TypeVar("_T")
# nome, caminho, usuário, pai, linha de comando — fixos durante a vida do processo
_Static = tuple[str | None, str | None, str | None, int | None, tuple[str, ...] | None]


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

    def collect(self) -> list[ProcessInfo]:
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
