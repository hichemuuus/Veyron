"""Tests for the context manager."""

from __future__ import annotations

from paios.core.context import build_system_prompt, initial_messages, trim_history
from paios.llm.base import Message


class TestContext:
    def test_build_system_prompt_includes_tools(self):
        schemas = [
            {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "file path"},
                    },
                    "required": ["path"],
                },
            }
        ]
        prompt = build_system_prompt(schemas)
        assert "test_tool" in prompt
        assert "A test tool" in prompt
        assert "path" in prompt
        assert "required" in prompt

    def test_build_system_prompt_no_schemas(self):
        prompt = build_system_prompt([])
        assert "Available tools:" in prompt

    def test_initial_messages(self):
        schemas = [{"name": "tool1", "description": "desc1", "parameters": {"type": "object", "properties": {}}}]
        msgs = initial_messages("Hello", schemas)
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"
        assert msgs[1].content == "Hello"

    def test_initial_messages_default_tool_schemas(self):
        msgs = initial_messages("Hello")
        assert len(msgs) == 2

    def test_trim_history_under_limit(self):
        msgs = [
            Message(role="system", content="system prompt"),
            Message(role="user", content="user msg"),
            Message(role="assistant", content="assistant msg"),
        ]
        trimmed = trim_history(msgs, max_messages=10)
        assert len(trimmed) == 3

    def test_trim_history_over_limit(self):
        msgs = [
            Message(role="system", content="system prompt"),
        ]
        for i in range(30):
            msgs.append(Message(role="user" if i % 2 == 0 else "assistant", content=f"msg {i}"))

        trimmed = trim_history(msgs, max_messages=10)
        assert len(trimmed) == 10
        # System prompt should always be first.
        assert trimmed[0].role == "system"
        assert trimmed[0].content == "system prompt"

    def test_trim_history_preserves_latest(self):
        msgs = [
            Message(role="system", content="system prompt"),
            Message(role="user", content="old"),
            Message(role="assistant", content="old resp"),
            Message(role="user", content="recent"),
        ]
        trimmed = trim_history(msgs, max_messages=2)
        assert len(trimmed) == 2
        assert trimmed[0].role == "system"
        assert trimmed[1].content == "recent"
