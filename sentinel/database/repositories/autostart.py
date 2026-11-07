"""Linha de base dos itens de inicialização automática."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from sentinel.core.clock import to_iso, utc_now
from sentinel.database.database import Database


class AutostartRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def all(self) -> dict[str, dict[str, Any]]:
        rows = await self._db.fetch_all("SELECT * FROM autostart_entries ORDER BY location, name")
        for row in rows:
            row["reasons"] = json.loads(row["reasons"])
            row["suspicious"] = bool(row["suspicious"])
        return {r["key"]: r for r in rows}

    async def apply(self, upserts: list[dict[str, Any]], removed: list[str], seen: list[str]) -> None:
        now = to_iso(utc_now())

        def apply(c: sqlite3.Connection) -> None:
            for e in upserts:
                c.execute(
                    "INSERT INTO autostart_entries (key, location, name, value, suspicious, reasons, first_seen, last_seen)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                    " suspicious = excluded.suspicious, reasons = excluded.reasons, last_seen = excluded.last_seen",
                    (e["key"], e["location"], e["name"], e["value"], int(bool(e["reasons"])),
                     json.dumps(e["reasons"], ensure_ascii=False), now, now),
                )
            for key in removed:
                c.execute("DELETE FROM autostart_entries WHERE key = ?", (key,))
            c.executemany("UPDATE autostart_entries SET last_seen = ? WHERE key = ?", [(now, k) for k in seen])

        await self._db.run(apply)
