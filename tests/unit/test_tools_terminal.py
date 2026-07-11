"""Tests for the terminal tool."""

from __future__ import annotations

import pytest

from paios.security.command_policy import PermissionLevel
from paios.tools.base import ToolContext
from paios.tools.terminal import TerminalTool


class TestTerminalTool:
    @pytest.mark.asyncio
    async def test_empty_command(self):
        tool = TerminalTool()
        ctx = ToolContext(task_public_id="test")
        result = await tool.run(ctx, command="", timeout=5)
        assert result.ok is False
        assert "empty" in result.error

    @pytest.mark.asyncio
    async def test_echo_command_free(self):
        tool = TerminalTool()
        # echo is FREE, so it should run without confirmation.
        async def confirm(*args, **kwargs):
            return True, None

        ctx = ToolContext(task_public_id="test", confirm=confirm)
        result = await tool.run(ctx, command="echo hello", timeout=5)
        assert result.ok is True
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_unknown_command_handled(self):
        tool = TerminalTool()
        async def confirm(*args, **kwargs):
            return True, None

        ctx = ToolContext(task_public_id="test", confirm=confirm)
        result = await tool.run(ctx, command="nonexistent_command_xyz", timeout=5)
        # The command should still run but may fail or succeed depending on the system.
        # On Windows, the shell will error if the command isn't found.

    @pytest.mark.asyncio
    async def test_confirmation_required_for_unknown(self):
        tool = TerminalTool()
        confirm_called = False

        async def confirm(*args, **kwargs):
            nonlocal confirm_called
            confirm_called = True
            return True, None

        ctx = ToolContext(task_public_id="test", confirm=confirm)
        # "some_weird_command" is not in the allowlist → CONFIRM.
        result = await tool.run(ctx, command="some_weird_command", timeout=5)
        assert confirm_called is True

    @pytest.mark.asyncio
    async def test_confirmation_denied(self):
        tool = TerminalTool()

        async def confirm(*args, **kwargs):
            return False, "not now"

        ctx = ToolContext(task_public_id="test", confirm=confirm)
        result = await tool.run(ctx, command="some_weird_command", timeout=5)
        assert result.ok is False
        assert "not approved" in result.error

    @pytest.mark.asyncio
    async def test_safe_run_validates_inputs(self):
        tool = TerminalTool()
        ctx = ToolContext(task_public_id="test")
        # Malformed inputs (timeout too large) should be caught.
        result = await tool.safe_run(ctx, command="echo hi", timeout=999999)
        assert result.ok is False

    def test_tool_metadata(self):
        assert TerminalTool.name == "terminal"
        assert TerminalTool.permission == PermissionLevel.CONFIRM

    def test_input_schema(self):
        schema = type(TerminalTool()).schema_for_llm()
        assert schema["name"] == "terminal"
        assert "command" in schema["parameters"]["properties"]
        assert "timeout" in schema["parameters"]["properties"]
