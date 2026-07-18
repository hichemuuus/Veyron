"""Agent API routes.

  POST /api/agent                — start a task
  GET  /api/agent/{id}           — get task detail with progress
  GET  /api/agent                — list tasks (filterable)
  GET  /api/agent/{id}/timeline  — execution step timeline
  POST /api/agent/{id}/cancel    — cancel a task
  POST /api/agent/{id}/pause     — pause a running task
  POST /api/agent/{id}/resume    — resume a paused/failed task
  DELETE /api/agent/{id}         — permanently delete a task
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from veyron.core.agent import get_agent
from veyron.core.events import Event, get_bus
from veyron.core.task_manager import get_task_manager
from veyron.db.models import TaskStatus

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentRequest(BaseModel):
    request: str = Field(..., min_length=1, max_length=8000)


class AgentResponse(BaseModel):
    public_id: str
    status: str
    request: str


@router.post("", response_model=AgentResponse)
async def create_task(req: AgentRequest) -> AgentResponse:
    """Create a task and start running it in the background."""
    mgr = get_task_manager()
    public_id = mgr.create_task(req.request)
    asyncio.create_task(_run_agent(req.request, public_id))
    return AgentResponse(public_id=public_id, status=TaskStatus.CREATED, request=req.request)


@router.get("/{public_id}")
def get_task(public_id: str) -> dict[str, Any]:
    """Get task detail with progress and recent history."""
    mgr = get_task_manager()
    info = mgr.get_task(public_id)
    if info is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _info_to_dict(info)


@router.get("")
def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
) -> dict[str, Any]:
    """List tasks with optional filters."""
    mgr = get_task_manager()
    tasks = mgr.list_tasks(limit=limit, offset=offset, status=status, mode=mode)
    return {
        "tasks": [_brief_to_dict(t) for t in tasks],
        "count": len(tasks),
    }


@router.get("/{public_id}/timeline")
def get_timeline(public_id: str, limit: int = 200) -> dict[str, Any]:
    """Return the execution step timeline for a task."""
    mgr = get_task_manager()
    info = mgr.get_task(public_id)
    if info is None:
        raise HTTPException(status_code=404, detail="task not found")
    history = mgr.get_history(public_id, limit=limit)
    p = info.progress
    return {
        "task_public_id": public_id,
        "steps": history,
        "summary": {
            "total_steps": p.total_steps,
            "completed_steps": p.completed_steps,
            "failed_steps": p.failed_steps,
            "retry_count": p.retry_count,
            "tool_count": p.tool_count,
            "current_step": p.current_step,
            "percent": p.percent,
        },
    }


@router.post("/{public_id}/cancel")
def cancel_task(public_id: str) -> dict[str, Any]:
    """Request cancellation of a running/paused task."""
    mgr = get_task_manager()
    info = mgr.cancel_task(public_id)
    if info is None:
        raise HTTPException(status_code=404, detail="task not found")
    get_bus().publish_nowait(Event(type="task.cancelling", topic=public_id, payload={}))
    return {"status": "cancellation_requested", "public_id": public_id}


@router.post("/{public_id}/pause")
def pause_task(public_id: str) -> dict[str, Any]:
    """Pause a running task."""
    mgr = get_task_manager()
    info = mgr.pause_task(public_id)
    if info is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"status": "paused", "public_id": public_id}


@router.post("/{public_id}/resume")
async def resume_task(public_id: str) -> dict[str, Any]:
    """Resume a paused or failed task."""
    mgr = get_task_manager()
    info = mgr.resume_task(public_id)
    if info is None:
        raise HTTPException(status_code=404, detail="task not found")

    asyncio.create_task(_run_agent(info.request, public_id))
    return {"status": "resumed", "public_id": public_id}


@router.delete("/{public_id}")
def delete_task(public_id: str) -> dict[str, Any]:
    """Permanently delete a task."""
    mgr = get_task_manager()
    deleted = mgr.delete_task(public_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="task not found")
    return {"status": "deleted", "public_id": public_id}


class UserFeedback(BaseModel):
    score: float = Field(default=0.5, ge=0.0, le=1.0, description="User satisfaction 0.0–1.0")
    comment: str = Field(default="", max_length=2000)


@router.post("/{public_id}/feedback")
def submit_feedback(public_id: str, fb: UserFeedback) -> dict[str, Any]:
    """Submit user feedback for a completed task.

    Updates the latest user interaction JSONL entry with the feedback score,
    which improves future retraining quality.
    """
    from veyron.intelligence.training.dataset import (
        load_user_interactions,
        save_user_interaction,
    )

    mgr = get_task_manager()
    info = mgr.get_task(public_id)
    if info is None:
        raise HTTPException(status_code=404, detail="task not found")

    interactions = load_user_interactions()
    updated = False
    for ui in reversed(interactions):
        if ui.task_id == public_id:
            ui.feedback_score = fb.score
            if fb.comment:
                ui.metadata["user_comment"] = fb.comment
            save_user_interaction(ui)
            updated = True
            break

    if not updated:
        raise HTTPException(status_code=404, detail="no interaction found for this task")

    if fb.score < 0.5:
        from sqlmodel import select
        from veyron.db.base import sync_session_scope
        from veyron.db.models import PredictionLog

        with sync_session_scope() as session:
            recent = (
                session.exec(
                    select(PredictionLog)
                    .where(PredictionLog.input_text == info.request)
                    .order_by(PredictionLog.id.desc())
                ).first()
            )
            if recent is not None:
                recent.needs_review = True
                session.add(recent)

    return {"status": "ok", "public_id": public_id, "feedback_score": fb.score}


# ── Background execution ─────────────────────────────────────────────


async def _run_agent(request: str, public_id: str) -> None:
    """Run agent in background and mark task as failed on exception."""
    try:
        await get_agent().run(request, task_public_id=public_id)
    except Exception as e:  # noqa: BLE001
        from sqlmodel import select
        from veyron.db.base import sync_session_scope
        from veyron.db.models import Task
        with sync_session_scope() as session:
            t = session.exec(select(Task).where(Task.public_id == public_id)).first()
            if t is not None:
                t.status = TaskStatus.FAILED
                t.error = f"{type(e).__name__}: {e}"
                session.add(t)
        get_bus().publish_nowait(
            Event(type="task.failed", topic=public_id, payload={"error": str(e)})
        )


# ── Response helpers ─────────────────────────────────────────────────


def _info_to_dict(info: Any) -> dict[str, Any]:
    """Convert TaskInfo to a serializable dict."""
    progress = info.progress
    return {
        "public_id": info.public_id,
        "request": info.request,
        "status": info.status,
        "mode": info.mode,
        "result": info.result,
        "error": info.error,
        "created_at": info.created_at,
        "started_at": info.started_at,
        "finished_at": info.finished_at,
        "updated_at": info.updated_at,
        "progress": {
            "total_steps": progress.total_steps,
            "completed_steps": progress.completed_steps,
            "failed_steps": progress.failed_steps,
            "retry_count": progress.retry_count,
            "tool_count": progress.tool_count,
            "current_step": progress.current_step,
            "percent": progress.percent,
        },
        "history": info.history,
    }


def _brief_to_dict(info: Any) -> dict[str, Any]:
    """Convert a brief TaskInfo to a serializable dict."""
    p = info.progress
    return {
        "public_id": info.public_id,
        "request": info.request,
        "status": info.status,
        "mode": info.mode,
        "result": info.result,
        "error": info.error,
        "created_at": info.created_at,
        "started_at": info.started_at,
        "finished_at": info.finished_at,
        "updated_at": info.updated_at,
        "progress": {
            "total_steps": getattr(p, "total_steps", 0) or 0,
            "completed_steps": getattr(p, "completed_steps", 0) or 0,
            "percent": getattr(p, "percent", 0.0) or 0.0,
        },
    }
