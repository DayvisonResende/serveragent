from sentinel.agent.config import AlertSettings, ResourceSettings
from sentinel.agent.scheduler import Scheduler
from sentinel.core.event_bus import EventBus, Severity
from sentinel.core.resource_manager import EVENT_PRESSURE_CHANGED, PressureLevel, ResourceManager
from sentinel.modules.monitor import alerts as A
from sentinel.modules.monitor.disk import DiskUsage


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_evaluator(**overrides):
    events, clock = [], Clock()
    settings = AlertSettings(**{"cpu_sustained_seconds": 60, "memory_sustained_seconds": 0, **overrides})
    ev = A.AlertEvaluator(settings, lambda e: events.append(e) or True, clock=clock, wall_clock=lambda: 1_800_000_000.0)
    return ev, events, clock


def test_cpu_alert_requires_sustained_load_and_hysteresis():
    ev, events, clock = make_evaluator()
    ev.check_cpu(95)
    clock.now = 59
    ev.check_cpu(96)
    assert events == []  # pico curto não alerta
    clock.now = 61
    ev.check_cpu(97)
    assert [e.event_type for e in events] == [A.EVENT_CPU_HIGH] and events[0].severity is Severity.HIGH
    ev.check_cpu(88)  # abaixo do limite, mas dentro da histerese (90-5)
    ev.check_cpu(99)
    assert len(events) == 1
    ev.check_cpu(80)
    assert events[-1].event_type == A.EVENT_CPU_NORMAL
    assert ev.active() == []


def test_cpu_spike_interrupted_restarts_timer():
    ev, events, clock = make_evaluator()
    ev.check_cpu(95)
    clock.now = 40
    ev.check_cpu(50)
    clock.now = 70
    ev.check_cpu(95)
    clock.now = 100
    ev.check_cpu(95)
    assert events == []


def test_memory_alert_and_active_listing():
    ev, events, _ = make_evaluator()
    ev.check_memory(93, 700 * 1024**2)
    assert events[0].event_type == A.EVENT_MEMORY_HIGH
    assert "0,7 GB" in events[0].description
    assert [a["key"] for a in ev.active()] == ["memory"]


def disk(free_pct, mount="C:\\"):
    total = 1000
    free = int(total * free_pct / 100)
    return DiskUsage("dev", mount, "NTFS", total, total - free, free, 100 - free_pct)


def test_disk_levels_escalate_and_recover_with_hysteresis():
    ev, events, _ = make_evaluator()
    ev.check_disks([disk(50)])
    assert events == []
    ev.check_disks([disk(9)])
    assert events[-1].severity is Severity.WARNING
    ev.check_disks([disk(4)])
    assert events[-1].severity is Severity.CRITICAL
    ev.check_disks([disk(7)])  # 5 + 5 de histerese: ainda crítico
    assert len(events) == 2
    ev.check_disks([disk(12)])  # melhora para atenção, sem novo evento
    assert len(events) == 2 and ev.active()[0]["severity"] == "warning"
    ev.check_disks([disk(16)])
    assert events[-1].event_type == A.EVENT_DISK_RECOVERED and ev.active() == []


def test_disks_are_tracked_independently():
    ev, events, _ = make_evaluator()
    ev.check_disks([disk(4, "C:\\"), disk(60, "D:\\")])
    assert len(events) == 1 and events[0].metadata["mountpoint"] == "C:\\"


def make_manager():
    bus = EventBus()
    sched = Scheduler(max_load_factor=4)
    rm = ResourceManager(ResourceSettings(smoothing_samples=1, hysteresis_percent=10), sched, bus)
    return rm, sched, bus


def drain(bus):
    return [bus._queue.get_nowait() for _ in range(bus._queue.qsize())]


def test_resource_manager_levels_and_load_factor():
    rm, sched, bus = make_manager()
    assert rm.update(50, 50) is PressureLevel.NORMAL and sched.load_factor == 1
    assert rm.update(85, 50) is PressureLevel.PRESSURE and sched.load_factor == 2
    assert rm.update(97, 50) is PressureLevel.SEVERE and sched.load_factor == 4
    assert rm.update(90, 50) is PressureLevel.SEVERE  # 95-10: histerese mantém
    assert rm.update(84, 50) is PressureLevel.PRESSURE
    assert rm.update(72, 50) is PressureLevel.PRESSURE  # 80-10
    assert rm.update(60, 50) is PressureLevel.NORMAL and sched.load_factor == 1
    events = drain(bus)
    assert [e.metadata["to"] for e in events] == ["pressure", "severe", "pressure", "normal"]
    assert events[0].event_type == EVENT_PRESSURE_CHANGED and events[0].severity is Severity.WARNING
    assert events[-1].severity is Severity.INFO


def test_memory_pressure_alone_triggers_low_priority_mode():
    rm, sched, _ = make_manager()
    assert rm.update(10, 95) is PressureLevel.PRESSURE and rm.under_pressure


def test_smoothing_ignores_single_spike():
    bus = EventBus()
    rm = ResourceManager(ResourceSettings(smoothing_samples=6), Scheduler(), bus)
    for _ in range(5):
        rm.update(10, 40)
    assert rm.update(100, 40) is PressureLevel.NORMAL
