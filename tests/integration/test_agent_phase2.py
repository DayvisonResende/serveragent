"""Agente completo (monitor + API) rodando de verdade numa porta livre."""

import asyncio
import json
import socket
import sqlite3
import urllib.error
import urllib.request

import pytest

from sentinel.agent.main import build_agent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def with_api_port(settings, port):
    # Hardware lento (ex.: i3 + antivírus) pode levar mais de 1 s na primeira importação
    # do servidor HTTP; o limite padrão do agente é 15 s.
    agent = settings.agent.model_copy(update={"module_start_timeout_seconds": 15})
    return settings.model_copy(update={"api": settings.api.model_copy(update={"port": port}), "agent": agent})


def query(settings, sql, params=()):
    conn = sqlite3.connect(settings.paths.database_file)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


async def http_get(url):
    def fetch():
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    return await asyncio.to_thread(fetch)


async def run_briefly(agent, seconds, probe=None):
    stop = asyncio.Event()
    task = asyncio.create_task(agent.run(stop))
    await asyncio.sleep(seconds)
    result = await probe() if probe else None
    report = agent.health_report()
    agent.request_stop(stop)
    await task
    return report, result


def test_full_agent_collects_serves_and_persists(settings):
    port = free_port()
    s = with_api_port(settings, port)
    agent = build_agent(s)

    async def probe():
        return await http_get(f"http://127.0.0.1:{port}/health"), await http_get(f"http://127.0.0.1:{port}/api/v1/system/status")

    report, (health, unauthenticated) = asyncio.run(run_briefly(agent, 1.5, probe))
    assert report["agent"]["state"] == "running", report["modules"]
    assert {m["name"]: m["status"] for m in report["modules"]} == {"monitor": "running", "servers": "running", "security": "running", "notifications": "running", "api": "running"}
    assert health == (200, {"status": "ok"})
    assert unauthenticated[0] == 401
    # a janela parcial é gravada no encerramento: o último minuto não se perde
    rows = query(s, "SELECT sample_count, cpu_percent FROM system_metrics")
    assert len(rows) == 1 and rows[0]["sample_count"] >= 1 and 0 <= rows[0]["cpu_percent"] <= 100


def test_port_in_use_degrades_api_but_monitoring_continues(settings):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    try:
        s = with_api_port(settings, blocker.getsockname()[1])
        report, _ = asyncio.run(run_briefly(build_agent(s), 1.0))
    finally:
        blocker.close()
    modules = {m["name"]: m for m in report["modules"]}
    assert report["agent"]["state"] == "degraded", report["modules"]
    assert modules["api"]["status"] == "failed" and "porta em uso" in modules["api"]["error"]
    assert modules["monitor"]["status"] == "running" and modules["monitor"]["health"]["healthy"]
    failed = query(s, "SELECT title FROM events WHERE event_type = 'module.failed'")
    assert failed == [{"title": "Módulo 'api' indisponível"}]


def test_windows_shutdown_is_recorded_as_clean_system_shutdown(settings, platform_info):
    s = settings.model_copy(update={"api": settings.api.model_copy(update={"enabled": False})})
    agent = build_agent(s)

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(agent.run(stop))
        await asyncio.sleep(0.5)
        agent.request_stop(stop, "system_shutdown", "shutdown")
        agent.request_stop(stop)  # um pedido posterior não apaga o motivo
        await task

    asyncio.run(scenario())
    assert query(s, "SELECT exit_status FROM agent_runs") == [{"exit_status": "system_shutdown"}]
    stopped = query(s, "SELECT title, severity FROM events WHERE event_type = 'agent.stopped'")
    assert stopped == [{"title": "Sentinel encerrado pelo desligamento do Windows", "severity": "info"}]
    assert query(s, "SELECT COUNT(*) AS n FROM events WHERE event_type = 'agent.unclean_shutdown'") == [{"n": 0}]


def test_invalid_stop_reason_is_rejected(settings):
    agent = build_agent(settings)
    with pytest.raises(ValueError):
        agent.request_stop(asyncio.Event(), "porque sim")
