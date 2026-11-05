"""Coletores com o psutil real (rodam em Linux e Windows)."""

import time
from collections import namedtuple

import psutil
import pytest

from sentinel.modules.monitor import temperature
from sentinel.modules.monitor.cpu import CpuCollector, busy_percent
from sentinel.modules.monitor.disk import collect_disks
from sentinel.modules.monitor.memory import collect_memory
from sentinel.modules.monitor.network import NetworkCollector
from sentinel.modules.monitor.processes import ProcessCollector, ProcessInfo, sort_processes

Times = namedtuple("Times", "user system idle")
TimesIo = namedtuple("TimesIo", "user system idle iowait")


def test_busy_percent_math():
    assert busy_percent(Times(10, 10, 80), Times(20, 20, 160)) == 20.0
    assert busy_percent(TimesIo(0, 0, 0, 0), TimesIo(5, 0, 3, 2)) == 50.0  # iowait conta como ocioso
    assert busy_percent(Times(1, 1, 1), Times(1, 1, 1)) is None  # sem intervalo: sem medição


def test_cpu_collector_returns_real_bounded_values():
    collector = CpuCollector()
    sample = collector.collect()  # primeira leitura respeita a janela mínima
    assert 0 <= sample.percent <= 100
    assert len(sample.per_core) == psutil.cpu_count(logical=True)
    time.sleep(0.2)
    assert 0 <= collector.collect().percent <= 100


def test_memory_is_consistent():
    m = collect_memory()
    assert m.total > 0 and 0 <= m.percent <= 100
    assert m.used + m.available == m.total


def test_disks_report_real_partitions():
    report = collect_disks()
    assert report.disks, "ao menos uma partição local esperada"
    for d in report.disks:
        assert d.total > 0 and d.used + d.free <= d.total + 1024**2


def test_network_rates_are_unknown_until_second_reading():
    collector = NetworkCollector()
    first = collector.collect()
    assert first.upload_bps is None and first.download_bps is None
    assert all(i.upload_bps is None for i in first.interfaces)
    time.sleep(0.2)
    second = collector.collect()
    measured = [i for i in second.interfaces if i.upload_bps is not None]
    assert measured and all(i.upload_bps >= 0 for i in measured)


def test_network_counter_reset_yields_unknown_rate(monkeypatch):
    Counters = namedtuple("Counters", "bytes_sent bytes_recv errin errout dropin dropout")
    values = iter([Counters(1000, 1000, 0, 0, 0, 0), Counters(10, 10, 0, 0, 0, 0)])
    monkeypatch.setattr(psutil, "net_io_counters", lambda pernic: {"eth0": next(values)})
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {})
    monkeypatch.setattr(psutil, "net_if_stats", lambda: {})
    collector = NetworkCollector()
    collector.collect()
    time.sleep(0.01)
    after_reset = collector.collect()
    assert after_reset.interfaces[0].upload_bps is None  # contador diminuiu: não inventa taxa
    assert after_reset.upload_bps is None


def test_process_cpu_is_unknown_on_first_sight_then_measured():
    collector = ProcessCollector()
    first = collector.collect()
    assert first and all(p.cpu_percent is None for p in first)
    assert all(p.pid != 0 for p in first)
    time.sleep(0.2)
    second = collector.collect()
    me = next(p for p in second if p.pid == psutil.Process().pid)
    assert me.cpu_percent is not None and me.memory_bytes > 0


def _proc(pid, name, cpu, mem, created):
    return ProcessInfo(pid, name, None, None, None, None, created, cpu, mem, None)


def test_sort_processes():
    procs = [_proc(1, "b", None, 50, 30.0), _proc(2, "A", 5.0, 10, 10.0), _proc(3, "c", 1.0, 99, None)]
    assert [p.pid for p in sort_processes(procs, "cpu", 10)] == [2, 3, 1]  # medidos primeiro
    assert [p.pid for p in sort_processes(procs, "memory", 2)] == [3, 1]
    assert [p.pid for p in sort_processes(procs, "name", 10)] == [2, 1, 3]
    assert [p.pid for p in sort_processes(procs, "runtime", 10)] == [2, 1, 3]
    with pytest.raises(ValueError):
        sort_processes(procs, "bogus", 1)  # type: ignore[arg-type]


def test_temperature_unavailable_is_reported_never_invented(monkeypatch):
    monkeypatch.delattr(psutil, "sensors_temperatures", raising=False)
    reading = temperature.read_temperatures()
    assert reading.available is False and reading.sensors == []
    assert reading.as_dict()["message"] == "Sensor de temperatura indisponível."


def test_temperature_empty_sensor_list_is_unavailable(monkeypatch):
    monkeypatch.setattr(psutil, "sensors_temperatures", lambda: {}, raising=False)
    assert temperature.read_temperatures().available is False
