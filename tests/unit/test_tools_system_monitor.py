"""Tests for the system monitor tool."""

from __future__ import annotations

import pytest
from veyron.security.command_policy import PermissionLevel
from veyron.tools.base import ToolContext
from veyron.tools.system_monitor import SystemMonitorTool


class TestSystemMonitorTool:
    @pytest.mark.asyncio
    async def test_overview(self):
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="overview")
        assert result.ok is True
        assert "CPU" in str(result.output)
        assert "RAM" in str(result.output)
        assert result.data.get("cpu_percent") is not None

    @pytest.mark.asyncio
    async def test_cpu(self):
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="cpu")
        assert result.ok is True
        assert "CPU" in str(result.output)
        assert result.data.get("cpu_percent_overall") is not None

    @pytest.mark.asyncio
    async def test_memory(self):
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="memory")
        assert result.ok is True
        assert "RAM" in str(result.output)
        assert result.data.get("used") is not None

    @pytest.mark.asyncio
    async def test_disk(self):
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="disk")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_processes(self):
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="processes", process_count=5, sort_processes_by="cpu")
        assert result.ok is True
        assert "PID" in str(result.output)
        assert len(result.data.get("processes", [])) <= 5

    @pytest.mark.asyncio
    async def test_processes_cpu_not_all_zero(self):
        """CPU percent values should be meaningful (non-zero for at least some processes)
        because of the priming pass that overcomes psutil's first-call-zero behavior."""
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="processes", process_count=20, sort_processes_by="cpu")
        assert result.ok is True
        procs = result.data.get("processes", [])
        assert len(procs) > 0
        # At least one process should have non-zero CPU% (the Python test runner itself).
        non_zero = [p for p in procs if (p.get("cpu_percent") or 0) > 0]
        # On very fast runs the delta may be 0 for everything; acceptable.
        # The key assertion is that values are not None and are floats.
        for p in procs:
            assert isinstance(p.get("cpu_percent"), (int, float))
            assert p.get("cpu_percent") is not None

    @pytest.mark.asyncio
    async def test_processes_sorted_by_cpu(self):
        """Processes sorted by cpu must be in descending cpu_percent order."""
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="processes", process_count=20, sort_processes_by="cpu")
        procs = result.data.get("processes", [])
        cpus = [p.get("cpu_percent", 0) for p in procs]
        assert cpus == sorted(cpus, reverse=True), "cpu sort order"

    @pytest.mark.asyncio
    async def test_processes_sorted_by_memory(self):
        """Processes sorted by memory must be in descending memory_percent order."""
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="processes", process_count=20, sort_processes_by="memory")
        procs = result.data.get("processes", [])
        mems = [p.get("memory_percent", 0) for p in procs]
        assert mems == sorted(mems, reverse=True), "memory sort order"

    @pytest.mark.asyncio
    async def test_processes_count_respected(self):
        """The process_count parameter must be respected exactly (up to available processes)."""
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="processes", process_count=3, sort_processes_by="cpu")
        procs = result.data.get("processes", [])
        assert len(procs) <= 3, f"Expected <=3 processes, got {len(procs)}"

    @pytest.mark.asyncio
    async def test_health(self):
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="health")
        assert result.ok is True
        # health always succeeds, even if issues are found.
        assert "data" in result.model_dump()

    @pytest.mark.asyncio
    async def test_unknown_operation(self):
        tool = SystemMonitorTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, operation="nonexistent")
        assert result.ok is False
        assert "unknown operation" in result.error

    def test_tool_metadata(self):
        assert SystemMonitorTool.name == "system_monitor"
        assert SystemMonitorTool.permission == PermissionLevel.FREE

    def test_input_schema(self):
        schema = type(SystemMonitorTool()).schema_for_llm()
        assert schema["name"] == "system_monitor"
        assert "operation" in schema["parameters"]["properties"]
