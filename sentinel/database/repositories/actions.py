"""Ações solicitadas e suas aprovações (PRD 11.3, 16.1)."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from sentinel.core.clock import to_iso, utc_now
from sentinel.database.database import Database

_VIEW = (
    "SELECT a.id, a.action_type, a.target, a.target_id, a.params_json, a.fingerprint, a.risk_level, a.requested_by,"
    " a.reason, a.status, a.approval_id, a.created_at, a.created_epoch, a.started_at, a.completed_at, a.result_json,"
    " a.error_message, p.expires_at, p.expires_epoch, p.decided_at, p.decided_by, p.status AS approval_status,"
    " p.impact, p.risks, p.requires_confirmation, p.note"
    " FROM actions a LEFT JOIN approvals p ON p.id = a.approval_id"
)


def _row(row: dict[str, Any]) -> dict[str, Any]:
    row["params"] = json.loads(row.pop("params_json") or "{}")
    row["result"] = json.loads(row.pop("result_json")) if row.get("result_json") else None
    row["requires_confirmation"] = bool(row.get("requires_confirmation"))
    return row


class ActionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, action: dict[str, Any], approval: dict[str, Any]) -> int:
        now = time.time()

        def create(c: sqlite3.Connection) -> int:
            cur = c.execute(
                "INSERT INTO actions (action_type, target, target_id, params_json, fingerprint, risk_level, requested_by,"
                " reason, status, created_at, created_epoch) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (action["action_type"], action["target"], action["target_id"], json.dumps(action["params"], ensure_ascii=False),
                 action["fingerprint"], action["risk_level"], action["requested_by"], action["reason"], to_iso(utc_now()), now),
            )
            action_id = int(cur.lastrowid)
            expires = now + approval["ttl_seconds"]
            cur = c.execute(
                "INSERT INTO approvals (action_id, requested_at, expires_at, expires_epoch, status, impact, risks,"
                " requires_confirmation) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
                (action_id, to_iso(utc_now()), to_iso(datetime.fromtimestamp(expires, timezone.utc)), expires,
                 approval["impact"], approval["risks"], int(approval["requires_confirmation"])),
            )
            c.execute("UPDATE actions SET approval_id = ? WHERE id = ?", (cur.lastrowid, action_id))
            return action_id

        return await self._db.run(create)

    async def get(self, action_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(f"{_VIEW} WHERE a.id = ?", (action_id,))
        return _row(row) if row else None

    async def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        where, params = ("WHERE a.status = ?", (status,)) if status else ("", ())
        rows = await self._db.fetch_all(f"{_VIEW} {where} ORDER BY a.created_epoch DESC LIMIT ?", (*params, min(max(limit, 1), 500)))
        return [_row(r) for r in rows]

    async def pending_for(self, action_type: str, target_id: int | None) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            f"{_VIEW} WHERE a.action_type = ? AND a.target_id IS ? AND a.status = 'pending' ORDER BY a.id DESC LIMIT 1",
            (action_type, target_id),
        )
        return _row(row) if row else None

    async def decide(self, action_id: int, decision: str, decided_by: str, note: str | None = None) -> bool:
        """Aprova/rejeita de forma atômica: só vale se ainda pendente e dentro do prazo (uso único)."""
        assert decision in ("approved", "rejected", "cancelled")
        now = time.time()

        def decide(c: sqlite3.Connection) -> bool:
            updated = c.execute(
                "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ?, note = ?"
                " WHERE action_id = ? AND status = 'pending' AND (expires_epoch > ? OR ? = 'cancelled')",
                (decision, to_iso(utc_now()), decided_by, note, action_id, now, decision),
            ).rowcount
            if updated != 1:
                return False
            c.execute("UPDATE actions SET status = ? WHERE id = ? AND status = 'pending'", (decision, action_id))
            return True

        return await self._db.run(decide)

    async def set_status(self, action_id: int, status: str, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        now = to_iso(utc_now())
        if status == "executing":
            await self._db.execute("UPDATE actions SET status = ?, started_at = ? WHERE id = ?", (status, now, action_id))
            return
        await self._db.execute(
            "UPDATE actions SET status = ?, completed_at = ?, result_json = ?, error_message = ? WHERE id = ?",
            (status, now, json.dumps(result, ensure_ascii=False, default=str) if result is not None else None, error, action_id),
        )

    async def expire_due(self) -> list[int]:
        now = time.time()

        def expire(c: sqlite3.Connection) -> list[int]:
            ids = [r[0] for r in c.execute(
                "SELECT action_id FROM approvals WHERE status = 'pending' AND expires_epoch <= ?", (now,)
            )]
            for action_id in ids:
                c.execute("UPDATE approvals SET status = 'expired', decided_at = ? WHERE action_id = ?", (to_iso(utc_now()), action_id))
                c.execute("UPDATE actions SET status = 'expired' WHERE id = ? AND status = 'pending'", (action_id,))
            return ids

        return await self._db.run(expire)

    async def count_pending(self) -> int:
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM actions WHERE status = 'pending'")
        return int(row["n"]) if row else 0
