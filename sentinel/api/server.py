"""Módulo da API: executa o uvicorn dentro do loop do agente (decisão D1).

Dois cuidados com o uvicorn embutido:
- ``Server.serve`` captura SIGINT/SIGTERM; desativamos isso para o agente
  continuar sendo o único dono dos sinais.
- Se o próprio uvicorn abrir a porta e ela estiver ocupada, ele chama
  ``sys.exit`` — derrubaria o agente. Por isso abrimos o socket antes e uma
  porta ocupada vira apenas falha deste módulo (o monitoramento continua).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import TYPE_CHECKING, Any, Callable, Generator

import uvicorn

from sentinel.api.app import ApiDeps, create_app
from sentinel.api.security import SessionAuth
from sentinel.api.websocket import WebSocketHub
from sentinel.core.clock import to_iso
from sentinel.core.event_bus import WILDCARD, Event
from sentinel.core.exceptions import ModuleError
from sentinel.core.module_registry import Module, ModuleHealth
from sentinel.database.repositories import AuthRepository
from sentinel.modules.monitor.store import FastSample, MetricsStore
from sentinel.modules.servers.manager import ServersModule
from sentinel.oslayer.sockets import bind_listener

if TYPE_CHECKING:
    from sentinel.core.context import AgentContext

log = logging.getLogger(__name__)

STARTUP_TIMEOUT = 5.0
SHUTDOWN_TIMEOUT = 3.0


class _EmbeddedServer(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


class ApiModule(Module):
    name = "api"

    def __init__(
        self,
        store: MetricsStore,
        health_provider: Callable[[], dict[str, Any]],
        alerts_provider: Callable[[], list[dict[str, Any]]],
        servers: ServersModule | None = None,
    ) -> None:
        self._store = store
        self._health = health_provider
        self._alerts = alerts_provider
        self._servers = servers
        self.hub = WebSocketHub()
        self._server: _EmbeddedServer | None = None
        self._task: asyncio.Task[None] | None = None
        self._socket: socket.socket | None = None
        self._unsubscribers: list[Callable[[], None]] = []
        self._context: AgentContext | None = None

    async def start(self, context: AgentContext) -> None:
        self._context = context
        api = context.settings.api
        try:
            self._socket = bind_listener(api.host, api.port)
        except OSError as exc:
            raise ModuleError(f"Não foi possível abrir {api.host}:{api.port} (porta em uso?): {exc}") from exc

        deps = ApiDeps(
            settings=context.settings,
            store=self._store,
            database=context.database,
            resources=context.resources,
            auth=SessionAuth(AuthRepository(context.database), api.session_hours * 3600),
            hub=self.hub,
            health=self._health,
            alerts=self._alerts,
            servers=self._servers,
        )
        config = uvicorn.Config(
            create_app(deps),
            lifespan="off",
            log_config=None,
            access_log=False,
            server_header=False,
            proxy_headers=False,
            ws="websockets-sansio",
        )
        self._server = _EmbeddedServer(config)
        self._task = asyncio.create_task(self._server.serve(sockets=[self._socket]), name="sentinel-api")

        deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT
        while not self._server.started:
            if self._task.done():
                exc = self._task.exception()
                raise ModuleError(f"Servidor da API encerrou na inicialização: {exc!r}")
            if asyncio.get_running_loop().time() > deadline:
                await self._abort()
                raise ModuleError(f"Servidor da API não iniciou em {STARTUP_TIMEOUT:.0f}s")
            await asyncio.sleep(0.05)

        self._unsubscribers.append(context.event_bus.subscribe(WILDCARD, self._on_event))
        self._unsubscribers.append(self._store.add_listener(self._on_sample))
        log.info("API disponível", extra={"url": f"http://{api.host}:{api.port}"})

    async def stop(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        await self.hub.close_all()
        await self._abort()

    def health(self) -> ModuleHealth:
        if self._task is None or self._task.done() or self._server is None or not self._server.started:
            return ModuleHealth(False, "Servidor HTTP parado")
        return ModuleHealth(True, f"{self.hub.client_count} cliente(s) em tempo real")

    async def _abort(self) -> None:
        if self._server is not None and self._task is not None:
            self._server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(self._task), SHUTDOWN_TIMEOUT)
            except TimeoutError:
                self._server.force_exit = True
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            except Exception:
                log.exception("Servidor da API terminou com erro")
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._server = None
        self._task = None

    async def _on_event(self, event: Event) -> None:
        self.hub.publish(
            {
                "type": "event",
                "data": {
                    "event_type": event.event_type,
                    "severity": event.severity.value,
                    "source": event.source,
                    "title": event.title,
                    "description": event.description,
                    "timestamp": to_iso(event.timestamp),
                },
            }
        )

    def _on_sample(self, sample: FastSample) -> None:
        if self.hub.client_count == 0 or self._context is None:
            return
        self.hub.publish(
            {
                "type": "metrics",
                "data": sample.as_dict(),
                "resources": self._context.resources.snapshot(),
                "alerts": self._alerts(),
                "servers": self._servers.snapshot() if self._servers else [],
            }
        )
