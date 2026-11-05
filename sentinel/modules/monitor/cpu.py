"""Coleta de CPU (PRD 5.2).

O uso é calculado pela diferença entre duas leituras de ``cpu_times()``,
guardadas por este coletor. Não usamos ``psutil.cpu_percent(None)`` porque o
estado interno dele é compartilhado e, chamado de threads diferentes, produziu
leituras alternadas de 0% — um valor falso.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

import psutil

log = logging.getLogger(__name__)

# A primeira medição precisa de uma janela mínima; janelas de poucos ms dão 0% ou 100%.
MIN_FIRST_WINDOW_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class CpuSample:
    percent: float
    per_core: list[float | None]  # None: núcleo sem intervalo mensurável nesta leitura
    frequency_mhz: float | None
    frequency_max_mhz: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def busy_percent(previous: Any, current: Any) -> float | None:
    """Percentual ocupado entre duas leituras de ``cpu_times``. None se não houve intervalo."""
    total = sum(current) - sum(previous)
    if total <= 0:
        return None
    idle = (current.idle - previous.idle) + (getattr(current, "iowait", 0.0) - getattr(previous, "iowait", 0.0))
    return round(min(max((total - idle) / total * 100.0, 0.0), 100.0), 1)


class CpuCollector:
    def __init__(self) -> None:
        self._last_total = psutil.cpu_times()
        self._last_cores = psutil.cpu_times(percpu=True)
        self._primed_at = time.monotonic()
        self._first = True
        self._freq_available = True

    def collect(self) -> CpuSample:
        if self._first:
            wait = MIN_FIRST_WINDOW_SECONDS - (time.monotonic() - self._primed_at)
            if wait > 0:
                time.sleep(wait)  # roda numa thread de coleta, não no loop principal
            self._first = False
        total = psutil.cpu_times()
        cores = psutil.cpu_times(percpu=True)
        percent = busy_percent(self._last_total, total)
        per_core = [busy_percent(a, b) for a, b in zip(self._last_cores, cores)]
        self._last_total, self._last_cores = total, cores
        current, maximum = self._frequency()
        if percent is None:
            # Sem tempo decorrido entre as leituras: não há medição — melhor falhar do que inventar 0%.
            raise RuntimeError("Intervalo de medição de CPU nulo")
        return CpuSample(percent, per_core, current, maximum)

    def _frequency(self) -> tuple[float | None, float | None]:
        if not self._freq_available:
            return None, None
        try:
            freq = psutil.cpu_freq()
        except (OSError, NotImplementedError, AttributeError) as exc:
            log.warning("Frequência da CPU indisponível", extra={"error": str(exc)})
            self._freq_available = False
            return None, None
        if freq is None:
            self._freq_available = False
            return None, None
        maximum = round(freq.max, 0) if freq.max else None
        return round(freq.current, 0), maximum
