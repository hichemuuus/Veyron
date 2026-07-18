"""Immutable snapshot types for the monitoring subsystem.

Each dataclass is frozen so it can be shared across threads safely.
The top-level ``SystemSnapshot`` holds the latest observed state across
all collectors and is atomically swapped in ``SnapshotCache``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CpuSnapshot:
    """CPU metrics from the last sample interval."""
    percent: float = 0.0
    per_cpu: tuple[float, ...] = ()
    frequency_mhz: float = 0.0
    count_logical: int = 0
    count_physical: int = 0
    load_avg: tuple[float, ...] = ()


@dataclass(frozen=True)
class MemorySnapshot:
    """RAM + swap metrics."""
    total: int = 0
    available: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0


@dataclass(frozen=True)
class ProcessSnapshot:
    """A single process entry suitable for top-N tables."""
    pid: int = 0
    name: str = ""
    username: str | None = None
    cpu_percent: float = 0.0
    memory_percent: float = 0.0


@dataclass(frozen=True)
class DiskSnapshot:
    """Single partition / mount."""
    device: str = ""
    mountpoint: str = ""
    fstype: str = ""
    total: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0


@dataclass(frozen=True)
class NetworkSnapshot:
    """Aggregate network I/O counters + rates."""
    bytes_sent: int = 0
    bytes_recv: int = 0
    packets_sent: int = 0
    packets_recv: int = 0
    bytes_sent_per_sec: float = 0.0
    bytes_recv_per_sec: float = 0.0


@dataclass(frozen=True)
class TemperatureSnapshot:
    """Single sensor reading."""
    name: str = ""
    label: str = ""
    current: float = 0.0
    high: float | None = None
    critical: float | None = None


@dataclass(frozen=True)
class SystemSnapshot:
    """Complete point-in-time system state.

    Every field is **immutable** and **always present** (defaults to a
    zero / empty value) so consumers never need ``None`` checks for
    rendering.
    """
    cpu: CpuSnapshot = field(default_factory=CpuSnapshot)
    memory: MemorySnapshot = field(default_factory=MemorySnapshot)
    gpu_exists: bool = False
    disks: tuple[DiskSnapshot, ...] = ()
    network: NetworkSnapshot = field(default_factory=NetworkSnapshot)
    temperatures: tuple[TemperatureSnapshot, ...] = ()
    top_processes: tuple[ProcessSnapshot, ...] = ()
    timestamp: float = field(default_factory=time.time)
