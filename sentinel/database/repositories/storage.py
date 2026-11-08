"""Análises de armazenamento, planos/relatórios de limpeza e quarentena (PRD 8, 16.1)."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any, Iterable

from sentinel.core.clock import to_iso, utc_now

if TYPE_CHECKING:
    from sentinel.database.database import Database
    from sentinel.modules.cleaner.analyzer import Finding

KEEP_ANALYSES = 10


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class StorageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------ análises

    async def start_analysis(self, trigger: str) -> int:
        return await self._db.insert(
            "INSERT INTO storage_analyses (started_at, status, trigger) VALUES (?, 'running', ?)", (to_iso(utc_now()), trigger))

    async def finish_analysis(self, analysis_id: int, status: str, summary: dict[str, Any] | None = None,
                              findings: Iterable[Finding] = (), error: str | None = None) -> None:
        rows = [(analysis_id, f.category, f.path, f.size, f.mtime, f.group_key, int(f.keep), int(f.cleanable), f.note) for f in findings]

        def write(conn: sqlite3.Connection) -> None:
            conn.executemany(
                "INSERT INTO storage_findings (analysis_id, category, path, size_bytes, modified_at, group_key, keep, cleanable, note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.execute("UPDATE storage_analyses SET finished_at = ?, status = ?, summary_json = ?, error = ? WHERE id = ?",
                         (to_iso(utc_now()), status, _json(summary or {}), error, analysis_id))
            # Só as análises recentes ficam (os achados de cada uma podem ser milhares de linhas).
            conn.execute("DELETE FROM storage_findings WHERE analysis_id NOT IN"
                         " (SELECT id FROM storage_analyses ORDER BY id DESC LIMIT ?)", (KEEP_ANALYSES,))
            conn.execute("DELETE FROM storage_analyses WHERE id NOT IN (SELECT id FROM storage_analyses ORDER BY id DESC LIMIT ?)",
                         (KEEP_ANALYSES,))

        await self._db.run(write)

    async def fail_running(self, note: str) -> None:
        """Análises 'running' de uma execução anterior do agente nunca vão terminar."""
        await self._db.execute("UPDATE storage_analyses SET status = 'failed', error = ?, finished_at = ? WHERE status = 'running'",
                               (note, to_iso(utc_now())))

    async def latest_analysis(self, status: str | None = "completed") -> dict[str, Any] | None:
        where = "WHERE status = ?" if status else ""
        row = await self._db.fetch_one(f"SELECT * FROM storage_analyses {where} ORDER BY id DESC LIMIT 1", (status,) if status else ())
        return _analysis(row)

    async def previous_completed(self, before_id: int) -> dict[str, Any] | None:
        return _analysis(await self._db.fetch_one(
            "SELECT * FROM storage_analyses WHERE status = 'completed' AND id < ? ORDER BY id DESC LIMIT 1", (before_id,)))

    async def set_summary(self, analysis_id: int, summary: dict[str, Any]) -> None:
        await self._db.execute("UPDATE storage_analyses SET summary_json = ? WHERE id = ?", (_json(summary), analysis_id))

    async def findings(self, analysis_id: int, category: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        where, params = "analysis_id = ?", [analysis_id]
        if category:
            where += " AND category = ?"
            params.append(category)
        order = "group_key, keep DESC, path" if category == "duplicate" else "size_bytes DESC"
        rows = await self._db.fetch_all(f"SELECT * FROM storage_findings WHERE {where} ORDER BY {order} LIMIT ?", (*params, limit))
        for r in rows:
            r["keep"], r["cleanable"] = bool(r["keep"]), bool(r["cleanable"])
        return rows

    async def findings_by_id(self, analysis_id: int, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return await self._db.fetch_all(f"SELECT * FROM storage_findings WHERE analysis_id = ? AND id IN ({marks})", (analysis_id, *ids))

    # ------------------------------------------------------------ planos e relatórios

    async def create_plan(self, analysis_id: int | None, requested_by: str, items: list[dict[str, Any]], reason: str) -> int:
        return await self._db.insert(
            "INSERT INTO cleanup_reports (created_at, analysis_id, requested_by, files_found, bytes_recoverable, status, details_json)"
            " VALUES (?, ?, ?, ?, ?, 'proposed', ?)",
            (to_iso(utc_now()), analysis_id, requested_by, len(items), sum(i["size"] for i in items),
             _json({"items": items, "reason": reason})))

    async def get_report(self, report_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM cleanup_reports WHERE id = ?", (report_id,))
        if row:
            row["details"] = json.loads(row.pop("details_json") or "{}")
        return row

    async def finish_report(self, report_id: int, status: str, moved: int, deleted: int, details: dict[str, Any]) -> None:
        await self._db.execute(
            "UPDATE cleanup_reports SET status = ?, files_moved = ?, files_deleted = ?, finished_at = ?, details_json = ? WHERE id = ?",
            (status, moved, deleted, to_iso(utc_now()), _json(details), report_id))

    async def add_deleted(self, report_id: int, count: int) -> None:
        await self._db.execute("UPDATE cleanup_reports SET files_deleted = files_deleted + ? WHERE id = ?", (count, report_id))

    async def discard_plan(self, report_id: int) -> bool:
        return await self._changed(
            "UPDATE cleanup_reports SET status = 'discarded', finished_at = ? WHERE id = ? AND status = 'proposed'",
            (to_iso(utc_now()), report_id))

    async def claim_plan(self, report_id: int) -> bool:
        """Marca o plano como em execução uma única vez (UPDATE condicional atômico)."""
        return await self._changed("UPDATE cleanup_reports SET status = 'partial' WHERE id = ? AND status = 'proposed'", (report_id,))

    async def _changed(self, sql: str, params: tuple[Any, ...]) -> bool:
        return bool(await self._db.run(lambda c: c.execute(sql, params).rowcount))

    async def reports(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT id, created_at, analysis_id, requested_by, files_found, bytes_recoverable, files_moved, files_deleted, status,"
            " finished_at FROM cleanup_reports ORDER BY id DESC LIMIT ?", (limit,))
        return rows

    # ------------------------------------------------------------ quarentena

    async def add_quarantined(self, report_id: int, item: dict[str, Any]) -> int:
        return await self._db.insert(
            "INSERT INTO quarantine_items (report_id, original_path, stored_path, size_bytes, sha256, modified_at, category, reason,"
            " quarantined_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'quarantined')",
            (report_id, item["original_path"], item["stored_path"], item["size"], item["sha256"], item["mtime"],
             item["category"], item["reason"], to_iso(utc_now())))

    async def quarantine_item(self, item_id: int) -> dict[str, Any] | None:
        return await self._db.fetch_one("SELECT * FROM quarantine_items WHERE id = ?", (item_id,))

    async def quarantine(self, status: str | None = "quarantined", report_id: int | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if report_id is not None:
            clauses.append("report_id = ?")
            params.append(report_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return await self._db.fetch_all(f"SELECT * FROM quarantine_items {where} ORDER BY id DESC LIMIT ?", (*params, limit))

    async def quarantine_usage(self) -> dict[str, int]:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS items, COALESCE(SUM(size_bytes), 0) AS bytes FROM quarantine_items WHERE status = 'quarantined'")
        return {"items": int(row["items"]), "bytes": int(row["bytes"])} if row else {"items": 0, "bytes": 0}

    async def expired_quarantine(self, older_than_iso: str) -> list[dict[str, Any]]:
        return await self._db.fetch_all(
            "SELECT * FROM quarantine_items WHERE status = 'quarantined' AND quarantined_at < ? ORDER BY id", (older_than_iso,))

    async def resolve_quarantined(self, item_id: int, status: str, actor: str) -> bool:
        return await self._changed(
            "UPDATE quarantine_items SET status = ?, resolved_at = ?, resolved_by = ? WHERE id = ? AND status = 'quarantined'",
            (status, to_iso(utc_now()), actor, item_id))


def _analysis(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row:
        row["summary"] = json.loads(row.pop("summary_json") or "{}")
    return row
