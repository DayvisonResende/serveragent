"""Estado atual e histórico recente das métricas, mantidos em memória.

É a fonte de leitura da API e do dashboard: consultas ao estado atual nunca
tocam o disco. O histórico em resolução total cobre ``live_history_seconds``;
períodos maiores vêm do banco (dados agregados).
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sentinel.core.clock import to_iso
from sentinel.modules.monitor.cpu import CpuSample
from sentinel.modules.monitor.disk import DiskReport
from sentinel.modules.monitor.memory import MemorySample
from sentinel.modules.monitor.network import NetworkSample
from sentinel.modules.monitor.processes import ProcessInfo
from sentinel.modules.monitor.temperature import TemperatureReading

log = logging.getLogger(__name__)


def epoch_iso(epoch: float) -> str:
    return to_iso(datetime.fromtimestamp(epoch, timezone.utc))


@dataclass(frozen=True, slots=True)
class FastSample:
    ts_epoch: float
    cpu: CpuSample
    memory: MemorySample
    network: NetworkSample

    def as_dict(self, include_interfaces: bool = False) -> dict[str, Any]:
        return {
            "timestamp": epoch_iso(self.ts_epoch),
            "ts_epoch": self.ts_epoch,
            "cpu": self.cpu.as_dict(),
            "memory": self.memory.as_dict(),
            "network": self.network.as_dict(include_interfaces=include_interfaces),
        }

    def point(self) -> dict[str, Any]:
        """Ponto compacto para gráficos."""
        return {
            "t": self.ts_epoch,
            "cpu": self.cpu.percent,
            "ram": self.memory.percent,
            "up": self.network.upload_bps,
            "down": self.network.download_bps,
        }


SampleListener = Callable[[FastSample], None]


class MetricsStore:
    def __init__(self, live_capacity: int) -> None:
        if live_capacity < 2:
            raise ValueError("live_capacity deve ser >= 2")
        self.static: dict[str, Any] | None = None
        self.latest: FastSample | None = None
        self.history: deque[FastSample] = deque(maxlen=live_capacity)
        self.disks: DiskReport | None = None
        self.disks_at: float | None = None
        self.processes: list[ProcessInfo] = []
        self.processes_at: float | None = None
        self.temperature: TemperatureReading | None = None
        self.temperature_at: float | None = None
        self._window: list[FastSample] = []
        self._listeners: list[SampleListener] = []

    def add_fast(self, sample: FastSample) -> None:
        self.latest = sample
        self.history.append(sample)
        self._window.append(sample)
        for listener in list(self._listeners):
            try:
                listener(sample)
            except Exception:
                log.exception("Ouvinte de métricas falhou")

    def take_window(self) -> list[FastSample]:
        """Entrega e esvazia as amostras acumuladas desde a última gravação."""
        window, self._window = self._window, []
        return window

    def add_listener(self, listener: SampleListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def live_points(self, since_epoch: float) -> list[dict[str, Any]]:
        return [s.point() for s in self.history if s.ts_epoch >= since_epoch]

    @property
    def live_span_seconds(self) -> float:
        if len(self.history) < 2:
            return 0.0
        return self.history[-1].ts_epoch - self.history[0].ts_epoch
