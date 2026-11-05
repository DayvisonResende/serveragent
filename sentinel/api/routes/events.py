"""Eventos e canal WebSocket."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, WebSocket

from sentinel.api.app import get_deps
from sentinel.api.security import SESSION_COOKIE
from sentinel.database.repositories import EventRepository

router = APIRouter(prefix="/api/v1")
ws_router = APIRouter()


@router.get("/events")
async def list_events(request: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    events = await EventRepository(get_deps(request).database).recent(limit)
    return {"events": events}


@ws_router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    deps = websocket.app.state.deps
    if not await deps.auth.is_valid(websocket.cookies.get(SESSION_COOKIE)):
        await websocket.close(code=1008)  # política: sem sessão
        return
    hello = {"type": "hello", "interval_seconds": deps.settings.monitoring.fast_interval_seconds}
    await deps.hub.serve(websocket, hello)
