"""Async event bus.

In-process pub/sub used to stream every meaningful action (tool calls, plan
steps, memory writes, task transitions, confirmation requests) to WebSocket
clients. One bus per process; subscribers get their own asyncio.Queue so a slow
consumer doesn't block others.

See ARCHITECTURE.md §3.5. Swap for Redis only if cross-process scaling is ever
needed (unlikely for a personal OS) — logged in DECISIONS.md.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from typing import Any, AsyncIterator
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Event(BaseModel):
    """A single event on the bus."""

    # Unique id for this event.
    id: str = Field(default_factory=lambda: uuid4().hex)
    # Type, e.g. "task.created", "tool.invoke", "plan.step", "security.confirm".
    type: str
    # Topic: typically the task public_id, or "system" for global events.
    topic: str = "system"
    # Monotonic-ish timestamp.
    ts: float = Field(default_factory=lambda: _event_time())
    # Arbitrary typed payload. Kept as dict for JSON-friendliness over the WS.
    payload: dict[str, Any] = Field(default_factory=dict)


def _event_time() -> float:
    try:
        return asyncio.get_running_loop().time()
    except RuntimeError:
        return time.time()


class EventBus:
    """Fan-out async event bus.

    Each subscriber owns a bounded queue. Publishers never block on a full
    queue — the oldest event is dropped with a warning (slow-consumer policy).
    """

    def __init__(self, max_queue: int = 256) -> None:
        self._subscribers: dict[str, asyncio.Queue[Event]] = {}
        # topic -> set of subscriber ids (None means "all topics")
        self._topic_subs: dict[str | None, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._max_queue = max_queue

    async def subscribe(self, topic: str | None = None) -> tuple[str, AsyncIterator[Event]]:
        """Subscribe to events on a topic (None = all topics).

        Returns (subscriber_id, async iterator). Iterate the iterator to receive
        events; cancel iteration to unsubscribe.
        """
        sub_id = uuid4().hex
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._subscribers[sub_id] = queue
            self._topic_subs[topic].add(sub_id)
        logger.debug("bus.subscribe id=%s topic=%s", sub_id, topic)

        async def _iterator() -> AsyncIterator[Event]:
            try:
                while True:
                    yield await queue.get()
            except GeneratorExit:
                await self.unsubscribe(sub_id)

        return sub_id, _iterator()

    async def unsubscribe(self, sub_id: str) -> None:
        async with self._lock:
            queue = self._subscribers.pop(sub_id, None)
            for subs in self._topic_subs.values():
                subs.discard(sub_id)
        if queue is not None:
            logger.debug("bus.unsubscribe id=%s", sub_id)

    async def publish(self, event: Event) -> None:
        """Fan-out an event to all matching subscribers.

        Snapshot subscriber state under the lock so concurrent subscribe/
        unsubscribe does not cause a dictionary-mutation-while-iterating
        crash or silently drop subscribers.
        """
        async with self._lock:
            targets: set[str] = set()
            targets |= self._topic_subs.get(event.topic, set())
            targets |= self._topic_subs.get(None, set())
            queues = [(sub_id, self._subscribers.get(sub_id)) for sub_id in targets]

        for sub_id, queue in queues:
            if queue is None:
                continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                    logger.warning("bus slow consumer, dropped old event for %s", sub_id)
                except asyncio.QueueEmpty:
                    pass

    def publish_nowait(self, event: Event) -> None:
        """Sync helper to publish from non-async contexts.

        Schedules publish on the running loop. No-op if there's no running loop.
        Uses a wrapper that catches exceptions to prevent orphaned task failures.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._publish_safe(event))
        except RuntimeError:
            logger.debug("bus.publish_nowait called without a running loop; dropping event")

    async def _publish_safe(self, event: Event) -> None:
        try:
            await self.publish(event)
        except Exception:
            logger.warning("bus background publish failed for event %s", event.type)

    async def shutdown(self) -> None:
        """Shut down the bus: clear subscribers and queues."""
        async with self._lock:
            for queue in self._subscribers.values():
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
            self._subscribers.clear()
            self._topic_subs.clear()
        logger.info("event bus shut down")


# Process-wide bus. Imported everywhere; tests may create their own instance.
_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus()
    return _bus


def reset_bus() -> None:
    """Test helper: replace the global bus with a fresh one."""
    global _bus
    _bus = EventBus()
