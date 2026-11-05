"""Migrações versionadas do esquema.

Arquivos ``migrations/NNNN_nome.sql`` são aplicados em ordem, cada um em sua
própria transação, e registrados em ``schema_migrations``. Um banco que contém
versões desconhecidas (criado por um Sentinel mais novo) é recusado.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sentinel.core.clock import to_iso, utc_now
from sentinel.core.exceptions import DatabaseError, MigrationError
from sentinel.database.database import Database

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_FILE_PATTERN = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path

    def statements(self) -> list[str]:
        return split_sql(self.path.read_text(encoding="utf-8"))


def split_sql(script: str) -> list[str]:
    """Divide um script em instruções, respeitando blocos ``BEGIN ... END`` de triggers."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines(keepends=True):
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue
        buffer.append(line)
        candidate = "".join(buffer)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            buffer = []
    if "".join(buffer).strip():
        raise MigrationError("Instrução SQL incompleta no fim do script")
    return statements


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"Nome de migração inválido: {path.name} (esperado NNNN_nome.sql)")
        version = int(match.group(1))
        if version in found:
            raise MigrationError(f"Versão de migração duplicada: {version:04d}")
        found[version] = Migration(version, match.group(2), path)
    return [found[v] for v in sorted(found)]


async def apply_migrations(db: Database, directory: Path = MIGRATIONS_DIR) -> list[int]:
    """Aplica as migrações pendentes e retorna as versões aplicadas nesta chamada."""
    migrations = discover_migrations(directory)

    def applied_versions(conn: sqlite3.Connection) -> set[int]:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

    done = await db.run(applied_versions)
    unknown = done - {m.version for m in migrations}
    if unknown:
        raise MigrationError(
            f"O banco possui migrações desconhecidas {sorted(unknown)}; "
            "ele pode ter sido criado por uma versão mais nova do Sentinel"
        )

    applied: list[int] = []
    for migration in migrations:
        if migration.version in done:
            continue
        statements = migration.statements()

        def apply(conn: sqlite3.Connection, m: Migration = migration, stmts: list[str] = statements) -> None:
            for statement in stmts:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (m.version, m.name, to_iso(utc_now())),
            )

        try:
            await db.run(apply)
        except DatabaseError as exc:
            raise MigrationError(
                f"Falha ao aplicar a migração {migration.version:04d}_{migration.name}: {exc}"
            ) from exc
        log.info("Migração aplicada", extra={"version": migration.version, "migration": migration.name})
        applied.append(migration.version)
    return applied
