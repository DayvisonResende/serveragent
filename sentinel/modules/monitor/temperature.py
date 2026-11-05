"""Temperatura (PRD 5.6). Nunca estima: sem sensor legível, informa indisponibilidade.

No Windows o psutil não expõe sensores, e a alternativa via WMI
(MSAcpi_ThermalZoneTemperature) exige administrador e raramente reflete a CPU.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import psutil

log = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "Sensor de temperatura indisponível."


@dataclass(frozen=True, slots=True)
class TemperatureReading:
    available: bool
    sensors: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["message"] = None if self.available else UNAVAILABLE_MESSAGE
        return data


def read_temperatures() -> TemperatureReading:
    reader = getattr(psutil, "sensors_temperatures", None)
    if reader is None:
        return TemperatureReading(False, reason="O sistema operacional não expõe sensores ao psutil.")
    try:
        groups = reader()
    except (OSError, RuntimeError) as exc:
        log.warning("Falha ao ler sensores de temperatura", extra={"error": str(exc)})
        return TemperatureReading(False, reason=f"Falha na leitura: {exc}")
    sensors = [
        {"group": group, "label": entry.label or group, "current": entry.current, "high": entry.high, "critical": entry.critical}
        for group, entries in groups.items()
        for entry in entries
        if entry.current is not None
    ]
    if not sensors:
        return TemperatureReading(False, reason="Nenhum sensor reportado pelo hardware/driver.")
    return TemperatureReading(True, sensors)
