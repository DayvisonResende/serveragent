"""Códigos de login de uso único e sessões do dashboard.

Valores são aleatórios de 256 bits (``secrets``); o banco guarda apenas o
SHA-256 deles. Hash lento (bcrypt/scrypt) não é necessário porque não há
senha humana: força bruta sobre 256 bits é inviável.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time

from sentinel.core.clock import to_iso, utc_now
from sentinel.database.database import Database


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_login_code(self, ttl_seconds: float) -> str:
        code = secrets.token_urlsafe(32)
        await self._db.insert(
            "INSERT INTO login_codes (code_hash, created_at, expires_at_epoch) VALUES (?, ?, ?)",
            (hash_secret(code), to_iso(utc_now()), time.time() + ttl_seconds),
        )
        return code

    async def consume_login_code(self, code: str) -> bool:
        """Valida e invalida o código numa única transação (não pode ser reutilizado)."""
        code_hash = hash_secret(code)

        def consume(c: sqlite3.Connection) -> bool:
            return (
                c.execute(
                    "UPDATE login_codes SET used_at = ?"
                    " WHERE code_hash = ? AND used_at IS NULL AND expires_at_epoch > ?",
                    (to_iso(utc_now()), code_hash, time.time()),
                ).rowcount
                == 1
            )

        return await self._db.run(consume)

    async def create_session(self, ttl_seconds: float) -> tuple[str, float]:
        token = secrets.token_urlsafe(32)
        expires = time.time() + ttl_seconds
        await self._db.insert(
            "INSERT INTO sessions (token_hash, created_at, expires_at_epoch) VALUES (?, ?, ?)",
            (hash_secret(token), to_iso(utc_now()), expires),
        )
        return token, expires

    async def session_expiry(self, token: str) -> float | None:
        """Retorna o vencimento da sessão, ou None se inválida/expirada."""
        row = await self._db.fetch_one(
            "SELECT expires_at_epoch FROM sessions WHERE token_hash = ? AND expires_at_epoch > ?",
            (hash_secret(token), time.time()),
        )
        return float(row["expires_at_epoch"]) if row else None

    async def delete_session(self, token: str) -> None:
        await self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_secret(token),))

    async def purge_expired(self) -> int:
        now = time.time()

        def purge(c: sqlite3.Connection) -> int:
            removed = c.execute("DELETE FROM sessions WHERE expires_at_epoch <= ?", (now,)).rowcount
            removed += c.execute(
                "DELETE FROM login_codes WHERE expires_at_epoch <= ? OR used_at IS NOT NULL", (now,)
            ).rowcount
            return removed

        return await self._db.run(purge)
