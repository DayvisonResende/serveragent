"""Repositórios da Fase 2: métricas, crescimento de disco, retenção e autenticação."""

import asyncio
import time

import pytest

from sentinel.database.database import Database
from sentinel.database.migrations import apply_migrations
from sentinel.database.repositories import AuthRepository, MetricsRepository
from sentinel.database.repositories.metrics import DiskUsageRow, ProcessSnapshotRow, SystemMetricRow


def with_db(tmp_path, scenario):
    async def runner():
        db = Database(tmp_path / "t.db")
        await db.open()
        try:
            await apply_migrations(db)
            return await scenario(db)
        finally:
            await db.close()

    return asyncio.run(runner())


def metric(ts, cpu, cpu_max=None, n=12):
    return SystemMetricRow(ts, n, cpu, cpu_max if cpu_max is not None else cpu, 100, 50, 66.0, None, None, None, 10.0, 20.0)


def test_history_buckets_weighted_average_and_keeps_peaks(tmp_path):
    now = time.time()
    bucket_start = (now // 50) * 50 - 50  # balde de 50 s inteiramente dentro do período

    async def scenario(db):
        repo = MetricsRepository(db)
        await repo.add_system_metric(metric(bucket_start + 5, 10, n=1))
        await repo.add_system_metric(metric(bucket_start + 15, 40, cpu_max=95, n=3))
        await repo.add_system_metric(metric(now - 7200, 99))  # fora do período
        return await repo.system_history(now - 100, max_points=2, until_epoch=now)

    rows = with_db(tmp_path, scenario)
    assert len(rows) == 1
    assert rows[0]["cpu_percent"] == pytest.approx((10 * 1 + 40 * 3) / 4)
    assert rows[0]["cpu_percent_max"] == 95 and rows[0]["samples"] == 4


def test_disk_growth_needs_an_hour_of_history(tmp_path):
    now = time.time()

    async def scenario(db):
        repo = MetricsRepository(db)
        await repo.add_disk_usage(now - 2 * 86400, [DiskUsageRow("C:\\", "C:", 100, 40, 60)])
        await repo.add_disk_usage(now - 86400, [DiskUsageRow("C:\\", "C:", 100, 50, 50)])
        await repo.add_disk_usage(now, [DiskUsageRow("C:\\", "C:", 100, 60, 40), DiskUsageRow("D:\\", "D:", 10, 1, 9)])
        return await repo.disk_growth(now - 7 * 86400)

    growth = with_db(tmp_path, scenario)
    assert growth["C:\\"]["bytes_per_day"] == pytest.approx(10, rel=1e-3)
    assert growth["D:\\"]["bytes_per_day"] is None  # um único ponto: sem tendência inventada


def test_retention_purges_only_old_rows_and_known_tables(tmp_path):
    now = time.time()

    async def scenario(db):
        repo = MetricsRepository(db)
        await repo.add_system_metric(metric(now - 40 * 86400, 1))
        await repo.add_system_metric(metric(now, 2))
        await repo.add_process_snapshots(now - 10 * 86400, [ProcessSnapshotRow(1, "x", None, 1.0, 10, "running")])
        removed = await repo.purge_older_than("system_metrics", now - 30 * 86400)
        with pytest.raises(ValueError):
            await repo.purge_older_than("audit_logs", now)
        remaining = await db.fetch_all("SELECT cpu_percent FROM system_metrics")
        return removed, remaining

    removed, remaining = with_db(tmp_path, scenario)
    assert removed == 1 and remaining == [{"cpu_percent": 2.0}]


def test_login_code_is_single_use_and_expires(tmp_path):
    async def scenario(db):
        repo = AuthRepository(db)
        code = await repo.create_login_code(60)
        stored = await db.fetch_one("SELECT code_hash FROM login_codes")
        assert code not in stored["code_hash"]  # só o hash é armazenado
        assert await repo.consume_login_code(code) is True
        assert await repo.consume_login_code(code) is False
        expired = await repo.create_login_code(-1)
        assert await repo.consume_login_code(expired) is False
        assert await repo.consume_login_code("inventado") is False

    with_db(tmp_path, scenario)


def test_sessions_validate_expire_and_logout(tmp_path):
    async def scenario(db):
        repo = AuthRepository(db)
        token, expires = await repo.create_session(3600)
        assert expires > time.time()
        assert await repo.session_expiry(token) == pytest.approx(expires)
        old, _ = await repo.create_session(-1)
        assert await repo.session_expiry(old) is None
        await repo.delete_session(token)
        assert await repo.session_expiry(token) is None
        assert await repo.purge_expired() >= 1

    with_db(tmp_path, scenario)


def test_agent_runs_accept_system_shutdown_after_migration(tmp_path):
    async def scenario(db):
        from sentinel.database.repositories import AgentRunRepository

        runs = AgentRunRepository(db)
        run = await runs.start(1, "0.1.0")
        await runs.finish(run, "system_shutdown")
        return await runs.latest()

    assert with_db(tmp_path, scenario)["exit_status"] == "system_shutdown"
