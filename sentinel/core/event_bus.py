"""Barramento de eventos assíncrono e não bloqueante.

``publish`` nunca bloqueia quem publica: o evento entra numa fila limitada e um
único despachante o entrega aos assinantes, em ordem. Se a fila encher, o
evento é descartado e contabilizado (e o descarte é registrado em log) — o
monitoramento nunca pode travar por causa de um assinante lento.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Awaitable, Callable, Mapping

from sentinel.core.clock import utc_now

log = logging.getLogger(__name__)

WILDCARD = "*"


class Severity(StrEnum):
    """Níveis de severidade (PRD 18.3)."""

    INFO = "info"  # Informativo
    WARNING = "warning"  # Atenção
    HIGH = "high"  # Alto
    CRITICAL = "critical"  # Crítico


class EventType:
    """Tipos de evento emitidos pelo núcleo."""

    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"
    AGENT_UNCLEAN_SHUTDOWN = "agent.unclean_shutdown"
    AGENT_RUNNING_AS_ADMIN = "agent.running_as_admin"
    MODULE_FAILED = "module.failed"
    MODULE_SKIPPED = "module.skipped"


@dataclass(frozen=True, slots=True)
class Event:
    event_type: str
    source: str
    title: str
    severity: Severity = Severity.INFO
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.event_type or not self.source or not self.title:
            raise ValueError("event_type, source e title são obrigatórios")
        if not isinstance(self.severity, Severity):
            raise ValueError(f"Severidade inválida: {self.severity!r}")


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self, queue_size: int = 1000, handler_timeout: float = 5.0) -> None:
        if queue_size < 1:
            raise ValueError("queue_size deve ser positivo")
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._handler_timeout = handler_timeout
        self._task: asyncio.Task[None] | None = None
        self.published = 0
        self.dropped = 0
        self.handler_errors = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        """Assina um tipo de evento (ou ``*`` para todos). Retorna a função de cancelamento."""
        self._handlers[event_type].append(handler)

        def unsubscribe() -> None:
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

        return unsubscribe

    def publish(self, event: Event) -> bool:
        """Enfileira o evento. Retorna ``False`` se ele foi descartado por fila cheia."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            log.warning(
                "Fila de eventos cheia; evento descartado",
                extra={"event_type": event.event_type, "dropped_total": self.dropped},
            )
            return False
        self.published += 1
        return True

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="sentinel-event-bus")

    async def stop(self, drain_timeout: float = 5.0) -> None:
        """Entrega os eventos pendentes (até ``drain_timeout``) e encerra o despachante."""
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), drain_timeout)
        except TimeoutError:
            log.warning(
                "Barramento encerrado com eventos não entregues",
                extra={"pending": self._queue.qsize()},
            )
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def stats(self) -> dict[str, int | bool]:
        return {
            "running": self.running,
            "pending": self._queue.qsize(),
            "published": self.published,
            "dropped": self.dropped,
            "handler_errors": self.handler_errors,
        }

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._dispatch(event)
            finally:
                self._queue.task_done()

    async def _dispatch(self, event: Event) -> None:
        handlers = [*self._handlers.get(event.event_type, ()), *self._handlers.get(WILDCARD, ())]
        for handler in handlers:
            try:
                await asyncio.wait_for(handler(event), self._handler_timeout)
            except TimeoutError:
                self.handler_errors += 1
                log.error(
                    "Assinante excedeu o tempo limite",
                    extra={"event_type": event.event_type, "handler": _handler_name(handler)},
                )
            except Exception:
                self.handler_errors += 1
                log.exception(
                    "Assinante falhou ao processar evento",
                    extra={"event_type": event.event_type, "handler": _handler_name(handler)},
                )


def _handler_name(handler: EventHandler) -> str:
    return getattr(handler, "__qualname__", repr(handler))
