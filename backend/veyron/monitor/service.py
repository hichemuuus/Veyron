"""Background monitoring service.

Continuously collects system metrics via dedicated collector functions,
each running in its own asyncio task at its own configurable interval.
Results are written to a shared ``SnapshotCache`` which REST endpoints and
WebSocket push tasks read from.

Architecture::

    MonitoringService
    ├─ _run_collector("cpu")        → cache.update(cpu=...)
    ├─ _run_collector("memory")     → cache.update(memory=...)
    ├─ _run_collector("processes")  → cache.update(top_processes=...)
    ├─ _run_collector("disks")      → cache.update(disks=...)
    ├─ _run_collector("network")    → cache.update(network=...)
    ├─ _run_collector("temperatures") → cache.update(temperatures=...)
    ├─ _run_collector("gpu")        → cache.update(gpu_exists=...)
    └─ _push_snapshot()             → WebSocket broadcast

Collector isolation:  if one collector fails the error is logged and it
waits for the next interval.  Other collectors are unaffected.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from veyron.monitor.cache import SnapshotCache
from veyron.monitor.collectors import (
    CpuTracker,
    NetworkTracker,
    ProcessTracker,
    sample_cpu,
    sample_disk,
    sample_gpu,
    sample_memory,
    sample_network,
    sample_processes,
    sample_temperatures,
)
from veyron.monitor.snapshot import SystemSnapshot

logger = logging.getLogger(__name__)

# ── Internal collector runner ───────────────────────────────────────────


@dataclass
class _CollectorState:
    """Per-collector runtime state."""
    cpu_tracker: CpuTracker | None = None
    process_tracker: ProcessTracker | None = None
    network_tracker: NetworkTracker | None = None


# ── Monitoring service ──────────────────────────────────────────────────


class MonitoringService:
    """Long-lived background monitoring service.

    Usage::

        service = MonitoringService()
        await service.start()
        # ... later ...
        await service.stop()
        snap = service.cache.get()
    """

    def __init__(self) -> None:
        self.cache = SnapshotCache()
        self._state = _CollectorState()
        self._tasks: list[asyncio.Task[Any]] = []
        self._running = False

        # Default intervals (overridable via configure()).
        self.cpu_interval: float = 0.2
        self.process_interval: float = 0.25
        self.memory_interval: float = 0.5
        self.disk_interval: float = 1.0
        self.network_interval: float = 0.5
        self.temp_interval: float = 1.0
        self.gpu_interval: float = 5.0
        self.top_n_processes: int = 30

        # WebSocket push interval (0 = disabled).
        self.push_interval: float = 0.2
        self._ws_push_callback: Callable[[SystemSnapshot], None] | None = None

    def configure(
        self,
        *,
        cpu_interval: float = 0.2,
        process_interval: float = 0.25,
        memory_interval: float = 0.5,
        disk_interval: float = 1.0,
        network_interval: float = 0.5,
        temp_interval: float = 1.0,
        gpu_interval: float = 5.0,
        top_n_processes: int = 30,
        push_interval: float = 0.2,
    ) -> None:
        self.cpu_interval = cpu_interval
        self.process_interval = process_interval
        self.memory_interval = memory_interval
        self.disk_interval = disk_interval
        self.network_interval = network_interval
        self.temp_interval = temp_interval
        self.gpu_interval = gpu_interval
        self.top_n_processes = top_n_processes

    def set_ws_push_callback(self, cb: Callable[[SystemSnapshot], None]) -> None:
        self._ws_push_callback = cb

    def clear_ws_push_callback(self) -> None:
        self._ws_push_callback = None

    async def start(self) -> None:
        if self._running:
            logger.warning("MonitoringService already running")
            return
        self._running = True
        logger.info(
            "Starting monitoring service (cpu=%ss, mem=%ss, procs=%ss, top_n=%d, push=%ss)",
            self.cpu_interval, self.memory_interval, self.process_interval,
            self.top_n_processes, self.push_interval,
        )

        self._tasks = [
            asyncio.create_task(self._run_collector("cpu", self.cpu_interval, self._sample_cpu_wrapper)),
            asyncio.create_task(self._run_collector("memory", self.memory_interval, self._sample_memory_wrapper)),
            asyncio.create_task(self._run_collector("processes", self.process_interval, self._sample_processes_wrapper)),
            asyncio.create_task(self._run_collector("disks", self.disk_interval, self._sample_disk_wrapper)),
            asyncio.create_task(self._run_collector("network", self.network_interval, self._sample_network_wrapper)),
            asyncio.create_task(self._run_collector("temperatures", self.temp_interval, self._sample_temp_wrapper)),
            asyncio.create_task(self._run_collector("gpu", self.gpu_interval, self._sample_gpu_wrapper)),
        ]

        if self._ws_push_callback and self.push_interval > 0:
            self._tasks.append(
                asyncio.create_task(self._push_loop())
            )

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.cache.reset()
        logger.info("Monitoring service stopped")

    async def _run_collector(
        self,
        name: str,
        interval: float,
        sample_fn: Callable[[], Any],
    ) -> None:
        while self._running:
            t0 = time.monotonic()
            try:
                await sample_fn()
                elapsed = time.monotonic() - t0
                if elapsed > interval * 2:
                    logger.warning("Collector '%s' took %.3fs (interval=%.3fs)", name, elapsed, interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Collector '%s' failed: %s", name, exc)
            await asyncio.sleep(max(0, interval - (time.monotonic() - t0)))

    # ── Collector wrappers (each does sampling + cache update) ──────────

    async def _sample_cpu_wrapper(self) -> None:
        snap, tracker = await asyncio.to_thread(sample_cpu, self._state.cpu_tracker)
        self._state.cpu_tracker = tracker
        self.cache.update(cpu=snap)

    async def _sample_memory_wrapper(self) -> None:
        snap = await asyncio.to_thread(sample_memory)
        self.cache.update(memory=snap)

    async def _sample_disk_wrapper(self) -> None:
        snap = await asyncio.to_thread(sample_disk)
        self.cache.update(disks=snap)

    async def _sample_network_wrapper(self) -> None:
        snap, tracker = await asyncio.to_thread(sample_network, self._state.network_tracker)
        self._state.network_tracker = tracker
        self.cache.update(network=snap)

    async def _sample_temp_wrapper(self) -> None:
        snap = await asyncio.to_thread(sample_temperatures)
        self.cache.update(temperatures=snap)

    async def _sample_gpu_wrapper(self) -> None:
        exists = await asyncio.to_thread(sample_gpu)
        self.cache.update(gpu_exists=exists)

    async def _sample_processes_wrapper(self) -> None:
        top, tracker = await asyncio.to_thread(sample_processes, self._state.process_tracker, self.top_n_processes)
        self._state.process_tracker = tracker
        self.cache.update(top_processes=top)

    async def _push_loop(self) -> None:
        while self._running:
            snap = self.cache.get()
            cb = self._ws_push_callback
            if cb is not None:
                try:
                    cb(snap)
                except Exception as exc:
                    logger.warning("WS push callback failed: %s", exc)
            await asyncio.sleep(self.push_interval)


# ── Singleton management (parallel to tool registry pattern) ────────────

_monitor: MonitoringService | None = None
_monitor_disabled: bool = False


def disable_monitor() -> None:
    """Disable the monitor for tests. Prevents lifespan from starting it."""
    global _monitor_disabled
    _monitor_disabled = True


def enable_monitor() -> None:
    """Re-enable the monitor."""
    global _monitor_disabled
    _monitor_disabled = False


def is_monitor_disabled() -> bool:
    return _monitor_disabled


def get_monitor() -> MonitoringService | None:
    """Return the global monitoring service, or ``None`` if not started."""
    return _monitor


def reset_monitor() -> None:
    """Test helper: clear the global monitor reference."""
    global _monitor
    _monitor = None


async def start_monitor(**kwargs: Any) -> MonitoringService:
    """Create, configure, and start the global monitoring service."""
    global _monitor
    if _monitor is not None:
        await _monitor.stop()
    _monitor = MonitoringService()
    _monitor.configure(**kwargs)
    await _monitor.start()
    logger.info("Global monitoring service started")
    return _monitor


async def stop_monitor() -> None:
    """Stop and clear the global monitoring service."""
    global _monitor
    if _monitor is not None:
        await _monitor.stop()
        _monitor = None
        logger.info("Global monitoring service stopped")
