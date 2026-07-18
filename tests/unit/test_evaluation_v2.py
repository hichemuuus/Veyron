"""Tests for the evaluation framework (Phase 20)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from veyron.db.base import init_db, reset_sync_engine, sync_session_scope
from veyron.db.models import (
    BenchmarkResult,
    FailureAnalysisRecord,
    FailureCategory,
    RegressionRecord,
    ToolStats,
)
from veyron.evaluation.evaluator_v2 import BenchmarkRunner, BenchmarkTask, TaskMetrics, format_benchmark_results
from veyron.evaluation.failure_analysis import classify_failure, get_failure_stats, record_failure
from veyron.evaluation.regression import _aggregate_results, _REGRESSION_THRESHOLDS, detect_regressions
from veyron.evaluation.reporting import SummaryReport
from veyron.evaluation.tool_intelligence import (
    get_all_tool_stats,
    get_tool_stats,
    record_tool_execution,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db():
    reset_sync_engine()
    init_db()
    yield


@pytest.fixture
def sample_task():
    return BenchmarkTask(
        id="test_001",
        category="code_debugging",
        prompt="Find the bug in this code",
        expected_outcome="Bug found",
        expected_tools=["filesystem_read"],
        expected_complexity="simple",
        difficulty="easy",
        success_criteria="correctly identifies the bug",
    )


@pytest.fixture
def sample_task_dicts():
    return [
        {
            "id": "bench_001",
            "category": "system_diagnostics",
            "prompt": "Show system health",
            "expected_outcome": "CPU and memory stats",
            "expected_tools": ["system_monitor"],
            "expected_complexity": "simple",
            "difficulty": "easy",
            "success_criteria": "calls system monitor",
        },
        {
            "id": "bench_002",
            "category": "file_management",
            "prompt": "List the files in backend/veyron/core/",
            "expected_outcome": "Directory listing",
            "expected_tools": ["filesystem_read"],
            "expected_complexity": "simple",
            "difficulty": "easy",
            "success_criteria": "lists directory",
        },
    ]


# ---------------------------------------------------------------------------
# BenchmarkTask
# ---------------------------------------------------------------------------


class TestBenchmarkTask:
    def test_from_dict(self, sample_task_dicts):
        task = BenchmarkTask.from_dict(sample_task_dicts[0])
        assert task.id == "bench_001"
        assert task.category == "system_diagnostics"
        assert task.expected_tools == ["system_monitor"]
        assert task.difficulty == "easy"
        assert task.expected_complexity == "simple"

    def test_from_dict_defaults(self):
        task = BenchmarkTask.from_dict({"id": "test", "prompt": "hello"})
        assert task.category == "general"
        assert task.expected_tools == []
        assert task.difficulty == "medium"

    def test_default_values(self):
        task = BenchmarkTask(id="t1", category="general", prompt="hello")
        assert task.expected_outcome == ""
        assert task.expected_tools == []
        assert task.min_steps == 1
        assert task.max_steps == 20


# ---------------------------------------------------------------------------
# TaskMetrics
# ---------------------------------------------------------------------------


class TestTaskMetrics:
    def test_defaults(self):
        m = TaskMetrics(task_id="t1", category="test", prompt="hello")
        assert m.success is False
        assert m.clarification_used is False
        assert m.hallucination_detected is False
        assert m.plan_length == 0
        assert m.total_latency_ms == 0


# ---------------------------------------------------------------------------
# format_benchmark_results
# ---------------------------------------------------------------------------


class TestFormatBenchmarkResults:
    def test_empty(self):
        result = format_benchmark_results([])
        assert "error" in result

    def test_single_result(self):
        metrics = [
            TaskMetrics(
                task_id="t1", category="general", prompt="hello",
                success=True, total_latency_ms=100,
            )
        ]
        result = format_benchmark_results(metrics)
        assert result["summary"]["total"] == 1
        assert result["summary"]["passed"] == 1
        assert result["summary"]["pass_rate"] == 1.0

    def test_mixed_results(self):
        metrics = [
            TaskMetrics(task_id="t1", category="code", prompt="a", success=True),
            TaskMetrics(task_id="t2", category="code", prompt="b", success=False),
            TaskMetrics(task_id="t3", category="sys", prompt="c", success=True),
        ]
        result = format_benchmark_results(metrics)
        assert result["summary"]["total"] == 3
        assert result["summary"]["passed"] == 2
        assert result["summary"]["pass_rate"] == pytest.approx(0.667, abs=0.01)
        assert "code" in result["categories"]
        assert "sys" in result["categories"]

    def test_clarification_and_hallucination(self):
        metrics = [
            TaskMetrics(task_id="t1", category="g", prompt="a", success=True, clarification_used=True),
            TaskMetrics(task_id="t2", category="g", prompt="b", success=True, hallucination_detected=True),
        ]
        result = format_benchmark_results(metrics)
        assert result["summary"]["clarification_rate"] == 0.5
        assert result["summary"]["hallucination_rate"] == 0.5


# ---------------------------------------------------------------------------
# SummaryReport
# ---------------------------------------------------------------------------


class TestSummaryReport:
    def test_to_dict(self):
        metrics = [
            TaskMetrics(task_id="t1", category="g", prompt="a", success=True),
        ]
        report = SummaryReport(metrics, run_id="test_run")
        d = report.to_dict()
        assert d["run_id"] == "test_run"
        assert "summary" in d
        assert d["summary"]["total"] == 1

    def test_to_markdown_contains_headers(self):
        metrics = [
            TaskMetrics(task_id="t1", category="g", prompt="a", success=True),
        ]
        report = SummaryReport(metrics)
        md = report.to_markdown()
        assert "Benchmark Report" in md
        assert "Overall Score" in md
        assert "Planner Quality" in md
        assert "Memory Quality" in md
        assert "Tool Accuracy" in md
        assert "Latency Analysis" in md
        assert "Failure Breakdown" in md
        assert "Category Scores" in md
        assert "Tool Statistics" in md


# ---------------------------------------------------------------------------
# Failure Analysis
# ---------------------------------------------------------------------------


class TestFailureAnalysis:
    def test_classify_timeout(self):
        assert classify_failure("command timed out after 30s") == FailureCategory.TIMEOUT

    def test_classify_tool_error(self):
        assert classify_failure("Tool returned error: something failed") == FailureCategory.TOOL_FAILURE

    def test_classify_permission_denied(self):
        assert classify_failure("Permission denied: access not allowed") == FailureCategory.PERMISSION_DENIED

    def test_classify_invalid_input(self):
        assert classify_failure("Validation error: invalid input detected") == FailureCategory.INVALID_INPUT

    def test_classify_memory_failure(self):
        assert classify_failure("Memory retrieval failed: embedding not found") == FailureCategory.MEMORY_FAILURE

    def test_classify_planner_failure(self):
        assert classify_failure("Planner step decomposition failed") == FailureCategory.PLANNER_FAILURE

    def test_classify_llm_issue(self):
        assert classify_failure("LLM provider returned 503") == FailureCategory.LLM_ISSUE

    def test_classify_hallucination(self):
        assert classify_failure("The model hallucinated incorrect data") == FailureCategory.HALLUCINATION

    def test_classify_environment(self):
        assert classify_failure("ImportError: no module named foo") == FailureCategory.ENVIRONMENT_ISSUE

    def test_classify_unknown(self):
        assert classify_failure("Something completely unexpected happened") == FailureCategory.UNKNOWN

    def test_record_and_retrieve(self):
        pid = record_failure(
            task_public_id="test_task",
            failure_category="timeout",
            error_message="timed out",
            tool_name="terminal",
            recovered=True,
            repair_strategy="retry",
        )
        assert pid
        stats = get_failure_stats()
        assert stats["total"] > 0
        assert stats["by_category"].get("timeout", 0) > 0
        assert stats["recovery_rate"] > 0


# ---------------------------------------------------------------------------
# Tool Intelligence
# ---------------------------------------------------------------------------


class TestToolIntelligence:
    def test_record_and_retrieve(self):
        record_tool_execution("test_tool", ok=True, duration_ms=100, error=None)
        record_tool_execution("test_tool", ok=True, duration_ms=200, error=None)
        record_tool_execution("test_tool", ok=False, duration_ms=50, error="timed out")

        stats = get_tool_stats("test_tool")
        assert stats is not None
        assert stats.total_executions == 3
        assert stats.success_count == 2
        assert stats.failure_count == 1
        assert stats.total_latency_ms == 350
        assert stats.avg_latency_ms == pytest.approx(116.67, abs=1)
        assert stats.success_rate == pytest.approx(0.667, abs=0.01)
        assert stats.reliability_score > 0

    def test_get_all(self):
        record_tool_execution("tool_a", ok=True, duration_ms=100)
        record_tool_execution("tool_b", ok=False, duration_ms=50, error="error")
        all_stats = get_all_tool_stats()
        names = {s["tool_name"] for s in all_stats}
        assert "tool_a" in names
        assert "tool_b" in names

    def test_common_failures_tracked(self):
        record_tool_execution("failing_tool", ok=False, duration_ms=10, error="timeout")
        record_tool_execution("failing_tool", ok=False, duration_ms=10, error="timeout")
        record_tool_execution("failing_tool", ok=False, duration_ms=10, error="permission denied")

        stats = get_tool_stats("failing_tool")
        assert stats is not None
        failures = json.loads(stats.common_failures) if stats.common_failures else []
        assert len(failures) == 2
        timeout_entry = next(f for f in failures if f["reason"] == "timeout")
        assert timeout_entry["count"] == 2


# ---------------------------------------------------------------------------
# Regression Detection
# ---------------------------------------------------------------------------


class TestRegressionDetection:
    @pytest.mark.asyncio
    async def test_detect_no_baseline(self):
        regressions = detect_regressions(current_run_id="run_1")
        assert regressions == []

    def test_aggregate_results_empty(self):
        assert _aggregate_results([]) == {}

    def test_aggregate_results(self):
        from datetime import datetime
        from veyron.evaluation.evaluator_v2 import TaskMetrics

        result = TaskMetrics(task_id="t1", category="g", prompt="a", success=True, plan_length=5)
        result2 = TaskMetrics(task_id="t2", category="g", prompt="b", success=False, plan_length=3)
        import json

        r1 = BenchmarkResult(
            task_id="t1", category="g", prompt="a", success=True,
            plan_length=5, run_id="r1",
            expected_tools="[]", tools_selected="[]",
            public_id="p1",
        )
        r2 = BenchmarkResult(
            task_id="t2", category="g", prompt="b", success=False,
            plan_length=3, run_id="r1",
            expected_tools="[]", tools_selected="[]",
            public_id="p2",
        )
        with sync_session_scope() as session:
            session.add(r1)
            session.add(r2)

        agg = _aggregate_results([r1, r2])
        assert "success_rate" in agg
        assert agg["success_rate"] == 0.5
        assert agg["plan_length"] == 4.0

    def test_thresholds_defined(self):
        assert "success_rate" in _REGRESSION_THRESHOLDS
        assert "plan_length" in _REGRESSION_THRESHOLDS
        assert "dependency_correctness" in _REGRESSION_THRESHOLDS
        assert "memory_precision" in _REGRESSION_THRESHOLDS
        assert "memory_recall" in _REGRESSION_THRESHOLDS
        assert "tool_success_rate" in _REGRESSION_THRESHOLDS
        assert "total_latency_ms" in _REGRESSION_THRESHOLDS


# ---------------------------------------------------------------------------
# BenchmarkRunner (unit level)
# ---------------------------------------------------------------------------


class TestBenchmarkRunner:
    @pytest.mark.asyncio
    async def test_run_suite_handles_no_agent(self):
        runner = BenchmarkRunner()
        tasks = [
            BenchmarkTask(id="t1", category="general", prompt="hello"),
        ]
        with patch.object(runner.agent, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                answer="Hi there!",
                iterations=1,
                error=None,
                tool_calls=[],
                needs_clarification=False,
                clarification_question="",
            )
            with patch.object(runner.tracker, "get_timeline") as mock_timeline:
                mock_timeline.return_value = []
                with patch.object(runner.tracker, "get_task_summary", new_callable=AsyncMock) as mock_summary:
                    mock_summary.return_value = {}
                    results = await runner.run_suite(tasks, max_concurrency=1)
                    assert len(results) == 1
                    assert results[0].success is True
                    assert results[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_run_suite_handles_agent_error(self):
        runner = BenchmarkRunner()
        tasks = [BenchmarkTask(id="t1", category="general", prompt="hello")]
        with patch.object(runner.agent, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                answer="", iterations=0, error="something broke",
                tool_calls=[], needs_clarification=False,
                clarification_question="",
            )
            with patch.object(runner.tracker, "get_timeline") as mock_timeline:
                mock_timeline.return_value = []
                with patch.object(runner.tracker, "get_task_summary", new_callable=AsyncMock) as mock_summary:
                    mock_summary.return_value = {}
                    results = await runner.run_suite(tasks, max_concurrency=1)
                    assert len(results) == 1
                    assert results[0].success is False
                    assert results[0].error_message == "something broke"

    @pytest.mark.asyncio
    async def test_run_suite_handles_exception(self):
        runner = BenchmarkRunner()
        tasks = [BenchmarkTask(id="t1", category="general", prompt="hello")]
        with patch.object(runner.agent, "run", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("crash")
            with patch.object(runner.tracker, "get_timeline") as mock_timeline:
                mock_timeline.return_value = []
                with patch.object(runner.tracker, "get_task_summary", new_callable=AsyncMock) as mock_summary:
                    mock_summary.return_value = {}
                    results = await runner.run_suite(tasks, max_concurrency=1)
                    assert len(results) == 1
                    assert results[0].success is False
                    assert "crash" in (results[0].error_message or "")

    @pytest.mark.asyncio
    async def test_captures_clarification(self):
        runner = BenchmarkRunner()
        tasks = [BenchmarkTask(id="t1", category="general", prompt="what?")]
        with patch.object(runner.agent, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                answer="Could you clarify?",
                iterations=1,
                error=None,
                tool_calls=[],
                needs_clarification=True,
                clarification_question="Could you clarify?",
            )
            with patch.object(runner.tracker, "get_timeline") as mock_timeline:
                mock_timeline.return_value = []
                with patch.object(runner.tracker, "get_task_summary", new_callable=AsyncMock) as mock_summary:
                    mock_summary.return_value = {}
                    results = await runner.run_suite(tasks, max_concurrency=1)
                    assert results[0].clarification_used is True
                    assert results[0].completion_status == "clarified"

    @pytest.mark.asyncio
    async def test_captures_hallucination(self):
        runner = BenchmarkRunner()
        tasks = [BenchmarkTask(id="t1", category="general", prompt="hello")]
        with patch.object(runner.agent, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                answer="As an AI, I don't have access to that information.",
                iterations=1, error=None,
                tool_calls=[], needs_clarification=False,
                clarification_question="",
            )
            with patch.object(runner.tracker, "get_timeline") as mock_timeline:
                mock_timeline.return_value = []
                with patch.object(runner.tracker, "get_task_summary", new_callable=AsyncMock) as mock_summary:
                    mock_summary.return_value = {}
                    results = await runner.run_suite(tasks, max_concurrency=1, detect_hallucinations=True)
                    assert results[0].hallucination_detected is True

    def test_format_benchmark_results_includes_all_keys(self):
        metrics = [
            TaskMetrics(task_id="t1", category="sys", prompt="health", success=True),
        ]
        result = format_benchmark_results(metrics)
        assert "summary" in result
        assert "planner" in result
        assert "memory" in result
        assert "tools" in result
        assert "latency" in result
        assert "failures" in result
        assert "categories" in result
        assert "tool_stats" in result
        assert "failure_stats" in result

    def test_benchmark_task_from_dict_full(self):
        d = {
            "id": "full_test",
            "category": "code_generation",
            "prompt": "Write a function",
            "expected_outcome": "Working function",
            "expected_tools": ["terminal"],
            "expected_complexity": "complex",
            "difficulty": "hard",
            "success_criteria": "compiles",
            "min_steps": 2,
            "max_steps": 15,
        }
        task = BenchmarkTask.from_dict(d)
        assert task.id == "full_test"
        assert task.expected_complexity == "complex"
        assert task.difficulty == "hard"
        assert task.min_steps == 2
        assert task.max_steps == 15

    def test_detect_regressions_stores_records(self):
        from datetime import datetime
        from uuid import uuid4

        run_id = "test_run_" + uuid4().hex[:8]
        r1 = BenchmarkResult(
            task_id="t1", category="g", prompt="a", success=True,
            plan_length=5, run_id=run_id,
            expected_tools="[]", tools_selected="[]",
            public_id=uuid4().hex,
        )
        r2 = BenchmarkResult(
            task_id="t2", category="g", prompt="b", success=False,
            plan_length=3, run_id=run_id,
            expected_tools="[]", tools_selected="[]",
            public_id=uuid4().hex,
        )
        with sync_session_scope() as session:
            session.add(r1)
            session.add(r2)

        regressions = detect_regressions(current_run_id=run_id, baseline_run_id=run_id)
        assert regressions == []  # same run = no regression


# ---------------------------------------------------------------------------
# JSON Round-trip
# ---------------------------------------------------------------------------


def test_benchmark_task_json_roundtrip():
    d = {
        "id": "roundtrip_test",
        "category": "general",
        "prompt": "Say hello",
        "expected_outcome": "Hello",
        "expected_tools": [],
    }
    task = BenchmarkTask.from_dict(d)
    assert task.id == "roundtrip_test"
    assert task.prompt == "Say hello"
