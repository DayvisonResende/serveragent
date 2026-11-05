"""Relatório de saúde interna do Sentinel.

Reúne estado do agente, módulos, tarefas agendadas e barramento num único
dicionário serializável. Será exposto pela API na Fase 2 (``/api/v1/system/status``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sentinel import __version__

if TYPE_CHECKING:
    from sentinel.agent.lifecycle import Agent


def build_health_report(agent: Agent) -> dict[str, Any]:
    modules = agent.registry.snapshot()
    jobs = agent.scheduler.snapshot()
    return {
        "version": __version__,
        "agent": agent.state.snapshot(),
        "run_id": agent.run_id,
        "modules": modules,
        "unavailable_modules": agent.registry.unavailable_modules,
        "jobs": jobs,
        "failing_jobs": [j["name"] for j in jobs if j["consecutive_failures"] > 0],
        "event_bus": agent.event_bus.stats(),
        "scheduler_load_factor": agent.scheduler.load_factor,
    }
