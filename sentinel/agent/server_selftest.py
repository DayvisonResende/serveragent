"""Autoteste de servidores contra o agente real (critérios 4 a 10 e 12 do MVP).

``prepare``: cadastra um servidor de teste (http.server do Python), inicia, derruba
à força, confirma detecção e incidente, reinicia e deixa rodando.
``finish``: depois que o Sentinel foi encerrado e reiniciado, confirma que o
servidor sobreviveu e foi reencontrado; então o para e remove o cadastro.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path
from typing import Any, Callable

import psutil

from sentinel.agent.client import ApiError, LocalClient
from sentinel.agent.config import Settings
from sentinel.agent.selfcheck import Check

TEST_NAME = "sentinel-teste"


def _state_file(settings: Settings) -> Path:
    return settings.paths.data_dir / "selftest" / "state.json"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _base_python() -> str:
    # No Windows o python.exe do venv é só um lançador; o interpretador real é o base.
    return getattr(sys, "_base_executable", None) or sys.executable


def _wait(fn: Callable[[], Any], timeout: float, interval: float = 1.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    return None


def _find(client: LocalClient) -> dict[str, Any] | None:
    for item in client.request("GET", "/api/v1/servers")["servers"]:
        if item["server"]["name"] == TEST_NAME:
            return item
    return None


def _cleanup_previous(client: LocalClient, checks: list[Check]) -> None:
    previous = _find(client)
    if previous is None:
        return
    sid = previous["server"]["id"]
    if previous["status"]["pids"]:
        try:
            client.request("POST", f"/api/v1/servers/{sid}/actions/stop", {"reason": "limpeza do autoteste"})
        except ApiError:
            pass
    client.request("DELETE", f"/api/v1/servers/{sid}")
    checks.append(Check("Limpeza de teste anterior", True, "cadastro de teste antigo removido"))


def prepare(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    client = LocalClient(settings)
    client.login()
    _cleanup_previous(client, checks)

    root = settings.paths.data_dir / "selftest" / "www"
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<p>Sentinel selftest</p>", encoding="utf-8")
    port = _free_port()
    spec = {
        "name": TEST_NAME,
        "description": "Servidor temporário do autoteste (verificar.bat)",
        "server_type": "python",
        "management": "managed",
        "executable": _base_python(),
        "arguments": ["-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(root)],
        "port": port,
        "protocol": "http",
        "health_check": {"type": "http", "path": "/", "timeout_seconds": 3},
        "criticality": "high",
        "startup_grace_seconds": 30,
    }
    created = client.request("POST", "/api/v1/servers", spec)
    sid = created["server"]["id"]
    checks.append(Check("Cadastro de servidor", True, f"'{TEST_NAME}' (id {sid}) na porta {port}"))

    started = client.request("POST", f"/api/v1/servers/{sid}/actions/start", {"reason": "autoteste"})
    ok = started["ok"] and started["state"] == "online"
    detail = f"{started['message']} em {started['duration_seconds']}s"
    if started.get("warning"):
        detail += f" — ATENÇÃO: {started['warning']}"
    checks.append(Check("Iniciar servidor (desacoplado do Sentinel)", ok and not started.get("warning"), detail))
    if not ok:
        return checks
    pid = started["pid"]

    # Simula uma queda: encerra o processo por fora do Sentinel.
    for proc in [psutil.Process(pid), *psutil.Process(pid).children(recursive=True)]:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    s = settings.servers
    detect_timeout = s.check_interval_seconds * (s.failure_threshold + 2) + 15
    down = _wait(lambda: (d := client.request("GET", f"/api/v1/servers/{sid}"))["status"]["state"] == "offline" and d, detect_timeout)
    checks.append(Check("Queda detectada", bool(down), "estado 'offline'" if down else f"não detectada em {detect_timeout:.0f}s"))
    if not down:
        return checks
    incidents = client.request("GET", f"/api/v1/servers/{sid}/incidents")["incidents"]
    open_incident = next((i for i in incidents if i["closed_epoch"] is None), None)
    checks.append(Check("Incidente registrado", open_incident is not None, open_incident["title"] if open_incident else "nenhum incidente aberto"))

    try:
        restarted = client.request("POST", f"/api/v1/servers/{sid}/actions/restart", {"reason": "recuperação no autoteste"})
    except ApiError as exc:
        checks.append(Check("Reinicialização controlada", False, str(exc.detail)))
        return checks
    checks.append(Check("Reinicialização controlada", restarted["ok"] and restarted["state"] == "online", restarted["message"]))
    if not restarted["ok"] or restarted["pid"] is None:
        return checks
    incidents = client.request("GET", f"/api/v1/servers/{sid}/incidents")["incidents"]
    closed = incidents and incidents[0]["closed_epoch"] is not None
    checks.append(Check("Incidente encerrado após recuperação", bool(closed),
                        f"duração {incidents[0]['duration_seconds']}s" if closed else "incidente continua aberto"))
    audit = _audited_operations(settings)
    checks.append(Check("Operações registradas no histórico", {"server_start", "server_restart"} <= audit,
                        "auditoria: " + ", ".join(sorted(audit)) if audit else "nenhum registro de auditoria"))

    _state_file(settings).write_text(json.dumps({"server_id": sid, "pid": restarted["pid"]}), encoding="utf-8")
    checks.append(Check("Servidor de teste em execução", True, f"PID {restarted['pid']} (usado na próxima etapa)"))
    return checks


def _audited_operations(settings: Settings) -> set[str]:
    import sqlite3

    conn = sqlite3.connect(f"file:{settings.paths.database_file}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT operation FROM audit_logs WHERE target = ? AND result = 'success' ORDER BY id DESC LIMIT 20", (TEST_NAME,)
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def finish(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    state_path = _state_file(settings)
    if not state_path.exists():
        return [Check("Estado do autoteste", False, "execute a etapa 'prepare' antes")]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    sid, pid = state["server_id"], state["pid"]
    if not isinstance(pid, int):
        return [Check("Estado do autoteste", False, "a etapa 'prepare' não terminou com sucesso")]
    checks.append(Check("Servidor sobreviveu ao encerramento do Sentinel", psutil.pid_exists(pid), f"PID {pid}"))

    client = LocalClient(settings)
    client.login()
    item = _wait(lambda: (d := client.request("GET", f"/api/v1/servers/{sid}"))["status"]["state"] == "online"
                 and d["status"]["main_pid"] is not None and d,
                 settings.servers.check_interval_seconds * 3 + 10)
    checks.append(Check("Agente reencontrou o servidor após reiniciar", bool(item) and item["status"]["main_pid"] == pid,
                        f"estado {item['status']['state']}, PID {item['status']['main_pid']}" if item else "não ficou online"))

    stopped = client.request("POST", f"/api/v1/servers/{sid}/actions/stop", {"reason": "fim do autoteste"})
    gone = not psutil.pid_exists(pid)
    checks.append(Check("Parar servidor", stopped["ok"] and gone, stopped["message"]))
    incidents = client.request("GET", f"/api/v1/servers/{sid}/incidents")["incidents"]
    new_incident = any(i["closed_epoch"] is None for i in incidents)
    checks.append(Check("Parada pedida não gera incidente", not new_incident, "nenhum incidente aberto" if not new_incident else "incidente indevido"))

    client.request("DELETE", f"/api/v1/servers/{sid}")
    state_path.unlink(missing_ok=True)
    checks.append(Check("Cadastro de teste removido", True, TEST_NAME))
    return checks
