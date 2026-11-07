"""Ciclo completo com o agente real: cadastro, início, queda, incidente, reinício,
servidor sobrevivendo ao fim do Sentinel e sendo reencontrado (MVP 4–10 e 12)."""

import asyncio
import socket
import threading
import time

import psutil
import pytest

from sentinel.agent import server_selftest
from sentinel.agent.client import ApiError, LocalClient
from sentinel.agent.main import build_agent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RunningAgent:
    """Agente completo num thread próprio, para os testes usarem a API de verdade."""

    def __init__(self, settings):
        self.settings = settings
        self.loop = None
        self.stop_event = None
        self.agent = build_agent(settings)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        client = LocalClient(settings, timeout=5)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if client.raw("GET", "/health")[0] == 200 and self.agent.registry.status("servers").value == "running":
                    return
            except OSError:
                pass
            time.sleep(0.2)
        raise RuntimeError("agente não iniciou")

    def _run(self):
        async def main():
            self.loop = asyncio.get_running_loop()
            self.stop_event = asyncio.Event()
            await self.agent.run(self.stop_event)

        asyncio.run(main())

    def stop(self):
        self.loop.call_soon_threadsafe(self.agent.request_stop, self.stop_event)
        self.thread.join(timeout=30)


@pytest.fixture
def fast_settings(settings):
    return settings.model_copy(
        update={
            "api": settings.api.model_copy(update={"port": free_port()}),
            "agent": settings.agent.model_copy(update={"module_start_timeout_seconds": 15}),
            "servers": settings.servers.model_copy(update={"check_interval_seconds": 5, "failure_threshold": 1}),
            "monitoring": settings.monitoring.model_copy(update={"process_interval_seconds": 5}),
        }
    )


def test_full_server_lifecycle_survives_agent_restart(fast_settings):
    agent = RunningAgent(fast_settings)
    try:
        prepared = server_selftest.prepare(fast_settings)
    finally:
        agent.stop()  # encerrar o Sentinel NÃO pode encerrar o servidor
    failed = [c for c in prepared if not c.ok]
    assert not failed, failed

    agent = RunningAgent(fast_settings)
    try:
        finished = server_selftest.finish(fast_settings)
    finally:
        agent.stop()
    failed = [c for c in finished if not c.ok]
    assert not failed, failed


def test_api_validation_conflicts_and_observed_protection(fast_settings, tmp_path):
    agent = RunningAgent(fast_settings)
    try:
        client = LocalClient(fast_settings)
        with pytest.raises(ApiError) as exc:
            client.request("POST", "/api/v1/servers", {"name": "x", "management": "managed", "executable": "/bin/bash"})
        assert exc.value.status == 422
        observed = client.request("POST", "/api/v1/servers", {"name": "Banco", "port": free_port(), "health_check": {"type": "tcp"}})
        with pytest.raises(ApiError) as exc:
            client.request("POST", "/api/v1/servers", {"name": "banco", "port": 1234})
        assert exc.value.status == 409  # nome único, sem diferenciar maiúsculas
        sid = observed["server"]["id"]
        with pytest.raises(ApiError) as exc:
            client.request("POST", f"/api/v1/servers/{sid}/actions/stop")
        assert exc.value.status == 409 and "apenas observado" in exc.value.detail
        with pytest.raises(ApiError) as exc:
            client.request("POST", f"/api/v1/servers/{sid}/actions/format")
        assert exc.value.status == 422  # só operações conhecidas existem
        logs = client.request("GET", f"/api/v1/servers/{sid}/logs")
        assert logs["available"] is False
        client.request("DELETE", f"/api/v1/servers/{sid}")
        with pytest.raises(ApiError) as exc:
            client.request("GET", f"/api/v1/servers/{sid}")
        assert exc.value.status == 404
    finally:
        agent.stop()


def test_server_opened_outside_sentinel_is_recognized_and_not_duplicated(fast_settings, tmp_path):
    """Cenário real: o servidor já rodava (aberto à mão, com outros argumentos)."""
    import shutil
    import subprocess
    import sys

    port = free_port()
    outside = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                               cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    agent = RunningAgent(fast_settings)
    try:
        client = LocalClient(fast_settings)
        deadline = time.time() + 10
        while time.time() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
        # Cadastro com argumentos diferentes dos usados para abrir o servidor.
        same_exe = client.request("POST", "/api/v1/servers", {
            "name": "aberto-fora", "management": "managed", "executable": sys.executable,
            "arguments": ["-m", "http.server", "9", "--directory", str(tmp_path)],
            "port": port, "health_check": {"type": "http"},
        })
        sid = same_exe["server"]["id"]
        item = None
        deadline = time.time() + 30
        while time.time() < deadline:
            item = client.request("GET", f"/api/v1/servers/{sid}")
            if item["status"]["state"] == "online":
                break
            time.sleep(1)
        assert item["status"]["state"] == "online" and item["status"]["match_source"] == "port"
        # No Windows o python.exe do venv é um lançador: quem abre a porta é o processo filho.
        family = {outside.pid} | {c.pid for c in psutil.Process(outside.pid).children(recursive=True)}
        assert item["status"]["main_pid"] in family

        with pytest.raises(ApiError) as exc:
            client.request("POST", f"/api/v1/servers/{sid}/actions/start")
        assert exc.value.status == 409 and "já está em execução" in exc.value.detail

        other = shutil.which("true") or sys.executable
        if other != sys.executable:
            wrong = client.request("POST", "/api/v1/servers", {
                "name": "outro-exe", "management": "managed", "executable": other, "port": port,
            })
            with pytest.raises(ApiError) as refused:
                client.request("POST", f"/api/v1/servers/{wrong['server']['id']}/actions/stop")
            assert refused.value.status == 409 and "não é o executável cadastrado" in refused.value.detail
            assert outside.poll() is None  # o processo de outro executável NÃO foi encerrado

        stopped = client.request("POST", f"/api/v1/servers/{sid}/actions/stop")
        assert stopped["ok"], stopped
        outside.wait(timeout=10)
    finally:
        agent.stop()
        if outside.poll() is None:
            outside.kill()


