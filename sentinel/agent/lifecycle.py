"""Ciclo de vida do agente: inicialização ordenada, execução e encerramento.

Ordem de inicialização:
  banco → integridade → migrações → barramento (com persistência de eventos)
  → detecção de encerramento inesperado → registro da execução
  → agendador (heartbeat) → módulos.

O encerramento percorre o caminho inverso e cada etapa é isolada: a falha de
uma etapa é registrada e não impede as seguintes. Encerrar o agente nunca
encerra processos monitorados (PRD 2.4) — o núcleo não possui código para isso.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Sequence

from sentinel import __version__
from sentinel.agent.config import Settings
from sentinel.agent.health import build_health_report
from sentinel.agent.scheduler import Scheduler
from sentinel.core.context import AgentContext
from sentinel.core.event_bus import WILDCARD, Event, EventBus, EventType, Severity
from sentinel.core.exceptions import DatabaseError
from sentinel.core.module_registry import Module, ModuleRegistry
from sentinel.core.state_manager import AgentState, StateManager
from sentinel.database.database import Database
from sentinel.database.migrations import apply_migrations
from sentinel.database.repositories import AgentRunRepository, AuditRepository, EventRepository
from sentinel.oslayer.info import PlatformInfo, get_platform_info

log = logging.getLogger(__name__)

HEARTBEAT_JOB = "agent.heartbeat"
SOURCE = "agent"


class Agent:
    def __init__(
        self,
        settings: Settings,
        modules: Sequence[Module] = (),
        platform_info: PlatformInfo | None = None,
    ) -> None:
        self.settings = settings
        self.state = StateManager()
        self.event_bus = EventBus(settings.event_bus.queue_size, settings.event_bus.handler_timeout_seconds)
        self.scheduler = Scheduler(
            settings.scheduler.default_job_timeout_seconds,
            settings.scheduler.max_backoff_multiplier,
            settings.scheduler.max_load_factor,
        )
        self.database = Database(settings.paths.database_file, settings.database.busy_timeout_ms)
        self.registry = ModuleRegistry(
            self.event_bus,
            settings.agent.module_start_timeout_seconds,
            settings.agent.module_stop_timeout_seconds,
        )
        for module in modules:
            self.registry.register(module)

        self._platform_info = platform_info
        self._events = EventRepository(self.database)
        self._audit = AuditRepository(self.database)
        self._runs = AgentRunRepository(self.database)
        self.run_id: int | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        """Inicia, aguarda ``stop_event`` e encerra. Exceções de inicialização são propagadas."""
        exit_status = "failed"
        try:
            await self._startup()
            await stop_event.wait()
            exit_status = "clean"
        except asyncio.CancelledError:
            exit_status = "interrupted"
            raise
        finally:
            await self._shutdown(exit_status)

    def health_report(self) -> dict[str, Any]:
        return build_health_report(self)

    # ------------------------------------------------------------------ início

    async def _startup(self) -> None:
        self.state.transition(AgentState.STARTING)
        platform = self._platform_info or get_platform_info()

        await self.database.open()
        if self.settings.database.integrity_check_on_start:
            result = await self.database.integrity_check()
            if result != ["ok"]:
                raise DatabaseError("Verificação de integridade do banco falhou: " + "; ".join(result[:5]))
        await apply_migrations(self.database)

        self.event_bus.subscribe(WILDCARD, self._persist_event)
        self.event_bus.start()

        for run in await self._runs.close_abandoned():
            self._publish(
                EventType.AGENT_UNCLEAN_SHUTDOWN,
                Severity.WARNING,
                "Encerramento inesperado do Sentinel detectado",
                f"A execução {run['id']} (PID {run['pid']}) não registrou término. "
                f"Último sinal de vida: {run['last_heartbeat']}.",
                {"run_id": run["id"], "pid": run["pid"], "last_heartbeat": run["last_heartbeat"]},
            )

        self.run_id = await self._runs.start(os.getpid(), __version__)

        if platform.is_admin:
            log.warning("Sentinel em execução com privilégios de administrador")
            self._publish(
                EventType.AGENT_RUNNING_AS_ADMIN,
                Severity.WARNING,
                "Sentinel em execução como administrador",
                "O Sentinel deve rodar com uma conta de privilégios limitados (PRD 17.1).",
            )

        self.scheduler.add_job(
            HEARTBEAT_JOB,
            self._heartbeat,
            self.settings.agent.heartbeat_interval_seconds,
            essential=True,
        )
        self.scheduler.start()

        context = AgentContext(self.settings, self.event_bus, self.scheduler, self.database, platform)
        await self.registry.start_all(context)

        unavailable = self.registry.unavailable_modules
        self.state.transition(AgentState.DEGRADED if unavailable else AgentState.RUNNING)

        details = {
            "version": __version__,
            "pid": os.getpid(),
            "run_id": self.run_id,
            "platform": platform.as_dict(),
            "unavailable_modules": unavailable,
        }
        self._publish(EventType.AGENT_STARTED, Severity.INFO, "Sentinel iniciado", metadata=details)
        await self._audit.record(actor="sentinel", operation="agent.start", result="success", details=details)
        log.info("Sentinel iniciado", extra={"run_id": self.run_id, "state": self.state.current.value})

    # ---------------------------------------------------------- encerramento

    async def _shutdown(self, exit_status: str) -> None:
        if self.state.current in (AgentState.STOPPING, AgentState.STOPPED):
            return
        self.state.transition(AgentState.STOPPING)
        log.info("Encerrando Sentinel", extra={"exit_status": exit_status})

        await self._step("parar módulos", self.registry.stop_all)
        await self._step("parar agendador", self.scheduler.stop)

        if self.run_id is not None:
            self._publish(
                EventType.AGENT_STOPPED,
                Severity.INFO if exit_status == "clean" else Severity.HIGH,
                "Sentinel encerrado" if exit_status == "clean" else "Sentinel encerrado com falha",
                metadata={"run_id": self.run_id, "exit_status": exit_status},
            )
            await self._step(
                "auditar encerramento",
                lambda: self._audit.record(
                    actor="sentinel",
                    operation="agent.stop",
                    result=exit_status,
                    details={"run_id": self.run_id},
                ),
            )

        await self._step(
            "esvaziar barramento", lambda: self.event_bus.stop(self.settings.agent.shutdown_timeout_seconds)
        )
        if self.run_id is not None:
            run_id = self.run_id
            await self._step("finalizar execução", lambda: self._runs.finish(run_id, exit_status))  # type: ignore[arg-type]
        await self._step("fechar banco", self.database.close)
        self.state.transition(AgentState.STOPPED)
        log.info("Sentinel encerrado", extra={"exit_status": exit_status})

    @staticmethod
    async def _step(description: str, action: Callable[[], Awaitable[Any]]) -> None:
        try:
            await action()
        except Exception:
            log.exception("Falha ao %s durante o encerramento", description)

    # ---------------------------------------------------------------- tarefas

    async def _heartbeat(self) -> None:
        if self.run_id is None:
            raise DatabaseError("Heartbeat sem execução registrada")
        await self._runs.heartbeat(self.run_id)

    async def _persist_event(self, event: Event) -> None:
        await self._events.add(event)

    def _publish(
        self,
        event_type: str,
        severity: Severity,
        title: str,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.event_bus.publish(
            Event(
                event_type=event_type,
                source=SOURCE,
                severity=severity,
                title=title,
                description=description,
                metadata=metadata or {},
            )
        )
