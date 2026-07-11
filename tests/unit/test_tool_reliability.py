"""Tests for tool reliability features: failure classification, retry, timeout."""

from __future__ import annotations

import asyncio
import time

import pytest

from paios.tools.base import FailureCategory, Tool, ToolContext, ToolResult, classify_failure


class TestFailureClassification:
    """FailureCategory and classify_failure tests."""

    def test_timeout_classification(self):
        assert classify_failure("TIMEOUT after 5000ms") == FailureCategory.TIMEOUT
        assert classify_failure("timed out waiting for response") == FailureCategory.TIMEOUT

    def test_invalid_input_classification(self):
        assert classify_failure("invalid input: expected string") == FailureCategory.INVALID_INPUT
        assert classify_failure("validation error at field path") == FailureCategory.INVALID_INPUT
        assert classify_failure("model_validate failed") == FailureCategory.INVALID_INPUT

    def test_permission_classification(self):
        assert classify_failure("permission denied") == FailureCategory.PERMISSION_DENIED
        assert classify_failure("not allowed by policy") == FailureCategory.PERMISSION_DENIED
        assert classify_failure("unauthorized access") == FailureCategory.PERMISSION_DENIED

    def test_tool_error_classification(self):
        assert classify_failure("Error: file not found") == FailureCategory.TOOL_ERROR
        assert classify_failure("Exception: division by zero") == FailureCategory.TOOL_ERROR
        assert classify_failure("failed to connect") == FailureCategory.TOOL_ERROR
        assert classify_failure("provider unavailable") == FailureCategory.TOOL_ERROR

    def test_unknown_classification(self):
        assert classify_failure("everything is fine") == FailureCategory.UNKNOWN
        assert classify_failure("") == FailureCategory.UNKNOWN


class TestToolRetry:
    """Tool retry logic tests."""

    async def test_retry_on_failure(self):
        """Tool should retry when the first attempt fails."""
        attempts = []

        class FlakyTool(Tool):
            name = "flaky"
            description = "Flaky tool"
            max_retries = 2
            retry_delay_ms = 10

            async def run(self, ctx, **inputs):
                attempts.append(1)
                if len(attempts) < 3:
                    return ToolResult(ok=False, error="not ready yet")
                return ToolResult(ok=True, output="success after retry")

        tool = FlakyTool()
        result = await tool.safe_run(ToolContext())
        assert result.ok
        assert "success after retry" in result.output
        assert len(attempts) == 3

    async def test_fails_after_max_retries(self):
        """Tool should give up after exhausting retries."""
        class AlwaysFailsTool(Tool):
            name = "bad"
            description = "Always fails"
            max_retries = 2
            retry_delay_ms = 10

            async def run(self, ctx, **inputs):
                return ToolResult(ok=False, error="persistent failure")

        tool = AlwaysFailsTool()
        result = await tool.safe_run(ToolContext())
        assert not result.ok
        assert "persistent failure" in result.error

    async def test_no_retry_on_success(self):
        """Tool should not retry if the first attempt succeeds."""
        attempts = []

        class GoodTool(Tool):
            name = "good"
            description = "Good tool"
            max_retries = 3

            async def run(self, ctx, **inputs):
                attempts.append(1)
                return ToolResult(ok=True, output="instant success")

        tool = GoodTool()
        result = await tool.safe_run(ToolContext())
        assert result.ok
        assert len(attempts) == 1

    async def test_retry_count_zero(self):
        """Tool with max_retries=0 should not retry."""
        attempts = []

        class NoRetryTool(Tool):
            name = "no_retry"
            description = "No retry"
            max_retries = 0

            async def run(self, ctx, **inputs):
                attempts.append(1)
                return ToolResult(ok=False, error="fail")

        tool = NoRetryTool()
        result = await tool.safe_run(ToolContext())
        assert not result.ok
        assert len(attempts) == 1


class TestToolTimeout:
    """Tool timeout tests."""

    async def test_timeout_returns_error(self):
        """Tool should return timeout error when execution exceeds timeout."""
        class SlowTool(Tool):
            name = "slow"
            description = "Slow tool"
            timeout_ms = 50

            async def run(self, ctx, **inputs):
                await asyncio.sleep(1.0)
                return ToolResult(ok=True, output="too late")

        tool = SlowTool()
        result = await tool.safe_run(ToolContext())
        assert not result.ok
        assert "TIMEOUT" in result.error

    async def test_no_timeout_when_set_to_zero(self):
        """Tool with timeout_ms=0 should have no timeout."""

        class PatientTool(Tool):
            name = "patient"
            description = "Patient tool"
            timeout_ms = 0

            async def run(self, ctx, **inputs):
                await asyncio.sleep(0.05)
                return ToolResult(ok=True, output="done patiently")

        tool = PatientTool()
        result = await tool.safe_run(ToolContext())
        assert result.ok

    async def test_timeout_with_retries(self):
        """Timeout should count as a failed attempt and trigger retry."""

        attempts = []

        class TimeoutThenOkTool(Tool):
            name = "timeout_then_ok"
            description = "Timeouts twice then succeeds"
            max_retries = 3
            retry_delay_ms = 10
            timeout_ms = 50

            async def run(self, ctx, **inputs):
                attempts.append(1)
                n = len(attempts)
                if n < 3:
                    await asyncio.sleep(1.0)
                return ToolResult(ok=True, output=f"attempt {n}")

        tool = TimeoutThenOkTool()
        result = await tool.safe_run(ToolContext())
        assert result.ok
        assert len(attempts) == 3


class TestToolInputValidation:
    """Tool input validation edge cases."""

    async def test_invalid_inputs(self):
        """Tool should return error for invalid inputs."""
        from pydantic import BaseModel

        class SpecTool(Tool):
            name = "spec"
            description = "Spec tool"

            class Inputs(BaseModel):
                name: str
                age: int

            async def run(self, ctx, **inputs):
                return ToolResult(ok=True, output=f"{inputs['name']} is {inputs['age']}")

        tool = SpecTool()
        result = await tool.safe_run(ToolContext(), name="Alice")  # missing age
        assert not result.ok
        assert "invalid inputs" in result.error

    async def test_classify_failure_from_safe_run(self):
        """safe_run failure should be classifiable."""
        from pydantic import BaseModel

        class FragileTool(Tool):
            name = "fragile"
            description = "Fragile tool"

            class Inputs(BaseModel):
                x: int

            async def run(self, ctx, **inputs):
                raise RuntimeError("unexpected crash")

        tool = FragileTool()
        result = await tool.safe_run(ToolContext(), x=1)
        assert not result.ok
        category = classify_failure(result.error or "")
        assert category == FailureCategory.TOOL_ERROR
