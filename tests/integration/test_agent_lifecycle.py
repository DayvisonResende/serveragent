"""Integração: o agente inicia, persiste eventos/auditoria, sobrevive a módulos
quebrados, detecta encerramentos inesperados e encerra de forma limpa."""

import asyncio
import contextlib
import dataclasses
import io
import json
import sqlite3

from sentinel.agent.lifecycle import HEARTBEAT_JOB, Agent
from sentinel.agent.main import cmd_status
from sentinel.core.event_bus import EventType
from sentinel.core.module_registry import Module
from sentinel.core.state_manager import AgentState


class GoodModule(Module):
    name = "good"

    def __init__(self):
        self.context = None
        self.stopped = False

    async def start(self, context):
        self.context = context

    async def stop(self):
        self.stopped = True


class BrokenModule(Module):
    name = "broken"

    async def start(self, context):
        raise RuntimeError("falha simulada")

    async def stop(self):
        raise AssertionError("não deve ser chamado")


def query(settings, sql, params=()):
    conn = sqlite3.connect(settings.paths.database_file)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


async def run_agent_briefly(agent: Agent, seconds: float = 0.2) -> dict:
    stop = asyncio.Event()
    task = asyncio.create_task(agent.run(stop))
    await asyncio.sleep(seconds)
    report = agent.health_report()
    stop.set()
    await task
    return report


def test_clean_run_records_events_audit_and_run(settings, platform_info):
    good = GoodModule()
    agent = Agent(settings, modules=[good], platform_info=platform_info)
    report = asyncio.run(run_agent_briefly(agent))

    assert report["agent"]["state"] == "running"
    assert report["unavailable_modules"] == []
    assert any(j["name"] == HEARTBEAT_JOB for j in report["jobs"])
    assert good.context is not None and good.context.platform is platform_info
    assert good.stopped
    assert agent.state.current is AgentState.STOPPED

    events = [e["event_type"] for e in query(settings, "SELECT event_type FROM events ORDER BY id")]
    assert events == [EventType.AGENT_STARTED, EventType.AGENT_STOPPED]
    audit = query(settings, "SELECT operation, result FROM audit_logs ORDER BY id")
    assert audit == [
        {"operation": "agent.start", "result": "success"},
        {"operation": "agent.stop", "result": "clean"},
    ]
    runs = query(settings, "SELECT * FROM agent_runs")
    assert len(runs) == 1 and runs[0]["exit_status"] == "clean"


def test_broken_module_degrades_but_agent_keeps_running(settings, platform_info):
    agent = Agent(settings, modules=[BrokenModule(), GoodModule()], platform_info=platform_info)
    report = asyncio.run(run_agent_briefly(agent))

    assert report["agent"]["state"] == "degraded"
    assert report["unavailable_modules"] == ["broken"]
    failed = query(settings, "SELECT * FROM events WHERE event_type = ?", (EventType.MODULE_FAILED,))
    assert len(failed) == 1 and "falha simulada" in failed[0]["description"]
    assert query(settings, "SELECT exit_status FROM agent_runs")[0]["exit_status"] == "clean"


def test_previous_crash_is_reported_on_next_start(settings, platform_info):
    asyncio.run(run_agent_briefly(Agent(settings, platform_info=platform_info)))
    # Simula uma execução que morreu sem registrar término (ex.: TerminateProcess).
    conn = sqlite3.connect(settings.paths.database_file)
    conn.execute(
        "INSERT INTO agent_runs (pid, version, started_at, last_heartbeat) VALUES (4242, '0.1.0', 'a', 'b')"
    )
    conn.commit()
    conn.close()

    asyncio.run(run_agent_briefly(Agent(settings, platform_info=platform_info)))

    unclean = query(settings, "SELECT * FROM events WHERE event_type = ?", (EventType.AGENT_UNCLEAN_SHUTDOWN,))
    assert len(unclean) == 1 and "4242" in unclean[0]["description"]

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_status(settings, as_json=True)
    data = json.loads(buf.getvalue())
    assert data["unclean_shutdown_events"] == 1
    assert data["latest_run"]["state"] == "stopped"
    assert buf.getvalue().isascii()
    crashed = query(settings, "SELECT exit_status FROM agent_runs WHERE pid = 4242")
    assert crashed == [{"exit_status": "unclean"}]


def test_running_as_admin_emits_warning(settings, platform_info):
    admin = dataclasses.replace(platform_info, is_admin=True)
    asyncio.run(run_agent_briefly(Agent(settings, platform_info=admin)))
    rows = query(settings, "SELECT severity FROM events WHERE event_type = ?", (EventType.AGENT_RUNNING_AS_ADMIN,))
    assert rows == [{"severity": "warning"}]


def test_heartbeat_updates_run(settings, platform_info):
    fast = settings.model_copy(
        update={"agent": settings.agent.model_copy(update={"heartbeat_interval_seconds": 0.05})}
    )
    agent = Agent(fast, platform_info=platform_info)
    report = asyncio.run(run_agent_briefly(agent, seconds=0.3))
    heartbeat = next(j for j in report["jobs"] if j["name"] == HEARTBEAT_JOB)
    assert heartbeat["runs"] >= 2 and heartbeat["failures"] == 0


def test_startup_failure_still_shuts_down_cleanly(settings, platform_info):
    settings.paths.database_file.parent.mkdir(parents=True)
    settings.paths.database_file.write_bytes(b"isto nao e um banco sqlite" * 100)
    agent = Agent(settings, platform_info=platform_info)

    async def scenario():
        try:
            await agent.run(asyncio.Event())
        except Exception as exc:
            return exc
        return None

    error = asyncio.run(scenario())
    assert error is not None
    assert agent.state.current is AgentState.STOPPED
    assert not agent.database.is_open
