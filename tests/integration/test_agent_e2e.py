"""End-to-end agent tests with a stub LLM provider.

Uses the StubProvider fixture from conftest.py to script deterministic
LLM responses (tool calls and final answers). Tests the full ReAct loop:
request → tool call → tool execution → result → final answer.
"""

from __future__ import annotations

import pytest

from paios.core.agent import Agent, get_agent, reset_agent
from paios.core.events import get_bus, reset_bus
from paios.db.base import init_db
from paios.llm.base import set_provider
from paios.tools.registry import get_registry, reset_registry


@pytest.fixture(autouse=True)
def _setup(fresh_db, settings_with_sandbox, sandbox_root):
    """Ensure singletons and DB are ready for each test."""
    # Create a real file in the sandbox so filesystem_read has something to find.
    file_a = sandbox_root / "hello.txt"
    file_a.write_text("Hello, world!")
    (sandbox_root / "subdir").mkdir()
    yield


class TestAgentReActLoop:
    """Integration tests for the full agent ReAct loop."""

    async def test_tool_call_then_answer(self, stub_provider):
        """Agent should: receive request → call tool → process result → emit answer."""
        provider = stub_provider([
            {"name": "filesystem_read", "arguments": {"operation": "list_dir", "path": "."}},
            "The directory contains hello.txt and subdir.",
        ])
        set_provider(provider)
        agent = get_agent()

        result = await agent.run("What's in the current directory?")

        assert result.iterations == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "filesystem_read"
        assert "hello.txt" in result.answer
        assert result.error is None
        assert result.intent is not None

    async def test_direct_answer_no_tool(self, stub_provider):
        """Agent should pass through a final answer without tool calls."""
        provider = stub_provider([
            "Hello! I'm PAIOS. How can I help you today?",
        ])
        set_provider(provider)
        agent = get_agent()

        result = await agent.run("Say hello")

        assert result.iterations == 1
        assert len(result.tool_calls) == 0
        assert "Hello" in result.answer
        assert result.error is None

    async def test_multiple_tool_calls(self, stub_provider):
        """Agent should chain multiple tool calls before answering."""
        provider = stub_provider([
            {"name": "filesystem_read", "arguments": {"operation": "stat", "path": "hello.txt"}},
            {"name": "filesystem_read", "arguments": {"operation": "read_file", "path": "hello.txt"}},
            "The file hello.txt is 13 bytes and contains 'Hello, world!'.",
        ])
        set_provider(provider)
        agent = get_agent()

        result = await agent.run("Check hello.txt")

        assert result.iterations == 3
        assert len(result.tool_calls) == 2
        assert result.error is None

    async def test_unknown_tool_returns_error(self, stub_provider):
        """Agent should handle the tool result even if the tool name is invalid."""
        provider = stub_provider([
            {"name": "nonexistent_tool", "arguments": {"foo": "bar"}},
            "The tool responded with an error.",
        ])
        set_provider(provider)
        agent = get_agent()

        result = await agent.run("Run unknown tool")

        assert result.iterations == 2
        assert len(result.tool_calls) == 1
        # The agent should still produce an answer after the error.
        assert result.error is None

    async def test_max_iterations_exhausted(self, stub_provider):
        """Agent should respect max_iterations and report exhaustion."""
        # Create a provider that keeps emitting tool calls.
        provider = stub_provider([
            {"name": "filesystem_read", "arguments": {"operation": "list_dir", "path": "."}},
        ] * 20)  # more than max iterations
        set_provider(provider)
        agent = Agent(max_iterations=3)

        result = await agent.run("Keep listing")

        assert result.iterations == 3
        assert result.error is not None
        assert "max iterations" in result.error

    async def test_events_emitted_during_run(self, stub_provider, fresh_db):
        """Agent should emit events at each stage of the loop."""
        provider = stub_provider([
            {"name": "filesystem_read", "arguments": {"operation": "stat", "path": "hello.txt"}},
            "The file exists.",
        ])
        set_provider(provider)

        bus = get_bus()
        sub_id, iterator = await bus.subscribe("system")
        agent = get_agent()

        result = await agent.run("Check hello.txt")

        assert result.error is None

        # Collect all events.
        events = []
        async for event in iterator:
            events.append(event)
            if event.type == "agent.answer":
                break

        event_types = {e.type for e in events}
        assert "task.intent" in event_types
        assert "agent.iteration" in event_types
        assert "agent.thinking" in event_types
        assert "tool.request" in event_types
        assert "tool.result" in event_types
        assert "agent.answer" in event_types

    async def test_llm_unavailable(self, stub_provider):
        """Agent should fail gracefully when LLM is unreachable."""

        class UnavailableProvider:
            name = "unavailable"

            async def is_available(self):
                return False

            async def generate_stream(self, messages, opts):
                from paios.llm.base import LLMUnavailableError
                raise LLMUnavailableError("model not reachable")
                if False:  # pragma: no cover
                    yield  # make this an async generator

            async def embed(self, text):
                return [0.0, 0.0, 0.0]

        set_provider(UnavailableProvider())
        agent = get_agent()

        result = await agent.run("Do something")

        assert result.error is not None
        assert "model not reachable" in result.error
        assert result.answer == ""

    async def test_cancellation_during_run(self, stub_provider):
        """Agent should respond to cancellation mid-execution."""
        provider = stub_provider([
            {"name": "filesystem_read", "arguments": {"operation": "list_dir", "path": "."}},
            "Final answer",
        ])
        set_provider(provider)
        agent = get_agent()

        agent.cancel("custom_task")
        result = await agent.run("Do work", task_public_id="custom_task")

        assert result.error == "cancelled"
        assert result.iterations < 2

    async def test_tracker_records_tool_calls(self, stub_provider):
        """Tracker should have entries for tool calls after a run."""
        from paios.core.tracker import ExecutionTracker

        provider = stub_provider([
            {"name": "filesystem_read", "arguments": {"operation": "list_dir", "path": "."}},
            "The directory contains hello.txt",
        ])
        set_provider(provider)
        agent = get_agent()

        result = await agent.run("What's in the current directory?", task_public_id="track_tools")

        tracker = ExecutionTracker()
        timeline = tracker.get_timeline("track_tools")
        step_types = {s["step_type"] for s in timeline}
        assert "llm_call" in step_types
        assert "tool_call" in step_types

        tool_steps = [s for s in timeline if s["step_type"] == "tool_call"]
        assert len(tool_steps) == 1
        assert tool_steps[0]["name"] == "filesystem_read"

        summary = tracker.get_task_summary("track_tools")
        assert summary["tool_count"] == 1
        assert summary["status"] == "completed"
