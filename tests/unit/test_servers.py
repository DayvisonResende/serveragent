"""Servidores: validação do cadastro, reconhecimento de processos, estados e verificações."""

import asyncio
import http.server
import socket
import sys
import threading
import time

import psutil
import pytest
from pydantic import ValidationError

from sentinel.modules.monitor.processes import ProcessInfo
from sentinel.modules.servers.health import HealthResult, Observation, check_health, evaluate
from sentinel.modules.servers.logs import tail_file
from sentinel.modules.servers.matching import confirm_alive, find_server_processes
from sentinel.modules.servers.models import HealthCheck, ProcessMatch, ServerSpec, ServerState
from sentinel.oslayer.process_control import launch_detached, protection_reason, terminate_tree

PY = sys.executable


# ------------------------------------------------------------------ cadastro

def test_managed_server_requires_existing_absolute_executable(tmp_path):
    with pytest.raises(ValidationError, match="executável"):
        ServerSpec(name="a", management="managed")
    with pytest.raises(ValidationError, match="absoluto"):
        ServerSpec(name="a", management="managed", executable="python")
    with pytest.raises(ValidationError, match="não encontrado"):
        ServerSpec(name="a", management="managed", executable=str(tmp_path / "nada"))
    assert ServerSpec(name="a", management="managed", executable=PY).executable == PY


