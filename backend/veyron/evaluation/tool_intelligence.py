"""Tool intelligence — per-tool reliability statistics and adaptive confidence.

Tracks every tool execution, computes reliability scores, and surfaces
historical performance for smarter tool selection.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlmodel import select, delete, update, func
from veyron.db.base import sync_session_scope
from veyron.db.models import ToolInvocation, ToolStats
from veyron.tools.base import classify_failure

logger = logging.getLogger(__name__)


def record_tool_execution(
    tool_name: str,
    ok: bool,
    duration_ms: int,
    error: str | None = None,
) -> None:
    """Record a tool execution and update its statistics."""
    failure_reason = None
    if not ok and error:
        failure_reason = classify_failure(error).value

    now = datetime.now(UTC).replace(tzinfo=None)

    with sync_session_scope() as session:
        stats = session.exec(select(ToolStats).where(ToolStats.tool_name == tool_name)).first()
        if stats is None:
            stats = ToolStats(tool_name=tool_name)
            session.add(stats)
            session.flush()

        stats.total_executions += 1
        stats.total_latency_ms += duration_ms

        if ok:
            stats.success_count += 1
            stats.last_successful_at = now
        else:
            stats.failure_count += 1
            stats.last_failed_at = now

        stats.success_rate = stats.success_count / max(stats.total_executions, 1)
        stats.avg_latency_ms = stats.total_latency_ms / max(stats.total_executions, 1)
        stats.reliability_score = _compute_reliability(stats)
        stats.updated_at = now

        if failure_reason:
            _update_common_failures(stats, failure_reason)

        session.add(stats)


def _compute_reliability(stats: ToolStats) -> float:
    """Compute a reliability score (0.0–1.0) from execution history.

    Factors:
    - Success rate (weighted heavily)
    - Recency of failures
    - Total execution count (more data = more confidence)
    """
    if stats.total_executions == 0:
        return 0.5

    success_weight = stats.success_rate * 0.7

    recency_penalty = 0.0
    if stats.last_failed_at and stats.last_successful_at:
        if stats.last_failed_at > stats.last_successful_at:
            recency_penalty = 0.1

    volume_bonus = min(stats.total_executions * 0.01, 0.1)

    raw = success_weight - recency_penalty + volume_bonus
    return max(0.0, min(1.0, raw))


def _update_common_failures(stats: ToolStats, reason: str) -> None:
    """Track failure reason frequency."""
    try:
        failures = json.loads(stats.common_failures) if stats.common_failures else []
    except (json.JSONDecodeError, TypeError):
        failures = []

    found = False
    for entry in failures:
        if entry.get("reason") == reason:
            entry["count"] = entry.get("count", 0) + 1
            found = True
            break
    if not found:
        failures.append({"reason": reason, "count": 1})

    stats.common_failures = json.dumps(failures[:20])


def get_tool_stats(tool_name: str) -> ToolStats | None:
    """Return current stats for a tool."""
    with sync_session_scope() as session:
        return session.exec(select(ToolStats).where(ToolStats.tool_name == tool_name)).first()


def get_all_tool_stats() -> list[dict[str, Any]]:
    """Return stats for all tools as dicts."""
    with sync_session_scope() as session:
        rows = session.exec(select(ToolStats).order_by(ToolStats.tool_name)).all()
        return [
            {
                "tool_name": r.tool_name,
                "total_executions": r.total_executions,
                "success_rate": r.success_rate,
                "avg_latency_ms": r.avg_latency_ms,
                "reliability_score": r.reliability_score,
                "common_failures": json.loads(r.common_failures) if r.common_failures else [],
                "last_successful_at": r.last_successful_at.isoformat() if r.last_successful_at else None,
                "last_failed_at": r.last_failed_at.isoformat() if r.last_failed_at else None,
            }
            for r in rows
        ]


def get_tool_reliability_scores() -> dict[str, float]:
    """Return a dict of tool_name -> reliability_score for all tools."""
    scores: dict[str, float] = {}
    with sync_session_scope() as session:
        rows = session.exec(select(ToolStats)).all()
        for r in rows:
            scores[r.tool_name] = r.reliability_score
    return scores
