"""Distribuição de métricas e eventos em tempo real para o dashboard (PRD 15.2).

Cada cliente tem uma fila própria e limitada: um navegador lento perde
mensagens (contadas em ``dropped``) em vez de atrasar o agente ou os demais.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

log = logging.getLogger(__name__)


class WebSocketHub:
    def __init__(self, max_clients: int = 20, queue_size: int = 100, send_timeout: float = 5.0) -> None:
        self._clients: dict[WebSocket, asyncio.Queue[dict[str, Any]]] = {}
        self._max_clients = max_clients
        self._queue_size = queue_size
        self._send_timeout = send_timeout
        self.dropped = 0

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, message: dict[str, Any]) -> None:
        for queue in list(self._clients.values()):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.dropped += 1

    async def serve(self, websocket: WebSocket, hello: dict[str, Any]) -> None:
        if len(self._clients) >= self._max_clients:
            await websocket.close(code=1013)  # tente novamente mais tarde
            return
        await websocket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        queue.put_nowait(hello)
        self._clients[websocket] = queue
        sender = asyncio.create_task(self._sender(websocket, queue), name="sentinel-ws-sender")
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.pop(websocket, None)
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender

    async def close_all(self) -> None:
        for websocket in list(self._clients):
            if websocket.application_state is WebSocketState.CONNECTED:
                with contextlib.suppress(RuntimeError, OSError):
                    await websocket.close(code=1001)  # servidor encerrando

    async def _sender(self, websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
        while True:
            message = await queue.get()
            try:
                await asyncio.wait_for(websocket.send_json(message), self._send_timeout)
            except (TimeoutError, RuntimeError, OSError, WebSocketDisconnect) as exc:
                log.info("Cliente WebSocket desconectado", extra={"reason": f"{type(exc).__name__}: {exc}"})
                with contextlib.suppress(RuntimeError, OSError):
                    await websocket.close(code=1011)
                return
