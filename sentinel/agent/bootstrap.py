"""Preparação do ambiente: diretórios, configuração padrão e banco (PRD 20.1)."""

from __future__ import annotations

from pathlib import Path

from sentinel.agent.config import Settings, default_settings_yaml
from sentinel.database.database import Database
from sentinel.database.migrations import apply_migrations


def ensure_directories(settings: Settings) -> None:
    for directory in (settings.paths.data_dir, settings.paths.log_dir, settings.paths.database_file.parent):
        directory.mkdir(parents=True, exist_ok=True)


def write_default_config(path: Path) -> bool:
    """Cria o arquivo de configuração com valores padrão. Nunca sobrescreve um existente."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_settings_yaml(), encoding="utf-8")
    return True


async def initialize_database(settings: Settings) -> tuple[list[int], list[str]]:
    """Cria/atualiza o banco. Retorna (migrações aplicadas, resultado da verificação de integridade)."""
    db = Database(settings.paths.database_file, settings.database.busy_timeout_ms)
    await db.open()
    try:
        applied = await apply_migrations(db)
        integrity = await db.integrity_check()
    finally:
        await db.close()
    return applied, integrity
