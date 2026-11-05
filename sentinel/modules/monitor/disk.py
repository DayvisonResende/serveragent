"""Coleta de armazenamento (PRD 5.4)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import psutil

log = logging.getLogger(__name__)

# Sistemas de arquivos virtuais/pseudo que não representam armazenamento real.
_IGNORED_FSTYPES = frozenset({"squashfs", "tmpfs", "devtmpfs", "overlay", "proc", "sysfs", "iso9660", "udf"})


@dataclass(frozen=True, slots=True)
class DiskUsage:
    device: str
    mountpoint: str
    fstype: str
    total: int
    used: int
    free: int
    percent: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DiskReport:
    disks: list[DiskUsage]
    errors: list[dict[str, str]] = field(default_factory=list)  # partições que não puderam ser lidas

    def as_dict(self) -> dict[str, Any]:
        return {"disks": [d.as_dict() for d in self.disks], "errors": self.errors}


def collect_disks() -> DiskReport:
    disks: list[DiskUsage] = []
    errors: list[dict[str, str]] = []
    seen_devices: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        if not part.fstype or part.fstype.lower() in _IGNORED_FSTYPES or "cdrom" in part.opts:
            continue
        if part.device in seen_devices:  # mesmo dispositivo montado em vários pontos (Linux)
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError as exc:  # ex.: leitor de cartão vazio, unidade desconectada
            errors.append({"mountpoint": part.mountpoint, "error": f"{type(exc).__name__}: {exc}"})
            continue
        seen_devices.add(part.device)
        disks.append(
            DiskUsage(part.device, part.mountpoint, part.fstype, usage.total, usage.used, usage.free, round(usage.percent, 1))
        )
    return DiskReport(disks, errors)
