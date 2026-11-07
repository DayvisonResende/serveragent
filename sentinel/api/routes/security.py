"""Ações, aprovações, auditoria e inicialização automática (PRD 11, 15.1)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.app import get_deps
from sentinel.database.repositories import AuditRepository
from sentinel.modules.security.actions import ActionNotFound, ActionService
from sentinel.modules.security.module import SecurityModule
from sentinel.modules.security.operations import ActionError

router = APIRouter(prefix="/api/v1")

Status = Literal["pending", "approved", "rejected", "expired", "executing", "completed", "failed", "cancelled"]


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str = Field(max_length=60)
    target_id: int
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = Field(None, max_length=300)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str | None = Field(None, max_length=200)  # operações críticas: nome do alvo
    note: str | None = Field(None, max_length=300)


def _security(request: Request) -> SecurityModule:
    module = get_deps(request).security
    if module is None or module.actions is None:
        raise HTTPException(503, "Módulo de segurança indisponível")
    return module


def _service(request: Request) -> ActionService:
    service = _security(request).actions
    assert service is not None
    return service


def actor(request: Request) -> str:
    return "usuario:cli" if request.headers.get("x-sentinel-client") == "cli" else "usuario:dashboard"


async def _guard(coro: Any) -> dict[str, Any]:
    try:
        return await coro
    except ActionNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ActionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/actions")
async def list_actions(request: Request, status: Status | None = None, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    return {"actions": await _service(request).list(status, limit)}


@router.get("/actions/catalog")
async def catalog(request: Request) -> dict[str, Any]:
    return {"operations": [
        {"name": s.name, "label": s.label, "risk_level": s.risk_level, "impact": s.impact, "risks": s.risks}
        for s in _service(request).catalog.values()
    ]}


@router.get("/actions/{action_id}")
async def get_action(request: Request, action_id: int) -> dict[str, Any]:
    return await _guard(_service(request).get(action_id))


@router.post("/actions", status_code=201)
async def request_action(request: Request, body: ActionRequest) -> dict[str, Any]:
    """Pedido explícito do usuário autenticado: a confirmação no dashboard é a aprovação."""
    return await _guard(_service(request).request(body.operation, body.target_id, body.params, actor(request),
                                                  body.reason or "pedido do usuário", approval="user"))


@router.get("/approvals")
async def list_approvals(request: Request, status: Status | None = "pending", limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    service = _service(request)
    return {"approvals": await service.list(status, limit), "pending": await service.count_pending()}


@router.post("/approvals/{action_id}/approve")
async def approve(request: Request, action_id: int, body: Decision | None = None) -> dict[str, Any]:
    return await _guard(_service(request).approve(action_id, actor(request), body.confirmation if body else None))


@router.post("/approvals/{action_id}/reject")
async def reject(request: Request, action_id: int, body: Decision | None = None) -> dict[str, Any]:
    return await _guard(_service(request).reject(action_id, actor(request), body.note if body else None))


@router.get("/audit")
async def audit(request: Request, limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    """Auditoria somente leitura (PRD 11.6): não há rota que altere ou apague registros."""
    return {"entries": await AuditRepository(get_deps(request).database).recent(limit)}


@router.get("/security/autostart")
async def autostart_entries(request: Request) -> dict[str, Any]:
    module = _security(request)
    entries = await module.autostart_entries()
    entries.sort(key=lambda e: (not e["suspicious"], e["location"], e["name"].lower()))
    return {"status": module.autostart_status, "entries": entries}


@router.post("/security/autostart/scan")
async def autostart_scan(request: Request) -> dict[str, Any]:
    return {"status": await _security(request).scan_autostart()}
