"""Máquina de estados do agente."""

from __future__ import annotations

import logging
from datetime import datetime
from enum import StrEnum
from typing import Any

from sentinel.core.clock import to_iso, utc_now
from sentinel.core.exceptions import StateTransitionError

log = logging.getLogger(__name__)


class AgentState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"  # rodando, mas com ao menos um módulo indisponível
    STOPPING = "stopping"
    STOPPED = "stopped"


_ALLOWED: dict[AgentState, frozenset[AgentState]] = {
    AgentState.CREATED: frozenset({AgentState.STARTING, AgentState.STOPPING}),
    AgentState.STARTING: frozenset({AgentState.RUNNING, AgentState.DEGRADED, AgentState.STOPPING}),
    AgentState.RUNNING: frozenset({AgentState.DEGRADED, AgentState.STOPPING}),
    AgentState.DEGRADED: frozenset({AgentState.RUNNING, AgentState.STOPPING}),
    AgentState.STOPPING: frozenset({AgentState.STOPPED}),
    AgentState.STOPPED: frozenset(),
}


class StateManager:
    def __init__(self) -> None:
        self._state = AgentState.CREATED
        self._changed_at = utc_now()
        self.started_at: datetime | None = None

    @property
    def current(self) -> AgentState:
        return self._state

    def transition(self, new: AgentState) -> None:
        if new not in _ALLOWED[self._state]:
            raise StateTransitionError(f"Transição inválida: {self._state.value} -> {new.value}")
        log.info("Estado do agente alterado", extra={"from": self._state.value, "to": new.value})
        self._state = new
        self._changed_at = utc_now()
        if new is AgentState.STARTING:
            self.started_at = self._changed_at

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "changed_at": to_iso(self._changed_at),
            "started_at": to_iso(self.started_at) if self.started_at else None,
        }
