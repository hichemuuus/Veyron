"""Training data feedback loop — converts completed tasks into high-quality training examples.

Connects the collector, reflection engine, and evaluator to produce a clean,
deduplicated, auto-labeled training dataset from real agent usage.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlmodel import select, delete, update, func
from veyron.db.base import sync_session_scope
from veyron.db.models import Task, TaskStatus, ToolInvocation
from veyron.intelligence.training.dataset import TrainingDataset, TrainingExample
from veyron.intelligence.training.quality import QualityScorer

logger = logging.getLogger(__name__)


def _word_in(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text))


def _infer_intent(request: str, tools_used: list[str]) -> str:
    request_lower = request.lower()
    tool_intent_map: dict[str, str] = {
        "filesystem_read": "file_operation",
        "system_monitor": "system_management",
        "terminal": "tool_execution",
        "project_analyzer": "project_analysis",
    }
    for tool in tools_used:
        if tool in tool_intent_map:
            return tool_intent_map[tool]
    if _word_in(request_lower, "debug"):
        return "debugging"
    if any(kw in request_lower for kw in ("?", "what", "how", "why", "who")):
        return "question_answering"
    if any(_word_in(request_lower, kw) for kw in ("code", "write", "implement", "fix", "bug")):
        return "coding_task"
    if any(_word_in(request_lower, kw) for kw in ("plan", "first", "then", "step")):
        return "planning_task"
    if any(_word_in(request_lower, kw) for kw in ("error", "issue")):
        return "debugging"
    if any(_word_in(request_lower, kw) for kw in ("analyze", "scan", "project", "report")):
        return "project_analysis"
    return "conversation"


class TrainingFeedbackLoop:
    """Converts completed tasks into high-quality training examples.

    Flow:
      1. Fetch completed/failed tasks from DB
      2. Quality-score each task
      3. Filter by quality threshold
      4. Deduplicate by content hash
      5. Auto-label intents
      6. Export to TrainingDataset
    """

    def __init__(self, min_quality: float = 0.5) -> None:
        self.scorer = QualityScorer()
        self.min_quality = min_quality

    def collect_from_db(
        self,
        limit: int = 500,
        min_quality: float | None = None,
    ) -> TrainingDataset:
        threshold = min_quality if min_quality is not None else self.min_quality
        tasks = self._fetch_completed_tasks(limit)
        examples: list[TrainingExample] = []
        for task in tasks:
            if not task.request:
                continue
            tools_used = self._fetch_tools(task.public_id)
            tool_calls_count, retry_count = self._fetch_step_counts(task.public_id)
            duration_ms = self._compute_duration(task)

            raw: dict[str, Any] = {
                "success": task.status == TaskStatus.COMPLETED,
                "total_steps": task.total_steps or 0,
                "retry_count": task.retry_count or retry_count,
                "tools_used": tools_used,
                "duration_ms": duration_ms,
                "tool_calls_count": tool_calls_count,
            }
            score = self.scorer.score(raw)

            if score.overall < threshold:
                continue

            intent = _infer_intent(task.request, tools_used)
            examples.append(
                TrainingExample(
                    request=task.request,
                    intent=intent,
                    tools_used=tools_used,
                    success=task.status == TaskStatus.COMPLETED,
                    duration_ms=duration_ms,
                    quality_score=score.overall,
                    total_steps=task.total_steps or 0,
                    retry_count=task.retry_count or retry_count,
                    tool_calls_count=tool_calls_count,
                    mode=task.mode,
                    error=task.error,
                    task_id=task.public_id,
                    category=intent,
                    metadata={
                        "source": "feedback_loop",
                        "collected_at": datetime.now(UTC).isoformat(),
                        "status": task.status.value,
                    },
                )
            )
        dataset = TrainingDataset(examples)
        deduped = dataset.deduplicate()
        logger.info(
            "feedback loop: %d raw -> %d after dedup (min_quality=%.2f)",
            len(examples), len(deduped), threshold,
        )
        return deduped

    def _fetch_completed_tasks(self, limit: int) -> list[Task]:
        with sync_session_scope() as session:
            return (
                session.exec(
                    select(Task)
                    .where(Task.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]))
                    .order_by(Task.finished_at.desc())
                    .limit(limit)
                )
                .all()
            )

    def _fetch_tools(self, task_public_id: str) -> list[str]:
        tools: list[str] = []
        try:
            with sync_session_scope() as session:
                invocations = (
                    session.exec(
                        select(ToolInvocation)
                        .where(ToolInvocation.task_public_id == task_public_id)
                    )
                    .all()
                )
                tools = [inv.tool_name for inv in invocations if inv.tool_name]
        except Exception as e:
            logger.debug("could not fetch tools for %s: %s", task_public_id, e)
        return tools

    def _fetch_step_counts(self, task_public_id: str) -> tuple[int, int]:
        tool_calls = 0
        retry_count = 0
        try:
            from veyron.db.models import ExecutionStep
            with sync_session_scope() as session:
                steps = (
                    session.exec(
                        select(ExecutionStep)
                        .where(ExecutionStep.task_public_id == task_public_id)
                    )
                    .all()
                )
                tool_calls = sum(1 for s in steps if s.step_type == "tool_call")
                retry_count = sum(s.retry_count or 0 for s in steps)
        except Exception as e:
            logger.debug("could not fetch steps for %s: %s", task_public_id, e)
        return tool_calls, retry_count

    def _compute_duration(self, task: Task) -> int:
        if task.finished_at and task.started_at:
            delta = task.finished_at - task.started_at
            if hasattr(delta, "total_seconds"):
                return int(delta.total_seconds() * 1000)
        return 0
