"""API: autenticação, proteções de Host/Origin, rotas e WebSocket (PRD 23.3)."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sentinel.agent.config import Settings
from sentinel.agent.scheduler import Scheduler
from sentinel.api.app import ApiDeps, create_app
from sentinel.api.security import SESSION_COOKIE, LoginRateLimiter, SessionAuth
from sentinel.api.websocket import WebSocketHub
from sentinel.core.event_bus import EventBus
from sentinel.core.resource_manager import ResourceManager
from sentinel.database.database import Database
from sentinel.database.migrations import apply_migrations
from sentinel.database.repositories import AuthRepository
from sentinel.modules.monitor.cpu import CpuSample
from sentinel.modules.monitor.memory import MemorySample
from sentinel.modules.monitor.network import NetworkSample
from sentinel.modules.monitor.processes import ProcessInfo
from sentinel.modules.monitor.store import FastSample, MetricsStore

BASE = "http://127.0.0.1:8765"
ORIGIN = {"origin": BASE}
WS_URL = "ws://127.0.0.1:8765/api/v1/ws"  # o cliente de WebSocket ignora base_url


def sample(ts, cpu=12.5):
    return FastSample(
        ts,
        CpuSample(cpu, [cpu, cpu], 2400.0, 3300.0),
        MemorySample(8 * 1024**3, 4 * 1024**3, 4 * 1024**3, 50.0, 1024, 0, 0.0),
        NetworkSample(100.0, 200.0, 1, 2, 0, 0, 0, 0, []),
    )


@pytest.fixture
def api(tmp_path):
    """App real sobre um banco real; a sessão do banco roda num loop próprio."""
    loop = asyncio.new_event_loop()
    db = Database(tmp_path / "api.db")
    loop.run_until_complete(db.open())
    loop.run_until_complete(apply_migrations(db))
    settings = Settings()
    store = MetricsStore(live_capacity=100)
    now = time.time()
    for i in range(3):
        store.add_fast(sample(now - 10 + i * 5, cpu=10 + i))
    store.static = {"hostname": "teste", "boot_epoch": now - 3600, "boot_time": "x", "cpu_model": "CPU", "cpu_cores_logical": 2}
    store.processes = [ProcessInfo(42, "server.exe", "C:\\srv\\server.exe", None, "running", None, now, 3.0, 1000, 0.1)]
    store.processes_at = now
    hub = WebSocketHub()
    deps = ApiDeps(
        settings=settings,
        store=store,
        database=db,
        resources=ResourceManager(settings.resources, Scheduler(), EventBus()),
        auth=SessionAuth(AuthRepository(db), 3600),
        hub=hub,
        health=lambda: {
            "agent": {"state": "running", "started_at": "x"}, "run_id": 1, "modules": [],
            "unavailable_modules": [], "failing_jobs": [],
        },
        alerts=lambda: [],
    )
    client = TestClient(create_app(deps), base_url=BASE)

    class Ctx:
        pass

    ctx = Ctx()
    ctx.client, ctx.deps, ctx.db, ctx.loop = client, deps, db, loop
    # O banco atende qualquer loop (usa uma thread própria); o teste usa um loop auxiliar.
    ctx.new_code = lambda ttl=60: loop.run_until_complete(AuthRepository(db).create_login_code(ttl))
    ctx.login = lambda: client.get(f"/login?code={ctx.new_code()}", follow_redirects=False)
    yield ctx
    loop.run_until_complete(db.close())
    loop.close()


def test_health_is_public_and_minimal(api):
    r = api.client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/api/v1/system/status", "/api/v1/system/metrics", "/api/v1/system/processes",
                                  "/api/v1/system/network", "/api/v1/system/disks", "/api/v1/events", "/api/v1/auth/session"])
def test_every_api_route_requires_session(api, path):
    assert api.client.get(path).status_code == 401


def test_unknown_host_is_rejected_dns_rebinding(api):
    r = api.client.get("/health", headers={"host": "attacker.example:8765"})
    assert r.status_code == 400
    assert api.client.get("/health", headers={"host": "127.0.0.1:9999"}).status_code == 400


def test_login_sets_strict_httponly_cookie_and_code_is_single_use(api):
    code = api.new_code()
    r = api.client.get(f"/login?code={code}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert api.client.get("/api/v1/auth/session").status_code == 200
    api.client.cookies.clear()
    assert api.client.get(f"/login?code={code}", follow_redirects=False).status_code == 401


def test_expired_or_forged_code_is_rejected(api):
    assert api.client.get(f"/login?code={api.new_code(ttl=-1)}").status_code == 401
    assert api.client.get("/login?code=forjado").status_code == 401
    assert SESSION_COOKIE not in api.client.cookies


def test_login_rate_limit():
    clock = [0.0]
    limiter = LoginRateLimiter(max_failures=3, window_seconds=60, clock=lambda: clock[0])
    for _ in range(3):
        limiter.record_failure()
    assert limiter.blocked()
    clock[0] = 61
    assert not limiter.blocked()


def test_rate_limited_login_returns_429(api):
    for _ in range(20):
        api.deps.auth.limiter.record_failure()
    assert api.client.get(f"/login?code={api.new_code()}").status_code == 429


def test_cross_origin_post_is_rejected(api):
    api.login()
    r = api.client.post("/api/v1/auth/logout", headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    assert api.client.get("/api/v1/auth/session").status_code == 200  # sessão intacta


def test_logout_invalidates_session(api):
    api.login()
    cookie = api.client.cookies[SESSION_COOKIE]
    assert api.client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 204
    api.client.cookies.set(SESSION_COOKIE, cookie)  # reutilizar o cookie antigo não funciona
    assert api.client.get("/api/v1/auth/session").status_code == 401


def test_status_reports_real_data_and_unavailable_ai(api):
    api.login()
    data = api.client.get("/api/v1/system/status").json()
    assert data["current"]["cpu"]["percent"] == 12
    assert data["machine"]["uptime_seconds"] >= 3599 and "boot_epoch" not in data["machine"]
    assert data["ai"]["available"] is False
    assert data["temperature"] is None  # ainda não coletada: nada é inventado


def test_metrics_live_range_and_validation(api):
    api.login()
    data = api.client.get("/api/v1/system/metrics?range=15m").json()
    assert data["source"] == "live" and [p["cpu"] for p in data["points"]] == [10, 11, 12]
    assert data["summary"]["cpu_peak"] == 12 and data["summary"]["cpu_avg"] == 11
    assert api.client.get("/api/v1/system/metrics?range=99y").status_code == 422
    history = api.client.get("/api/v1/system/metrics?range=24h").json()
    assert history["source"] == "history" and history["points"] == []


def test_processes_and_security_headers(api):
    api.login()
    r = api.client.get("/api/v1/system/processes?sort=memory&limit=5")
    assert r.json()["processes"][0]["name"] == "server.exe"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert api.client.get("/api/v1/system/processes?sort=evil").status_code == 422


def test_dashboard_is_served(api):
    r = api.client.get("/")
    assert r.status_code == 200 and "Sentinel" in r.text


def test_websocket_requires_session(api, caplog):
    with pytest.raises(WebSocketDisconnect) as exc:
        with api.client.websocket_connect(WS_URL, headers=ORIGIN) as ws:
            ws.receive_json()
    assert exc.value.code == 1008
    assert "Host não permitido" not in caplog.text  # recusado pela falta de sessão, não pelo Host


def test_websocket_rejects_foreign_origin(api, caplog):
    api.login()
    with pytest.raises(WebSocketDisconnect):
        with api.client.websocket_connect(WS_URL, headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()
    assert "Origin não permitida" in caplog.text


def test_websocket_rejects_foreign_host(api):
    api.login()
    with pytest.raises(WebSocketDisconnect):
        with api.client.websocket_connect("ws://attacker.example:8765/api/v1/ws", headers=ORIGIN) as ws:
            ws.receive_json()


def test_websocket_streams_after_login(api):
    api.login()
    with api.client.websocket_connect(WS_URL, headers=ORIGIN) as ws:
        assert ws.receive_json()["type"] == "hello"
        assert api.deps.hub.client_count == 1
        api.deps.hub.publish({"type": "event", "data": {"title": "teste"}})
        assert ws.receive_json() == {"type": "event", "data": {"title": "teste"}}
