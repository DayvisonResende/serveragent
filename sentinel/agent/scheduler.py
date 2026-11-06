"""Agendador assíncrono leve para tarefas periódicas.

- Cada tarefa roda em seu próprio loop; uma execução nunca se sobrepõe à anterior.
- Toda execução tem tempo limite.
- Falhas consecutivas aumentam o intervalo exponencialmente (até um teto),
  evitando que uma tarefa quebrada consuma recursos em ciclo.
- ``set_load_factor`` alonga os intervalos de tarefas não essenciais quando a
  máquina está sob pressão (PRD 5.8 e 13.3). Tarefas essenciais não são afetadas.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from sentinel.core.clock import to_iso, utc_now
from sentinel.core.exceptions import SchedulerError

log = logging.getLogger(__name__)

JobFunc = Callable[[], Awaitable[None]]


@dataclass
class JobStats:
    runs: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    last_started_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_duration_seconds: float | None = None
    total_duration_seconds: float = 0.0


@dataclass
class Job:
    name: str
    func: JobFunc
    interval: float
    timeout: float
    essential: bool
    run_immediately: bool
    stats: JobStats = field(default_factory=JobStats)
    task: asyncio.Task[None] | None = None


class Scheduler:
    def __init__(
        self,
        default_timeout: float = 30.0,
        max_backoff_multiplier: float = 8.0,
        max_load_factor: float = 4.0,
    ) -> None:
        self._default_timeout = default_timeout
        self._max_backoff = max_backoff_multiplier
        self._max_load_factor = max_load_factor
        self._load_factor = 1.0
        self._jobs: dict[str, Job] = {}
        self._running = False

    @property
    def load_factor(self) -> float:
        return self._load_factor

    def add_job(
        self,
        name: str,
        func: JobFunc,
        interval: float,
        *,
        timeout: float | None = None,
        essential: bool = False,
        run_immediately: bool = False,
    ) -> None:
        if not name:
            raise SchedulerError("Tarefa sem nome")
        if name in self._jobs:
            raise SchedulerError(f"Tarefa '{name}' já agendada")
        if not inspect.iscoroutinefunction(func):
            raise SchedulerError(f"Tarefa '{name}' deve ser uma função async")
        if interval <= 0:
            raise SchedulerError(f"Intervalo da tarefa '{name}' deve ser positivo")
        effective_timeout = self._default_timeout if timeout is None else timeout
        if effective_timeout <= 0:
            raise SchedulerError(f"Tempo limite da tarefa '{name}' deve ser positivo")

        job = Job(name, func, interval, effective_timeout, essential, run_immediately)
        self._jobs[name] = job
        if self._running:
            self._spawn(job)

    async def remove_job(self, name: str) -> None:
        job = self._jobs.pop(name, None)
        if job is None:
            raise SchedulerError(f"Tarefa '{name}' não existe")
        await _cancel(job)

    def set_load_factor(self, factor: float) -> None:
        if not 1.0 <= factor <= self._max_load_factor:
            raise SchedulerError(f"Fator de carga deve estar entre 1.0 e {self._max_load_factor}")
        if factor != self._load_factor:
            log.info("Fator de carga do agendador alterado", extra={"load_factor": factor})
        self._load_factor = factor

    def effective_interval(self, name: str) -> float:
        return self._effective_interval(self._jobs[name])

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for job in self._jobs.values():
            self._spawn(job)

    async def stop(self) -> None:
        self._running = False
        await asyncio.gather(*(_cancel(job) for job in self._jobs.values()))

    def snapshot(self) -> list[dict[str, Any]]:
        out = []
        for job in self._jobs.values():
            s = job.stats
            out.append(
                {
                    "name": job.name,
                    "interval_seconds": job.interval,
                    "effective_interval_seconds": self._effective_interval(job),
                    "essential": job.essential,
                    "runs": s.runs,
                    "failures": s.failures,
                    "consecutive_failures": s.consecutive_failures,
                    "last_started_at": to_iso(s.last_started_at) if s.last_started_at else None,
                    "last_success_at": to_iso(s.last_success_at) if s.last_success_at else None,
                    "last_error": s.last_error,
                    "last_duration_seconds": s.last_duration_seconds,
                    # média em regime: a 1ª execução (aquecimento, ex.: janela inicial de CPU) não entra
                    "avg_duration_ms": round(s.total_duration_seconds / (s.runs - 1) * 1000, 1) if s.runs > 1 else None,
                    # fração aproximada de um núcleo ocupada pela tarefa (duração média / intervalo)
                    "load_share": round(s.total_duration_seconds / (s.runs - 1) / self._effective_interval(job), 4) if s.runs > 1 else None,
                }
            )
        return out

    def _effective_interval(self, job: Job) -> float:
        interval = job.interval
        if not job.essential:
            interval *= self._load_factor
        if job.stats.consecutive_failures:
            interval *= min(2.0 ** job.stats.consecutive_failures, self._max_backoff)
        return interval

    def _spawn(self, job: Job) -> None:
        job.task = asyncio.create_task(self._loop(job), name=f"sentinel-job:{job.name}")

    async def _loop(self, job: Job) -> None:
        if not job.run_immediately:
            await asyncio.sleep(self._effective_interval(job))
        while True:
            await self._run_once(job)
            await asyncio.sleep(self._effective_interval(job))

    async def _run_once(self, job: Job) -> None:
        stats = job.stats
        stats.runs += 1
        stats.last_started_at = utc_now()
        started = time.monotonic()
        try:
            await asyncio.wait_for(job.func(), job.timeout)
        except TimeoutError:
            self._record_failure(job, f"tempo limite de {job.timeout}s excedido")
            log.error("Tarefa excedeu o tempo limite", extra={"job": job.name, "timeout": job.timeout})
        except Exception as exc:
            self._record_failure(job, f"{type(exc).__name__}: {exc}")
            log.exception("Tarefa falhou", extra={"job": job.name})
        else:
            stats.consecutive_failures = 0
            stats.last_success_at = utc_now()
        finally:
            elapsed = time.monotonic() - started
            stats.last_duration_seconds = round(elapsed, 4)
            if stats.runs > 1:
                stats.total_duration_seconds += elapsed

    @staticmethod
    def _record_failure(job: Job, message: str) -> None:
        job.stats.failures += 1
        job.stats.consecutive_failures += 1
        job.stats.last_error = message


async def _cancel(job: Job) -> None:
    if job.task is None:
        return
    job.task.cancel()
    try:
        await job.task
    except asyncio.CancelledError:
        pass
    job.task = None
