"""Configuração centralizada (PRD 26.9).

Lida de ``config/settings.yaml`` (ou do caminho em ``SENTINEL_CONFIG``),
validada com pydantic. Chaves desconhecidas são rejeitadas para que erros de
digitação não passem despercebidos. Caminhos relativos são resolvidos a partir
da raiz do projeto, nunca do diretório de trabalho atual.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sentinel.core.exceptions import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"
CONFIG_ENV_VAR = "SENTINEL_CONFIG"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsSettings(_Section):
    data_dir: Path = Path("data")
    log_dir: Path = Path("logs")
    database_file: Path = Path("data/sentinel.db")

    def resolved(self, base: Path) -> PathsSettings:
        def fix(p: Path) -> Path:
            return p if p.is_absolute() else (base / p)

        return PathsSettings(
            data_dir=fix(self.data_dir), log_dir=fix(self.log_dir), database_file=fix(self.database_file)
        )


class LoggingSettings(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_bytes: int = Field(5 * 1024 * 1024, ge=64 * 1024, le=100 * 1024 * 1024)
    backup_count: int = Field(5, ge=1, le=50)
    console: bool = True


class DatabaseSettings(_Section):
    busy_timeout_ms: int = Field(5000, ge=100, le=60_000)
    integrity_check_on_start: bool = True


class AgentSettings(_Section):
    heartbeat_interval_seconds: float = Field(30, ge=5, le=600)
    module_start_timeout_seconds: float = Field(15, ge=1, le=300)
    module_stop_timeout_seconds: float = Field(10, ge=1, le=300)
    shutdown_timeout_seconds: float = Field(10, ge=1, le=120)


class EventBusSettings(_Section):
    queue_size: int = Field(1000, ge=10, le=100_000)
    handler_timeout_seconds: float = Field(5, ge=0.1, le=60)


class SchedulerSettings(_Section):
    default_job_timeout_seconds: float = Field(30, ge=1, le=3600)
    max_backoff_multiplier: float = Field(8, ge=1, le=64)
    max_load_factor: float = Field(4, ge=1, le=16)


class Settings(_Section):
    paths: PathsSettings = PathsSettings()
    logging: LoggingSettings = LoggingSettings()
    database: DatabaseSettings = DatabaseSettings()
    agent: AgentSettings = AgentSettings()
    event_bus: EventBusSettings = EventBusSettings()
    scheduler: SchedulerSettings = SchedulerSettings()

    def with_resolved_paths(self, base: Path = PROJECT_ROOT) -> Settings:
        return self.model_copy(update={"paths": self.paths.resolved(base)})


def resolve_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get(CONFIG_ENV_VAR)
    return Path(env) if env else DEFAULT_CONFIG_PATH


def load_settings(path: Path | None = None, base: Path = PROJECT_ROOT) -> Settings:
    config_path = resolve_config_path(path)
    if not config_path.is_file():
        raise ConfigurationError(
            f"Arquivo de configuração não encontrado: {config_path}. Execute 'python -m sentinel init'."
        )
    try:
        raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Não foi possível ler {config_path}: {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigurationError(f"{config_path} deve conter um mapeamento YAML no nível raiz")

    try:
        settings = Settings.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigurationError(f"Configuração inválida em {config_path}: {problems}") from exc
    return settings.with_resolved_paths(base)


def default_settings_yaml() -> str:
    """YAML com os valores padrão, usado pelo ``init`` quando o arquivo não existe."""
    data = Settings().model_dump(mode="json")
    header = (
        "# Configuração do Sentinel. Caminhos relativos partem da raiz do projeto.\n"
        "# Chaves desconhecidas são rejeitadas na inicialização.\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
