"""ExecutionTracker — persistent observability for every agent run.

Records every step (iterations, tool calls, LLM calls, plan steps) to the
database so runs can be audited, debugged, and resumed after interruption.

Publishes `tracker.*` events on the bus for live UI updates.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from paios.core.events import Event, EventBus, get_bus
from paios.db.base import sync_session_scope
from paios.db.models import (
    ExecutionStep,
    StepStatus,
    Task,
    TaskStatus,
    TaskType,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return a naive datetime in UTC, matching SQLModel/SQLite storage format."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ExecutionTracker:
    """Records and queries execution steps for agent tasks.

    Designed for injection into Agent and Planner. Uses sync DB writes.
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus or get_bus()

    # ── Task lifecycle ─────────────────────────────────────────────────────

    def start_task(
        self,
        task_public_id: str,
        request: str,
        mode: str = "react",
        model_used: str | None = None,
    ) -> None:
        """Record a task as started. Called when execution begins."""
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == task_public_id).first()
            if task is None:
                logger.warning("tracker.start_task: task %s not found, creating", task_public_id)
                task = Task(public_id=task_public_id, request=request[:500], mode=mode)
                session.add(task)
            task.status = TaskStatus.RUNNING
            task.started_at = _utcnow()
            task.mode = mode
            if model_used:
                task.model_used = model_used
            session.add(task)

    def complete_task(
        self,
        task_public_id: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record task completion or failure."""
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == task_public_id).first()
            if task is None:
                logger.warning("tracker.complete_task: task %s not found", task_public_id)
                return
            now = _utcnow()
            task.finished_at = now
            task.updated_at = now
            if error:
                task.status = TaskStatus.FAILED
                task.error = error
            else:
                task.status = TaskStatus.COMPLETED
                if result:
                    task.result = result

    def set_task_status(
        self,
        task_public_id: str,
        status: TaskStatus,
        error: str | None = None,
    ) -> None:
        """Update the task status field."""
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == task_public_id).first()
            if task is None:
                logger.warning("tracker.set_task_status: task %s not found", task_public_id)
                return
            task.status = status
            task.updated_at = _utcnow()
            if error:
                task.error = error

    # ── Step recording ─────────────────────────────────────────────────────

    def start_step(
        self,
        task_public_id: str,
        step_type: TaskType,
        name: str,
        step_index: int = 0,
        input_preview: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        """Record the start of an execution step. Returns the step id."""
        with sync_session_scope() as session:
            step = ExecutionStep(
                task_public_id=task_public_id,
                step_index=step_index,
                step_type=step_type,
                name=name,
                status=StepStatus.RUNNING,
                input_preview=input_preview[:500],
                metadata_json=json.dumps(metadata or {}, default=str),
            )
            session.add(step)
            session.flush()
            step_id: int | None = step.id
            return step_id

    def complete_step(
        self,
        step_id: int,
        output_preview: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark a step as successfully completed."""
        with sync_session_scope() as session:
            step = session.query(ExecutionStep).filter(ExecutionStep.id == step_id).first()
            if step is None:
                logger.warning("tracker.complete_step: step %s not found", step_id)
                return
            now = _utcnow()
            step.status = StepStatus.COMPLETED
            step.finished_at = now
            step.duration_ms = int((now - step.started_at).total_seconds() * 1000)
            step.output_preview = output_preview[:500]
            if metadata:
                step.metadata_json = json.dumps(metadata, default=str)

    def fail_step(
        self,
        step_id: int,
        error: str,
        retry_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark a step as failed."""
        with sync_session_scope() as session:
            step = session.query(ExecutionStep).filter(ExecutionStep.id == step_id).first()
            if step is None:
                logger.warning("tracker.fail_step: step %s not found", step_id)
                return
            now = _utcnow()
            step.status = StepStatus.FAILED
            step.finished_at = now
            step.duration_ms = int((now - step.started_at).total_seconds() * 1000)
            step.error = error[:1000]
            step.retry_count = retry_count
            if metadata:
                step.metadata_json = json.dumps(metadata, default=str)

    def skip_step(
        self,
        step_id: int,
        reason: str | None = None,
    ) -> None:
        """Mark a step as skipped."""
        with sync_session_scope() as session:
            step = session.query(ExecutionStep).filter(ExecutionStep.id == step_id).first()
            if step is None:
                return
            now = _utcnow()
            step.status = StepStatus.SKIPPED
            step.finished_at = now
            step.duration_ms = int((now - step.started_at).total_seconds() * 1000)
            if reason:
                step.error = reason[:1000]

    # ── Checkpoints ────────────────────────────────────────────────────────

    def save_checkpoint(
        self,
        task_public_id: str,
        checkpoint_data: str,
        step_index: int,
    ) -> None:
        """Persist a checkpoint so the task can be resumed after restart."""
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == task_public_id).first()
            if task is None:
                logger.warning("tracker.save_checkpoint: task %s not found", task_public_id)
                return
            task.checkpoint_data = checkpoint_data
            task.checkpoint_step = step_index
            task.updated_at = _utcnow()

    def load_checkpoint(self, task_public_id: str) -> tuple[str | None, int]:
        """Load the last checkpoint. Returns (checkpoint_data, step_index)."""
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == task_public_id).first()
            if task is None or not task.checkpoint_data:
                return None, 0
            return task.checkpoint_data, task.checkpoint_step

    # ── Queries ─────────────────────────────────────────────────────────────

    def get_timeline(
        self,
        task_public_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return ordered execution steps as dicts."""
        with sync_session_scope() as session:
            steps = (
                session.query(ExecutionStep)
                .filter(ExecutionStep.task_public_id == task_public_id)
                .order_by(ExecutionStep.step_index)
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": s.id,
                    "step_index": s.step_index,
                    "step_type": s.step_type.value,
                    "name": s.name,
                    "status": s.status.value,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                    "retry_count": s.retry_count,
                }
                for s in steps
            ]

    def get_task_summary(self, task_public_id: str) -> dict[str, Any]:
        """Return aggregated execution stats for a task."""
        steps = self.get_timeline(task_public_id)
        total = len(steps)
        completed = sum(1 for s in steps if s["status"] == "completed")
        failed = sum(1 for s in steps if s["status"] == "failed")
        skipped = sum(1 for s in steps if s["status"] == "skipped")
        total_duration = sum(s["duration_ms"] for s in steps if s["duration_ms"])

        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == task_public_id).first()

        return {
            "task_public_id": task_public_id,
            "total_steps": total,
            "completed_steps": completed,
            "failed_steps": failed,
            "skipped_steps": skipped,
            "total_duration_ms": total_duration,
            "tool_count": task.tool_count if task else 0,
            "retry_count": task.retry_count if task else 0,
            "status": task.status.value if task else "unknown",
        }

    def increment_tool_count(self, task_public_id: str) -> None:
        """Increment the tool usage counter for a task."""
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == task_public_id).first()
            if task:
                task.tool_count = (task.tool_count or 0) + 1
                task.updated_at = _utcnow()

    def increment_retry_count(self, task_public_id: str) -> None:
        """Increment the retry counter for a task."""
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == task_public_id).first()
            if task:
                task.retry_count = (task.retry_count or 0) + 1
                task.updated_at = _utcnow()
