"""Training data collector — gathers successful task examples from the database.

Queries completed tasks with their execution steps and tool invocations,
computes quality scores, and produces TrainingExample records suitable for
export as training datasets.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlmodel import select, delete, update, func
from veyron.db.base import sync_session_scope
from veyron.db.models import ExecutionStep, Task, TaskStatus, ToolInvocation
from veyron.intelligence.training.dataset import TrainingDataset, TrainingExample
from veyron.intelligence.training.quality import QualityScorer

logger = logging.getLogger(__name__)


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
    if any(kw in request_lower for kw in ("?", "what", "how", "why", "who")):
        return "question_answering"
    if any(kw in request_lower for kw in ("code", "write", "implement", "fix", "bug")):
        return "coding_task"
    if any(kw in request_lower for kw in ("plan", "first", "then", "step")):
        return "planning_task"
    if any(kw in request_lower for kw in ("debug", "error", "issue")):
        return "debugging"
    if any(kw in request_lower for kw in ("analyze", "scan", "project", "report")):
        return "project_analysis"
    return "conversation"


class TrainingDataCollector:
    def __init__(self) -> None:
        self.scorer = QualityScorer()

    def collect_successful(
        self,
        limit: int = 500,
        min_quality: float = 0.0,
    ) -> TrainingDataset:
        tasks = self._fetch_completed_tasks(limit)
        examples: list[TrainingExample] = []
        for task in tasks:
            if not task.request:
                continue
            tools_used = self._fetch_tools_used(task.public_id)
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

            if min_quality > 0.0 and score.overall < min_quality:
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
                    category="agent_task",
                    metadata={
                        "status": task.status.value,
                        "started_at": str(task.started_at) if task.started_at else "",
                        "finished_at": str(task.finished_at) if task.finished_at else "",
                        "quality_details": {
                            "completion_bonus": score.completion_bonus,
                            "efficiency_score": score.efficiency_score,
                            "tool_diversity_score": score.tool_diversity_score,
                            "duration_penalty": score.duration_penalty,
                            "retry_penalty": score.retry_penalty,
                        },
                    },
                )
            )
        logger.info("collected %d training examples", len(examples))
        return TrainingDataset(examples)

    def collect_all(self, limit: int = 500) -> dict[str, TrainingDataset]:
        successful = self.collect_successful(limit=limit, min_quality=0.0)
        return {"all": successful}

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

    def _fetch_tools_used(self, task_public_id: str) -> list[str]:
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
                if tools:
                    return tools
                steps = (
                    session.exec(
                        select(ExecutionStep)
                        .where(
                            ExecutionStep.task_public_id == task_public_id,
                            ExecutionStep.step_type == "tool_call",
                        )
                    )
                    .all()
                )
                tools = [s.name for s in steps if s.name]
        except Exception as e:
            logger.debug("could not fetch tools for %s: %s", task_public_id, e)
        return tools

    def _fetch_step_counts(self, task_public_id: str) -> tuple[int, int]:
        tool_calls = 0
        retry_count = 0
        try:
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


_collector: TrainingDataCollector | None = None
_collector_lock = threading.Lock()


def get_collector() -> TrainingDataCollector:
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = TrainingDataCollector()
    return _collector


def reset_collector() -> None:
    global _collector
    _collector = None