def _wait_for(fn, timeout, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    return None


def _events(settings, event_type):
    import sqlite3

    conn = sqlite3.connect(settings.paths.database_file)
    try:
        return [r[0] for r in conn.execute("SELECT title FROM events WHERE event_type = ? ORDER BY id", (event_type,))]
    finally:
        conn.close()


def test_auto_restart_recovers_and_respects_attempt_limit(fast_settings, tmp_path):
    """Política autorizada: recupera uma queda; quando a recuperação é impossível, desiste no limite."""
    import sys

    flag = tmp_path / "pode-iniciar"
    flag.write_text("1")
    script = tmp_path / "srv.py"
    script.write_text(
        "import http.server, os, sys\n"
        f"if not os.path.exists({str(flag)!r}): sys.exit(3)\n"
        "http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), http.server.SimpleHTTPRequestHandler).serve_forever()\n"
    )
    port = free_port()
    agent = RunningAgent(fast_settings)
    try:
        client = LocalClient(fast_settings)
        created = client.request("POST", "/api/v1/servers", {
            "name": "auto", "management": "managed", "executable": sys.executable,
            "arguments": [str(script), str(port)], "port": port, "health_check": {"type": "tcp"},
            "startup_grace_seconds": 5,
            "restart_policy": {"enabled": True, "max_attempts": 2, "window_minutes": 60, "initial_delay_seconds": 0},
        })
        sid = created["server"]["id"]
        first = client.request("POST", f"/api/v1/servers/{sid}/actions/start")
        assert first["ok"], first

        # 1) queda recuperável: o Sentinel reinicia sozinho
        psutil.Process(first["pid"]).kill()
        recovered = _wait_for(lambda: (d := client.request("GET", f"/api/v1/servers/{sid}"))["status"]["state"] == "online"
                              and d["status"]["main_pid"] not in (None, first["pid"]) and d, 40)
        assert recovered, "não recuperou automaticamente"
        assert any("recuperado" in t for t in _events(fast_settings, "server.auto_restart"))

        # 2) queda irrecuperável: tenta até o limite e desiste avisando
        flag.unlink()
        psutil.Process(recovered["status"]["main_pid"]).kill()
        exhausted = _wait_for(lambda: any("esgotado" in t for t in _events(fast_settings, "server.auto_restart")), 60)
        assert exhausted, _events(fast_settings, "server.auto_restart")
        status = client.request("GET", f"/api/v1/servers/{sid}")["status"]
        assert status["auto_restart_exhausted"] and len(status["auto_restarts"]) == 2
        assert status["state"] == "offline"

        # auditoria identifica a política como autora
        import sqlite3
        conn = sqlite3.connect(fast_settings.paths.database_file)
        actors = {r[0] for r in conn.execute("SELECT actor FROM audit_logs WHERE target = 'auto'")}
        conn.close()
        assert "sentinel:politica-reinicio" in actors
    finally:
        agent.stop()


def test_restart_policy_requires_managed_server(fast_settings):
    agent = RunningAgent(fast_settings)
    try:
        client = LocalClient(fast_settings)
        with pytest.raises(ApiError) as exc:
            client.request("POST", "/api/v1/servers", {"name": "obs", "port": 5432, "restart_policy": {"enabled": True}})
        assert exc.value.status == 422
    finally:
        agent.stop()


def test_crash_creates_approval_and_deleting_server_cancels_it(fast_settings):
    import sys

    agent = RunningAgent(fast_settings)
    try:
        client = LocalClient(fast_settings)
        port = free_port()
        sid = client.request("POST", "/api/v1/servers", {
            "name": "proposta", "management": "managed", "executable": sys.executable,
            "arguments": ["-m", "http.server", str(port), "--bind", "127.0.0.1"], "port": port, "health_check": {"type": "tcp"},
        })["server"]["id"]
        started = client.request("POST", f"/api/v1/servers/{sid}/actions/start")
        psutil.Process(started["pid"]).kill()
        pending = _wait_for(lambda: client.request("GET", "/api/v1/approvals")["approvals"], 30)
        assert pending and pending[0]["target_id"] == sid and pending[0]["requested_by"] == "sentinel:servidores"
        client.request("DELETE", f"/api/v1/servers/{sid}")
        assert client.request("GET", "/api/v1/approvals")["pending"] == 0
        assert client.request("GET", f"/api/v1/actions/{pending[0]['id']}")["status"] == "cancelled"
    finally:
        agent.stop()
