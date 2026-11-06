"""Configurações editáveis pelo dashboard e segredos protegidos."""

from __future__ import annotations

import json
from typing import Any

from sentinel.core.clock import to_iso, utc_now
from sentinel.database.database import Database
from sentinel.oslayer import secrets


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str, default: Any = None) -> Any:
        row = await self._db.fetch_one("SELECT value_json FROM settings_kv WHERE key = ?", (key,))
        return json.loads(row["value_json"]) if row else default

    async def set(self, key: str, value: Any) -> None:
        await self._db.execute(
            "INSERT INTO settings_kv (key, value_json, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), to_iso(utc_now())),
        )


class SecretRepository:
    """Segredos cifrados em repouso (DPAPI no Windows). O valor nunca sai pela API."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def set(self, name: str, value: str) -> str:
        protection, data = secrets.protect(value.encode("utf-8"))
        await self._db.execute(
            "INSERT INTO secrets (name, protection, value, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET protection = excluded.protection, value = excluded.value,"
            " updated_at = excluded.updated_at",
            (name, protection, data, to_iso(utc_now())),
        )
        return protection

    async def get(self, name: str) -> str | None:
        row = await self._db.fetch_one("SELECT protection, value FROM secrets WHERE name = ?", (name,))
        if row is None:
            return None
        return secrets.unprotect(row["protection"], bytes(row["value"])).decode("utf-8")

    async def info(self, name: str) -> dict[str, Any] | None:
        return await self._db.fetch_one("SELECT protection, updated_at FROM secrets WHERE name = ?", (name,))

    async def delete(self, name: str) -> None:
        await self._db.execute("DELETE FROM secrets WHERE name = ?", (name,))
