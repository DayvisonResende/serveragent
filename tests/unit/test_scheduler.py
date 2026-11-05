import asyncio

import pytest

from sentinel.agent.scheduler import Scheduler
from sentinel.core.exceptions import SchedulerError


def test_job_runs_periodically_and_stops():
    async def scenario():
        sched = Scheduler()
        calls = []

        async def tick():
            calls.append(1)

        sched.add_job("tick", tick, 0.02, run_immediately=True)
        sched.start()
        await asyncio.sleep(0.11)
        await sched.stop()
        count = len(calls)
        await asyncio.sleep(0.05)
        return count, len(calls), sched.snapshot()[0]

    count, after_stop, snap = asyncio.run(scenario())
    assert count >= 3
    assert after_stop == count
    assert snap["runs"] == count and snap["failures"] == 0


def test_failures_trigger_capped_backoff():
    async def scenario():
        sched = Scheduler(max_backoff_multiplier=4)

        async def broken():
            raise RuntimeError("falhou")

        sched.add_job("broken", broken, 0.01, run_immediately=True)
        sched.start()
        await asyncio.sleep(0.2)
        await sched.stop()
        return sched

    sched = asyncio.run(scenario())
    snap = sched.snapshot()[0]
    assert snap["failures"] >= 2
    assert snap["consecutive_failures"] == snap["failures"]
    assert "RuntimeError: falhou" in snap["last_error"]
    assert sched.effective_interval("broken") == pytest.approx(0.04)  # 0.01 * teto 4


def test_success_resets_backoff():
    async def scenario():
        sched = Scheduler()
        state = {"n": 0}

        async def flaky():
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("primeira falha")

        sched.add_job("flaky", flaky, 0.01, run_immediately=True)
        sched.start()
        await asyncio.sleep(0.1)
        await sched.stop()
        return sched.snapshot()[0]

    snap = asyncio.run(scenario())
    assert snap["failures"] == 1
    assert snap["consecutive_failures"] == 0
    assert snap["last_success_at"] is not None


def test_timeout_counts_as_failure():
    async def scenario():
        sched = Scheduler()

        async def hang():
            await asyncio.sleep(10)

        sched.add_job("hang", hang, 5, timeout=0.05, run_immediately=True)
        sched.start()
        await asyncio.sleep(0.15)
        await sched.stop()
        return sched.snapshot()[0]

    snap = asyncio.run(scenario())
    assert snap["failures"] == 1
    assert "tempo limite" in snap["last_error"]


def test_load_factor_only_slows_non_essential_jobs():
    sched = Scheduler(max_load_factor=4)

    async def noop():
        pass

    sched.add_job("essential", noop, 5, essential=True)
    sched.add_job("analysis", noop, 5)
    sched.set_load_factor(3)
    assert sched.effective_interval("essential") == 5
    assert sched.effective_interval("analysis") == 15
    with pytest.raises(SchedulerError):
        sched.set_load_factor(5)
    with pytest.raises(SchedulerError):
        sched.set_load_factor(0.5)


def test_invalid_jobs_are_rejected():
    sched = Scheduler()

    def sync_func():
        pass

    async def ok():
        pass

    with pytest.raises(SchedulerError, match="async"):
        sched.add_job("sync", sync_func, 1)  # type: ignore[arg-type]
    with pytest.raises(SchedulerError, match="positivo"):
        sched.add_job("zero", ok, 0)
    sched.add_job("dup", ok, 1)
    with pytest.raises(SchedulerError, match="já agendada"):
        sched.add_job("dup", ok, 1)


def test_job_added_while_running_starts_and_can_be_removed():
    async def scenario():
        sched = Scheduler()
        calls = []

        async def tick():
            calls.append(1)

        sched.start()
        sched.add_job("late", tick, 0.01, run_immediately=True)
        await asyncio.sleep(0.05)
        await sched.remove_job("late")
        count = len(calls)
        await asyncio.sleep(0.03)
        await sched.stop()
        return count, len(calls)

    count, final = asyncio.run(scenario())
    assert count >= 1 and final == count
