import asyncio

import pytest

from sentinel.core.event_bus import Event, Severity
from sentinel.core.exceptions import DatabaseError, MigrationError
from sentinel.database.database import Database
from sentinel.database.migrations import apply_migrations, discover_migrations, split_sql
from sentinel.database.repositories import AgentRunRepository, AuditRepository, EventRepository


def with_db(tmp_path, scenario):
    async def runner():
        db = Database(tmp_path / "t.db")
        await db.open()
        try:
            return await scenario(db)
        finally:
            await db.close()

    return asyncio.run(runner())


def test_split_sql_keeps_trigger_bodies_intact():
    script = """
    -- comentário
    CREATE TABLE t (x);

    CREATE TRIGGER tr BEFORE DELETE ON t
    BEGIN
        SELECT RAISE(ABORT, 'não; mesmo');
    END;
    """
    statements = split_sql(script)
    assert len(statements) == 2
    assert statements[1].startswith("CREATE TRIGGER") and statements[1].endswith("END;")


def test_split_sql_rejects_incomplete_statement():
    with pytest.raises(MigrationError):
        split_sql("CREATE TABLE t (x)")


def test_discovered_migrations_are_ordered():
    versions = [m.version for m in discover_migrations()]
    assert versions == sorted(versions) and versions[0] == 1


def test_migrations_apply_once_and_enable_wal(tmp_path):
    async def scenario(db):
        first = await apply_migrations(db)
        second = await apply_migrations(db)
        mode = await db.fetch_one("PRAGMA journal_mode")
        tables = {r["name"] for r in await db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
        return first, second, mode, tables

    first, second, mode, tables = with_db(tmp_path, scenario)
    assert first == [1] and second == []
    assert mode["journal_mode"] == "wal"
    assert {"events", "audit_logs", "agent_runs", "schema_migrations"} <= tables


def test_failed_migration_rolls_back(tmp_path):
    migrations = tmp_path / "migs"
    migrations.mkdir()
    (migrations / "0001_ok.sql").write_text("CREATE TABLE a (x);")
    (migrations / "0002_bad.sql").write_text("CREATE TABLE b (x);\nINSERT INTO missing VALUES (1);")

    async def scenario(db):
        with pytest.raises(MigrationError, match="0002_bad"):
            await apply_migrations(db, migrations)
        return {r["name"] for r in await db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}

    tables = with_db(tmp_path, scenario)
    assert "a" in tables and "b" not in tables


def test_database_from_newer_version_is_refused(tmp_path):
    async def scenario(db):
        await apply_migrations(db)
        await db.execute("INSERT INTO schema_migrations VALUES (999, 'future', 'x')")
        with pytest.raises(MigrationError, match="mais nova"):
            await apply_migrations(db)

    with_db(tmp_path, scenario)


def test_audit_log_is_append_only(tmp_path):
    async def scenario(db):
        await apply_migrations(db)
        audit = AuditRepository(db)
        audit_id = await audit.record(actor="user", operation="server.restart", result="success", target="game")
        with pytest.raises(DatabaseError, match="somente-inserção"):
            await db.execute("UPDATE audit_logs SET result = 'forjado' WHERE id = ?", (audit_id,))
        with pytest.raises(DatabaseError, match="somente-inserção"):
            await db.execute("DELETE FROM audit_logs")
        with pytest.raises(ValueError):
            await audit.record(actor="", operation="x", result="y")
        return await audit.recent()

    rows = with_db(tmp_path, scenario)
    assert len(rows) == 1 and rows[0]["result"] == "success"


def test_event_repository_round_trip(tmp_path):
    async def scenario(db):
        await apply_migrations(db)
        repo = EventRepository(db)
        await repo.add(Event("a.b", "test", "Primeiro", Severity.WARNING, "desc", {"k": 1}))
        await repo.add(Event("a.c", "test", "Segundo"))
        with pytest.raises(ValueError):
            await repo.recent(0)
        return await repo.recent(10)

    rows = with_db(tmp_path, scenario)
    assert [r["title"] for r in rows] == ["Segundo", "Primeiro"]
    assert rows[1]["metadata"] == {"k": 1} and rows[1]["severity"] == "warning"


def test_invalid_severity_is_rejected_by_schema(tmp_path):
    async def scenario(db):
        await apply_migrations(db)
        with pytest.raises(DatabaseError):
            await db.execute(
                "INSERT INTO events (event_type, severity, source, title, timestamp) VALUES ('x','loud','s','t','now')"
            )

    with_db(tmp_path, scenario)


def test_agent_runs_detect_abandoned_runs(tmp_path):
    async def scenario(db):
        await apply_migrations(db)
        runs = AgentRunRepository(db)
        crashed = await runs.start(111, "0.1.0")
        await runs.heartbeat(crashed)
        abandoned = await runs.close_abandoned()
        assert await runs.close_abandoned() == []  # já fechadas não voltam
        current = await runs.start(222, "0.1.0")
        await runs.finish(current, "clean")
        with pytest.raises(DatabaseError):
            await runs.heartbeat(current)
        crashed_row = await db.fetch_one("SELECT * FROM agent_runs WHERE id = ?", (crashed,))
        return abandoned, crashed_row, await runs.latest()

    abandoned, crashed_row, latest = with_db(tmp_path, scenario)
    assert [r["pid"] for r in abandoned] == [111]
    assert crashed_row["exit_status"] == "unclean"
    assert crashed_row["stopped_at"] == crashed_row["last_heartbeat"]
    assert latest["pid"] == 222 and latest["exit_status"] == "clean"


def test_transaction_rolls_back_on_error(tmp_path):
    async def scenario(db):
        await db.execute("CREATE TABLE t (x INTEGER)")

        def work(conn):
            conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("abortar")

        with pytest.raises(RuntimeError):
            await db.run(work)
        return await db.fetch_all("SELECT * FROM t")

    assert with_db(tmp_path, scenario) == []


def test_closed_database_raises(tmp_path):
    async def scenario():
        db = Database(tmp_path / "t.db")
        with pytest.raises(DatabaseError, match="não está aberto"):
            await db.fetch_all("SELECT 1")
        await db.open()
        assert await db.integrity_check() == ["ok"]
        await db.close()
        await db.close()  # idempotente

    asyncio.run(scenario())
