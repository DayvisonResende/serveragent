"""Modo de baixa prioridade (PRD 2.2 e 13.3).

Recebe as amostras rápidas de CPU/RAM, calcula uma média móvel e decide o
nível de pressão da máquina. Em pressão, as tarefas não essenciais do
agendador são desaceleradas; módulos futuros (análise de armazenamento, IA)
consultam ``level`` para adiar trabalho pesado.

A saída de um nível exige cair abaixo do limite menos a histerese, para que o
modo não fique oscilando.
"""

from __future__ import annotations

import logging
from collections import deque
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sentinel.core.event_bus import Event, EventBus, Severity

if TYPE_CHECKING:
    from sentinel.agent.config import ResourceSettings
    from sentinel.agent.scheduler import Scheduler

log = logging.getLogger(__name__)

EVENT_PRESSURE_CHANGED = "resources.pressure_changed"


class PressureLevel(StrEnum):
    NORMAL = "normal"
    PRESSURE = "pressure"
    SEVERE = "severe"


_ORDER = {PressureLevel.NORMAL: 0, PressureLevel.PRESSURE: 1, PressureLevel.SEVERE: 2}
_LABEL = {
    PressureLevel.NORMAL: "normal",
    PressureLevel.PRESSURE: "sob pressão",
    PressureLevel.SEVERE: "sob pressão severa",
}


class ResourceManager:
    def __init__(self, settings: ResourceSettings, scheduler: Scheduler, event_bus: EventBus) -> None:
        self._s = settings
        self._scheduler = scheduler
        self._bus = event_bus
        self._cpu: deque[float] = deque(maxlen=settings.smoothing_samples)
        self._mem: deque[float] = deque(maxlen=settings.smoothing_samples)
        self.level = PressureLevel.NORMAL

    @property
    def under_pressure(self) -> bool:
        return self.level is not PressureLevel.NORMAL

    def update(self, cpu_percent: float, memory_percent: float) -> PressureLevel:
        self._cpu.append(cpu_percent)
        self._mem.append(memory_percent)
        cpu = sum(self._cpu) / len(self._cpu)
        mem = sum(self._mem) / len(self._mem)

        target = self._target_level(cpu, mem)
        if target is not self.level:
            self._apply(target, cpu, mem)
        return self.level

    def snapshot(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "load_factor": self._scheduler.load_factor,
            "cpu_avg": round(sum(self._cpu) / len(self._cpu), 1) if self._cpu else None,
            "memory_avg": round(sum(self._mem) / len(self._mem), 1) if self._mem else None,
        }

    def _target_level(self, cpu: float, mem: float) -> PressureLevel:
        s = self._s
        h = s.hysteresis_percent
        current = _ORDER[self.level]

        def above(value: float, limit: float, level_rank: int) -> bool:
            # Para permanecer num nível já ativo basta não cair abaixo de (limite - histerese).
            return value >= (limit - h if current >= level_rank else limit)

        if above(cpu, s.severe_cpu_percent, 2):
            return PressureLevel.SEVERE
        if above(cpu, s.pressure_cpu_percent, 1) or above(mem, s.pressure_memory_percent, 1):
            return PressureLevel.PRESSURE
        return PressureLevel.NORMAL

    def _apply(self, level: PressureLevel, cpu: float, mem: float) -> None:
        factor = {
            PressureLevel.NORMAL: 1.0,
            PressureLevel.PRESSURE: self._s.pressure_load_factor,
            PressureLevel.SEVERE: self._s.severe_load_factor,
        }[level]
        previous = self.level
        self.level = level
        self._scheduler.set_load_factor(factor)
        worsening = _ORDER[level] > _ORDER[previous]
        log.info(
            "Nível de pressão alterado",
            extra={"from": previous.value, "to": level.value, "cpu_avg": round(cpu, 1), "mem_avg": round(mem, 1)},
        )
        self._bus.publish(
            Event(
                event_type=EVENT_PRESSURE_CHANGED,
                source="core.resource_manager",
                severity=Severity.WARNING if worsening else Severity.INFO,
                title=f"Computador {_LABEL[level]}",
                description=(
                    f"CPU média {cpu:.0f}%, memória média {mem:.0f}%. "
                    + (
                        f"Tarefas não essenciais do Sentinel desaceleradas {factor:g}x."
                        if level is not PressureLevel.NORMAL
                        else "Frequência normal de coleta restabelecida."
                    )
                ),
                metadata={"from": previous.value, "to": level.value, "load_factor": factor},
            )
        )
