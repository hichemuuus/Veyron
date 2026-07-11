"""Tests for the evaluation suite."""

from __future__ import annotations

import json

import pytest

from paios.core.evaluator import EvalResult, EvalTask, Evaluator
from paios.db.models import EvaluationMetric


class TestEvalTask:
    def test_defaults(self):
        task = EvalTask(id="test_1", prompt="Do something")
        assert task.category == "general"
        assert task.expected_outcome == ""
        assert task.expected_tools == []
        assert task.min_steps == 1
        assert task.max_steps == 20

    def test_full_init(self):
        task = EvalTask(
            id="t1",
            prompt="Check CPU",
            expected_outcome="CPU usage shown",
            category="system",
            expected_tools=["system_monitor"],
            min_steps=1,
            max_steps=5,
        )
        assert task.id == "t1"
        assert task.category == "system"


class TestEvalResult:
    def test_defaults(self):
        r = EvalResult(
            task_id="t1", category="general", prompt="test", success=True, duration_ms=100,
            iterations=2, tool_calls_count=1, retry_count=0,
        )
        assert r.memory_count == 0
        assert r.memory_usefulness_avg == 0.0
        assert r.error is None
        assert r.replan_count == 0

    def test_summary_pass(self):
        r = EvalResult(
            task_id="check_cpu", category="sys", prompt="", success=True,
            duration_ms=500, iterations=3, tool_calls_count=2, retry_count=0,
        )
        s = r.summary
        assert "[PASS]" in s
        assert "check_cpu" in s
        assert "500ms" in s

    def test_summary_fail(self):
        r = EvalResult(
            task_id="bad_task", category="gen", prompt="", success=False,
            duration_ms=100, iterations=0, tool_calls_count=0, retry_count=0,
            error="timeout",
        )
        s = r.summary
        assert "[FAIL]" in s
        assert "bad_task" in s


class FakeEvalAgent:
    """A deterministic fake agent for evaluator tests."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.tracker = _FakeTracker()

    async def run(self, prompt: str, task_public_id: str = "system"):
        from paios.core.agent import AgentRunResult

        if self.fail:
            return AgentRunResult(answer="", iterations=1, error="simulated failure")
        return AgentRunResult(answer="done", iterations=3, tool_calls=[{"name": "test_tool", "arguments": {}}])


class _FakeTracker:
    """Minimal tracker stub."""

    def get_task_summary(self, pid: str) -> dict:
        return {"tool_count": 2, "retry_count": 1, "total_steps": 3}

    def get_timeline(self, pid: str, limit: int = 100) -> list[dict]:
        return [
            {"step_type": "plan_step", "name": "replan_1"},
            {"step_type": "tool_call", "name": "system_monitor"},
        ]


class TestEvaluator:
    @pytest.mark.asyncio
    async def test_run_single_success(self):
        evaluator = Evaluator(agent=FakeEvalAgent())
        task = EvalTask(id="simple", prompt="Do a simple thing")
        result = await evaluator._run_single(task)
        assert result.task_id == "simple"
        assert result.success is True
        assert result.iterations == 3
        assert result.tool_calls_count == 2
        assert result.retry_count == 1

    @pytest.mark.asyncio
    async def test_run_single_failure(self):
        evaluator = Evaluator(agent=FakeEvalAgent(fail=True))
        task = EvalTask(id="failing", prompt="This will fail")
        result = await evaluator._run_single(task)
        assert result.task_id == "failing"
        assert result.success is False
        assert result.error == "simulated failure"

    @pytest.mark.asyncio
    async def test_run_single_exception(self):
        class ExplodingAgent:
            def __init__(self):
                self.tracker = _FakeTracker()

            async def run(self, prompt, task_public_id="system"):
                raise RuntimeError("explosion")

        evaluator = Evaluator(agent=ExplodingAgent())
        task = EvalTask(id="explode", prompt="boom")
        result = await evaluator._run_single(task)
        assert result.success is False
        assert "explosion" in (result.error or "")

    @pytest.mark.asyncio
    async def test_run_suite_collects_results(self):
        evaluator = Evaluator(agent=FakeEvalAgent())
        tasks = [
            EvalTask(id="a", prompt="Do A"),
            EvalTask(id="b", prompt="Do B"),
        ]
        results = await evaluator.run_suite(tasks, include_memory_metrics=False)
        assert len(results) == 2
        assert all(r.success for r in results)
        assert [r.task_id for r in results] == ["a", "b"]

    def test_print_report_empty(self):
        report = Evaluator.print_report([])
        assert "No results" in report

    def test_print_report_with_results(self):
        results = [
            EvalResult(
                task_id="t1", category="sys", prompt="", success=True,
                duration_ms=100, iterations=2, tool_calls_count=1, retry_count=0,
            ),
            EvalResult(
                task_id="t2", category="gen", prompt="", success=False,
                duration_ms=200, iterations=0, tool_calls_count=0, retry_count=1,
                error="fail",
            ),
        ]
        report = Evaluator.print_report(results)
        assert "EVALUATION REPORT" in report
        assert "[PASS]" in report
        assert "[FAIL]" in report
        assert "50.0%" in report

    def test_summary_report(self):
        results = [
            EvalResult(
                task_id="t1", category="sys", prompt="", success=True,
                duration_ms=100, iterations=2, tool_calls_count=1, retry_count=0,
            ),
            EvalResult(
                task_id="t2", category="gen", prompt="", success=False,
                duration_ms=200, iterations=0, tool_calls_count=0, retry_count=0,
                error="err",
            ),
        ]
        summ = Evaluator.summary_report(results)
        assert summ["total"] == 2
        assert summ["passed"] == 1
        assert summ["failed"] == 1
        assert 0.4 <= summ["pass_rate"] <= 0.6

    def test_summary_report_empty(self):
        summ = Evaluator.summary_report([])
        assert summ["total"] == 0

    @pytest.mark.asyncio
    async def test_store_result_persists_to_db(self, fresh_db):
        evaluator = Evaluator(agent=FakeEvalAgent())
        result = EvalResult(
            task_id="db_test", category="test", prompt="store me", success=True,
            duration_ms=300, iterations=2, tool_calls_count=1, retry_count=0,
        )
        evaluator._store_result(result)

        from paios.db.base import sync_session_scope
        with sync_session_scope() as session:
            stored = session.query(EvaluationMetric).filter(EvaluationMetric.task_id == "db_test").first()
            assert stored is not None
            assert stored.success is True
            assert stored.duration_ms == 300
            assert stored.iterations == 2
            assert stored.category == "test"

    @pytest.mark.asyncio
    async def test_run_suite_with_db_storage(self, fresh_db):
        evaluator = Evaluator(agent=FakeEvalAgent())
        tasks = [
            EvalTask(id="stored1", prompt="Task 1"),
            EvalTask(id="stored2", prompt="Task 2"),
        ]
        results = await evaluator.run_suite(tasks, include_memory_metrics=False)
        assert len(results) == 2

        from paios.db.base import sync_session_scope
        with sync_session_scope() as session:
            count = session.query(EvaluationMetric).count()
            assert count == 2

    def test_evalresult_summary_no_replan(self):
        r = EvalResult(
            task_id="no_plan", category="gen", prompt="", success=True,
            duration_ms=50, iterations=1, tool_calls_count=0, retry_count=0,
        )
        assert r.replan_count == 0
        assert "[PASS]" in r.summary
