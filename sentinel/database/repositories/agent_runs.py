"""Registro de execuções do agente e detecção de encerramentos inesperados."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from sentinel.core.clock import to_iso, utc_now
from sentinel.core.exceptions import DatabaseError
from sentinel.database.database import Database

ExitStatus = Literal["clean", "failed", "interrupted", "system_shutdown"]


class AgentRunRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def start(self, pid: int, version: str) -> int:
        now = to_iso(utc_now())
        return await self._db.insert(
            "INSERT INTO agent_runs (pid, version, started_at, last_heartbeat) VALUES (?, ?, ?, ?)",
            (pid, version, now, now),
        )

    async def heartbeat(self, run_id: int) -> None:
        def update(c: sqlite3.Connection) -> int:
            return c.execute(
                "UPDATE agent_runs SET last_heartbeat = ? WHERE id = ? AND stopped_at IS NULL",
                (to_iso(utc_now()), run_id),
            ).rowcount

        if await self._db.run(update, transaction=False) != 1:
            raise DatabaseError(f"Execução {run_id} não encontrada ou já finalizada")

    async def finish(self, run_id: int, status: ExitStatus) -> None:
        now = to_iso(utc_now())

        def update(c: sqlite3.Connection) -> int:
            return c.execute(
                "UPDATE agent_runs SET stopped_at = ?, last_heartbeat = ?, exit_status = ?"
                " WHERE id = ? AND stopped_at IS NULL",
                (now, now, status, run_id),
            ).rowcount

        if await self._db.run(update, transaction=False) != 1:
            raise DatabaseError(f"Execução {run_id} não encontrada ou já finalizada")

    async def close_abandoned(self) -> list[dict[str, Any]]:
        """Marca como ``unclean`` execuções anteriores que nunca registraram término.

        O horário de parada considerado é o último sinal de vida — o melhor dado
        real disponível, sem inventar um horário exato.
        """

        def close(c: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = [dict(r) for r in c.execute("SELECT * FROM agent_runs WHERE stopped_at IS NULL ORDER BY id")]
            c.execute(
                "UPDATE agent_runs SET stopped_at = last_heartbeat, exit_status = 'unclean'"
                " WHERE stopped_at IS NULL"
            )
            return rows

        return await self._db.run(close)

    async def latest(self) -> dict[str, Any] | None:
        return await self._db.fetch_one("SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1")

    async def previous(self) -> dict[str, Any] | None:
        """Execução anterior à mais recente (mostra como o agente terminou da última vez)."""
        return await self._db.fetch_one("SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1 OFFSET 1")
