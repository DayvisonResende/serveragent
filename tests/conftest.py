from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.agent.config import (
    AgentSettings,
    LoggingSettings,
    PathsSettings,
    Settings,
)
from sentinel.oslayer.info import PlatformInfo


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        paths=PathsSettings(
            data_dir=tmp_path / "data",
            log_dir=tmp_path / "logs",
            database_file=tmp_path / "data" / "sentinel.db",
        ),
        logging=LoggingSettings(console=False),
        agent=AgentSettings(
            heartbeat_interval_seconds=5,
            module_start_timeout_seconds=1,
            module_stop_timeout_seconds=1,
            shutdown_timeout_seconds=2,
        ),
    )


@pytest.fixture
def platform_info() -> PlatformInfo:
    return PlatformInfo("TestOS", "1", "1", "x86_64", "3.14", is_admin=False)


@pytest.fixture(autouse=True)
def _isolate_error_log(tmp_path, monkeypatch):
    """Erros anteriores à leitura da configuração não devem sujar a pasta logs/ do projeto."""
    monkeypatch.setattr("sentinel.agent.main.DEFAULT_ERROR_LOG_DIR", tmp_path / "default-logs")
