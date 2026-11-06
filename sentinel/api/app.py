"""Montagem da aplicação FastAPI.

Rotas sob ``/api/v1`` exigem sessão, exceto o login. ``/health`` responde sem
autenticação e sem expor dados. O dashboard estático é servido em ``/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from sentinel import __version__
from sentinel.agent.config import Settings
from sentinel.api.security import SESSION_COOKIE, GuardMiddleware, SessionAuth
from sentinel.api.websocket import WebSocketHub
from sentinel.core.resource_manager import ResourceManager
from sentinel.database.database import Database
from sentinel.modules.monitor.store import MetricsStore

if TYPE_CHECKING:
    from sentinel.modules.servers.manager import ServersModule

DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "dashboard"


@dataclass(frozen=True)
class ApiDeps:
    settings: Settings
    store: MetricsStore
    database: Database
    resources: ResourceManager
    auth: SessionAuth
    hub: WebSocketHub
    health: Callable[[], dict[str, Any]]
    alerts: Callable[[], list[dict[str, Any]]]
    servers: ServersModule | None = None


def get_deps(request: Request) -> ApiDeps:
    return request.app.state.deps


async def require_session(request: Request) -> None:
    deps = get_deps(request)
    if not await deps.auth.is_valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Sessão ausente ou expirada. Use abrir-dashboard.bat.")


def create_app(deps: ApiDeps, dashboard_dir: Path = DASHBOARD_DIR) -> FastAPI:
    from sentinel.api.routes import auth, events, servers, system

    app = FastAPI(
        title="Sentinel",
        version=__version__,
        docs_url=None,  # sem páginas interativas expostas; a API é consumida pelo dashboard
        redoc_url=None,
        openapi_url=None,
    )
    app.state.deps = deps

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    protected = [Depends(require_session)]
    app.include_router(auth.public_router)
    app.include_router(auth.router, dependencies=protected)
    app.include_router(system.router, dependencies=protected)
    app.include_router(events.router, dependencies=protected)
    app.include_router(servers.router, dependencies=protected)
    app.include_router(events.ws_router)  # autenticação feita no handshake

    app.mount("/", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")
    return GuardMiddleware(app, deps.settings.api.port)  # type: ignore[return-value]
