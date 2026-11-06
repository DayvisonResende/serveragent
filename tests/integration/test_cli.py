"""Integração da CLI: init, check-config, status e o agente real em subprocesso."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from sentinel.agent import bootstrap
from sentinel.agent.config import PROJECT_ROOT
from sentinel.agent.main import EXIT_CONFIG, EXIT_LOCKED, EXIT_OK, main


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_config(tmp_path: Path) -> Path:
    cfg = {
        "api": {"port": free_port()},
        "paths": {
            "data_dir": str(tmp_path / "data"),
            "log_dir": str(tmp_path / "logs"),
            "database_file": str(tmp_path / "data" / "sentinel.db"),
        },
        "logging": {"console": False},
        "agent": {"heartbeat_interval_seconds": 5},
    }
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_init_prepares_database_and_is_idempotent(tmp_path, capsys):
    config = make_config(tmp_path)
    assert main(["--config", str(config), "init"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "existente" in out and "0001, 0002, 0003" in out and "Integridade  : ok" in out
    assert (tmp_path / "data" / "sentinel.db").exists()
    assert main(["--config", str(config), "init"]) == EXIT_OK
    assert "nenhuma pendente" in capsys.readouterr().out


def test_write_default_config_never_overwrites(tmp_path):
    path = tmp_path / "cfg" / "settings.yaml"
    assert bootstrap.write_default_config(path) is True
    path.write_text("logging: {level: DEBUG}")
    assert bootstrap.write_default_config(path) is False
    assert path.read_text() == "logging: {level: DEBUG}"


def test_check_config_reports_invalid_file(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("agent: {nope: 1}")
    assert main(["--config", str(bad), "check-config"]) == EXIT_CONFIG
    assert "agent.nope" in capsys.readouterr().err
    assert "agent.nope" in (tmp_path / "default-logs" / "startup-error.log").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="usa SIGTERM")
def test_real_agent_process_runs_refuses_second_instance_and_stops_cleanly(tmp_path, capsys):
    config = make_config(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    cmd = [sys.executable, "-m", "sentinel", "--config", str(config), "run"]
    proc = subprocess.Popen(cmd, cwd=tmp_path, env=env)
    try:
        db = tmp_path / "data" / "sentinel.db"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if db.exists() and main(["--config", str(config), "status"]) == EXIT_OK:
                if "em execução" in capsys.readouterr().out:
                    break
            time.sleep(0.2)
        else:
            pytest.fail("agente não ficou em execução")

        second = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15)
        assert second.returncode == EXIT_LOCKED
        assert "já está em execução" in second.stderr
        assert "já está em execução" in (tmp_path / "logs" / "startup-error.log").read_text(encoding="utf-8")
    finally:
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=15) == EXIT_OK

    assert main(["--config", str(config), "status"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "parado (clean)" in out
    assert "Sentinel encerrado" in out


@pytest.mark.skipif(sys.platform == "win32", reason="agente em subprocesso encerrado por sinal")
def test_stop_command_stops_agent_cleanly_and_dashboard_link(tmp_path, capsys):
    config = make_config(tmp_path)
    assert main(["--config", str(config), "stop"]) == EXIT_OK  # sem banco: nada a fazer
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    proc = subprocess.Popen([sys.executable, "-m", "sentinel", "--config", str(config), "run"], cwd=tmp_path, env=env)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (tmp_path / "data" / "sentinel.db").exists() and main(["--config", str(config), "status"]) == EXIT_OK:
                if "em execução" in capsys.readouterr().out:
                    break
            time.sleep(0.2)
        assert main(["--config", str(config), "dashboard", "--no-browser"]) == EXIT_OK
        assert "/login?code=" in capsys.readouterr().out
        assert main(["--config", str(config), "stop"]) == EXIT_OK
        assert "Agente encerrado (clean)" in capsys.readouterr().out
        assert proc.wait(timeout=10) == EXIT_OK
    finally:
        if proc.poll() is None:
            proc.kill()
    assert main(["--config", str(config), "dashboard", "--no-browser"]) == 1  # agente parado
    assert not (tmp_path / "data" / "stop.request").exists()
