"""Auditoria (PRD 11.6). Somente inserção e leitura — não existe método de alteração.

O banco também bloqueia UPDATE/DELETE por trigger, então nem código futuro do
Sentinel (dashboard, IA) consegue reescrever o histórico por esta conexão.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from sentinel.core.clock import to_iso, utc_now
from sentinel.database.database import Database

MAX_PAGE = 1000


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        actor: str,
        operation: str,
        result: str,
        target: str | None = None,
        reason: str | None = None,
        approval_id: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> int:
        for field_name, value in (("actor", actor), ("operation", operation), ("result", result)):
            if not value or not value.strip():
                raise ValueError(f"'{field_name}' é obrigatório na auditoria")
        return await self._db.insert(
            "INSERT INTO audit_logs (actor, operation, target, reason, approval_id, result, details_json, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                actor,
                operation,
                target,
                reason,
                approval_id,
                result,
                json.dumps(dict(details or {}), ensure_ascii=False, default=str),
                to_iso(utc_now()),
            ),
        )

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= MAX_PAGE:
            raise ValueError(f"limit deve estar entre 1 e {MAX_PAGE}")
        rows = await self._db.fetch_all(
            "SELECT * FROM audit_logs ORDER BY timestamp DESC, id DESC LIMIT ?", (limit,)
        )
        for row in rows:
            row["details"] = json.loads(row.pop("details_json"))
        return rows
