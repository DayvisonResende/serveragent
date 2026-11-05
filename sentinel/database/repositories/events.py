from __future__ import annotations

import json
from typing import Any

from sentinel.core.clock import to_iso
from sentinel.core.event_bus import Event
from sentinel.database.database import Database

MAX_PAGE = 1000


class EventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, event: Event) -> int:
        return await self._db.insert(
            "INSERT INTO events (event_type, severity, source, title, description, metadata_json, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.event_type,
                event.severity.value,
                event.source,
                event.title,
                event.description,
                json.dumps(dict(event.metadata), ensure_ascii=False, default=str),
                to_iso(event.timestamp),
            ),
        )

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= MAX_PAGE:
            raise ValueError(f"limit deve estar entre 1 e {MAX_PAGE}")
        rows = await self._db.fetch_all(
            "SELECT id, event_type, severity, source, title, description, metadata_json, timestamp"
            " FROM events ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
        )
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json"))
        return rows
