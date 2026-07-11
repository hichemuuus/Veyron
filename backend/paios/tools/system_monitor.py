"""System monitoring tool.

Reports real CPU, RAM, disk, and process stats via psutil. No fake data —
every number comes from an actual measurement. See ARCHITECTURE.md §5.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Type

import psutil
from pydantic import BaseModel, Field

from paios.db.base import sync_session_scope
from paios.db.models import ToolInvocation
from paios.security.command_policy import PermissionLevel
from paios.tools.base import Tool, ToolResult


class SystemMonitorInputs(BaseModel):
    operation: Literal["overview", "cpu", "memory", "disk", "processes", "health"] = Field(
        ...,
        description=(
            "overview: top-level snapshot; cpu: CPU detail; memory: RAM detail; "
            "disk: per-mount usage; processes: top processes; health: issue checks."
        ),
    )
    process_count: int = Field(default=10, description="Number of top processes to return.", ge=1, le=100)
    sort_processes_by: Literal["cpu", "memory"] = Field(
        default="cpu", description="Sort top processes by cpu or memory."
    )


class SystemMonitorTool(Tool):
    name: ClassVar[str] = "system_monitor"
    description: ClassVar[str] = (
        "Inspect this machine: CPU, memory, disk, processes, and health checks. "
        "Use to answer 'how is my system doing', 'what's using CPU', etc."
    )
    permission: ClassVar[PermissionLevel] = PermissionLevel.FREE
    Inputs: ClassVar[Type[BaseModel]] = SystemMonitorInputs

    async def run(self, ctx, **inputs: Any) -> ToolResult:
        op = inputs["operation"]
        if op == "overview":
            result = self._overview()
        elif op == "cpu":
            result = self._cpu()
        elif op == "memory":
            result = self._memory()
        elif op == "disk":
            result = self._disk()
        elif op == "processes":
            result = self._processes(inputs["process_count"], inputs["sort_processes_by"])
        elif op == "health":
            result = self._health()
        else:
            return ToolResult(ok=False, error=f"unknown operation: {op}")
        self._log(ctx, op, result)
        return result

    # --- Operations -------------------------------------------------------

    def _overview(self) -> ToolResult:
        vm = psutil.virtual_memory()
        data = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count": psutil.cpu_count(logical=True),
            "memory_total": vm.total,
            "memory_used": vm.used,
            "memory_percent": vm.percent,
            "disk_percent": _disk_avg_percent(),
            "boot_time": psutil.boot_time(),
        }
        text = (
            f"CPU: {data['cpu_percent']}% ({data['cpu_count']} cores)\n"
            f"RAM: {data['memory_percent']}% "
            f"({_fmt_bytes(data['memory_used'])} / {_fmt_bytes(data['memory_total'])})\n"
            f"Disk: {data['disk_percent']:.1f}% avg usage"
        )
        return ToolResult(output=text, data=data)

    def _cpu(self) -> ToolResult:
        # interval=0.1 gives a real short-sample reading.
        per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
        freq = psutil.cpu_freq()
        load = psutil.getloadavg() if hasattr(psutil, "getloadavg") else None
        data = {
            "cpu_percent_overall": sum(per_cpu) / len(per_cpu) if per_cpu else 0,
            "per_cpu": per_cpu,
            "cores_logical": psutil.cpu_count(logical=True),
            "cores_physical": psutil.cpu_count(logical=False),
            "freq_mhz_current": freq.current if freq else None,
            "freq_mhz_max": freq.max if freq else None,
            "load_avg": list(load) if load else None,
        }
        text = (
            f"Overall CPU: {data['cpu_percent_overall']:.1f}%\n"
            f"Per-core: {per_cpu}\n"
            f"Cores: {data['cores_physical']} physical / {data['cores_logical']} logical"
        )
        return ToolResult(output=text, data=data)

    def _memory(self) -> ToolResult:
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        data = {
            "total": vm.total,
            "available": vm.available,
            "used": vm.used,
            "free": vm.free,
            "percent": vm.percent,
            "swap_total": sm.total,
            "swap_used": sm.used,
            "swap_percent": sm.percent,
        }
        text = (
            f"RAM: {vm.percent}% used "
            f"({_fmt_bytes(vm.used)} / {_fmt_bytes(vm.total)}), "
            f"{_fmt_bytes(vm.available)} available\n"
            f"Swap: {sm.percent}% ({_fmt_bytes(sm.used)} / {_fmt_bytes(sm.total)})"
        )
        return ToolResult(output=text, data=data)

    def _disk(self) -> ToolResult:
        mounts = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            mounts.append(
                {
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                }
            )
        data = {"partitions": mounts}
        lines = []
        for m in mounts:
            lines.append(
                f"{m['mountpoint']} ({m['fstype']}): "
                f"{m['percent']}% — {_fmt_bytes(m['used'])} / {_fmt_bytes(m['total'])} free {_fmt_bytes(m['free'])}"
            )
        return ToolResult(output="\n".join(lines) or "(no mounts)", data=data)

    def _processes(self, count: int, sort_by: str) -> ToolResult:
        procs = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
            info = p.info
            info["cpu_percent"] = info.get("cpu_percent") or 0.0
            info["memory_percent"] = info.get("memory_percent") or 0.0
            procs.append(info)
        key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
        procs.sort(key=lambda x: x.get(key, 0), reverse=True)
        top = procs[:count]
        data = {"processes": top, "sort_by": key}
        lines = [f"{'PID':>7}  {'CPU%':>6}  {'MEM%':>6}  NAME"]
        for p in top:
            lines.append(
                f"{p.get('pid','-'):>7}  {p.get('cpu_percent',0):>6.1f}  "
                f"{p.get('memory_percent',0):>6.1f}  {p.get('name','?')}"
            )
        return ToolResult(output="\n".join(lines), data=data)

    def _health(self) -> ToolResult:
        issues = []
        cpu = psutil.cpu_percent(interval=0.1)
        vm = psutil.virtual_memory()
        if cpu > 85:
            issues.append(f"High CPU usage: {cpu:.0f}%")
        if vm.percent > 90:
            issues.append(f"High memory usage: {vm.percent:.0f}%")
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            if usage.percent > 90:
                issues.append(f"Low disk space on {part.mountpoint}: {usage.percent:.0f}% used")
        # Temperature sensors (best-effort; often absent on desktops).
        try:
            temps = psutil.sensors_temperatures()
            for name, entries in (temps or {}).items():
                for e in entries:
                    if e.current and e.high and e.current > e.high:
                        issues.append(f"Temperature high: {name} {e.label or ''} = {e.current}°C")
        except (AttributeError, OSError):
            pass
        data = {"issues": issues, "ok": len(issues) == 0}
        text = "No issues detected." if not issues else "\n".join(f"- {i}" for i in issues)
        return ToolResult(output=text, data=data)

    def _log(self, ctx, operation: str, result: ToolResult) -> None:
        """Persist a ToolInvocation row."""
        import json

        try:
            with sync_session_scope() as session:
                session.add(
                    ToolInvocation(
                        task_public_id=ctx.task_public_id,
                        tool_name=self.name,
                        permission=self.permission.value,
                        inputs=json.dumps({"operation": operation}),
                        result=str(result.data),
                        ok=result.ok,
                        duration_ms=result.duration_ms,
                        error=result.error,
                    )
                )
        except Exception:
            pass


def _fmt_bytes(n: int | float) -> str:
    """Human-readable byte size."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}EB"


def _disk_avg_percent() -> float:
    usages = []
    for part in psutil.disk_partitions(all=False):
        try:
            usages.append(psutil.disk_usage(part.mountpoint).percent)
        except (PermissionError, OSError):
            continue
    return sum(usages) / len(usages) if usages else 0.0
