"""Cadastro de servidores, histórico de verificações e incidentes."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from sentinel.core.clock import to_iso, utc_now
from sentinel.core.exceptions import DatabaseError
from sentinel.database.database import Database
from sentinel.modules.servers.models import ServerRecord, ServerSpec

_COLUMNS = (
    "id, name, description, server_type, management, executable, arguments_json, working_directory, port, "
    "protocol, health_check_json, process_match_json, log_path, criticality, startup_grace_seconds, enabled, "
    "created_at, updated_at"
)


class DuplicateServerError(DatabaseError):
    """Já existe um servidor com esse nome."""


def _record(row: dict[str, Any]) -> ServerRecord:
    return ServerRecord.model_validate(
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "server_type": row["server_type"],
            "management": row["management"],
            "executable": row["executable"],
            "arguments": json.loads(row["arguments_json"]),
            "working_directory": row["working_directory"],
            "port": row["port"],
            "protocol": row["protocol"],
            "health_check": json.loads(row["health_check_json"]),
            "process_match": json.loads(row["process_match_json"]),
            "log_path": row["log_path"],
            "criticality": row["criticality"],
            "startup_grace_seconds": row["startup_grace_seconds"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        },
        context={"skip_exists": True},
    )


def _params(spec: ServerSpec) -> tuple[Any, ...]:
    return (
        spec.name, spec.description, spec.server_type, spec.management, spec.executable,
        json.dumps(spec.arguments, ensure_ascii=False), spec.working_directory, spec.port, spec.protocol,
        spec.health_check.model_dump_json(), spec.process_match.model_dump_json(), spec.log_path,
        spec.criticality, spec.startup_grace_seconds, int(spec.enabled),
    )


class ServerRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list(self) -> list[ServerRecord]:
        rows = await self._db.fetch_all(f"SELECT {_COLUMNS} FROM servers ORDER BY name")
        return [_record(r) for r in rows]

    async def get(self, server_id: int) -> ServerRecord | None:
        row = await self._db.fetch_one(f"SELECT {_COLUMNS} FROM servers WHERE id = ?", (server_id,))
        return _record(row) if row else None

    async def get_by_name(self, name: str) -> ServerRecord | None:
        row = await self._db.fetch_one(f"SELECT {_COLUMNS} FROM servers WHERE name = ?", (name,))
        return _record(row) if row else None

    async def create(self, spec: ServerSpec) -> ServerRecord:
        now = to_iso(utc_now())
        try:
            server_id = await self._db.insert(
                "INSERT INTO servers (name, description, server_type, management, executable, arguments_json,"
                " working_directory, port, protocol, health_check_json, process_match_json, log_path, criticality,"
                " startup_grace_seconds, enabled, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*_params(spec), now, now),
            )
        except DatabaseError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateServerError(f"Já existe um servidor chamado '{spec.name}'") from exc
            raise
        record = await self.get(server_id)
        assert record is not None
        return record

    async def update(self, server_id: int, spec: ServerSpec) -> ServerRecord | None:
        now = to_iso(utc_now())

        def update(c: sqlite3.Connection) -> int:
            return c.execute(
                "UPDATE servers SET name = ?, description = ?, server_type = ?, management = ?, executable = ?,"
                " arguments_json = ?, working_directory = ?, port = ?, protocol = ?, health_check_json = ?,"
                " process_match_json = ?, log_path = ?, criticality = ?, startup_grace_seconds = ?, enabled = ?,"
                " updated_at = ? WHERE id = ?",
                (*_params(spec), now, server_id),
            ).rowcount

        try:
            changed = await self._db.run(update)
        except DatabaseError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateServerError(f"Já existe um servidor chamado '{spec.name}'") from exc
            raise
        return await self.get(server_id) if changed else None

    async def delete(self, server_id: int) -> bool:
        return bool(await self._db.run(lambda c: c.execute("DELETE FROM servers WHERE id = ?", (server_id,)).rowcount))

    # ------------------------------------------------------------ verificações

    async def add_check(self, server_id: int, check: dict[str, Any]) -> None:
        await self._db.insert(
            "INSERT INTO server_checks (server_id, timestamp, ts_epoch, state, process_alive, pid, port_listening,"
            " health_status, response_time_ms, error_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                server_id, check["timestamp"], check["ts_epoch"], check["state"], int(check["process_alive"]),
                check.get("pid"), None if check.get("port_listening") is None else int(check["port_listening"]),
                check["health_status"], check.get("response_time_ms"), check.get("error"),
            ),
        )

    async def recent_checks(self, server_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return await self._db.fetch_all(
            "SELECT timestamp, ts_epoch, state, process_alive, pid, port_listening, health_status,"
            " response_time_ms, error_message FROM server_checks WHERE server_id = ?"
            " ORDER BY ts_epoch DESC LIMIT ?",
            (server_id, min(max(limit, 1), 1000)),
        )

    async def purge_checks(self, cutoff_epoch: float) -> int:
        return await self._db.run(
            lambda c: c.execute("DELETE FROM server_checks WHERE ts_epoch < ?", (cutoff_epoch,)).rowcount
        )

    # -------------------------------------------------------------- incidentes

    async def open_incident(self, server: ServerRecord, kind: str, severity: str, title: str, entry: dict[str, Any]) -> int:
        now = time.time()
        return await self._db.insert(
            "INSERT INTO incidents (server_id, server_name, kind, severity, title, timeline_json, opened_at, opened_epoch)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (server.id, server.name, kind, severity, title, json.dumps([entry], ensure_ascii=False), to_iso(utc_now()), now),
        )

    async def append_incident(self, incident_id: int, entry: dict[str, Any]) -> None:
        def append(c: sqlite3.Connection) -> None:
            row = c.execute("SELECT timeline_json FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            if row is None:
                return
            timeline = json.loads(row[0])[-49:]  # limita o tamanho da linha do tempo
            timeline.append(entry)
            c.execute("UPDATE incidents SET timeline_json = ? WHERE id = ?", (json.dumps(timeline, ensure_ascii=False), incident_id))

        await self._db.run(append)

    async def close_incident(self, incident_id: int, resolution: str, entry: dict[str, Any]) -> float | None:
        """Fecha o incidente e retorna sua duração em segundos."""
        await self.append_incident(incident_id, entry)
        now = time.time()

        def close(c: sqlite3.Connection) -> float | None:
            row = c.execute("SELECT opened_epoch FROM incidents WHERE id = ? AND closed_epoch IS NULL", (incident_id,)).fetchone()
            if row is None:
                return None
            c.execute(
                "UPDATE incidents SET closed_at = ?, closed_epoch = ?, resolution = ? WHERE id = ?",
                (to_iso(utc_now()), now, resolution, incident_id),
            )
            return now - row[0]

        return await self._db.run(close)

    async def open_incident_for(self, server_id: int) -> dict[str, Any] | None:
        return await self._db.fetch_one(
            "SELECT id, kind, opened_epoch FROM incidents WHERE server_id = ? AND closed_epoch IS NULL"
            " ORDER BY opened_epoch DESC LIMIT 1",
            (server_id,),
        )

    async def incidents(self, server_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        where, params = ("WHERE server_id = ?", (server_id,)) if server_id is not None else ("", ())
        rows = await self._db.fetch_all(
            f"SELECT * FROM incidents {where} ORDER BY opened_epoch DESC LIMIT ?", (*params, min(max(limit, 1), 500))
        )
        for row in rows:
            row["timeline"] = json.loads(row.pop("timeline_json"))
            row["duration_seconds"] = (
                round((row["closed_epoch"] or time.time()) - row["opened_epoch"], 1)
            )
        return rows
