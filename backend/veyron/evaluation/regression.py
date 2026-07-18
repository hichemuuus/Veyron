"""Regression detection — compare benchmark runs and detect regressions.

Every benchmark run is stored. Future runs compare against the latest baseline
to detect degradation in any metric.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlmodel import select, delete, update, func
from veyron.db.base import sync_session_scope
from veyron.db.models import BenchmarkResult, RegressionRecord

logger = logging.getLogger(__name__)

_REGRESSION_THRESHOLDS = {
    "success_rate": 0.05,
    "plan_length": 2,
    "dependency_correctness": 0.1,
    "memory_precision": 0.1,
    "memory_recall": 0.1,
    "tool_success_rate": 0.05,
    "expected_tools_match": 0.1,
    "total_latency_ms": 500,
    "llm_latency_ms": 300,
    "memory_latency_ms": 100,
}


def get_latest_baseline_run_id() -> str | None:
    """Return the public_id of the most recent benchmark run."""
    with sync_session_scope() as session:
        row = (
            session.exec(
                select(BenchmarkResult).order_by(BenchmarkResult.created_at.desc())
            )
            .first()
        )
        if row:
            return row.run_id
        return None


def detect_regressions(
    current_run_id: str,
    baseline_run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Compare a benchmark run against a baseline and detect regressions.

    Args:
        current_run_id: The current benchmark run to evaluate.
        baseline_run_id: The baseline to compare against. If None, uses the
            most recent complete run.

    Returns:
        List of regression dicts with metric, delta, severity.
    """
    if baseline_run_id is None:
        baseline_run_id = get_latest_baseline_run_id()
        if baseline_run_id is None or baseline_run_id == current_run_id:
            return []

    with sync_session_scope() as session:
        current_results = (
            session.exec(
                select(BenchmarkResult)
                .where(BenchmarkResult.run_id == current_run_id)
            )
            .all()
        )
        baseline_results = (
            session.exec(
                select(BenchmarkResult)
                .where(BenchmarkResult.run_id == baseline_run_id)
            )
            .all()
        )

    if not current_results or not baseline_results:
        return []

    current_agg = _aggregate_results(current_results)
    baseline_agg = _aggregate_results(baseline_results)

    regressions: list[dict[str, Any]] = []

    for metric, threshold in _REGRESSION_THRESHOLDS.items():
        if metric not in current_agg or metric not in baseline_agg:
            continue

        cur = current_agg[metric]
        base = baseline_agg[metric]
        delta = cur - base

        higher_is_better = metric not in ("plan_length", "total_latency_ms", "llm_latency_ms", "memory_latency_ms")

        is_regression = False
        if higher_is_better:
            if delta < -abs(threshold):
                is_regression = True
        else:
            if delta > abs(threshold):
                is_regression = True

        if is_regression:
            severity = "critical" if abs(delta) >= abs(threshold) * 2 else "warning"
            regressions.append({
                "metric": metric,
                "baseline_value": base,
                "current_value": cur,
                "delta": delta,
                "severity": severity,
                "higher_is_better": higher_is_better,
            })

    for reg in regressions:
        _store_regression(
            baseline_run_id=baseline_run_id,
            current_run_id=current_run_id,
            metric_name=reg["metric"],
            baseline_value=reg["baseline_value"],
            current_value=reg["current_value"],
            delta=reg["delta"],
            severity=reg["severity"],
        )

    return regressions


def _aggregate_results(results: list[BenchmarkResult]) -> dict[str, float]:
    """Aggregate individual task results into summary metrics."""
    if not results:
        return {}

    n = len(results)
    successful = sum(1 for r in results if r.success)

    return {
        "success_rate": successful / n,
        "plan_length": sum(r.plan_length for r in results) / n,
        "dependency_correctness": sum(r.dependency_correctness for r in results) / n,
        "memory_precision": sum(r.memory_precision for r in results) / n,
        "memory_recall": sum(r.memory_recall for r in results) / n,
        "tool_success_rate": sum(r.tool_success_rate for r in results) / n,
        "expected_tools_match": sum(r.expected_tools_match for r in results) / n,
        "total_latency_ms": sum(r.total_latency_ms for r in results) / n,
        "llm_latency_ms": sum(r.llm_latency_ms for r in results) / n,
        "memory_latency_ms": sum(r.memory_latency_ms for r in results) / n,
    }


def _store_regression(
    baseline_run_id: str,
    current_run_id: str,
    metric_name: str,
    baseline_value: float,
    current_value: float,
    delta: float,
    severity: str,
) -> None:
    """Persist a regression record."""
    record = RegressionRecord(
        public_id=uuid4().hex,
        baseline_run_id=baseline_run_id,
        current_run_id=current_run_id,
        metric_name=metric_name,
        baseline_value=baseline_value,
        current_value=current_value,
        delta=delta,
        severity=severity,
    )
    with sync_session_scope() as session:
        session.add(record)


def get_regression_history(run_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Return regression records, optionally filtered by run_id."""
    with sync_session_scope() as session:
        stmt = select(RegressionRecord)
        if run_id:
            stmt = stmt.where(
                (RegressionRecord.baseline_run_id == run_id) |
                (RegressionRecord.current_run_id == run_id)
            )
        rows = session.exec(stmt.order_by(RegressionRecord.created_at.desc()).limit(limit)).all()
        return [
            {
                "public_id": r.public_id,
                "metric_name": r.metric_name,
                "baseline_value": r.baseline_value,
                "current_value": r.current_value,
                "delta": r.delta,
                "severity": r.severity,
                "category": r.category,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
