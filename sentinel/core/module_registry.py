"""Registro e ciclo de vida dos módulos funcionais.

Garantias:
- Módulos iniciam em ordem de dependência e param na ordem inversa.
- A falha (ou tempo excedido) de um módulo não derruba o agente: ele fica
  ``FAILED`` e os módulos que dependem dele ficam ``SKIPPED``.
- Cada falha é registrada em log e publicada como evento.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from sentinel.core.clock import to_iso, utc_now
from sentinel.core.event_bus import Event, EventBus, EventType, Severity
from sentinel.core.exceptions import DependencyError, ModuleRegistrationError

if TYPE_CHECKING:
    from sentinel.core.context import AgentContext

log = logging.getLogger(__name__)


class ModuleStatus(StrEnum):
    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    SKIPPED = "skipped"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class ModuleHealth:
    healthy: bool
    detail: str = ""


class Module(ABC):
    """Contrato de todo módulo funcional (Monitor, Servers, Security, ...)."""

    name: ClassVar[str] = ""
    depends_on: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    async def start(self, context: AgentContext) -> None:
        """Inicializa recursos e agenda tarefas. Deve retornar rapidamente."""

    @abstractmethod
    async def stop(self) -> None:
        """Libera recursos. Nunca deve encerrar processos monitorados."""

    def health(self) -> ModuleHealth:
        return ModuleHealth(healthy=True)


@dataclass
class _Entry:
    module: Module
    status: ModuleStatus = ModuleStatus.REGISTERED
    error: str | None = None
    started_at: datetime | None = None


class ModuleRegistry:
    def __init__(self, event_bus: EventBus, start_timeout: float, stop_timeout: float) -> None:
        self._bus = event_bus
        self._start_timeout = start_timeout
        self._stop_timeout = stop_timeout
        self._entries: dict[str, _Entry] = {}
        self._order: list[str] = []

    def register(self, module: Module) -> None:
        name = module.name
        if not isinstance(name, str) or not name:
            raise ModuleRegistrationError(f"Módulo {type(module).__name__} não define 'name'")
        if name in self._entries:
            raise ModuleRegistrationError(f"Módulo '{name}' já registrado")
        self._entries[name] = _Entry(module)

    def status(self, name: str) -> ModuleStatus:
        return self._entries[name].status

    @property
    def unavailable_modules(self) -> list[str]:
        return [
            name
            for name, entry in self._entries.items()
            if entry.status in (ModuleStatus.FAILED, ModuleStatus.SKIPPED)
        ]

    def start_order(self) -> list[str]:
        """Ordem topológica estável (respeita a ordem de registro entre independentes)."""
        for name, entry in self._entries.items():
            for dep in entry.module.depends_on:
                if dep not in self._entries:
                    raise DependencyError(f"Módulo '{name}' depende de '{dep}', que não está registrado")

        order: list[str] = []
        state: dict[str, str] = {}

        def visit(name: str, path: list[str]) -> None:
            if state.get(name) == "done":
                return
            if state.get(name) == "visiting":
                raise DependencyError("Dependência cíclica: " + " -> ".join([*path, name]))
            state[name] = "visiting"
            for dep in self._entries[name].module.depends_on:
                visit(dep, [*path, name])
            state[name] = "done"
            order.append(name)

        for name in self._entries:
            visit(name, [])
        return order

    async def start_all(self, context: AgentContext) -> None:
        self._order = self.start_order()
        for name in self._order:
            entry = self._entries[name]
            missing = [
                dep for dep in entry.module.depends_on if self._entries[dep].status is not ModuleStatus.RUNNING
            ]
            if missing:
                entry.status = ModuleStatus.SKIPPED
                entry.error = "Dependências indisponíveis: " + ", ".join(missing)
                log.warning("Módulo não iniciado", extra={"module_name": name, "reason": entry.error})
                self._publish(EventType.MODULE_SKIPPED, Severity.WARNING, name, entry.error)
                continue

            entry.status = ModuleStatus.STARTING
            try:
                await asyncio.wait_for(entry.module.start(context), self._start_timeout)
            except TimeoutError:
                self._mark_failed(entry, name, f"Tempo limite de {self._start_timeout}s excedido na inicialização")
            except Exception as exc:
                log.exception("Falha ao iniciar módulo", extra={"module_name": name})
                self._mark_failed(entry, name, f"{type(exc).__name__}: {exc}")
            else:
                entry.status = ModuleStatus.RUNNING
                entry.started_at = utc_now()
                log.info("Módulo iniciado", extra={"module_name": name})

    async def stop_all(self) -> None:
        for name in reversed(self._order):
            entry = self._entries[name]
            if entry.status is not ModuleStatus.RUNNING:
                continue
            entry.status = ModuleStatus.STOPPING
            try:
                await asyncio.wait_for(entry.module.stop(), self._stop_timeout)
            except TimeoutError:
                entry.error = f"Tempo limite de {self._stop_timeout}s excedido no encerramento"
                log.error("Módulo não encerrou a tempo", extra={"module_name": name})
            except Exception as exc:
                entry.error = f"{type(exc).__name__}: {exc}"
                log.exception("Falha ao encerrar módulo", extra={"module_name": name})
            entry.status = ModuleStatus.STOPPED

    def snapshot(self) -> list[dict[str, Any]]:
        result = []
        for name, entry in self._entries.items():
            health: dict[str, Any] | None = None
            if entry.status is ModuleStatus.RUNNING:
                try:
                    h = entry.module.health()
                except Exception as exc:
                    log.exception("health() do módulo falhou", extra={"module_name": name})
                    h = ModuleHealth(False, f"health() falhou: {type(exc).__name__}: {exc}")
                health = {"healthy": h.healthy, "detail": h.detail}
            result.append(
                {
                    "name": name,
                    "status": entry.status.value,
                    "error": entry.error,
                    "started_at": to_iso(entry.started_at) if entry.started_at else None,
                    "health": health,
                }
            )
        return result

    def _mark_failed(self, entry: _Entry, name: str, reason: str) -> None:
        entry.status = ModuleStatus.FAILED
        entry.error = reason
        log.error("Módulo '%s' falhou: %s", name, reason, extra={"module_name": name, "reason": reason})
        self._publish(EventType.MODULE_FAILED, Severity.HIGH, name, reason)

    def _publish(self, event_type: str, severity: Severity, name: str, reason: str) -> None:
        self._bus.publish(
            Event(
                event_type=event_type,
                source="core.module_registry",
                severity=severity,
                title=f"Módulo '{name}' indisponível",
                description=reason,
                metadata={"module": name},
            )
        )
