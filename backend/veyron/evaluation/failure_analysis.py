"""Failure analysis — automatic classification, aggregate statistics, and pattern detection.

Every tool or planner failure is categorized and stored for analysis.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlmodel import select, delete, update, func
from veyron.db.base import sync_session_scope
from veyron.db.models import FailureAnalysisRecord, FailureCategory
from veyron.tools.base import classify_failure as classify_tool_failure

logger = logging.getLogger(__name__)


def classify_failure(
    error: str,
    context: str = "",
) -> FailureCategory:
    """Classify a failure into a category based on error message and context.

    Uses keyword matching on the error string, then falls back to the
    tool-level classifier, then to UNKNOWN.
    """
    err_lower = error.lower()

    if any(kw in err_lower for kw in ("timeout", "timed out", "deadline")):
        return FailureCategory.TIMEOUT
    if any(kw in err_lower for kw in ("hallucinat", "invent", "made up", "not real")):
        return FailureCategory.HALLUCINATION
    if any(kw in err_lower for kw in ("permission", "denied", "not allowed", "unauthorized", "blocked")):
        return FailureCategory.PERMISSION_DENIED
    if any(kw in err_lower for kw in ("invalid input", "validation error", "model_validate")):
        return FailureCategory.INVALID_INPUT
    if any(kw in err_lower for kw in ("memory", "retriev", "embedding")):
        return FailureCategory.MEMORY_FAILURE
    if any(kw in err_lower for kw in ("planner", "plan", "decompos", "step")):
        return FailureCategory.PLANNER_FAILURE
    if any(kw in err_lower for kw in ("llm", "model", "provider", "generat", "token")):
        return FailureCategory.LLM_ISSUE
    if any(kw in err_lower for kw in ("environment", "python", "import", "module", "dependency")):
        return FailureCategory.ENVIRONMENT_ISSUE

    tool_category = classify_tool_failure(error)
    if tool_category.value != "unknown":
        _MAPPING = {"tool_error": "tool_failure"}
        mapped = _MAPPING.get(tool_category.value, tool_category.value)
        return FailureCategory(mapped)

    return FailureCategory.UNKNOWN


def record_failure(
    task_public_id: str,
    failure_category: FailureCategory | str,
    error_message: str,
    tool_name: str | None = None,
    plan_step_id: str | None = None,
    context: str = "",
    recovered: bool = False,
    repair_strategy: str | None = None,
) -> str:
    """Record a categorized failure for analytics."""
    cat = FailureCategory(failure_category) if isinstance(failure_category, str) else failure_category
    public_id = uuid4().hex

    record = FailureAnalysisRecord(
        public_id=public_id,
        task_public_id=task_public_id,
        failure_category=cat,
        error_message=error_message[:500],
        tool_name=tool_name,
        plan_step_id=plan_step_id,
        context=context[:500],
        recovered=recovered,
        repair_strategy=repair_strategy,
    )
    with sync_session_scope() as session:
        session.add(record)
    return public_id


def get_failure_stats() -> dict[str, Any]:
    """Return aggregate failure statistics across all records."""
    with sync_session_scope() as session:
        total = len(session.exec(select(FailureAnalysisRecord)).all())
        if total == 0:
            return {"total": 0, "by_category": {}, "top_tool_failures": [], "recovery_rate": 0.0}

        by_category: dict[str, int] = {}
        tool_failures: dict[str, int] = {}
        recovered = 0
        top_patterns: Counter = Counter()

        rows = session.exec(select(FailureAnalysisRecord)).all()
        for r in rows:
            cat = r.failure_category.value if hasattr(r.failure_category, "value") else str(r.failure_category)
            by_category[cat] = by_category.get(cat, 0) + 1
            if r.tool_name:
                tool_failures[r.tool_name] = tool_failures.get(r.tool_name, 0) + 1
            if r.recovered:
                recovered += 1

            err_lower = r.error_message.lower()
            for pattern in [
                "timeout", "not found", "permission", "invalid",
                "connection", "unavailable", "crash",
            ]:
                if pattern in err_lower:
                    top_patterns[pattern] += 1

        return {
            "total": total,
            "by_category": dict(sorted(by_category.items(), key=lambda x: x[1], reverse=True)),
            "top_tool_failures": dict(sorted(tool_failures.items(), key=lambda x: x[1], reverse=True)[:10]),
            "recovery_rate": round(recovered / total, 3),
            "top_patterns": dict(top_patterns.most_common(10)),
        }


def get_failures_for_task(task_public_id: str) -> list[dict[str, Any]]:
    """Return all failure records for a specific task."""
    with sync_session_scope() as session:
        rows = (
            session.exec(
                select(FailureAnalysisRecord)
                .where(FailureAnalysisRecord.task_public_id == task_public_id)
                .order_by(FailureAnalysisRecord.created_at)
            )
            .all()
        )
        return [
            {
                "public_id": r.public_id,
                "failure_category": r.failure_category.value if hasattr(r.failure_category, "value") else str(r.failure_category),
                "error_message": r.error_message,
                "tool_name": r.tool_name,
                "plan_step_id": r.plan_step_id,
                "recovered": r.recovered,
                "repair_strategy": r.repair_strategy,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
