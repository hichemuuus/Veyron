"""Individual collector functions for the monitoring service.

Each function is a **pure sampler** — it takes nothing (or a reference
to the previous sample's tracking data) and returns a dataclass snapshot
plus updated tracking state.  None of them know about the cache or the
service; they are called by the ``MonitoringService`` loop.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import psutil

from veyron.monitor.snapshot import (
    CpuSnapshot,
    DiskSnapshot,
    MemorySnapshot,
    NetworkSnapshot,
    ProcessSnapshot,
    TemperatureSnapshot,
)

logger = logging.getLogger(__name__)

# ── Tracking state types (stored in the service, updated each cycle) ────


@dataclass
class CpuTracker:
    """Tracks previous CPU times for delta computation."""
    prev_cpu_times: tuple[float, ...] = ()
    prev_per_cpu_times: tuple[tuple[float, ...], ...] = ()
    prev_wall: float = 0.0


@dataclass
class ProcessTracker:
    """Tracks previous process CPU times for delta computation."""
    pid_map: dict[int, tuple[float, float]] = field(default_factory=dict)
    prev_wall: float = 0.0


@dataclass
class NetworkTracker:
    """Tracks previous network I/O counters for rate computation."""
    prev_counters: Any = None  # psutil._common.snetio or None
    prev_wall: float = 0.0


# ── Collector implementations ──────────────────────────────────────────


def sample_cpu(tracker: CpuTracker | None) -> tuple[CpuSnapshot, CpuTracker]:
    """Sample CPU: percent, per-core, frequency, load average.

    Uses absolute CPU-time deltas so results are accurate regardless of
    the sampling interval (no ``interval=`` parameter needed).
    """
    now = time.monotonic()

    cpu_count_logical = psutil.cpu_count(logical=True) or 0
    cpu_count_physical = psutil.cpu_count(logical=False) or 0
    freq = psutil.cpu_freq()
    freq_mhz = freq.current if freq else 0.0

    try:
        load_avg = tuple(round(x, 2) for x in psutil.getloadavg())
    except OSError:
        load_avg = ()

    if tracker is None or not tracker.prev_cpu_times:
        # First run — capture baseline, return 0% values.
        per_cpu_raw = psutil.cpu_times_percent(percpu=True, interval=0)
        overall_raw = psutil.cpu_times_percent(interval=0)
        tracker = CpuTracker(
            prev_cpu_times=tuple(overall_raw),
            prev_per_cpu_times=tuple(tuple(c) for c in per_cpu_raw),
            prev_wall=now,
        )
        per_cpu = tuple(c.user + c.system + c.nice + c.iowait for c in per_cpu_raw)
        return CpuSnapshot(
            percent=overall_raw.user + overall_raw.system + overall_raw.nice,
            per_cpu=per_cpu,
            frequency_mhz=freq_mhz,
            count_logical=cpu_count_logical,
            count_physical=cpu_count_physical,
            load_avg=load_avg,
        ), tracker

    # Delta computation over the actual elapsed interval.
    now_cpu_times = psutil.cpu_times_percent(interval=0)
    now_per_cpu = psutil.cpu_times_percent(percpu=True, interval=0)

    delta = now - tracker.prev_wall
    if delta < 0.001:
        delta = 0.001  # avoid division-by-zero

    overall_busy = (
        (now_cpu_times.user - tracker.prev_cpu_times[0])
        + (now_cpu_times.system - tracker.prev_cpu_times[2])
        + (now_cpu_times.nice - tracker.prev_cpu_times[1])
        + (now_cpu_times.iowait - tracker.prev_cpu_times[4])
        if hasattr(now_cpu_times, "iowait") else 0.0
    )
    overall_busy = max(0.0, min(100.0, overall_busy * 100.0))

    per_cpu = []
    for i, c in enumerate(now_per_cpu):
        if i < len(tracker.prev_per_cpu_times):
            busy = (c.user - tracker.prev_per_cpu_times[i][0]) + (c.system - tracker.prev_per_cpu_times[i][2])
            if hasattr(c, "nice"):
                busy += c.nice - tracker.prev_per_cpu_times[i][1]
            if hasattr(c, "iowait"):
                busy += c.iowait - tracker.prev_per_cpu_times[i][4]
            busy = max(0.0, min(100.0, busy * 100.0))
            per_cpu.append(busy)
        else:
            per_cpu.append(0.0)

    tracker = CpuTracker(
        prev_cpu_times=tuple(now_cpu_times),
        prev_per_cpu_times=tuple(tuple(c) for c in now_per_cpu),
        prev_wall=now,
    )

    return CpuSnapshot(
        percent=round(overall_busy, 1),
        per_cpu=tuple(round(v, 1) for v in per_cpu),
        frequency_mhz=freq_mhz,
        count_logical=cpu_count_logical,
        count_physical=cpu_count_physical,
        load_avg=load_avg,
    ), tracker


def sample_memory() -> MemorySnapshot:
    """Sample RAM + swap."""
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return MemorySnapshot(
        total=vm.total,
        available=vm.available,
        used=vm.used,
        free=vm.free,
        percent=vm.percent,
        swap_total=sw.total,
        swap_used=sw.used,
        swap_percent=sw.percent,
    )


def sample_disk() -> tuple[DiskSnapshot, ...]:
    """Sample disk partitions."""
    parts: list[DiskSnapshot] = []
    for p in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(p.mountpoint)
            parts.append(DiskSnapshot(
                device=p.device,
                mountpoint=p.mountpoint,
                fstype=p.fstype,
                total=usage.total,
                used=usage.used,
                free=usage.free,
                percent=usage.percent,
            ))
        except (OSError, PermissionError):
            continue
    return tuple(parts)


def sample_network(tracker: NetworkTracker | None) -> tuple[NetworkSnapshot, NetworkTracker]:
    """Sample network I/O with rate computation."""
    now = time.monotonic()
    try:
        counters = psutil.net_io_counters()
    except OSError:
        return NetworkSnapshot(), tracker or NetworkTracker()

    if tracker is None or tracker.prev_counters is None:
        tracker = NetworkTracker(prev_counters=counters, prev_wall=now)
        return NetworkSnapshot(
            bytes_sent=counters.bytes_sent,
            bytes_recv=counters.bytes_recv,
            packets_sent=counters.packets_sent,
            packets_recv=counters.packets_recv,
        ), tracker

    delta = now - tracker.prev_wall
    if delta < 0.001:
        delta = 0.001

    b_sent_sec = (counters.bytes_sent - tracker.prev_counters.bytes_sent) / delta
    b_recv_sec = (counters.bytes_recv - tracker.prev_counters.bytes_recv) / delta

    tracker = NetworkTracker(prev_counters=counters, prev_wall=now)

    return NetworkSnapshot(
        bytes_sent=counters.bytes_sent,
        bytes_recv=counters.bytes_recv,
        packets_sent=counters.packets_sent,
        packets_recv=counters.packets_recv,
        bytes_sent_per_sec=round(max(0, b_sent_sec), 1),
        bytes_recv_per_sec=round(max(0, b_recv_sec), 1),
    ), tracker


def sample_temperatures() -> tuple[TemperatureSnapshot, ...]:
    """Sample hardware temperatures (if supported)."""
    try:
        sensors = psutil.sensors_temperatures()
    except AttributeError:
        return ()
    if not sensors:
        return ()

    results: list[TemperatureSnapshot] = []
    for name, entries in sensors.items():
        for entry in entries:
            results.append(TemperatureSnapshot(
                name=name,
                label=entry.label or "",
                current=entry.current,
                high=entry.high,
                critical=entry.critical,
            ))
    return tuple(results)


def sample_gpu() -> bool:
    """Check whether a GPU appears to be present.

    Returns ``True`` if any GPU-like device is found.  Actual GPU
    monitoring is platform-specific and not implemented in this collector.
    """
    try:
        for part in psutil.disk_partitions():
            if "gpu" in part.device.lower():
                return True
    except (OSError, PermissionError):
        pass
    return False


def sample_processes(
    tracker: ProcessTracker | None,
    top_n: int = 30,
) -> tuple[tuple[ProcessSnapshot, ...], ProcessTracker]:
    """Sample top-N processes by CPU, sorted descending.

    Uses the same delta approach as ``sample_cpu``: tracks previous
    CPU-times per PID and computes the percentage over the real elapsed
    interval.
    """
    now = time.monotonic()
    now_procs: list[ProcessSnapshot] = []

    # Build a fresh pid_map for this cycle.
    next_pid_map: dict[int, tuple[float, float]] = {}

    for p in psutil.process_iter(["pid", "name", "username", "cpu_times", "memory_percent"]):
        try:
            info = p.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        pid = info["pid"]
        cpu_times = info.get("cpu_times")
        mem_pct = info.get("memory_percent") or 0.0

        if cpu_times is not None:
            proc_cpu_total = cpu_times.user + cpu_times.system
        else:
            proc_cpu_total = 0.0

        next_pid_map[pid] = (proc_cpu_total, now)

        if tracker is not None and pid in tracker.pid_map:
            prev_total, prev_wall = tracker.pid_map[pid]
            elapsed = now - prev_wall
            if elapsed > 0.001:
                cpu_delta = proc_cpu_total - prev_total
                cpu_pct = max(0.0, (cpu_delta / elapsed) * 100.0)
            else:
                cpu_pct = 0.0
        else:
            cpu_pct = 0.0

        now_procs.append(ProcessSnapshot(
            pid=pid,
            name=info.get("name", "") or "",
            username=str(info.get("username", "")) if info.get("username") else None,
            cpu_percent=round(cpu_pct, 1),
            memory_percent=round(mem_pct, 1),
        ))

    new_tracker = ProcessTracker(pid_map=next_pid_map, prev_wall=now)

    # Sort descending by CPU, keep top N.
    now_procs.sort(key=lambda p: p.cpu_percent, reverse=True)
    top = tuple(now_procs[:top_n])

    return top, new_tracker
