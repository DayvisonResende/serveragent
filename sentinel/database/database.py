"""Acesso assíncrono ao SQLite sem bloquear o loop de eventos (PRD 16.3).

Todo acesso passa por uma única thread dedicada. Isso serializa as gravações
(SQLite aceita um escritor por vez), evita ``database is locked`` dentro do
próprio processo e mantém o loop principal livre para o monitoramento.
O modo WAL permite leitores externos (ex.: ``sentinel status``) simultâneos.

Repositórios usam apenas ``execute``/``fetch_*``/``run``; nenhum outro código
toca a conexão — isso isola o SQLite para uma futura troca por PostgreSQL.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar

from sentinel.core.exceptions import DatabaseError

log = logging.getLogger(__name__)

T = TypeVar("T")
Params = Sequence[Any]


class Database:
    def __init__(self, path: Path, busy_timeout_ms: int = 5000) -> None:
        self.path = path
        self._busy_timeout_ms = busy_timeout_ms
        self._executor: ThreadPoolExecutor | None = None
        self._conn: sqlite3.Connection | None = None

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    async def open(self) -> None:
        if self._conn is not None:
            return
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sentinel-db")
        try:
            self._conn = await self._submit(self._connect)
        except BaseException:
            self._executor.shutdown(wait=False)
            self._executor = None
            raise

    async def close(self) -> None:
        if self._conn is None:
            return
        conn, self._conn = self._conn, None
        try:
            await self._submit(conn.close)
        finally:
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None

    async def run(self, fn: Callable[[sqlite3.Connection], T], *, transaction: bool = True) -> T:
        """Executa ``fn(conn)`` na thread do banco, por padrão dentro de uma transação."""
        conn = self._require_conn()

        def work() -> T:
            try:
                if not transaction:
                    return fn(conn)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    result = fn(conn)
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
                return result
            except sqlite3.Error as exc:
                raise DatabaseError(f"{type(exc).__name__}: {exc}") from exc

        return await self._submit(work)

    async def execute(self, sql: str, params: Params = ()) -> int | None:
        """Executa uma instrução (atômica por si só) e retorna ``lastrowid``."""
        return await self.run(lambda c: c.execute(sql, params).lastrowid, transaction=False)

    async def insert(self, sql: str, params: Params = ()) -> int:
        """Executa um INSERT e retorna o id da nova linha."""
        row_id = await self.execute(sql, params)
        if row_id is None:
            raise DatabaseError("INSERT não retornou id")
        return row_id

    async def fetch_all(self, sql: str, params: Params = ()) -> list[dict[str, Any]]:
        return await self.run(
            lambda c: [dict(row) for row in c.execute(sql, params).fetchall()], transaction=False
        )

    async def fetch_one(self, sql: str, params: Params = ()) -> dict[str, Any] | None:
        def query(c: sqlite3.Connection) -> dict[str, Any] | None:
            row = c.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

        return await self.run(query, transaction=False)

    async def integrity_check(self) -> list[str]:
        """Retorna ``["ok"]`` quando o arquivo está íntegro."""
        return await self.run(
            lambda c: [row[0] for row in c.execute("PRAGMA quick_check").fetchall()], transaction=False
        )

    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout_ms)}")
            mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                log.warning("SQLite não aceitou o modo WAL", extra={"journal_mode": mode})
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA synchronous = NORMAL")
            return conn
        except (sqlite3.Error, OSError) as exc:
            raise DatabaseError(f"Não foi possível abrir o banco {self.path}: {exc}") from exc

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise DatabaseError("Banco de dados não está aberto")
        return self._conn

    async def _submit(self, fn: Callable[..., T], *args: Any) -> T:
        if self._executor is None:
            raise DatabaseError("Banco de dados não está aberto")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args))
