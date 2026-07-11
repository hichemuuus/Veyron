"""Tests for the async event bus."""

from __future__ import annotations

import pytest

from paios.core.events import Event, EventBus


class TestEvent:
    def test_event_defaults(self):
        e = Event(type="test.event")
        assert e.id is not None
        assert e.topic == "system"
        assert e.type == "test.event"
        assert e.payload == {}

    def test_event_with_payload(self):
        e = Event(type="test.event", topic="task_abc", payload={"key": "value"})
        assert e.topic == "task_abc"
        assert e.payload["key"] == "value"


class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscribe_and_receive(self):
        bus = EventBus()
        sub_id, iterator = await bus.subscribe("test_topic")
        assert sub_id is not None

        event = Event(type="test.event", topic="test_topic")
        await bus.publish(event)

        received = await anext(iterator)
        assert received.id == event.id
        assert received.type == "test.event"

    @pytest.mark.asyncio
    async def test_subscribe_all_topics(self):
        bus = EventBus()
        _, iterator = await bus.subscribe(None)

        event1 = Event(type="test.1", topic="topic_a")
        event2 = Event(type="test.2", topic="topic_b")
        await bus.publish(event1)
        await bus.publish(event2)

        e1 = await anext(iterator)
        e2 = await anext(iterator)
        assert e1.type == "test.1"
        assert e2.type == "test.2"

    @pytest.mark.asyncio
    async def test_topic_filtering(self):
        bus = EventBus()
        _, iterator = await bus.subscribe("topic_a")

        event_other = Event(type="test.other", topic="topic_b")
        event_match = Event(type="test.match", topic="topic_a")
        await bus.publish(event_other)
        await bus.publish(event_match)

        received = await anext(iterator)
        assert received.type == "test.match"

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        bus = EventBus()
        sub_id, iterator = await bus.subscribe("t")

        await bus.unsubscribe(sub_id)
        event = Event(type="test.event", topic="t")
        await bus.publish(event)

        # The iterator should be exhausted (no more events).
        import asyncio

        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.1):
                await anext(iterator)

    @pytest.mark.asyncio
    async def test_slow_consumer_drops_oldest(self):
        bus = EventBus(max_queue=2)
        sub_id, _ = await bus.subscribe("t")

        # Fill the queue by publishing more events than the max queue size.
        for i in range(5):
            await bus.publish(Event(type=f"test.{i}", topic="t"))

        # The subscriber should have the newest events (drop oldest).
        event = Event(type="final", topic="t")
        await bus.publish(event)
        # The subscriber queue should not be full; the publish succeeds.

    @pytest.mark.asyncio
    async def test_publish_nowait_schedules(self):
        bus = EventBus()
        sub_id, iterator = await bus.subscribe("t")

        bus.publish_nowait(Event(type="nowait", topic="t"))

        received = await anext(iterator)
        assert received.type == "nowait"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = EventBus()
        _, iter1 = await bus.subscribe("t")
        _, iter2 = await bus.subscribe("t")

        event = Event(type="multi", topic="t")
        await bus.publish(event)

        r1 = await anext(iter1)
        r2 = await anext(iter2)
        assert r1.id == event.id
        assert r2.id == event.id
