"""Armazenamento e limpeza (PRD 8.7, 15.1).

A execução de uma limpeza, a restauração e a exclusão definitiva NÃO têm rota
própria: passam por ``POST /api/v1/actions`` (catálogo fechado da Fase 4), com
aprovação, revalidação e auditoria. Aqui ficam só análise, consulta, montagem do
plano e as pastas autorizadas.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.app import get_deps
from sentinel.api.routes.security import actor
from sentinel.modules.cleaner.module import CleanerModule, StorageError

router = APIRouter(prefix="/api/v1/storage")
Category = Literal["temp", "old_log", "large", "duplicate"]


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_disk: bool | None = None  # None = conforme settings.yaml


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_ids: list[int] | None = Field(None, max_length=5000)
    category: Category | None = None
    reason: str | None = Field(None, max_length=300)


class AuthorizedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folders: list[str] = Field(max_length=50)


def _module(request: Request) -> CleanerModule:
    module = get_deps(request).storage
    if module is None:
        raise HTTPException(503, "Módulo de armazenamento indisponível")
    return module


async def _guard(coro: Any) -> Any:
    try:
        return await coro
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    return await _module(request).status()


@router.post("/analyze", status_code=202)
async def analyze(request: Request, body: AnalyzeRequest | None = None) -> dict[str, Any]:
    analysis_id = await _guard(_module(request).start_analysis("usuario", body.full_disk if body else None))
    return {"analysis_id": analysis_id}


@router.post("/analyze/cancel")
async def cancel(request: Request) -> dict[str, Any]:
    return {"cancelled": _module(request).cancel_analysis()}


@router.get("/findings")
async def findings(request: Request, category: Category | None = None, limit: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
    return await _module(request).findings(category, limit)


@router.post("/plans", status_code=201)
async def create_plan(request: Request, body: PlanRequest) -> dict[str, Any]:
    return await _guard(_module(request).create_plan(actor(request), body.finding_ids, body.category, body.reason or ""))


@router.post("/plans/{report_id}/discard")
async def discard_plan(request: Request, report_id: int) -> dict[str, Any]:
    return {"discarded": await _module(request).discard_plan(report_id)}


@router.get("/reports")
async def reports(request: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    module = _module(request)
    assert module._repo is not None
    return {"reports": await module._repo.reports(limit)}


@router.get("/reports/{report_id}")
async def report(request: Request, report_id: int) -> dict[str, Any]:
    try:
        return await _module(request).report(report_id)
    except StorageError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/quarantine")
async def quarantine(request: Request, status: Literal["quarantined", "restored", "deleted"] | None = "quarantined",
                     limit: int = Query(1000, ge=1, le=5000)) -> dict[str, Any]:
    module = _module(request)
    assert module._repo is not None
    return {"items": await module._repo.quarantine(status, None, limit)}


@router.put("/authorized")
async def set_authorized(request: Request, body: AuthorizedRequest) -> dict[str, Any]:
    return {"folders": await _guard(_module(request).set_authorized(body.folders))}
