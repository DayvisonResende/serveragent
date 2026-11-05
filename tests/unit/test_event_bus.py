import asyncio

import pytest

from sentinel.core.event_bus import WILDCARD, Event, EventBus, Severity


def make_event(event_type: str = "test.happened") -> Event:
    return Event(event_type=event_type, source="test", title="Algo aconteceu")


def test_event_requires_fields():
    with pytest.raises(ValueError):
        Event(event_type="", source="x", title="y")
    with pytest.raises(ValueError):
        Event(event_type="a", source="x", title="y", severity="loud")  # type: ignore[arg-type]


def test_handlers_receive_matching_and_wildcard_events():
    async def scenario():
        bus = EventBus()
        typed, wild = [], []

        async def on_typed(e):
            typed.append(e.event_type)

        async def on_any(e):
            wild.append(e.event_type)

        bus.subscribe("a", on_typed)
        bus.subscribe(WILDCARD, on_any)
        bus.start()
        bus.publish(make_event("a"))
        bus.publish(make_event("b"))
        await bus.stop()
        return typed, wild

    typed, wild = asyncio.run(scenario())
    assert typed == ["a"]
    assert wild == ["a", "b"]


def test_failing_handler_does_not_block_others():
    async def scenario():
        bus = EventBus()
        received = []

        async def broken(e):
            raise RuntimeError("boom")

        async def good(e):
            received.append(e)

        bus.subscribe("x", broken)
        bus.subscribe("x", good)
        bus.start()
        bus.publish(make_event("x"))
        await bus.stop()
        return bus, received

    bus, received = asyncio.run(scenario())
    assert len(received) == 1
    assert bus.handler_errors == 1


def test_slow_handler_times_out():
    async def scenario():
        bus = EventBus(handler_timeout=0.05)

        async def slow(e):
            await asyncio.sleep(10)

        bus.subscribe("x", slow)
        bus.start()
        bus.publish(make_event("x"))
        await bus.stop(drain_timeout=2)
        return bus

    assert asyncio.run(scenario()).handler_errors == 1


def test_full_queue_drops_and_counts_without_blocking():
    async def scenario():
        bus = EventBus(queue_size=2)  # não iniciado: nada é consumido
        results = [bus.publish(make_event()) for _ in range(5)]
        return bus, results

    bus, results = asyncio.run(scenario())
    assert results == [True, True, False, False, False]
    assert bus.dropped == 3
    assert bus.published == 2


def test_unsubscribe_is_idempotent():
    async def scenario():
        bus = EventBus()
        received = []

        async def handler(e):
            received.append(e)

        unsubscribe = bus.subscribe("x", handler)
        unsubscribe()
        unsubscribe()
        bus.start()
        bus.publish(make_event("x"))
        await bus.stop()
        return received

    assert asyncio.run(scenario()) == []


def test_stop_drains_pending_events():
    async def scenario():
        bus = EventBus()
        received = []

        async def handler(e):
            await asyncio.sleep(0.001)
            received.append(e)

        bus.subscribe(WILDCARD, handler)
        for _ in range(20):
            bus.publish(make_event())
        bus.start()
        await bus.stop()
        return received

    assert len(asyncio.run(scenario())) == 20


def test_severity_values_match_prd_levels():
    assert [s.value for s in Severity] == ["info", "warning", "high", "critical"]
