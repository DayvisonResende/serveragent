from pathlib import Path

import pytest
import yaml

from sentinel.agent.config import (
    CONFIG_ENV_VAR,
    DEFAULT_CONFIG_PATH,
    Settings,
    default_settings_yaml,
    load_settings,
)
from sentinel.core.exceptions import ConfigurationError


def write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_repository_settings_file_is_valid_and_matches_defaults():
    loaded = load_settings(DEFAULT_CONFIG_PATH, base=Path("/base"))
    assert loaded == Settings().with_resolved_paths(Path("/base"))


def test_default_yaml_round_trips(tmp_path):
    path = write(tmp_path / "s.yaml", default_settings_yaml())
    assert load_settings(path, base=tmp_path) == Settings().with_resolved_paths(tmp_path)


def test_empty_file_uses_defaults(tmp_path):
    settings = load_settings(write(tmp_path / "s.yaml", ""), base=tmp_path)
    assert settings.agent.heartbeat_interval_seconds == 30


def test_relative_paths_resolve_against_base_not_cwd(tmp_path):
    settings = load_settings(write(tmp_path / "s.yaml", "paths: {data_dir: dados}"), base=tmp_path)
    assert settings.paths.data_dir == tmp_path / "dados"
    assert settings.paths.database_file == tmp_path / "data" / "sentinel.db"


def test_absolute_paths_are_kept(tmp_path):
    target = tmp_path / "abs"
    cfg = yaml.safe_dump({"paths": {"log_dir": str(target)}})
    settings = load_settings(write(tmp_path / "s.yaml", cfg), base=Path("/other"))
    assert settings.paths.log_dir == target


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="agent.heartbeat_intervl"):
        load_settings(write(tmp_path / "s.yaml", "agent: {heartbeat_intervl: 10}"))


def test_out_of_range_value_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="heartbeat_interval_seconds"):
        load_settings(write(tmp_path / "s.yaml", "agent: {heartbeat_interval_seconds: 1}"))


def test_non_mapping_root_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="mapeamento"):
        load_settings(write(tmp_path / "s.yaml", "- a\n- b\n"))


def test_malformed_yaml_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="Não foi possível ler"):
        load_settings(write(tmp_path / "s.yaml", "agent: [unclosed"))


def test_missing_file_mentions_init(tmp_path):
    with pytest.raises(ConfigurationError, match="sentinel init"):
        load_settings(tmp_path / "missing.yaml")


def test_env_var_selects_config(tmp_path, monkeypatch):
    path = write(tmp_path / "env.yaml", "logging: {level: DEBUG}")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
    assert load_settings().logging.level == "DEBUG"


def test_settings_are_immutable():
    with pytest.raises(Exception):
        Settings().agent.heartbeat_interval_seconds = 99  # type: ignore[misc]
