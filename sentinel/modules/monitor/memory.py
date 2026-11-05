"""Coleta de memória (PRD 5.3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import psutil


@dataclass(frozen=True, slots=True)
class MemorySample:
    total: int
    available: int
    used: int
    percent: float
    swap_total: int
    swap_used: int
    swap_percent: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_memory() -> MemorySample:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()  # no Windows reflete o arquivo de paginação
    return MemorySample(
        total=vm.total,
        available=vm.available,
        used=vm.total - vm.available,  # "em uso" coerente com o Gerenciador de Tarefas
        percent=round(vm.percent, 1),
        swap_total=sw.total,
        swap_used=sw.used,
        swap_percent=round(sw.percent, 1),
    )
