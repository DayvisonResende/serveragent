"""Módulo de IA (PRD 9.6): disponibilidade do Ollama e o assistente.

O monitoramento NUNCA depende da IA: se o Ollama estiver desligado, este módulo
apenas informa "indisponível" e o resto do Sentinel segue normalmente.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable

from sentinel.core.event_bus import Event, Severity
from sentinel.core.module_registry import Module, ModuleHealth
from sentinel.modules.ai.assistant import Assistant
from sentinel.modules.ai.ollama import OllamaClient, OllamaError
from sentinel.modules.ai.tools import ToolBox

if TYPE_CHECKING:
    from sentinel.core.context import AgentContext
    from sentinel.modules.cleaner.module import CleanerModule
    from sentinel.modules.monitor.store import MetricsStore
    from sentinel.modules.security.module import SecurityModule
    from sentinel.modules.servers.manager import ServersModule

log = logging.getLogger(__name__)


class AIModule(Module):
    name = "ai"

    def __init__(self, store: MetricsStore, servers: ServersModule | None, security: SecurityModule | None,
                 alerts: Callable[[], list[dict[str, Any]]], client: OllamaClient | None = None,
                 storage: CleanerModule | None = None) -> None:
        self._store = store
        self._servers = servers
        self._security = security
        self._alerts = alerts
        self._client = client
        self._storage = storage
        self._ctx: AgentContext | None = None
        self.assistant: Assistant | None = None
        self.status: dict[str, Any] = {"available": None, "message": "verificando…", "model": None, "ollama_version": None}

    async def start(self, context: AgentContext) -> None:
        self._ctx = context
        ai = context.settings.ai
        self._client = self._client or OllamaClient(ai.ollama_url, timeout=ai.timeout_seconds)
        toolbox = ToolBox(self._store, context.database, self._servers, self._security, self._alerts,
                          context.settings.monitoring.live_history_seconds, self._storage)
        self.assistant = Assistant(self._client, toolbox, context.database, ai)
        self.status["model"] = ai.model
        context.scheduler.add_job("ai.status", self.refresh_status, 60, timeout=20, run_immediately=True)

    async def stop(self) -> None:
        if self._ctx is not None:
            try:
                await self._ctx.scheduler.remove_job("ai.status")
            except Exception:
                log.warning("Tarefa já removida", extra={"job": "ai.status"})

    def health(self) -> ModuleHealth:
        return ModuleHealth(True, self.status["message"])

    def snapshot(self) -> dict[str, Any]:
        return {**self.status, "busy": bool(self.assistant and self.assistant.busy),
                "warming": bool(self.assistant and self.assistant.warming)}

    async def refresh_status(self) -> dict[str, Any]:
        assert self._client is not None and self._ctx is not None
        model = self._ctx.settings.ai.model
        was = self.status.get("available")
        try:
            version = await asyncio.to_thread(self._client.version)
            present = bool(model) and await asyncio.to_thread(self._client.has_model, model)
            if not model:
                message = "nenhum modelo configurado"
            elif not present:
                message = f"modelo não baixado: rode testar-ia.bat (ou: ollama pull {model})"
            else:
                message = f"pronta · Ollama {version}"
            self.status = {"available": present, "message": message, "model": model, "ollama_version": version}
        except OllamaError as exc:
            self.status = {"available": False, "message": f"Ollama desligado ou inacessível ({exc})", "model": model, "ollama_version": None}
        if was is not None and was != self.status["available"]:
            self._ctx.event_bus.publish(Event(
                event_type="ai.availability", source="ai", severity=Severity.INFO,
                title="IA local disponível" if self.status["available"] else "IA local indisponível",
                description=self.status["message"], metadata={"available": self.status["available"]},
            ))
        return self.snapshot()
