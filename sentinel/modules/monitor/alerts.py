"""Alertas de limite (PRD 5.3, 5.4 e 18.2).

Regras para não gerar ruído:
- CPU e memória só alertam após ficarem acima do limite pelo tempo configurado;
- um alerta ativo só é considerado resolvido abaixo de (limite − histerese);
- cada mudança de estado gera exatamente um evento.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal

from sentinel.core.clock import br_number
from sentinel.core.event_bus import Event, Severity
from sentinel.modules.monitor.disk import DiskUsage
from sentinel.modules.monitor.store import epoch_iso

if TYPE_CHECKING:
    from sentinel.agent.config import AlertSettings

SOURCE = "monitor.alerts"

EVENT_CPU_HIGH = "system.cpu_high"
EVENT_CPU_NORMAL = "system.cpu_normalized"
EVENT_MEMORY_HIGH = "system.memory_high"
EVENT_MEMORY_NORMAL = "system.memory_normalized"
EVENT_DISK_LOW = "system.disk_space_low"
EVENT_DISK_RECOVERED = "system.disk_space_recovered"

DiskLevel = Literal["ok", "warning", "critical"]
_DISK_RANK = {"ok": 0, "warning": 1, "critical": 2}


@dataclass
class _Sustained:
    active: bool = False
    exceeded_since: float | None = None
    active_since: float | None = None

    def evaluate(self, value: float, limit: float, sustain: float, hysteresis: float, now: float) -> str | None:
        if not self.active:
            if value >= limit:
                if self.exceeded_since is None:
                    self.exceeded_since = now
                if now - self.exceeded_since >= sustain:
                    self.active = True
                    self.active_since = now
                    return "activate"
            else:
                self.exceeded_since = None
        elif value < limit - hysteresis:
            self.active = False
            self.exceeded_since = None
            self.active_since = None
            return "clear"
        return None


class AlertEvaluator:
    def __init__(
        self,
        settings: AlertSettings,
        publish: Callable[[Event], bool],
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._s = settings
        self._publish = publish
        self._clock = clock
        self._wall = wall_clock
        self._cpu = _Sustained()
        self._mem = _Sustained()
        self._disk: dict[str, DiskLevel] = {}
        self._active_since_wall: dict[str, float] = {}

    def check_cpu(self, percent: float) -> None:
        s = self._s
        change = self._cpu.evaluate(percent, s.cpu_percent, s.cpu_sustained_seconds, s.hysteresis_percent, self._clock())
        if change == "activate":
            self._active_since_wall["cpu"] = self._wall()
            self._emit(
                EVENT_CPU_HIGH, Severity.HIGH, "Uso de CPU elevado",
                f"CPU em {percent:.0f}% (limite {s.cpu_percent:.0f}%) por pelo menos {s.cpu_sustained_seconds:.0f}s.",
                {"cpu_percent": percent, "limit": s.cpu_percent},
            )
        elif change == "clear":
            self._active_since_wall.pop("cpu", None)
            self._emit(EVENT_CPU_NORMAL, Severity.INFO, "Uso de CPU normalizado", f"CPU em {percent:.0f}%.", {"cpu_percent": percent})

    def check_memory(self, percent: float, available_bytes: int) -> None:
        s = self._s
        change = self._mem.evaluate(
            percent, s.memory_percent, s.memory_sustained_seconds, s.hysteresis_percent, self._clock()
        )
        available_gb = available_bytes / 1024**3
        if change == "activate":
            self._active_since_wall["memory"] = self._wall()
            self._emit(
                EVENT_MEMORY_HIGH, Severity.HIGH, "Memória quase esgotada",
                f"Memória em {percent:.0f}% (limite {s.memory_percent:.0f}%); {br_number(available_gb)} GB disponíveis.",
                {"memory_percent": percent, "available_bytes": available_bytes, "limit": s.memory_percent},
            )
        elif change == "clear":
            self._active_since_wall.pop("memory", None)
            self._emit(
                EVENT_MEMORY_NORMAL, Severity.INFO, "Uso de memória normalizado",
                f"Memória em {percent:.0f}%; {br_number(available_gb)} GB disponíveis.", {"memory_percent": percent},
            )

    def check_disks(self, disks: Iterable[DiskUsage]) -> None:
        s = self._s
        for disk in disks:
            if disk.total <= 0:
                continue
            free_pct = disk.free / disk.total * 100
            current = self._disk.get(disk.mountpoint, "ok")
            new = self._disk_level(free_pct, current)
            if new == current:
                continue
            self._disk[disk.mountpoint] = new
            key = f"disk:{disk.mountpoint}"
            free_gb = disk.free / 1024**3
            meta = {"mountpoint": disk.mountpoint, "free_percent": round(free_pct, 1), "free_bytes": disk.free}
            if _DISK_RANK[new] > _DISK_RANK[current]:
                self._active_since_wall.setdefault(key, self._wall())
                critical = new == "critical"
                limit = s.disk_free_critical_percent if critical else s.disk_free_warning_percent
                self._emit(
                    EVENT_DISK_LOW, Severity.CRITICAL if critical else Severity.WARNING,
                    f"Pouco espaço livre em {disk.mountpoint}",
                    f"{br_number(free_gb)} GB livres ({br_number(free_pct)}%), abaixo do limite de {br_number(limit, 0)}%.", meta,
                )
            elif new == "ok":
                self._active_since_wall.pop(key, None)
                self._emit(
                    EVENT_DISK_RECOVERED, Severity.INFO, f"Espaço livre recuperado em {disk.mountpoint}",
                    f"{br_number(free_gb)} GB livres ({br_number(free_pct)}%).", meta,
                )
            # crítico → atenção: o alerta continua ativo, sem novo evento

    def active(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._cpu.active:
            out.append(self._active_entry("cpu", "Uso de CPU elevado", Severity.HIGH))
        if self._mem.active:
            out.append(self._active_entry("memory", "Memória quase esgotada", Severity.HIGH))
        for mount, level in self._disk.items():
            if level != "ok":
                severity = Severity.CRITICAL if level == "critical" else Severity.WARNING
                out.append(self._active_entry(f"disk:{mount}", f"Pouco espaço livre em {mount}", severity))
        return out

    def _active_entry(self, key: str, title: str, severity: Severity) -> dict[str, Any]:
        since = self._active_since_wall.get(key)
        return {"key": key, "title": title, "severity": severity.value, "since": epoch_iso(since) if since else None}

    def _disk_level(self, free_pct: float, current: DiskLevel) -> DiskLevel:
        s = self._s
        h = s.hysteresis_percent
        crit_exit = s.disk_free_critical_percent + (h if current == "critical" else 0)
        warn_exit = s.disk_free_warning_percent + (h if current != "ok" else 0)
        if free_pct <= crit_exit:
            return "critical"
        if free_pct <= warn_exit:
            return "warning"
        return "ok"

    def _emit(self, event_type: str, severity: Severity, title: str, description: str, meta: dict[str, Any]) -> None:
        self._publish(
            Event(event_type=event_type, source=SOURCE, severity=severity, title=title, description=description, metadata=meta)
        )
