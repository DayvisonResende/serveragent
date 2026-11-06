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
