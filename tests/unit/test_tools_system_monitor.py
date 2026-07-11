"""Tests for the system monitor tool."""

from __future__ import annotations

import pytest

from paios.security.command_policy import PermissionLevel
from paios.tools.base import ToolContext
from paios.tools.system_monitor import SystemMonitorTool


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
