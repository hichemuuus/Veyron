"""Learning Dashboard API endpoint.

Read-only endpoints for learning, reflection, skill, workflow, benchmark,
and model version data.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlmodel import select

from veyron.db.base import sync_session_scope
from veyron.db.models import (
    BenchmarkRun,
    LearningEvent,
    ModelVersion,
    ReflectionRecord,
    Skill,
    Workflow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/learning", tags=["learning"])


# ── Synchronous DB helpers (run in thread pool to avoid blocking) ──────────


def _query_reflections(limit: int, offset: int) -> dict:
    """Fetch reflection records — runs in a thread via ``_run_sync``."""
    with sync_session_scope() as session:
        total = len(session.exec(select(ReflectionRecord)).all())
        records = (
            session.exec(
                select(ReflectionRecord)
                .order_by(ReflectionRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            .all()
        )
        return {
            "reflections": [
                {
                    "public_id": r.public_id,
                    "task_public_id": r.task_public_id,
                    "category": (
                        r.category.value if hasattr(r.category, "value") else str(r.category)
                    ),
                    "success": r.success,
                    "confidence": r.confidence,
                    "planning_quality": r.planning_quality,
                    "tool_selection_quality": r.tool_selection_quality,
                    "parameter_quality": r.parameter_quality,
                    "memory_usefulness": r.memory_usefulness,
                    "mistake_count": r.mistake_count,
                    "improvement_count": r.improvement_count,
                    "tool_issue_count": r.tool_issue_count,
                    "summary": r.summary,
                    "improvement_notes": r.improvement_notes,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def _query_skill_count() -> int:
    """Return total skill count — runs in a thread via ``_run_sync``."""
    with sync_session_scope() as session:
        return len(session.exec(select(Skill)).all())


def _query_workflow_count() -> int:
    """Return total workflow count — runs in a thread via ``_run_sync``."""
    with sync_session_scope() as session:
        return len(session.exec(select(Workflow)).all())


def _query_models() -> dict:
    """Fetch model versions grouped by type — runs in a thread via ``_run_sync``."""
    with sync_session_scope() as session:
        models = session.exec(select(ModelVersion).order_by(ModelVersion.created_at.desc())).all()
        by_type: dict[str, list[dict]] = {}
        for m in models:
            mt = m.model_type
            if mt not in by_type:
                by_type[mt] = []
            by_type[mt].append({
                "version": m.version,
                "status": m.status,
                "dataset_size": m.dataset_size,
                "metrics": json.loads(m.metrics_json) if m.metrics_json else {},
                "path": m.path,
                "parent_version": m.parent_version,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            })
        return {"models_by_type": by_type, "total": len(models)}


def _query_benchmarks(limit: int, offset: int) -> dict:
    """Fetch benchmark runs — runs in a thread via ``_run_sync``."""
    with sync_session_scope() as session:
        total = len(session.exec(select(BenchmarkRun)).all())
        runs = (
            session.exec(
                select(BenchmarkRun)
                .order_by(BenchmarkRun.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            .all()
        )
        return {
            "benchmarks": [
                {
                    "public_id": b.public_id,
                    "benchmark_name": b.benchmark_name,
                    "model_type": b.model_type,
                    "model_version": b.model_version,
                    "metrics": json.loads(b.metrics_json) if b.metrics_json else {},
                    "score": b.score,
                    "regressions": json.loads(b.regressions) if b.regressions else [],
                    "duration_ms": b.duration_ms,
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                }
                for b in runs
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def _query_events(category: str | None, limit: int, offset: int) -> dict:
    """Fetch learning events — runs in a thread via ``_run_sync``."""
    with sync_session_scope() as session:
        q = select(LearningEvent)
        if category:
            q = q.where(LearningEvent.category == category)
        total = len(session.exec(q).all())
        events = session.exec(q.order_by(LearningEvent.created_at.desc()).offset(offset).limit(limit)).all()
        return {
            "events": [
                {
                    "public_id": e.public_id,
                    "event_type": e.event_type,
                    "category": e.category,
                    "summary": e.summary,
                    "details": json.loads(e.details_json) if e.details_json else {},
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def _query_overview_counts() -> dict:
    """Return aggregate counts for the overview — runs in a thread via ``_run_sync``."""
    with sync_session_scope() as session:
        return {
            "reflection_count": len(session.exec(select(ReflectionRecord)).all()),
            "skill_count": len(session.exec(select(Skill)).all()),
            "workflow_count": len(session.exec(select(Workflow)).all()),
            "benchmark_count": len(session.exec(select(BenchmarkRun)).all()),
            "event_count": len(session.exec(select(LearningEvent)).all()),
            "model_count": len(session.exec(select(ModelVersion)).all()),
        }


@router.get("/reflections")
async def get_reflections(limit: int = 50, offset: int = 0) -> dict:
    """Return reflection history."""
    return await _run_sync(_query_reflections, limit, offset)


@router.get("/reflections/stats")
async def reflection_stats() -> dict:
    """Return aggregate reflection statistics."""
    from veyron.core.reflection import ReflectionEngine

    engine = ReflectionEngine()
    return await _run_sync(engine.get_reflection_stats)


@router.get("/skills")
async def list_skills(enabled_only: bool = True, limit: int = 50, offset: int = 0) -> dict:
    """Return detected skills."""
    from veyron.learning.skill_store import get_skill_store

    store = get_skill_store()
    skills, total = await asyncio.to_thread(
        lambda: (
            store.list_skills(enabled_only=enabled_only, limit=limit, offset=offset),
            _query_skill_count(),
        )
    )
    return {
        "skills": [
            {
                "public_id": s.public_id,
                "name": s.name,
                "description": s.description,
                "frequency": s.frequency,
                "confidence": s.confidence,
                "pattern_steps": json.loads(s.pattern_steps) if s.pattern_steps else [],
                "enabled": s.enabled,
                "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in skills
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/skills/stats")
async def skill_stats() -> dict:
    """Return skill statistics."""
    from veyron.learning.skill_store import get_skill_store

    return await _run_sync(get_skill_store().get_skill_stats)


@router.get("/workflows")
async def list_workflows(enabled_only: bool = True, limit: int = 50, offset: int = 0) -> dict:
    """Return workflow definitions."""
    from veyron.workflow.registry import get_workflow_registry

    registry = get_workflow_registry()
    workflows, total = await asyncio.to_thread(
        lambda: (
            registry.list_workflows(enabled_only=enabled_only, limit=limit, offset=offset),
            _query_workflow_count(),
        )
    )
    return {"workflows": workflows, "total": total, "limit": limit, "offset": offset}


@router.get("/workflows/stats")
async def workflow_stats() -> dict:
    """Return workflow statistics."""
    from veyron.workflow.registry import get_workflow_registry

    return await _run_sync(get_workflow_registry().get_stats)


@router.get("/models")
async def list_models() -> dict:
    """Return model version history."""
    return await _run_sync(_query_models)


@router.get("/benchmarks")
async def list_benchmarks(limit: int = 50, offset: int = 0) -> dict:
    """Return benchmark run history."""
    return await _run_sync(_query_benchmarks, limit, offset)


@router.get("/events")
async def list_learning_events(
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return learning system events."""
    return await _run_sync(_query_events, category, limit, offset)


@router.get("/scheduler")
async def scheduler_status() -> dict:
    """Return scheduler status."""
    return {"note": "scheduler status available via /api/intelligence/metrics"}


@router.get("/overview")
async def learning_overview() -> dict:
    """Aggregated learning dashboard overview."""
    counts = await _run_sync(_query_overview_counts)
    return {
        **counts,
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def _run_sync(fn, *args, **kwargs):
    """Run a synchronous function in a thread to avoid blocking."""
    return await asyncio.to_thread(fn, *args, **kwargs)
