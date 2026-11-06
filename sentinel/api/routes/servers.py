"""Servidores (PRD 15.1): cadastro, estado, saúde, logs, incidentes e operações."""

from __future__ import annotations

from typing import Any, Literal

import psutil
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from sentinel.api.app import get_deps
from sentinel.database.repositories import AuditRepository
from sentinel.database.repositories.servers import DuplicateServerError, ServerRepository
from sentinel.modules.servers.manager import OperationError, ServerNotFound, ServersModule
from sentinel.modules.servers.models import ServerSpec
from sentinel.oslayer.process_control import listening_ports

router = APIRouter(prefix="/api/v1")

OPERATIONS = {"start": "server_start", "stop": "server_stop", "restart": "server_restart"}


class OperationRequest(BaseModel):
    reason: str | None = Field(None, max_length=300)


def _module(request: Request) -> ServersModule:
    module = get_deps(request).servers
    if module is None:
        raise HTTPException(503, "Módulo de servidores indisponível")
    return module


def _actor(request: Request) -> str:
    return "usuario:cli" if request.headers.get("x-sentinel-client") == "cli" else "usuario:dashboard"


def _describe(module: ServersModule, server_id: int) -> dict[str, Any]:
    try:
        return module.describe(server_id)
    except ServerNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/servers")
async def list_servers(request: Request) -> dict[str, Any]:
    module = _module(request)
    return {"servers": module.snapshot(), "counts": module.counts()}


@router.post("/servers", status_code=201)
async def create_server(request: Request, spec: ServerSpec) -> dict[str, Any]:
    module = _module(request)
    deps = get_deps(request)
    try:
        record = await ServerRepository(deps.database).create(spec)
    except DuplicateServerError as exc:
        raise HTTPException(409, str(exc)) from exc
    await module.reload()
    await AuditRepository(deps.database).record(
        actor=_actor(request), operation="server.create", target=record.name, result="success",
        details=record.summary(),
    )
    return _describe(module, record.id)


@router.get("/servers/{server_id}")
async def get_server(request: Request, server_id: int) -> dict[str, Any]:
    return _describe(_module(request), server_id)


@router.put("/servers/{server_id}")
async def update_server(request: Request, server_id: int, spec: ServerSpec) -> dict[str, Any]:
    module = _module(request)
    deps = get_deps(request)
    try:
        record = await ServerRepository(deps.database).update(server_id, spec)
    except DuplicateServerError as exc:
        raise HTTPException(409, str(exc)) from exc
    if record is None:
        raise HTTPException(404, f"Servidor {server_id} não encontrado")
    await module.reload()
    await AuditRepository(deps.database).record(
        actor=_actor(request), operation="server.update", target=record.name, result="success", details=record.summary()
    )
    return _describe(module, server_id)


@router.delete("/servers/{server_id}", status_code=204)
async def delete_server(request: Request, server_id: int) -> Response:
    """Remove apenas o cadastro: o processo do servidor NÃO é encerrado."""
    module = _module(request)
    deps = get_deps(request)
    repo = ServerRepository(deps.database)
    record = await repo.get(server_id)
    if record is None:
        raise HTTPException(404, f"Servidor {server_id} não encontrado")
    await repo.delete(server_id)
    await module.reload()
    await AuditRepository(deps.database).record(
        actor=_actor(request), operation="server.delete", target=record.name, result="success", details=record.summary()
    )
    return Response(status_code=204)


@router.get("/servers/{server_id}/health")
async def server_health(request: Request, server_id: int, limit: int = Query(50, ge=1, le=1000)) -> dict[str, Any]:
    _describe(_module(request), server_id)
    return {"checks": await ServerRepository(get_deps(request).database).recent_checks(server_id, limit)}


@router.get("/servers/{server_id}/logs")
async def server_logs(
    request: Request,
    server_id: int,
    source: Literal["app", "sentinel"] = "app",
    lines: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    try:
        return _module(request).logs(server_id, source, lines)
    except ServerNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/servers/{server_id}/incidents")
async def server_incidents(request: Request, server_id: int, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    _describe(_module(request), server_id)
    return {"incidents": await ServerRepository(get_deps(request).database).incidents(server_id, limit)}


@router.get("/incidents")
async def all_incidents(request: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    return {"incidents": await ServerRepository(get_deps(request).database).incidents(None, limit)}


@router.post("/servers/{server_id}/actions/{action}")
async def server_action(request: Request, server_id: int, action: Literal["start", "stop", "restart"], body: OperationRequest | None = None) -> dict[str, Any]:
    """Operação pedida explicitamente pelo usuário autenticado (com confirmação no dashboard).
    Na Fase 4 passará pelo sistema de aprovações."""
    module = _module(request)
    try:
        return await module.execute(OPERATIONS[action], server_id, _actor(request), body.reason if body else None)
    except ServerNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except OperationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/system/processes/{pid}/candidate")
async def process_candidate(request: Request, pid: int) -> dict[str, Any]:
    """Sugestão de cadastro a partir de um processo em execução (sem expor a linha de comando)."""
    store = get_deps(request).store
    proc = next((p for p in store.processes if p.pid == pid), None)
    if proc is None:
        raise HTTPException(404, f"Processo {pid} não encontrado na última coleta")
    import asyncio

    listeners = await asyncio.to_thread(listening_ports)
    family = {pid}
    try:
        family |= {c.pid for c in psutil.Process(pid).children(recursive=True)}
    except psutil.Error:
        pass
    ports = sorted(port for port, pids in listeners.items() if pids & family)
    return {
        "pid": pid,
        "suggestion": {
            "name": (proc.name or "").removesuffix(".exe"),
            "management": "observed",
            "executable": proc.exe,
            "port": ports[0] if ports else None,
            "process_match": {"exe_path": proc.exe} if proc.exe else {"name": proc.name},
            "health_check": {"type": "tcp" if ports else "none"},
        },
        "listening_ports": ports,
        "username": proc.username,
    }
