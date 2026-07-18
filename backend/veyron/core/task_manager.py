"""Task Management System — lifecycle, progress, artifacts, history.

Provides a higher-level interface over the Task model + ExecutionTracker
for managing task creation, lifecycle transitions, progress tracking,
artifact association, and history queries.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from veyron.core.agent import get_agent
from veyron.core.events import Event, get_bus
from veyron.core.tracker import ExecutionTracker
from sqlmodel import select, delete, update

from veyron.db.base import sync_session_scope
from veyron.db.models import Task, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class TaskProgress:
    """Progress snapshot for a task."""

    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    retry_count: int = 0
    tool_count: int = 0
    current_step: str = ""
    percent: float = 0.0


@dataclass
class TaskInfo:
    """Full task detail returned by the manager."""

    public_id: str
    request: str
    status: str
    mode: str
    result: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
    progress: TaskProgress | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)


class TaskManager:
    """High-level task lifecycle manager.

    Wraps the existing Task model, ExecutionTracker, and Agent into a
    unified interface for frontend consumption.
    """

    def __init__(self) -> None:
        self.tracker = ExecutionTracker()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def create_task(self, request: str) -> str:
        """Create a new task and return its public_id."""
        public_id = uuid4().hex
        with sync_session_scope() as session:
            task = Task(public_id=public_id, request=request, status=TaskStatus.CREATED)
            session.add(task)
        get_bus().publish_nowait(
            Event(
                type="task.created",
                topic=public_id,
                payload={"public_id": public_id, "request": request[:200]},
            )
        )
        logger.info("task created: %s", public_id)
        return public_id

    def get_task(self, public_id: str) -> TaskInfo | None:
        """Get full task detail with progress."""
        with sync_session_scope() as session:
            task = session.exec(select(Task).where(Task.public_id == public_id)).first()
            if task is None:
                return None
            return self._to_info(task)

    def list_tasks(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        mode: str | None = None,
    ) -> list[TaskInfo]:
        """List tasks with optional filters."""
        with sync_session_scope() as session:
            stmt = select(Task)
            if status:
                stmt = stmt.where(Task.status == status)
            if mode:
                stmt = stmt.where(Task.mode == mode)
            stmt = stmt.order_by(Task.created_at.desc()).offset(offset).limit(limit)
            return [self._to_brief(t) for t in session.exec(stmt).all()]

    def cancel_task(self, public_id: str) -> TaskInfo | None:
        """Cancel a running or paused task."""
        with sync_session_scope() as session:
            task = session.exec(select(Task).where(Task.public_id == public_id)).first()
            if task is None:
                return None
            if task.status in (TaskStatus.RUNNING, TaskStatus.PLANNING, TaskStatus.CREATED, TaskStatus.PAUSED):
                get_agent().cancel(public_id)
                task.status = TaskStatus.CANCELLED
                task.finished_at = datetime.now(UTC)
                task.updated_at = datetime.now(UTC)
                session.add(task)
                get_bus().publish_nowait(Event(
                    type="task.cancelled", topic=public_id,
                    payload={"public_id": public_id},
                ))
                logger.info("task cancelled: %s", public_id)
            return self._to_info(task)

    def pause_task(self, public_id: str) -> TaskInfo | None:
        """Pause a running task."""
        with sync_session_scope() as session:
            task = session.exec(select(Task).where(Task.public_id == public_id)).first()
            if task is None:
                return None
            if task.status == TaskStatus.RUNNING:
                get_agent().cancel(public_id)
                task.status = TaskStatus.PAUSED
                task.updated_at = datetime.now(UTC)
                session.add(task)
                get_bus().publish_nowait(Event(
                    type="task.paused", topic=public_id,
                    payload={"public_id": public_id},
                ))
                logger.info("task paused: %s", public_id)
            return self._to_info(task)

    def resume_task(self, public_id: str) -> TaskInfo | None:
        """Resume a paused or failed task."""
        with sync_session_scope() as session:
            task = session.exec(select(Task).where(Task.public_id == public_id)).first()
            if task is None:
                return None
            if task.status in (TaskStatus.PAUSED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.status = TaskStatus.CREATED
                task.error = None
                task.updated_at = datetime.now(UTC)
                session.add(task)
                logger.info("task queued for resume: %s", public_id)
            return self._to_info(task)

    def delete_task(self, public_id: str) -> bool:
        """Permanently delete a task and its steps."""
        with sync_session_scope() as session:
            task = session.exec(select(Task).where(Task.public_id == public_id)).first()
            if task is None:
                return False
            # Delete associated execution steps.
            from veyron.db.models import ExecutionStep
            session.exec(delete(ExecutionStep).where(ExecutionStep.task_public_id == public_id))
            session.delete(task)
            logger.info("task deleted: %s", public_id)
            return True

    # ── Progress ───────────────────────────────────────────────────────

    def get_progress(self, public_id: str) -> TaskProgress | None:
        """Compute progress for a task."""
        info = self.get_task(public_id)
        if info is None:
            return None
        return info.progress

    # ── History ────────────────────────────────────────────────────────

    def get_history(
        self,
        public_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Get execution step timeline for a task."""
        return self._query_timeline_sync(public_id, limit=limit)

    # ── Internals ─────────────────────────────────────────────────────

    def _query_timeline_sync(
        self,
        task_public_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Sync fallback to get timeline from DB directly (avoids async tracker)."""
        from veyron.db.base import sync_session_scope
        from veyron.db.models import ExecutionStep

        with sync_session_scope() as session:
            steps = (
                session.exec(
                    select(ExecutionStep)
                    .where(ExecutionStep.task_public_id == task_public_id)
                    .order_by(ExecutionStep.step_index)
                    .limit(limit)
                )
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
                    "input_preview": s.input_preview[:200] if s.input_preview else "",
                    "output_preview": s.output_preview[:200] if s.output_preview else "",
                    "error": s.error,
                    "retry_count": s.retry_count,
                }
                for s in steps
            ]

    def _query_task_summary_sync(self, task_public_id: str) -> dict[str, Any]:
        """Sync fallback to get task summary directly from DB."""
        from veyron.db.base import sync_session_scope
        from veyron.db.models import Task

        steps = self._query_timeline_sync(task_public_id)
        total = len(steps)
        completed = sum(1 for s in steps if s["status"] == "completed")
        failed = sum(1 for s in steps if s["status"] == "failed")
        skipped = sum(1 for s in steps if s["status"] == "skipped")
        total_duration = sum(s["duration_ms"] for s in steps if s["duration_ms"])

        with sync_session_scope() as session:
            task = session.exec(select(Task).where(Task.public_id == task_public_id)).first()

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

    def _compute_progress(self, task: Task) -> TaskProgress:
        """Build a TaskProgress from a Task record."""
        _safe_int = lambda v: v if isinstance(v, int) else 0
        summary = self._query_task_summary_sync(task.public_id)
        total = _safe_int(summary.get("total_steps", 0) or task.total_steps)
        completed = _safe_int(summary.get("completed_steps", 0) or task.completed_steps)
        failed = summary.get("failed_steps", 0) or 0
        retries = _safe_int(summary.get("retry_count", 0) or task.retry_count)
        tools = _safe_int(summary.get("tool_count", 0) or task.tool_count)
        current = summary.get("current_step", "") or ""

        percent = (completed / total * 100) if total > 0 else 0.0
        return TaskProgress(
            total_steps=total,
            completed_steps=completed,
            failed_steps=failed,
            retry_count=retries,
            tool_count=tools,
            current_step=current,
            percent=round(percent, 1),
        )

    def _to_info(self, task: Task) -> TaskInfo:
        """Convert a Task model to a TaskInfo."""
        progress = self._compute_progress(task)
        history = self._query_timeline_sync(task.public_id, limit=20)
        return TaskInfo(
            public_id=task.public_id,
            request=task.request,
            status=task.status,
            mode=task.mode,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            updated_at=task.updated_at,
            progress=progress,
            history=history,
        )

    def _to_brief(self, task: Task) -> TaskInfo:
        """Convert a Task model to a brief TaskInfo (no details)."""
        summary = self._query_task_summary_sync(task.public_id)
        _safe_int = lambda v: v if isinstance(v, int) else 0
        return TaskInfo(
            public_id=task.public_id,
            request=task.request,
            status=task.status,
            mode=task.mode,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            updated_at=task.updated_at,
            progress=TaskProgress(
                total_steps=_safe_int(summary.get("total_steps", 0) or task.total_steps),
                completed_steps=_safe_int(summary.get("completed_steps", 0) or task.completed_steps),
                retry_count=_safe_int(summary.get("retry_count", 0) or task.retry_count),
                tool_count=_safe_int(summary.get("tool_count", 0) or task.tool_count),
            ),
        )


# Singleton.
_manager: TaskManager | None = None
_manager_lock = threading.Lock()


def get_task_manager() -> TaskManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = TaskManager()
    return _manager


def reset_task_manager() -> None:
    global _manager
    _manager = None
