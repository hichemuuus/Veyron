"""Evaluation suite — benchmark framework for agent performance.

Runs a suite of evaluation tasks through the agent, collects metrics,
and stores results for analysis.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from paios.core.agent import Agent, AgentRunResult
from paios.core.tracker import ExecutionTracker
from paios.db.base import sync_session_scope
from paios.db.models import EvaluationMetric
from paios.memory.store import get_memory_store
from paios.tools.registry import get_registry

logger = logging.getLogger(__name__)


@dataclass
class EvalTask:
    """A single benchmark task definition."""

    id: str
    prompt: str
    expected_outcome: str = ""
    category: str = "general"
    expected_tools: list[str] = field(default_factory=list)
    min_steps: int = 1
    max_steps: int = 20


@dataclass
class EvalResult:
    """Metrics collected from a single eval run."""

    task_id: str
    category: str
    prompt: str
    success: bool
    duration_ms: int
    iterations: int
    tool_calls_count: int
    retry_count: int
    replan_count: int = 0
    memory_count: int = 0
    memory_usefulness_avg: float = 0.0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        """Short one-line summary."""
        status = "PASS" if self.success else "FAIL"
        return (
            f"[{status}] {self.task_id}: {self.iterations} iters, "
            f"{self.tool_calls_count} tools, {self.duration_ms}ms"
        )


class Evaluator:
    """Runs evaluation tasks and collects metrics.

    Usage:
        evaluator = Evaluator(agent=my_agent)
        results = await evaluator.run_suite(tasks)
        evaluator.print_report(results)
    """

    def __init__(self, agent: Agent | None = None) -> None:
        self.agent = agent or Agent()
        self.tracker = self.agent.tracker

    async def run_suite(
        self,
        tasks: list[EvalTask],
        include_memory_metrics: bool = True,
    ) -> list[EvalResult]:
        """Run a suite of eval tasks and collect metrics."""
        results: list[EvalResult] = []
        for task in tasks:
            logger.info("eval: running task '%s' (%s)", task.id, task.category)
            result = await self._run_single(task)
            if include_memory_metrics:
                self._collect_memory_metrics(result)
            results.append(result)
            self._store_result(result)
        return results

    async def _run_single(self, task: EvalTask) -> EvalResult:
        """Execute a single eval task and measure metrics."""
        pid = f"eval_{task.id}_{int(time.time())}"
        start = time.monotonic()

        agent_result: AgentRunResult | None = None
        error: str | None = None
        replan_count = 0

        try:
            agent_result = await self.agent.run(task.prompt, task_public_id=pid)
            if agent_result.error:
                error = agent_result.error
        except Exception as e:
            error = str(e)
            logger.exception("eval task '%s' raised exception", task.id)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        summary = self.tracker.get_task_summary(pid) if error is None else {}

        tool_calls_count = summary.get("tool_count", 0)
        retry_count = summary.get("retry_count", 0)
        iterations = summary.get("total_steps", 0) if agent_result is None else (agent_result.iterations or 0)

        # Estimate replan count from timeline.
        if pid != "system":
            try:
                timeline = self.tracker.get_timeline(pid, limit=200)
                replan_count = sum(
                    1
                    for s in timeline
                    if s.get("step_type") == "plan_step" and "replan" in s.get("name", "").lower()
                )
            except Exception:
                pass

        # Default to mock replan count if planner was not involved.
        if replan_count == 0 and iterations > 10:
            replan_count = 1

        success = error is None and (agent_result is None or agent_result.error is None)

        return EvalResult(
            task_id=task.id,
            category=task.category,
            prompt=task.prompt[:200],
            success=success,
            duration_ms=elapsed_ms,
            iterations=iterations,
            tool_calls_count=tool_calls_count,
            retry_count=retry_count,
            replan_count=replan_count,
            error=error,
            details={
                "public_id": pid,
                "expected_outcome": task.expected_outcome,
                "expected_tools": list(task.expected_tools),
            },
        )

    def _collect_memory_metrics(self, result: EvalResult) -> None:
        """Add memory-related metrics to an eval result."""
        try:
            store = get_memory_store()
            result.memory_count = store.count()
            memories = store.recent(limit=50)
            if memories:
                result.memory_usefulness_avg = sum(
                    m.usefulness_score for m in memories if m.usefulness_score is not None
                ) / len(memories)
        except Exception as e:
            logger.warning("memory metrics unavailable: %s", e)

    def _store_result(self, result: EvalResult) -> None:
        """Persist an eval result to the database."""
        try:
            with sync_session_scope() as session:
                metric = EvaluationMetric(
                    task_id=result.task_id,
                    category=result.category,
                    success=result.success,
                    duration_ms=result.duration_ms,
                    iterations=result.iterations,
                    tool_calls_count=result.tool_calls_count,
                    retry_count=result.retry_count,
                    replan_count=result.replan_count,
                    memory_count=result.memory_count,
                    memory_usefulness_avg=result.memory_usefulness_avg,
                    error=result.error,
                    details_json=json.dumps(result.details, default=str),
                )
                session.add(metric)
        except Exception as e:
            logger.warning("failed to store eval result: %s", e)

    @staticmethod
    def print_report(results: list[EvalResult]) -> str:
        """Format a human-readable summary of eval results."""
        if not results:
            return "No results to report."

        total = len(results)
        passed = sum(1 for r in results if r.success)
        failed = total - passed
        avg_duration = sum(r.duration_ms for r in results) / total if total > 0 else 0
        avg_iters = sum(r.iterations for r in results) / total if total > 0 else 0
        avg_tools = sum(r.tool_calls_count for r in results) / total if total > 0 else 0
        avg_retries = sum(r.retry_count for r in results) / total if total > 0 else 0

        by_category: dict[str, list[EvalResult]] = {}
        for r in results:
            by_category.setdefault(r.category, []).append(r)

        lines = [
            "=" * 60,
            "EVALUATION REPORT",
            "=" * 60,
            f"Total: {total}  Passed: {passed}  Failed: {failed}  "
            f"Pass rate: {passed / total * 100:.1f}%" if total > 0 else "N/A",
            f"Avg duration: {avg_duration:.0f}ms  Avg iterations: {avg_iters:.1f}  "
            f"Avg tool calls: {avg_tools:.1f}  Avg retries: {avg_retries:.1f}",
            "",
        ]

        for cat, cat_results in sorted(by_category.items()):
            cat_pass = sum(1 for r in cat_results if r.success)
            cat_total = len(cat_results)
            lines.append(f"  [{cat}] {cat_pass}/{cat_total} passed")
            for r in cat_results:
                lines.append(f"    {r.summary}")

        lines.append("=" * 60)
        return "\n".join(lines)

    @staticmethod
    def summary_report(results: list[EvalResult]) -> dict[str, Any]:
        """Return structured summary as a dict for API consumption."""
        total = len(results)
        if total == 0:
            return {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0}

        passed = sum(1 for r in results if r.success)
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 3),
            "avg_duration_ms": round(sum(r.duration_ms for r in results) / total, 1),
            "avg_iterations": round(sum(r.iterations for r in results) / total, 1),
            "avg_tool_calls": round(sum(r.tool_calls_count for r in results) / total, 1),
            "categories": list({r.category for r in results}),
        }
