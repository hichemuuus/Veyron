"""Dashboard API endpoint.

Aggregates task, system, and tool data for the frontend dashboard.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from paios.core.task_manager import get_task_manager
from paios.db.base import sync_session_scope
from paios.db.models import Task, TaskStatus
from paios.tools.base import ToolContext
from paios.tools.system_monitor import SystemMonitorTool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard() -> dict:
    """Aggregated dashboard data: task counts, recent activity, system overview."""
    tm = get_task_manager()

    # Task counts from DB directly for efficiency.
    active_count = 0
    completed_count = 0
    failed_count = 0
    with sync_session_scope() as session:
        active_count = (
            session.query(Task)
            .filter(Task.status.in_([TaskStatus.RUNNING, TaskStatus.PLANNING, TaskStatus.PAUSED, TaskStatus.CREATED]))
            .count()
        )
        completed_count = (
            session.query(Task).filter(Task.status == TaskStatus.COMPLETED).count()
        )
        failed_count = (
            session.query(Task).filter(Task.status.in_([TaskStatus.FAILED, TaskStatus.CANCELLED])).count()
        )

    recent = tm.list_tasks(limit=10, offset=0)

    # System overview.
    monitor = SystemMonitorTool()
    ctx = ToolContext(task_public_id="dashboard")
    overview_result = await monitor.run(ctx, operation="overview")
    system = {}
    if overview_result.ok and overview_result.data:
        system = overview_result.data

    return {
        "active_tasks": active_count,
        "completed_tasks": completed_count,
        "failed_tasks": failed_count,
        "total_tasks": active_count + completed_count + failed_count,
        "recent_tasks": [
            {
                "public_id": t.public_id,
                "request": t.request[:200] if t.request else "",
                "status": t.status,
                "mode": t.mode,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in recent
        ],
        "system": system,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
