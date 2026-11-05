import asyncio

import pytest

from sentinel.core.event_bus import EventBus, EventType
from sentinel.core.exceptions import DependencyError, ModuleRegistrationError
from sentinel.core.module_registry import Module, ModuleHealth, ModuleRegistry, ModuleStatus


class Recorder(Module):
    def __init__(self, name, depends_on=(), fail=False, hang=False, log=None):
        self.name = name  # type: ignore[misc]
        self.depends_on = tuple(depends_on)  # type: ignore[misc]
        self.fail = fail
        self.hang = hang
        self.log = log if log is not None else []

    async def start(self, context):
        if self.hang:
            await asyncio.sleep(10)
        if self.fail:
            raise RuntimeError(f"{self.name} quebrou")
        self.log.append(("start", self.name))

    async def stop(self):
        self.log.append(("stop", self.name))


def make_registry(bus=None):
    return ModuleRegistry(bus or EventBus(), start_timeout=0.2, stop_timeout=0.2)


def test_start_order_respects_dependencies():
    reg = make_registry()
    reg.register(Recorder("api", ["monitor", "security"]))
    reg.register(Recorder("monitor"))
    reg.register(Recorder("security", ["monitor"]))
    assert reg.start_order() == ["monitor", "security", "api"]


def test_cycle_is_detected():
    reg = make_registry()
    reg.register(Recorder("a", ["b"]))
    reg.register(Recorder("b", ["a"]))
    with pytest.raises(DependencyError, match="cíclica"):
        reg.start_order()


def test_unknown_dependency_is_rejected():
    reg = make_registry()
    reg.register(Recorder("a", ["ghost"]))
    with pytest.raises(DependencyError, match="ghost"):
        reg.start_order()


def test_duplicate_and_unnamed_modules_are_rejected():
    reg = make_registry()
    reg.register(Recorder("a"))
    with pytest.raises(ModuleRegistrationError):
        reg.register(Recorder("a"))
    with pytest.raises(ModuleRegistrationError):
        reg.register(Recorder(""))


def test_failure_is_isolated_and_dependents_are_skipped():
    async def scenario():
        bus = EventBus()
        reg = make_registry(bus)
        log = []
        reg.register(Recorder("monitor", fail=True, log=log))
        reg.register(Recorder("servers", ["monitor"], log=log))
        reg.register(Recorder("notifications", log=log))
        await reg.start_all(context=None)
        return reg, bus, log

    reg, bus, log = asyncio.run(scenario())
    assert reg.status("monitor") is ModuleStatus.FAILED
    assert reg.status("servers") is ModuleStatus.SKIPPED
    assert reg.status("notifications") is ModuleStatus.RUNNING
    assert log == [("start", "notifications")]
    assert sorted(reg.unavailable_modules) == ["monitor", "servers"]
    events = [bus._queue.get_nowait() for _ in range(bus._queue.qsize())]
    assert {e.event_type for e in events} == {EventType.MODULE_FAILED, EventType.MODULE_SKIPPED}


def test_start_timeout_marks_module_failed():
    async def scenario():
        reg = make_registry()
        reg.register(Recorder("slow", hang=True))
        await reg.start_all(context=None)
        return reg

    reg = asyncio.run(scenario())
    assert reg.status("slow") is ModuleStatus.FAILED
    assert "Tempo limite" in reg.snapshot()[0]["error"]


def test_stop_runs_in_reverse_order_only_for_running_modules():
    async def scenario():
        reg = make_registry()
        log = []
        reg.register(Recorder("a", log=log))
        reg.register(Recorder("b", ["a"], log=log))
        reg.register(Recorder("broken", fail=True, log=log))
        await reg.start_all(context=None)
        await reg.stop_all()
        return reg, log

    reg, log = asyncio.run(scenario())
    assert [entry for entry in log if entry[0] == "stop"] == [("stop", "b"), ("stop", "a")]
    assert reg.status("a") is ModuleStatus.STOPPED
    assert reg.status("broken") is ModuleStatus.FAILED


def test_snapshot_reports_health_and_survives_broken_health():
    class BadHealth(Recorder):
        def health(self):
            raise ValueError("sensor")

    class Unhealthy(Recorder):
        def health(self):
            return ModuleHealth(False, "atrasado")

    async def scenario():
        reg = make_registry()
        reg.register(BadHealth("bad"))
        reg.register(Unhealthy("meh"))
        await reg.start_all(context=None)
        return reg.snapshot()

    snap = {m["name"]: m for m in asyncio.run(scenario())}
    assert snap["bad"]["health"]["healthy"] is False
    assert "sensor" in snap["bad"]["health"]["detail"]
    assert snap["meh"]["health"] == {"healthy": False, "detail": "atrasado"}
