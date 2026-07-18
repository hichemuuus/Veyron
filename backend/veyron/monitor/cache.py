"""Thread-safe snapshot cache.

The cache stores a single ``SystemSnapshot`` and provides atomic
read/write access.  Because ``SystemSnapshot`` is frozen we use a lock
for write serialisation (to avoid lost updates when two collectors
finish at the same instant) but reads are lock-free on CPython thanks
to the GIL and atomic reference assignment.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import ClassVar

from veyron.monitor.snapshot import SystemSnapshot


@dataclass
class SnapshotCache:
    """Holds the latest system snapshot.

    Usage::

        cache = SnapshotCache()
        cache.update(cpu=my_cpu_snapshot, memory=my_mem_snapshot)
        snap = cache.get()
    """

    _snapshot: SystemSnapshot = SystemSnapshot()
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Sentinel so callers can detect "no data yet" without a None check.
    EMPTY: ClassVar[SystemSnapshot] = SystemSnapshot()

    def get(self) -> SystemSnapshot:
        """Return the latest snapshot (lock-free read)."""
        return self._snapshot

    def update(self, **kwargs) -> None:
        """Atomically replace fields on the current snapshot.

        Accepts any keyword argument that matches a ``SystemSnapshot``
        field (e.g. ``cpu=..., memory=..., top_processes=...``).
        """
        with self._lock:
            current = self._snapshot
            self._snapshot = replace(current, **kwargs)

    def reset(self) -> None:
        """Reset to an empty snapshot (used during testing / shutdown)."""
        with self._lock:
            self._snapshot = SystemSnapshot()
