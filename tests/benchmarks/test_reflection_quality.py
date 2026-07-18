"""Benchmarks for reflection quality — measures before vs after performance."""

from __future__ import annotations

import pytest
from veyron.core.reflection import ReflectionEngine, ReflectionResult
from veyron.core.tracker import ExecutionTracker


class BenchmarkReflectionProvider:
    """Simulated LLM provider for benchmark testing."""

    def __init__(self, quality: str = "good"):
        self.quality = quality
        self.responses = {
            "good": (
                '{"success": true, "mistakes": [], "improvements": ["add validation"], '
                '"memories_to_store": [], "tool_issues": [], "plan_efficiency": 0.9, '
                '"summary": "Task completed successfully.", '
                '"confidence": 0.85, "planning_quality": 0.8, '
                '"tool_selection_quality": 0.9, "parameter_quality": 0.85, '
                '"memory_usefulness": 0.7, "improvement_notes": "Consider adding early validation."}'
            ),
            "poor": (
                '{"success": false, "mistakes": ["missed context", "wrong tool"], '
                '"improvements": ["use better tools"], '
                '"memories_to_store": [], "tool_issues": ["tool_x"], "plan_efficiency": 0.3, '
                '"summary": "Task failed.", '
                '"confidence": 0.4, "planning_quality": 0.3, '
                '"tool_selection_quality": 0.2, "parameter_quality": 0.3, '
                '"memory_usefulness": 0.2, "improvement_notes": "Major retooling needed."}'
            ),
        }

    async def generate_stream(self, messages, opts):
        class Chunk:
            def __init__(self):
                self.text = ""
                self.tool_call = None
                self.done = False
        chunk = Chunk()
        chunk.text = self.responses.get(self.quality, self.responses["good"])
        chunk.done = True
        yield chunk


class TestReflectionQualityBenchmarks:

    @pytest.mark.asyncio
    async def test_reflection_quality_good(self):
        """Verify good-quality reflection produces high confidence scores."""
        engine = ReflectionEngine(provider=BenchmarkReflectionProvider("good"))
        result = await engine.reflect("test task", task_public_id="system")
        assert result.confidence >= 0.8
        assert result.planning_quality >= 0.7
        assert result.tool_selection_quality >= 0.8
        assert result.parameter_quality >= 0.7
        assert result.memory_usefulness >= 0.6
        assert result.success is True

    @pytest.mark.asyncio
    async def test_reflection_quality_poor(self):
        """Verify poor-quality reflection produces low confidence scores."""
        engine = ReflectionEngine(provider=BenchmarkReflectionProvider("poor"))
        result = await engine.reflect("test task", task_public_id="system", success=False)
        assert result.confidence <= 0.5
        assert result.planning_quality <= 0.5
        assert result.tool_selection_quality <= 0.5
        assert result.parameter_quality <= 0.5
        assert result.memory_usefulness <= 0.5
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reflection_with_tracker_data(self):
        """Benchmark reflection with tracker data produces valid results."""
        # This test needs a DB for tracker; skip if not available
        tracker = ExecutionTracker()
        pid = "bench_reflect_001"
        try:
            await tracker.start_task(pid, "benchmark task")
            await tracker.complete_task(pid, result="done")
        except Exception:
            pytest.skip("DB not available for tracker test")

        engine = ReflectionEngine(
            provider=BenchmarkReflectionProvider("good"),
            tracker=tracker,
        )
        result = await engine.reflect("benchmark task", task_public_id=pid)
        assert isinstance(result, ReflectionResult)
        assert result.summary != ""

    def test_reflection_parse_speed(self):
        """Benchmark JSON parsing speed (should be < 10ms)."""
        import time
        engine = ReflectionEngine()
        texts = [
            '{"success": true, "confidence": 0.9, "summary": "ok"}',
            '{"success": false, "mistakes": ["a", "b"], "confidence": 0.3, "summary": "fail"}',
            'not json at all',
            '',
            '{"success": true, "confidence": 0.5, "planning_quality": 0.6, "tool_selection_quality": 0.7, '
            '"parameter_quality": 0.8, "memory_usefulness": 0.9, "summary": "detailed"}',
        ]
        start = time.perf_counter()
        iterations = 100
        for _ in range(iterations):
            for text in texts:
                engine._parse_reflection(text)
        elapsed_ms = (time.perf_counter() - start) * 1000
        avg_ms = elapsed_ms / (iterations * len(texts))
        assert avg_ms < 10, f"Parse speed too slow: {avg_ms:.2f}ms avg"