@pytest.mark.parametrize("shell", ["/bin/bash", "/bin/sh", r"C:\Windows\System32\cmd.exe", r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"])
def test_command_interpreters_cannot_be_servers(shell):
    with pytest.raises(ValidationError, match="interpretador"):
        ServerSpec(name="x", management="managed", executable=shell)


def test_argument_and_field_limits():
    with pytest.raises(ValidationError):
        ServerSpec(name="x", management="managed", executable=PY, arguments=["a"] * 51)
    with pytest.raises(ValidationError):
        ServerSpec(name="x", management="managed", executable=PY, arguments=["a\x00b"])
    with pytest.raises(ValidationError, match="porta"):
        ServerSpec(name="x", executable=PY, health_check={"type": "http"})
    with pytest.raises(ValidationError):
        ServerSpec(name="x", port=80, health_check={"type": "http", "path": "sem-barra"})
    with pytest.raises(ValidationError, match="reconhecer"):
        ServerSpec(name="x")
    with pytest.raises(ValidationError):
        ServerSpec(name="x", port=80, comando="rm -rf /")  # campos desconhecidos são recusados


def test_observed_server_needs_only_a_way_to_be_recognized():
    spec = ServerSpec(name="db", port=5432, health_check={"type": "tcp"})
    assert spec.management == "observed"
    assert spec.effective_match() == ProcessMatch(port_owner=True)
    spec = ServerSpec(name="game", management="managed", executable=PY, arguments=["server.py", ""])
    assert spec.effective_match().cmdline_contains == ["server.py"]


# ---------------------------------------------------------- reconhecimento

def proc(pid, name="node.exe", exe="/srv/node", cmd=("node", "server.js"), ppid=1, created=100.0, status="running"):
    return ProcessInfo(pid, name, exe, None, status, None, created, 1.0, 1000, 0.1, ppid=ppid, cmdline=cmd)


def test_match_by_exe_and_cmdline_picks_root_process():
    procs = [
        proc(10, cmd=("node", "server.js")),
        proc(11, cmd=("node", "server.js", "--worker"), ppid=10, created=101),
        proc(12, cmd=("node", "outro.js")),
        proc(13, exe="/outro/node", cmd=("node", "server.js")),
    ]
    result = find_server_processes(procs, ProcessMatch(exe_path="/srv/node", cmdline_contains=["server.js"]), None, {})
    assert result.pids == [10, 11] and result.main_pid == 10


def test_match_by_port_owner_and_zombies_are_ignored():
    procs = [proc(20, name="postgres.exe"), proc(21, name="postgres.exe", status="zombie")]
    listeners = {5432: {20}}
    result = find_server_processes(procs, ProcessMatch(port_owner=True), 5432, listeners)
    assert result.pids == [20]
    by_name = find_server_processes(procs, ProcessMatch(name="POSTGRES.EXE"), None, {})
    assert by_name.pids == [20]


def test_broad_match_is_flagged():
    procs = [proc(i, name="svchost.exe", exe=None, cmd=None) for i in range(100, 140)]
    assert find_server_processes(procs, ProcessMatch(name="svchost.exe"), None, {}).too_broad


def test_confirm_alive_drops_dead_and_reused_pids():
    me = psutil.Process()
    live = proc(me.pid, created=me.create_time())
    reused = proc(me.pid + 0, created=me.create_time() - 1000)  # mesmo PID, outro processo
    dead = proc(999_999_9, created=1.0)
    result = find_server_processes([live, dead], ProcessMatch(name="node.exe"), None, {})
    assert confirm_alive(result).pids == [me.pid]
    assert confirm_alive(find_server_processes([reused], ProcessMatch(name="node.exe"), None, {})).pids == []


# ------------------------------------------------------------------ estados

def obs(alive=True, status="ok"):
    return Observation(alive, HealthResult(status))


def test_state_needs_consecutive_failures_but_recovers_immediately():
    e = evaluate(ServerState.ONLINE, 0, obs(status="fail"), failure_threshold=2)
    assert e.state is ServerState.ONLINE and e.failures == 1  # tolerância
    e = evaluate(ServerState.ONLINE, e.failures, obs(status="fail"), failure_threshold=2)
    assert e.state is ServerState.DEGRADED
    assert evaluate(ServerState.DEGRADED, 5, obs()).state is ServerState.ONLINE


def test_state_mapping():
    assert evaluate(ServerState.UNKNOWN, 0, obs(alive=False)).state is ServerState.OFFLINE  # 1ª observação
    assert evaluate(ServerState.UNKNOWN, 0, obs(status="timeout")).state is ServerState.UNRESPONSIVE
    online = evaluate(ServerState.UNKNOWN, 0, obs(status="skipped"))
    assert online.state is ServerState.ONLINE and online.health_verified is False  # processo ativo ≠ saudável
    assert evaluate(ServerState.OFFLINE, 3, obs(status="timeout")).state is ServerState.UNRESPONSIVE


# ------------------------------------------------------------- verificações

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            code = 500 if self.path == "/erro" else 200
            if self.path == "/lento":
                time.sleep(2)
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


def test_http_tcp_and_port_checks(http_server):
    port = http_server
    listeners = {port: {None}}
    run = lambda check, p=port: asyncio.run(check_health(check, p, listeners))  # noqa: E731
    ok = run(HealthCheck(type="http", path="/"))
    assert ok.status == "ok" and ok.response_time_ms is not None
    assert run(HealthCheck(type="http", path="/erro")).status == "fail"
    assert run(HealthCheck(type="http", path="/erro", expected_status=500)).status == "ok"
    assert run(HealthCheck(type="http", path="/lento", timeout_seconds=0.5)).status == "timeout"
    assert run(HealthCheck(type="tcp")).status == "ok"
    assert run(HealthCheck(type="port")).status == "ok"
    closed = free_port()
    assert asyncio.run(check_health(HealthCheck(type="tcp"), closed, {})).status == "fail"
    assert asyncio.run(check_health(HealthCheck(type="port"), closed, {})).status == "fail"
    assert asyncio.run(check_health(HealthCheck(), None, {})).status == "skipped"


# ------------------------------------------------------- controle de processos

def test_launch_detached_logs_output_and_terminate_tree(tmp_path):
    log_file = tmp_path / "logs" / "srv.log"
    script = "import time,sys; print('pronto', flush=True); time.sleep(60)"
    result = launch_detached(PY, ["-c", script], str(tmp_path), log_file)
    try:
        assert result.detached_from_job and psutil.pid_exists(result.pid)
        if sys.platform != "win32":
            assert psutil.Process(result.pid).pid == __import__("os").getsid(result.pid)  # nova sessão
        deadline = time.time() + 5
        while "pronto" not in log_file.read_text(encoding="utf-8") and time.time() < deadline:
            time.sleep(0.1)
        assert "pronto" in log_file.read_text(encoding="utf-8")
        stopped = terminate_tree(result.pid, timeout=5)
        assert result.pid in stopped.stopped + stopped.forced and not stopped.still_alive
    finally:
        if result.popen:
            result.popen.wait(timeout=5)


def test_protected_processes_are_refused():
    assert protection_reason(psutil.Process()) is not None  # o próprio Sentinel
    with pytest.raises(PermissionError):
        terminate_tree(psutil.Process().pid)


def test_tail_file_reads_end_and_reports_missing(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(f"linha {i}" for i in range(1000)), encoding="utf-8")
    tail = tail_file(log, lines=3)
    assert tail["lines"] == ["linha 997", "linha 998", "linha 999"] and tail["truncated"]
    assert tail_file(tmp_path / "nao-existe.log")["available"] is False


# ------------------------------------------------------------ scripts .bat

from sentinel.modules.servers.models import is_script, validate_script  # noqa: E402
from sentinel.oslayer.process_control import script_command_line  # noqa: E402


def test_script_arguments_cannot_inject_commands():
    validate_script(r"C:\Servers\Mine (1.20)\start.bat", ["nogui", "-Xmx2G", "--port=25565", r"C:\dados\mundo"])
    for bad in (["a&calc"], ["x|y"], ["%PATH%"], ["dois args"], ["a>b"], ["^x"], ["!v!"], ['"q"']):
        with pytest.raises(ValueError, match="não permitido"):
            validate_script(r"C:\s\start.bat", bad)
    with pytest.raises(ValueError, match="caracteres"):
        validate_script(r"C:\s\a&b.bat", [])
    assert is_script(r"C:\x\START.CMD") and not is_script("/usr/bin/python") and not is_script(None)


def test_script_command_line_is_fixed_format(monkeypatch):
    monkeypatch.setenv("ComSpec", r"C:\Windows\system32\cmd.exe")
    line = script_command_line(r"C:\Servers\Mine (1.20)\start.bat", ["nogui"])
    assert line == r'"C:\Windows\system32\cmd.exe" /d /s /c ""C:\Servers\Mine (1.20)\start.bat" nogui"'


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows .bat é aceito")
def test_bat_is_refused_outside_windows(tmp_path):
    script = tmp_path / "start.bat"
    script.write_text("@echo off")
    with pytest.raises(ValidationError, match="só podem ser iniciados no Windows"):
        ServerSpec(name="x", management="managed", executable=str(script))


def test_script_server_is_recognized_by_its_cmd_host():
    spec = ServerSpec.model_validate(
        {"name": "mc", "management": "managed", "executable": r"C:\mc\start.bat"}, context={"skip_exists": True}
    )
    assert spec.effective_match() == ProcessMatch(name="cmd.exe", cmdline_contains=[r"C:\mc\start.bat"])


def test_descendants_count_towards_server_resources():
    cmd = proc(50, name="cmd.exe", exe=r"C:\Windows\system32\cmd.exe", cmd=("cmd.exe", "/c", r"C:\mc\start.bat"))
    java = proc(51, name="java.exe", exe=r"C:\java\java.exe", cmd=("java", "-jar", "server.jar"), ppid=50, created=101)
    grandchild = proc(52, name="conhost.exe", exe=None, cmd=None, ppid=51, created=102)
    other = proc(60, name="java.exe", exe=r"C:\java\java.exe", cmd=("java",), ppid=1)
    result = find_server_processes([cmd, java, grandchild, other], ProcessMatch(name="cmd.exe", cmdline_contains=[r"C:\mc\start.bat"]), None, {})
    assert result.main_pid == 50 and result.pids == [50, 51, 52]


# ------------------------------------------- reconhecimento pela porta (fallback)

from sentinel.modules.servers.matching import identify_server, port_owner_names  # noqa: E402


def test_server_started_outside_sentinel_is_recognized_by_port():
    caddy = proc(70, name="caddy.exe", exe=r"C:\caddy\caddy.exe", cmd=("caddy", "run", "--config", "outro.json"))
    registered = ProcessMatch(exe_path=r"C:\caddy\caddy.exe", cmdline_contains=["run", "--config", "Caddyfile"])
    listeners = {443: {70}}
    by_criteria = find_server_processes([caddy], registered, 443, listeners)
    assert not by_criteria.alive  # argumentos diferentes: o critério não bate
    result = identify_server([caddy], registered, 443, listeners)
    assert result.alive and result.source == "port" and result.main_pid == 70
    assert identify_server([caddy], registered, 443, {}).alive is False  # porta livre: offline mesmo


def test_port_owner_names():
    procs = [proc(70, name="caddy.exe")]
    assert port_owner_names(procs, 443, {}) is None  # livre
    assert port_owner_names(procs, 443, {443: {70}}) == [{"pid": 70, "name": "caddy.exe"}]
    assert port_owner_names(procs, 443, {443: {None}}) == []  # em uso, dono desconhecido
