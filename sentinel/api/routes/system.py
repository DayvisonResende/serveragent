"""Estado e métricas do computador (PRD 15.1)."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from sentinel import __version__
from sentinel.api.app import get_deps
from sentinel.core.clock import to_iso, utc_now
from sentinel.database.repositories import MetricsRepository
from sentinel.modules.monitor.processes import sort_processes
from sentinel.modules.monitor.store import epoch_iso

router = APIRouter(prefix="/api/v1/system")

RANGES: dict[str, int] = {"15m": 900, "1h": 3600, "6h": 6 * 3600, "24h": 86_400, "7d": 7 * 86_400, "30d": 30 * 86_400}
AI_STATUS = {
    "available": False,
    "status": "not_configured",
    "message": "Integração com IA local prevista para a Fase 5.",
}


def _age(epoch: float | None) -> float | None:
    return round(time.time() - epoch, 1) if epoch is not None else None


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    deps = get_deps(request)
    store = deps.store
    health = deps.health()
    machine = dict(store.static) if store.static else None
    if machine is not None:
        machine["uptime_seconds"] = round(time.time() - machine.pop("boot_epoch"))

    current = None
    if store.latest is not None:
        current = store.latest.as_dict()
        current["age_seconds"] = _age(store.latest.ts_epoch)

    return {
        "generated_at": to_iso(utc_now()),
        "agent": {
            "version": __version__,
            "state": health["agent"]["state"],
            "started_at": health["agent"]["started_at"],
            "run_id": health["run_id"],
            "modules": health["modules"],
            "unavailable_modules": health["unavailable_modules"],
            "failing_jobs": health["failing_jobs"],
            "websocket_clients": deps.hub.client_count,
            "jobs": [
                {k: j[k] for k in ("name", "runs", "avg_duration_ms", "load_share", "effective_interval_seconds", "consecutive_failures")}
                for j in health.get("jobs", [])
            ],
        },
        "resources": deps.resources.snapshot(),
        "machine": machine,
        "current": current,
        "disks": (
            {**store.disks.as_dict(), "collected_at": epoch_iso(store.disks_at)}
            if store.disks is not None and store.disks_at is not None
            else None
        ),
        "temperature": (
            {**store.temperature.as_dict(), "collected_at": epoch_iso(store.temperature_at)}
            if store.temperature is not None and store.temperature_at is not None
            else None
        ),
        "processes": {
            "count": len(store.processes),
            "collected_at": epoch_iso(store.processes_at) if store.processes_at else None,
        },
        "alerts": deps.alerts(),
        "ai": AI_STATUS,
    }


@router.get("/metrics")
async def metrics(request: Request, range: str = Query("1h")) -> dict[str, Any]:  # noqa: A002
    if range not in RANGES:
        raise HTTPException(422, f"range deve ser um de: {', '.join(RANGES)}")
    deps = get_deps(request)
    seconds = RANGES[range]
    since = time.time() - seconds

    if seconds <= deps.settings.monitoring.live_history_seconds:
        source = "live"
        points = deps.store.live_points(since)
        for p in points:
            p["cpu_max"] = p["cpu"]
    else:
        source = "history"
        rows = await MetricsRepository(deps.database).system_history(since, max_points=500)
        points = [
            {
                "t": r["t"],
                "cpu": _round(r["cpu_percent"]),
                "cpu_max": _round(r["cpu_percent_max"]),
                "ram": _round(r["ram_percent"]),
                "up": _round(r["network_upload"]),
                "down": _round(r["network_download"]),
            }
            for r in rows
        ]
    return {"range": range, "source": source, "since": epoch_iso(since), "points": points, "summary": _summary(points)}


@router.get("/processes")
async def processes(
    request: Request,
    sort: Literal["cpu", "memory", "name", "runtime"] = "cpu",
    limit: int = Query(50, ge=1, le=1000),
) -> dict[str, Any]:
    store = get_deps(request).store
    return {
        "collected_at": epoch_iso(store.processes_at) if store.processes_at else None,
        "count": len(store.processes),
        "sort": sort,
        "processes": [p.as_dict() for p in sort_processes(store.processes, sort, limit)],
    }


@router.get("/processes/at")
async def processes_at(request: Request, ts: float = Query(..., gt=0)) -> dict[str, Any]:
    """O que estava rodando num momento passado (instantâneos gravados a cada 5 min)."""
    data = await MetricsRepository(get_deps(request).database).processes_near(ts)
    data["snapshot_at"] = epoch_iso(data["snapshot_epoch"]) if data["snapshot_epoch"] else None
    data["interval_seconds"] = get_deps(request).settings.monitoring.process_snapshot_interval_seconds
    return data


@router.get("/network")
async def network(request: Request) -> dict[str, Any]:
    latest = get_deps(request).store.latest
    if latest is None:
        return {"collected_at": None, "network": None}
    return {"collected_at": epoch_iso(latest.ts_epoch), "network": latest.network.as_dict(include_interfaces=True)}


@router.get("/disks")
async def disks(request: Request) -> dict[str, Any]:
    deps = get_deps(request)
    store = deps.store
    growth = await MetricsRepository(deps.database).disk_growth(time.time() - 7 * 86_400)
    if store.disks is None or store.disks_at is None:
        return {"collected_at": None, "disks": [], "errors": [], "growth_7d": growth}
    return {**store.disks.as_dict(), "collected_at": epoch_iso(store.disks_at), "growth_7d": growth}


def _round(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) if value is not None else None


def _summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    def values(key: str) -> list[float]:
        return [p[key] for p in points if p.get(key) is not None]

    cpu, cpu_max, ram = values("cpu"), values("cpu_max"), values("ram")
    up, down = values("up"), values("down")
    return {
        "points": len(points),
        "cpu_avg": _round(sum(cpu) / len(cpu)) if cpu else None,
        "cpu_peak": max(cpu_max) if cpu_max else None,
        "ram_avg": _round(sum(ram) / len(ram)) if ram else None,
        "ram_peak": max(ram) if ram else None,
        "upload_avg": _round(sum(up) / len(up)) if up else None,
        "download_avg": _round(sum(down) / len(down)) if down else None,
    }
