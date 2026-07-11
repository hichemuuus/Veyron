"""Tests for the reflection engine."""

from __future__ import annotations

import json

import pytest

from paios.config import get_settings, reset_settings_cache
from paios.core.reflection import ReflectionEngine, ReflectionResult
from paios.core.tracker import ExecutionTracker


class FakeReflectionProvider:
    """LLM provider that returns a canned reflection response."""

    def __init__(self, response_text: str | None = None) -> None:
        self.response_text = response_text or json.dumps({
            "success": True,
            "mistakes": ["did not verify output encoding"],
            "improvements": ["add validation step"],
            "memories_to_store": [
                {"content": "Remember to validate encoding", "importance": 0.7, "category": "skill"},
                {"content": "Output was correct", "importance": 0.3, "category": "project"},
            ],
            "tool_issues": ["read_file truncated long lines"],
            "plan_efficiency": 0.8,
            "summary": "Task succeeded but validation was missing.",
        })

    async def generate_stream(self, messages, opts):
        class Chunk:
            def __init__(self) -> None:
                self.text = ""
                self.tool_call = None
                self.done = False

        chunk = Chunk()
        chunk.text = self.response_text
        chunk.done = True
        yield chunk


class FailingReflectionProvider:
    """LLM provider that simulates a failure."""

    async def generate_stream(self, messages, opts):
        raise RuntimeError("LLM unavailable")


@pytest.fixture(autouse=True)
def _reset_settings():
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def engine():
    provider = FakeReflectionProvider()
    return ReflectionEngine(provider=provider)


@pytest.mark.asyncio
async def test_reflect_returns_result(engine):
    result = await engine.reflect("test request", task_public_id="system")
    assert isinstance(result, ReflectionResult)
    assert result.success is True
    assert len(result.mistakes) == 1
    assert "verify" in result.mistakes[0]
    assert len(result.improvements) == 1
    assert len(result.memories_to_store) == 2
    assert len(result.tool_issues) == 1
    assert result.plan_efficiency == 0.8
    assert "validation" in result.summary


@pytest.mark.asyncio
async def test_reflect_with_bad_json(engine):
    engine.provider = FakeReflectionProvider("not valid json at all")
    result = await engine.reflect("test")
    assert isinstance(result, ReflectionResult)
    assert result.summary == "not valid json at all"
    assert result.success is True


@pytest.mark.asyncio
async def test_reflect_with_empty_response(engine):
    engine.provider = FakeReflectionProvider("")
    result = await engine.reflect("test")
    assert isinstance(result, ReflectionResult)


@pytest.mark.asyncio
async def test_reflect_llm_failure(engine):
    engine.provider = FailingReflectionProvider()
    result = await engine.reflect("test")
    assert isinstance(result, ReflectionResult)
    assert "unavailable" in result.summary


@pytest.mark.asyncio
async def test_reflect_overrides_success(engine):
    result = await engine.reflect("test", success=False, error="something broke")
    assert result.success is False


@pytest.mark.asyncio
async def test_store_reflection_memories(fresh_db, engine):
    ref = ReflectionResult(
        memories_to_store=[
            {"content": "Remember to validate encoding on output", "importance": 0.5, "category": "skill"},
            {"content": "Output was verified correct", "importance": 0.8, "category": "project"},
            {"content": "", "importance": 0.1, "category": "history"},
        ]
    )
    count = engine.store_reflection_memories(ref)
    assert count == 2

    from paios.memory.store import get_memory_store, reset_memory_store
    reset_memory_store()
    store = get_memory_store()
    memories = store.search("")
    contents = {m.content for m in memories}
    assert "Remember to validate encoding on output" in contents
    assert "Output was verified correct" in contents
    assert "" not in contents


@pytest.mark.asyncio
async def test_reflect_with_tracker_data(fresh_db, engine):
    tracker = ExecutionTracker()
    pid = "test_tracker_reflect"
    tracker.start_task(pid, "test request")
    tracker.complete_task(pid, result="done")

    engine.tracker = tracker
    result = await engine.reflect("test request", task_public_id=pid)
    assert isinstance(result, ReflectionResult)


def test_parse_reflection_empty():
    engine = ReflectionEngine()
    result = engine._parse_reflection("")
    assert isinstance(result, ReflectionResult)
    assert result.summary == ""


def test_parse_reflection_partial_json():
    engine = ReflectionEngine()
    text = 'Some text before {"success": false, "summary": "nope"} and after'
    result = engine._parse_reflection(text)
    assert result.success is False
    assert result.summary == "nope"


def test_reflection_engine_init_defaults():
    engine = ReflectionEngine()
    assert engine.provider is not None
    assert engine.tracker is not None
