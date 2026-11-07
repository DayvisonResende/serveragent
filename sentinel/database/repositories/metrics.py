"""Histórico de métricas do sistema, processos e uso de disco."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sentinel.core.clock import to_iso
from sentinel.database.database import Database

RETENTION_TABLES = frozenset({"system_metrics", "process_snapshots", "disk_usage_history"})


@dataclass(frozen=True, slots=True)
class SystemMetricRow:
    ts_epoch: float
    sample_count: int
    cpu_percent: float
    cpu_percent_max: float
    ram_used: int
    ram_available: int
    ram_percent: float
    swap_used: int | None
    disk_used: int | None
    disk_free: int | None
    network_upload: float | None
    network_download: float | None


@dataclass(frozen=True, slots=True)
class ProcessSnapshotRow:
    pid: int
    process_name: str
    executable_path: str | None
    cpu_percent: float | None
    memory_bytes: int | None
    status: str | None


@dataclass(frozen=True, slots=True)
class DiskUsageRow:
    mountpoint: str
    device: str
    total: int
    used: int
    free: int


def _iso(epoch: float) -> str:
    return to_iso(datetime.fromtimestamp(epoch, timezone.utc))


class MetricsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add_system_metric(self, row: SystemMetricRow) -> int:
        return await self._db.insert(
            "INSERT INTO system_metrics (timestamp, ts_epoch, sample_count, cpu_percent, cpu_percent_max,"
            " ram_used, ram_available, ram_percent, swap_used, disk_used, disk_free, network_upload, network_download)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _iso(row.ts_epoch), row.ts_epoch, row.sample_count, row.cpu_percent, row.cpu_percent_max,
                row.ram_used, row.ram_available, row.ram_percent, row.swap_used, row.disk_used, row.disk_free,
                row.network_upload, row.network_download,
            ),
        )

    async def add_process_snapshots(self, ts_epoch: float, rows: Iterable[ProcessSnapshotRow]) -> int:
        params = [
            (_iso(ts_epoch), ts_epoch, r.pid, r.process_name, r.executable_path, r.cpu_percent, r.memory_bytes, r.status)
            for r in rows
        ]
        if not params:
            return 0

        def insert(c: sqlite3.Connection) -> int:
            c.executemany(
                "INSERT INTO process_snapshots (timestamp, ts_epoch, pid, process_name, executable_path,"
                " cpu_percent, memory_bytes, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            return len(params)

        return await self._db.run(insert)

    async def add_disk_usage(self, ts_epoch: float, rows: Iterable[DiskUsageRow]) -> int:
        params = [(_iso(ts_epoch), ts_epoch, r.mountpoint, r.device, r.total, r.used, r.free) for r in rows]
        if not params:
            return 0

        def insert(c: sqlite3.Connection) -> int:
            c.executemany(
                "INSERT INTO disk_usage_history (timestamp, ts_epoch, mountpoint, device, total, used, free)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            return len(params)

        return await self._db.run(insert)

    async def system_history(
        self, since_epoch: float, max_points: int = 500, until_epoch: float | None = None
    ) -> list[dict[str, Any]]:
        """Histórico desde ``since_epoch``, agregado em baldes para no máximo ``max_points`` pontos.

        Picos usam MAX, demais valores a média ponderada pelo número de amostras.
        """
        if max_points < 2:
            raise ValueError("max_points deve ser >= 2")
        span = max((until_epoch if until_epoch is not None else time.time()) - since_epoch, 1.0)
        bucket = max(span / max_points, 1.0)
        return await self._db.fetch_all(
            "SELECT CAST(ts_epoch / ? AS INTEGER) * ? AS t,"
            " SUM(cpu_percent * sample_count) / SUM(sample_count) AS cpu_percent,"
            " MAX(cpu_percent_max) AS cpu_percent_max,"
            " SUM(ram_percent * sample_count) / SUM(sample_count) AS ram_percent,"
            " AVG(ram_used) AS ram_used,"
            " AVG(network_upload) AS network_upload,"
            " AVG(network_download) AS network_download,"
            " SUM(sample_count) AS samples"
            " FROM system_metrics WHERE ts_epoch >= ? GROUP BY 1 ORDER BY 1",
            (bucket, bucket, since_epoch),
        )

    async def disk_growth(self, since_epoch: float) -> dict[str, dict[str, Any]]:
        """Crescimento do espaço usado por partição entre a primeira e a última medição do período."""
        rows = await self._db.fetch_all(
            "SELECT h.mountpoint, h.ts_epoch, h.used FROM disk_usage_history h"
            " JOIN (SELECT mountpoint, MIN(ts_epoch) AS first, MAX(ts_epoch) AS last"
            "       FROM disk_usage_history WHERE ts_epoch >= ? GROUP BY mountpoint) w"
            " ON h.mountpoint = w.mountpoint AND h.ts_epoch IN (w.first, w.last)"
            " ORDER BY h.mountpoint, h.ts_epoch",
            (since_epoch,),
        )
        by_mount: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_mount.setdefault(row["mountpoint"], []).append(row)
        result: dict[str, dict[str, Any]] = {}
        for mount, points in by_mount.items():
            first, last = points[0], points[-1]
            elapsed = last["ts_epoch"] - first["ts_epoch"]
            result[mount] = {
                "period_hours": round(elapsed / 3600, 2),
                "used_change_bytes": last["used"] - first["used"],
                "bytes_per_day": (last["used"] - first["used"]) / elapsed * 86_400 if elapsed >= 3600 else None,
            }
        return result

    async def processes_near(self, ts_epoch: float, window: float = 600) -> dict[str, Any]:
        """Instantâneo dos processos mais pesados mais próximo de ``ts_epoch`` (até ``window`` s de distância)."""
        row = await self._db.fetch_one(
            "SELECT ts_epoch FROM process_snapshots WHERE ts_epoch BETWEEN ? AND ?"
            " ORDER BY ABS(ts_epoch - ?) LIMIT 1",
            (ts_epoch - window, ts_epoch + window, ts_epoch),
        )
        if row is None:
            return {"snapshot_epoch": None, "processes": [], "system": None}
        snap = row["ts_epoch"]
        processes = await self._db.fetch_all(
            "SELECT pid, process_name, executable_path, cpu_percent, memory_bytes FROM process_snapshots"
            " WHERE ts_epoch = ? ORDER BY COALESCE(cpu_percent, 0) DESC, memory_bytes DESC",
            (snap,),
        )
        system = await self._db.fetch_one(
            "SELECT ts_epoch, cpu_percent, cpu_percent_max, ram_percent FROM system_metrics"
            " WHERE ts_epoch BETWEEN ? AND ? ORDER BY ABS(ts_epoch - ?) LIMIT 1",
            (ts_epoch - 120, ts_epoch + 120, ts_epoch),
        )
        return {"snapshot_epoch": snap, "processes": processes, "system": system}

    async def purge_older_than(self, table: str, cutoff_epoch: float) -> int:
        if table not in RETENTION_TABLES:
            raise ValueError(f"Tabela sem política de retenção: {table}")
        return await self._db.run(
            lambda c: c.execute(f"DELETE FROM {table} WHERE ts_epoch < ?", (cutoff_epoch,)).rowcount
        )
