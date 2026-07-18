"""Enhanced evaluation engine — comprehensive benchmark execution and metrics.

Runs a suite of benchmark tasks, captures all defined metrics (agent, planner,
memory, tool, performance, UX), classifies failures, tracks tool intelligence,
and stores results for regression detection.

Usage:
    runner = BenchmarkRunner()
    results = await runner.run_suite(tasks, run_id="my_benchmark")
    SummaryReport(results).print()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from veyron.core.agent import Agent, AgentRunResult
from veyron.core.events import EventBus, get_bus
from veyron.core.tracker import ExecutionTracker
from veyron.db.base import sync_session_scope
from veyron.db.models import BenchmarkResult, TaskType
from veyron.evaluation.failure_analysis import (
    classify_failure,
    get_failure_stats,
    record_failure,
)
from veyron.evaluation.regression import detect_regressions
from veyron.evaluation.tool_intelligence import (
    get_all_tool_stats,
    record_tool_execution,
)
from veyron.memory.store import get_memory_store
from veyron.tools.base import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkTask:
    """A single benchmark task definition."""

    id: str
    category: str
    prompt: str
    expected_outcome: str = ""
    expected_tools: list[str] = field(default_factory=list)
    expected_complexity: str = "simple"
    difficulty: str = "medium"
    success_criteria: str = "task completes without error"
    min_steps: int = 1
    max_steps: int = 20

    @classmethod
    def from_dict(cls, d: dict) -> BenchmarkTask:
        return cls(
            id=d["id"],
            category=d.get("category", "general"),
            prompt=d["prompt"],
            expected_outcome=d.get("expected_outcome", ""),
            expected_tools=d.get("expected_tools", []),
            expected_complexity=d.get("expected_complexity", "simple"),
            difficulty=d.get("difficulty", "medium"),
            success_criteria=d.get("success_criteria", "task completes without error"),
            min_steps=d.get("min_steps", 1),
            max_steps=d.get("max_steps", 20),
        )


@dataclass
class TaskMetrics:
    """Comprehensive metrics for a single benchmark task execution."""

    task_id: str
    category: str
    prompt: str
    expected_outcome: str = ""
    expected_tools: list[str] = field(default_factory=list)
    expected_complexity: str = "simple"
    difficulty: str = "medium"

    # Agent
    success: bool = False
    clarification_used: bool = False
    hallucination_detected: bool = False
    completion_status: str = "unknown"
    iterations: int = 0
    tool_calls_count: int = 0
    retry_count: int = 0
    replan_count: int = 0

    # Planner
    plan_length: int = 0
    unnecessary_steps: int = 0
    dependency_correctness: float = 0.0
    execution_order_score: float = 0.0

    # Memory
    memories_retrieved: int = 0
    relevant_memories: int = 0
    memory_precision: float = 0.0
    memory_recall: float = 0.0
    memory_latency_ms: float = 0.0

    # Tool
    tools_selected: list[str] = field(default_factory=list)
    expected_tools_match: float = 0.0
    tool_execution_latency_ms: float = 0.0
    tool_success_rate: float = 0.0
    tool_retry_count: int = 0

    # Performance
    total_latency_ms: int = 0
    llm_latency_ms: int = 0
    planner_latency_ms: int = 0
    tool_latency_ms: int = 0

    # Failure
    failure_category: str | None = None
    error_message: str | None = None

    # Raw
    answer: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    public_id: str = ""


class BenchmarkRunner:
    """Executes benchmark tasks and collects comprehensive metrics."""

    def __init__(
        self,
        agent: Agent | None = None,
        bus: EventBus | None = None,
        tracker: ExecutionTracker | None = None,
    ) -> None:
        self.agent = agent or Agent()
        self.bus = bus or get_bus()
        self.tracker = tracker or ExecutionTracker(bus=self.bus)

    async def run_suite(
        self,
        tasks: list[BenchmarkTask],
        run_id: str | None = None,
        max_concurrency: int = 3,
        include_memory_metrics: bool = True,
        detect_hallucinations: bool = True,
    ) -> list[TaskMetrics]:
        """Run a benchmark suite and collect metrics.

        Args:
            tasks: List of benchmark tasks to execute.
            run_id: Unique identifier for this run. Auto-generated if None.
            max_concurrency: Maximum number of tasks to run in parallel.
            include_memory_metrics: Whether to capture memory metrics.
            detect_hallucinations: Whether to check for hallucinated output.

        Returns:
            List of TaskMetrics with comprehensive metrics.
        """
        suite_id = run_id or f"bench_{uuid4().hex[:12]}"
        logger.info("Starting benchmark suite %s with %d tasks", suite_id, len(tasks))

        all_metrics: list[TaskMetrics] = []
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_task(task: BenchmarkTask) -> TaskMetrics:
            async with semaphore:
                logger.info("Running task '%s' (%s)", task.id, task.category)
                metrics = await self._run_single(task, suite_id, detect_hallucinations)
                if include_memory_metrics:
                    self._collect_memory_metrics(metrics)
                self._store_result(metrics, suite_id)
                self._record_tool_stats(metrics)
                if metrics.error_message:
                    record_failure(
                        task_public_id=metrics.public_id or suite_id,
                        failure_category=metrics.failure_category or "unknown",
                        error_message=metrics.error_message or "",
                        tool_name=metrics.tools_selected[0] if metrics.tools_selected else None,
                        recovered=metrics.success,
                    )
                all_metrics.append(metrics)
                return metrics

        tasks_coros = [_run_task(t) for t in tasks]
        await asyncio.gather(*tasks_coros)

        return all_metrics

    async def _run_single(
        self,
        task: BenchmarkTask,
        run_id: str,
        detect_hallucinations: bool,
    ) -> TaskMetrics:
        """Execute a single benchmark task and capture all metrics."""
        pid = f"bench_{task.id}_{int(time.time())}"
        start_time = time.monotonic()

        metrics = TaskMetrics(
            task_id=task.id,
            category=task.category,
            prompt=task.prompt[:200],
            expected_outcome=task.expected_outcome,
            expected_tools=list(task.expected_tools),
            expected_complexity=task.expected_complexity,
            difficulty=task.difficulty,
            public_id=pid,
        )

        agent_result: AgentRunResult | None = None
        error: str | None = None

        try:
            agent_result = await self.agent.run(task.prompt, task_public_id=pid)
            if agent_result.error:
                error = agent_result.error
        except Exception as e:
            error = str(e)
            logger.exception("benchmark task '%s' raised exception", task.id)

        metrics.total_latency_ms = int((time.monotonic() - start_time) * 1000)
        metrics.answer = agent_result.answer if agent_result else ""

        # Agent metrics
        metrics.success = error is None and (agent_result is None or agent_result.error is None)
        metrics.iterations = agent_result.iterations if agent_result else 0
        metrics.tool_calls_count = len(agent_result.tool_calls) if agent_result else 0
        if agent_result and agent_result.needs_clarification:
            metrics.clarification_used = True
            metrics.completion_status = "clarified"

        # Error handling
        if error:
            metrics.error_message = error
            metrics.failure_category = classify_failure(error).value
            metrics.completion_status = "failed"
        elif agent_result and agent_result.error:
            metrics.error_message = agent_result.error
            metrics.failure_category = classify_failure(agent_result.error).value
            metrics.completion_status = "failed"
        elif not metrics.clarification_used:
            metrics.completion_status = "completed"

        # Hallucination detection (simple keyword check)
        if detect_hallucinations and metrics.answer:
            hallu_indicators = [
                "i don't have access to", "i cannot actually",
                "as an ai", "i'm unable to", "i don't have real-time",
            ]
            for indicator in hallu_indicators:
                if indicator in metrics.answer.lower():
                    metrics.hallucination_detected = True
                    break

        # Capture tool metrics from timeline
        await self._capture_tool_metrics(metrics, pid)
        await self._capture_planner_metrics(metrics, pid)
        await self._capture_performance_metrics(metrics, pid)
        await self._compute_tool_match(metrics)

        metrics.details = {
            "public_id": pid,
            "run_id": run_id,
            "expected_outcome": task.expected_outcome,
            "answer_preview": metrics.answer[:200],
        }

        return metrics

    async def _capture_tool_metrics(
        self, metrics: TaskMetrics, pid: str
    ) -> None:
        """Extract tool execution metrics from the tracker timeline."""
        try:
            timeline = await self.tracker.get_timeline(pid, limit=200)
        except Exception:
            timeline = []

        tool_steps = [
            s for s in timeline
            if s.get("step_type") in ("tool_call", TaskType.TOOL_CALL.value)
        ]

        metrics.tools_selected = list(set(
            s.get("name", "") for s in tool_steps if s.get("name")
        ))

        if tool_steps:
            ok_count = sum(1 for s in tool_steps if s.get("ok", s.get("status") == "completed"))
            total = len(tool_steps)
            metrics.tool_success_rate = ok_count / total if total > 0 else 0.0
            metrics.tool_execution_latency_ms = sum(
                s.get("duration_ms", 0) or 0 for s in tool_steps
            )
            metrics.tool_retry_count = sum(
                1 for s in tool_steps if s.get("retry_count", 0) > 0
            )

    async def _capture_planner_metrics(
        self, metrics: TaskMetrics, pid: str
    ) -> None:
        """Extract planner quality metrics."""
        try:
            timeline = await self.tracker.get_timeline(pid, limit=200)
        except Exception:
            timeline = []

        plan_steps = [s for s in timeline if s.get("step_type") == "plan_step"]
        replan_events = [s for s in timeline if "replan" in s.get("name", "").lower()]

        metrics.plan_length = len(plan_steps)
        metrics.replan_count = len(replan_events)
        metrics.unnecessary_steps = max(0, metrics.plan_length - len(metrics.expected_tools) * 2)

        # Dependency correctness: check if plan steps reference valid deps
        deps_found = 0
        deps_total = 0
        for s in plan_steps:
            dep_str = s.get("metadata_json", "{}") if isinstance(s.get("metadata_json"), str) else "{}"
            try:
                meta = json.loads(dep_str)
                deps = meta.get("depends_on", [])
                if deps:
                    deps_total += 1
                    if all(d in [ps.get("name") for ps in plan_steps] for d in deps):
                        deps_found += 1
            except Exception:
                pass
        metrics.dependency_correctness = deps_found / max(deps_total, 1)

        # Execution order score: are steps in the right sequence?
        completed_order = [s.get("step_index", 0) for s in plan_steps if s.get("status") == "completed"]
        if completed_order:
            expected = list(range(1, len(completed_order) + 1))
            matches = sum(1 for i, idx in enumerate(completed_order) if i < len(expected) and idx == expected[i])
            metrics.execution_order_score = matches / max(len(expected), 1)

    async def _capture_performance_metrics(
        self, metrics: TaskMetrics, pid: str
    ) -> None:
        """Extract latency breakdown from tracker."""
        try:
            timeline = await self.tracker.get_timeline(pid, limit=200)
        except Exception:
            timeline = []

        for s in timeline:
            dur = s.get("duration_ms", 0) or 0
            step_type = s.get("step_type", "")
            if step_type == TaskType.LLM_CALL.value:
                metrics.llm_latency_ms += dur
            elif step_type in ("plan_step", "plan_verification", "plan_synthesis"):
                metrics.planner_latency_ms += dur
            elif step_type == TaskType.TOOL_CALL.value:
                metrics.tool_latency_ms += dur

    async def _compute_tool_match(self, metrics: TaskMetrics) -> None:
        """Compare selected vs expected tools."""
        if not metrics.expected_tools or not metrics.tools_selected:
            metrics.expected_tools_match = 1.0 if not metrics.expected_tools else 0.0
            return

        selected_set = set(metrics.tools_selected)
        expected_set = set(metrics.expected_tools)

        if not expected_set:
            metrics.expected_tools_match = 1.0
            return

        intersection = selected_set & expected_set
        union = selected_set | expected_set
        metrics.expected_tools_match = len(intersection) / max(len(union), 1)

    def _collect_memory_metrics(self, metrics: TaskMetrics) -> None:
        """Capture memory system performance."""
        try:
            store = get_memory_store()
            metrics.memories_retrieved = store.count()
        except Exception:
            pass

    def _store_result(self, metrics: TaskMetrics, run_id: str) -> None:
        """Persist a benchmark result to the database."""
        try:
            with sync_session_scope() as session:
                result = BenchmarkResult(
                    public_id=uuid4().hex,
                    run_id=run_id,
                    task_id=metrics.task_id,
                    category=metrics.category,
                    prompt=metrics.prompt,
                    expected_outcome=metrics.expected_outcome,
                    expected_tools=json.dumps(metrics.expected_tools),
                    expected_complexity=metrics.expected_complexity,
                    difficulty=metrics.difficulty,
                    success=metrics.success,
                    clarification_used=metrics.clarification_used,
                    hallucination_detected=metrics.hallucination_detected,
                    completion_status=metrics.completion_status,
                    plan_length=metrics.plan_length,
                    unnecessary_steps=metrics.unnecessary_steps,
                    dependency_correctness=metrics.dependency_correctness,
                    execution_order_score=metrics.execution_order_score,
                    memories_retrieved=metrics.memories_retrieved,
                    relevant_memories=metrics.relevant_memories,
                    memory_precision=metrics.memory_precision,
                    memory_recall=metrics.memory_recall,
                    memory_latency_ms=metrics.memory_latency_ms,
                    tools_selected=json.dumps(metrics.tools_selected),
                    expected_tools_match=metrics.expected_tools_match,
                    tool_execution_latency_ms=metrics.tool_execution_latency_ms,
                    tool_success_rate=metrics.tool_success_rate,
                    tool_retry_count=metrics.tool_retry_count,
                    total_latency_ms=metrics.total_latency_ms,
                    llm_latency_ms=metrics.llm_latency_ms,
                    planner_latency_ms=metrics.planner_latency_ms,
                    tool_latency_ms=metrics.tool_latency_ms,
                    failure_category=metrics.failure_category,
                    error_message=metrics.error_message,
                    retry_count=metrics.retry_count,
                    replan_count=metrics.replan_count,
                    iterations=metrics.iterations,
                    tool_calls_count=metrics.tool_calls_count,
                    details_json=json.dumps(metrics.details, default=str),
                )
                session.add(result)
        except Exception as e:
            logger.warning("failed to store benchmark result: %s", e)

    def _record_tool_stats(self, metrics: TaskMetrics) -> None:
        """Update per-tool statistics from this task."""
        try:
            timeline = self.tracker.get_timeline(metrics.public_id, limit=200)
            for entry in timeline:
                if entry.get("step_type") == "tool_call":
                    record_tool_execution(
                        tool_name=entry.get("name", ""),
                        ok=entry.get("ok", entry.get("status") == "completed"),
                        duration_ms=entry.get("duration_ms", 0) or 0,
                        error=entry.get("error", ""),
                    )
        except Exception:
            pass


def format_benchmark_results(metrics: list[TaskMetrics]) -> dict[str, Any]:
    """Aggregate all task metrics into a structured summary report."""
    if not metrics:
        return {"error": "no results"}

    n = len(metrics)
    successful = sum(1 for m in metrics if m.success)
    clarified = sum(1 for m in metrics if m.clarification_used)
    hallucinated = sum(1 for m in metrics if m.hallucination_detected)
    failed = n - successful

    by_category: dict[str, list[TaskMetrics]] = {}
    for m in metrics:
        by_category.setdefault(m.category, []).append(m)

    category_scores = {}
    for cat, cat_results in by_category.items():
        cat_pass = sum(1 for r in cat_results if r.success)
        cat_total = len(cat_results)
        category_scores[cat] = {
            "passed": cat_pass,
            "total": cat_total,
            "rate": round(cat_pass / cat_total, 3) if cat_total > 0 else 0.0,
        }

    failure_dist = {}
    for m in metrics:
        fc = m.failure_category or "none"
        failure_dist[fc] = failure_dist.get(fc, 0) + 1

    return {
        "summary": {
            "total": n,
            "passed": successful,
            "failed": failed,
            "pass_rate": round(successful / n, 3) if n > 0 else 0.0,
            "clarification_rate": round(clarified / n, 3) if n > 0 else 0.0,
            "hallucination_rate": round(hallucinated / n, 3) if n > 0 else 0.0,
        },
        "planner": {
            "avg_plan_length": round(sum(m.plan_length for m in metrics) / n, 2),
            "avg_dependency_correctness": round(sum(m.dependency_correctness for m in metrics) / n, 3),
            "avg_execution_order_score": round(sum(m.execution_order_score for m in metrics) / n, 3),
            "avg_unnecessary_steps": round(sum(m.unnecessary_steps for m in metrics) / n, 2),
            "total_replans": sum(m.replan_count for m in metrics),
        },
        "memory": {
            "avg_retrieved": round(sum(m.memories_retrieved for m in metrics) / n, 1),
            "avg_precision": round(sum(m.memory_precision for m in metrics) / n, 3),
            "avg_recall": round(sum(m.memory_recall for m in metrics) / n, 3),
            "avg_latency_ms": round(sum(m.memory_latency_ms for m in metrics) / n, 1),
        },
        "tools": {
            "avg_success_rate": round(sum(m.tool_success_rate for m in metrics) / n, 3),
            "avg_expected_match": round(sum(m.expected_tools_match for m in metrics) / n, 3),
            "total_tool_calls": sum(m.tool_calls_count for m in metrics),
            "avg_execution_latency_ms": round(sum(m.tool_execution_latency_ms for m in metrics) / n, 1),
        },
        "latency": {
            "avg_total_ms": round(sum(m.total_latency_ms for m in metrics) / n, 1),
            "avg_llm_ms": round(sum(m.llm_latency_ms for m in metrics) / n, 1),
            "avg_planner_ms": round(sum(m.planner_latency_ms for m in metrics) / n, 1),
            "avg_tool_ms": round(sum(m.tool_latency_ms for m in metrics) / n, 1),
            "avg_iterations": round(sum(m.iterations for m in metrics) / n, 1),
        },
        "failures": {
            "distribution": dict(sorted(failure_dist.items(), key=lambda x: x[1], reverse=True)),
            "total": failed,
        },
        "categories": category_scores,
        "tool_stats": get_all_tool_stats(),
        "failure_stats": get_failure_stats(),
    }
