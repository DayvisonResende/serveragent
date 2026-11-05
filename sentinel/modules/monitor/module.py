"""Módulo de monitoramento: agenda as coletas, alimenta o store, os alertas,
o gerenciador de recursos e o histórico no banco.

Toda chamada ao psutil roda numa thread (``asyncio.to_thread``) para nunca
bloquear o loop — ex.: ``disk_usage`` numa unidade lenta.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import psutil

from sentinel.core.exceptions import SchedulerError
from sentinel.core.module_registry import Module, ModuleHealth
from sentinel.database.repositories.metrics import (
    DiskUsageRow,
    MetricsRepository,
    ProcessSnapshotRow,
    SystemMetricRow,
)
from sentinel.modules.monitor.alerts import AlertEvaluator
from sentinel.modules.monitor.cpu import CpuCollector
from sentinel.modules.monitor.disk import collect_disks
from sentinel.modules.monitor.memory import collect_memory
from sentinel.modules.monitor.network import NetworkCollector
from sentinel.modules.monitor.processes import ProcessCollector, sort_processes
from sentinel.modules.monitor.store import FastSample, MetricsStore, epoch_iso
from sentinel.modules.monitor.temperature import read_temperatures
from sentinel.oslayer.hardware import cpu_model, hostname

if TYPE_CHECKING:
    from sentinel.core.context import AgentContext

log = logging.getLogger(__name__)

DAY = 86_400.0


class MonitorModule(Module):
    name = "monitor"

    def __init__(self, store: MetricsStore) -> None:
        self.store = store
        self.alerts: AlertEvaluator | None = None
        self._ctx: AgentContext | None = None
        self._repo: MetricsRepository | None = None
        self._cpu: CpuCollector | None = None
        self._net: NetworkCollector | None = None
        self._procs: ProcessCollector | None = None
        self._jobs: list[str] = []
        self._reported_disk_errors: set[str] = set()

    # ------------------------------------------------------------- ciclo de vida

    async def start(self, context: AgentContext) -> None:
        self._ctx = context
        self._repo = MetricsRepository(context.database)
        self.alerts = AlertEvaluator(context.settings.alerts, context.event_bus.publish)
        self._cpu, self._net, self._procs = await asyncio.to_thread(
            lambda: (CpuCollector(), NetworkCollector(), ProcessCollector())
        )
        self.store.static = await asyncio.to_thread(self._static_info, context)

        m = context.settings.monitoring
        timeout = m.collector_timeout_seconds
        jobs = [
            ("monitor.fast", self._collect_fast, m.fast_interval_seconds, True, True),
            ("monitor.disks", self._collect_disks, m.disk_interval_seconds, False, True),
            ("monitor.processes", self._collect_processes, m.process_interval_seconds, False, True),
            ("monitor.temperature", self._collect_temperature, m.temperature_interval_seconds, False, True),
            ("monitor.persist", self._persist, m.persist_interval_seconds, True, False),
            ("monitor.process_snapshot", self._snapshot_processes, m.process_snapshot_interval_seconds, False, False),
            ("monitor.disk_history", self._record_disk_history, m.disk_history_interval_seconds, False, False),
            ("monitor.retention", self._apply_retention, DAY, False, False),
        ]
        for name, func, interval, essential, immediately in jobs:
            context.scheduler.add_job(
                name, func, interval, timeout=timeout if name != "monitor.retention" else 300,
                essential=essential, run_immediately=immediately,
            )
            self._jobs.append(name)

    async def stop(self) -> None:
        if self._ctx is None:
            return
        for name in self._jobs:
            try:
                await self._ctx.scheduler.remove_job(name)
            except SchedulerError:
                log.warning("Tarefa já removida", extra={"job": name})
        self._jobs.clear()
        await self._persist()  # grava a janela parcial para não perder o último minuto

    def health(self) -> ModuleHealth:
        if self._ctx is None or self.store.latest is None:
            return ModuleHealth(False, "Nenhuma coleta concluída ainda")
        age = time.time() - self.store.latest.ts_epoch
        limit = self._ctx.settings.monitoring.fast_interval_seconds * 3
        if age > limit:
            return ModuleHealth(False, f"Última coleta há {age:.0f}s")
        return ModuleHealth(True, f"Última coleta há {age:.0f}s")

    # ------------------------------------------------------------------ coletas

    async def _collect_fast(self) -> None:
        assert self._ctx is not None and self.alerts is not None
        sample = await asyncio.to_thread(self._fast_sync)
        self.store.add_fast(sample)
        self._ctx.resources.update(sample.cpu.percent, sample.memory.percent)
        self.alerts.check_cpu(sample.cpu.percent)
        self.alerts.check_memory(sample.memory.percent, sample.memory.available)

    def _fast_sync(self) -> FastSample:
        assert self._cpu is not None and self._net is not None
        return FastSample(time.time(), self._cpu.collect(), collect_memory(), self._net.collect())

    async def _collect_disks(self) -> None:
        assert self.alerts is not None
        report = await asyncio.to_thread(collect_disks)
        self.store.disks, self.store.disks_at = report, time.time()
        self.alerts.check_disks(report.disks)
        for err in report.errors:
            if err["mountpoint"] not in self._reported_disk_errors:
                self._reported_disk_errors.add(err["mountpoint"])
                log.warning("Partição não pôde ser lida", extra=err)

    async def _collect_processes(self) -> None:
        assert self._procs is not None
        self.store.processes = await asyncio.to_thread(self._procs.collect)
        self.store.processes_at = time.time()

    async def _collect_temperature(self) -> None:
        self.store.temperature = await asyncio.to_thread(read_temperatures)
        self.store.temperature_at = time.time()

    # ------------------------------------------------------------- persistência

    async def _persist(self) -> None:
        if self._repo is None:
            return
        window = self.store.take_window()
        if not window:
            return
        n = len(window)
        ups = [s.network.upload_bps for s in window if s.network.upload_bps is not None]
        downs = [s.network.download_bps for s in window if s.network.download_bps is not None]
        last = window[-1]
        disks = self.store.disks.disks if self.store.disks else []
        await self._repo.add_system_metric(
            SystemMetricRow(
                ts_epoch=last.ts_epoch,
                sample_count=n,
                cpu_percent=round(sum(s.cpu.percent for s in window) / n, 2),
                cpu_percent_max=max(s.cpu.percent for s in window),
                ram_used=round(sum(s.memory.used for s in window) / n),
                ram_available=round(sum(s.memory.available for s in window) / n),
                ram_percent=round(sum(s.memory.percent for s in window) / n, 2),
                swap_used=last.memory.swap_used,
                disk_used=sum(d.used for d in disks) if disks else None,
                disk_free=sum(d.free for d in disks) if disks else None,
                network_upload=round(sum(ups) / len(ups), 1) if ups else None,
                network_download=round(sum(downs) / len(downs), 1) if downs else None,
            )
        )

    async def _snapshot_processes(self) -> None:
        assert self._repo is not None and self._ctx is not None
        procs = self.store.processes
        if not procs or self.store.processes_at is None:
            return
        n = self._ctx.settings.monitoring.process_snapshot_top_n
        chosen = {p.pid: p for p in sort_processes(procs, "cpu", n) + sort_processes(procs, "memory", n)}
        await self._repo.add_process_snapshots(
            self.store.processes_at,
            [
                ProcessSnapshotRow(p.pid, p.name, p.exe, p.cpu_percent, p.memory_bytes, p.status)
                for p in chosen.values()
            ],
        )

    async def _record_disk_history(self) -> None:
        assert self._repo is not None
        report, at = self.store.disks, self.store.disks_at
        if report is None or at is None:
            return
        await self._repo.add_disk_usage(
            at, [DiskUsageRow(d.mountpoint, d.device, d.total, d.used, d.free) for d in report.disks]
        )

    async def _apply_retention(self) -> None:
        assert self._repo is not None and self._ctx is not None
        r = self._ctx.settings.retention
        now = time.time()
        removed = {
            "system_metrics": await self._repo.purge_older_than("system_metrics", now - r.metrics_days * DAY),
            "process_snapshots": await self._repo.purge_older_than(
                "process_snapshots", now - r.process_snapshots_days * DAY
            ),
            "disk_usage_history": await self._repo.purge_older_than(
                "disk_usage_history", now - r.disk_history_days * DAY
            ),
        }
        log.info("Retenção de métricas aplicada", extra={"removed": removed})

    # --------------------------------------------------------------- utilidades

    @staticmethod
    def _static_info(context: AgentContext) -> dict[str, Any]:
        boot = psutil.boot_time()
        return {
            "hostname": hostname(),
            "os": f"{context.platform.system} {context.platform.release}",
            "os_version": context.platform.version,
            "machine": context.platform.machine,
            "cpu_model": cpu_model(),
            "cpu_cores_logical": psutil.cpu_count(logical=True),
            "cpu_cores_physical": psutil.cpu_count(logical=False),
            "memory_total": psutil.virtual_memory().total,
            "boot_time": epoch_iso(boot),
            "boot_epoch": boot,
        }
