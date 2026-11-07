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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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


class MonitoringSettings(_Section):
    """Intervalos de coleta (PRD 5.8). Sob carga, os não essenciais são alongados."""

    fast_interval_seconds: float = Field(5, ge=1, le=300)  # CPU, RAM, rede (essencial)
    disk_interval_seconds: float = Field(30, ge=5, le=3600)
    process_interval_seconds: float = Field(15, ge=5, le=3600)
    temperature_interval_seconds: float = Field(30, ge=5, le=3600)
    persist_interval_seconds: float = Field(60, ge=10, le=3600)  # agregação gravada no banco
    process_snapshot_interval_seconds: float = Field(300, ge=30, le=86_400)
    process_snapshot_top_n: int = Field(10, ge=1, le=100)
    disk_history_interval_seconds: float = Field(1800, ge=60, le=86_400)
    live_history_seconds: int = Field(3600, ge=60, le=6 * 3600)  # histórico em memória (resolução total)
    collector_timeout_seconds: float = Field(10, ge=1, le=60)


class AlertSettings(_Section):
    cpu_percent: float = Field(90, ge=10, le=100)
    cpu_sustained_seconds: float = Field(60, ge=0, le=3600)
    memory_percent: float = Field(90, ge=10, le=100)
    memory_sustained_seconds: float = Field(30, ge=0, le=3600)
    disk_free_warning_percent: float = Field(10, ge=1, le=50)
    disk_free_critical_percent: float = Field(5, ge=0.5, le=50)
    hysteresis_percent: float = Field(5, ge=0, le=20)  # margem para considerar normalizado


class ResourceSettings(_Section):
    """Modo de baixa prioridade (PRD 13.3)."""

    pressure_cpu_percent: float = Field(80, ge=10, le=100)
    pressure_memory_percent: float = Field(90, ge=10, le=100)
    severe_cpu_percent: float = Field(95, ge=10, le=100)
    pressure_load_factor: float = Field(2, ge=1, le=16)
    severe_load_factor: float = Field(4, ge=1, le=16)
    smoothing_samples: int = Field(6, ge=1, le=120)  # média móvel das amostras rápidas
    hysteresis_percent: float = Field(10, ge=0, le=50)


class ServersSettings(_Section):
    """Gerenciamento de servidores (PRD 6)."""

    check_interval_seconds: float = Field(15, ge=5, le=600)
    failure_threshold: int = Field(2, ge=1, le=10)  # falhas seguidas antes de rebaixar o estado
    check_concurrency: int = Field(4, ge=1, le=16)
    stop_timeout_seconds: float = Field(10, ge=1, le=120)
    operations_per_window: int = Field(5, ge=1, le=50)  # limite de operações por servidor...
    operations_window_seconds: float = Field(600, ge=60, le=86_400)  # ...nesta janela


class SecuritySettings(_Section):
    """Aprovações (PRD 11.3)."""

    approval_ttl_minutes: int = Field(30, ge=1, le=1440)  # prazo para aprovar antes de expirar
    propose_server_restart: bool = True  # servidor gerenciado caiu sem política → pede aprovação para reiniciar
    autostart_scan_minutes: int = Field(10, ge=1, le=1440)


class RetentionSettings(_Section):
    """Retenção por categoria (PRD 16.2). Executada diariamente."""

    metrics_days: int = Field(30, ge=1, le=3650)
    process_snapshots_days: int = Field(7, ge=1, le=3650)
    disk_history_days: int = Field(365, ge=7, le=3650)
    events_days: int = Field(90, ge=7, le=3650)
    server_checks_days: int = Field(7, ge=1, le=365)


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ApiSettings(_Section):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1024, le=65_535)
    session_hours: float = Field(12, ge=0.25, le=720)
    login_code_seconds: int = Field(120, ge=10, le=600)

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        # Acesso remoto exige autenticação por senha e HTTPS (PRD 17.3/17.4) — previsto para fase futura.
        if value not in _LOOPBACK_HOSTS:
            raise ValueError("a API só pode escutar em 127.0.0.1, ::1 ou localhost nesta versão")
        return value


class Settings(_Section):
    paths: PathsSettings = PathsSettings()
    logging: LoggingSettings = LoggingSettings()
    database: DatabaseSettings = DatabaseSettings()
    agent: AgentSettings = AgentSettings()
    event_bus: EventBusSettings = EventBusSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    monitoring: MonitoringSettings = MonitoringSettings()
    alerts: AlertSettings = AlertSettings()
    resources: ResourceSettings = ResourceSettings()
    servers: ServersSettings = ServersSettings()
    security: SecuritySettings = SecuritySettings()
    retention: RetentionSettings = RetentionSettings()
    api: ApiSettings = ApiSettings()

    @model_validator(mode="after")
    def _cross_checks(self) -> Settings:
        if self.resources.severe_load_factor > self.scheduler.max_load_factor:
            raise ValueError("resources.severe_load_factor não pode exceder scheduler.max_load_factor")
        if self.resources.pressure_load_factor > self.resources.severe_load_factor:
            raise ValueError("resources.pressure_load_factor não pode exceder resources.severe_load_factor")
        if self.alerts.disk_free_critical_percent >= self.alerts.disk_free_warning_percent:
            raise ValueError("alerts.disk_free_critical_percent deve ser menor que disk_free_warning_percent")
        return self

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
