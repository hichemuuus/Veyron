"""Memory quality scoring — assess usefulness, reliability, and success frequency.

Each memory gets quality scores that influence retrieval ranking and
lifecycle decisions. Scores are updated based on usage patterns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC

from sqlmodel import select, delete, update, func
from veyron.db.base import sync_session_scope
from veyron.db.models import Memory

logger = logging.getLogger(__name__)


@dataclass
class MemoryQualityScores:
    """Aggregated quality scores for a memory."""

    usefulness: float = 0.5
    reliability: float = 0.5
    success_frequency: float = 0.5

    @property
    def overall(self) -> float:
        """Weighted average: usefulness (0.4) + reliability (0.3) + success_freq (0.3)."""
        return round(
            self.usefulness * 0.4 + self.reliability * 0.3 + self.success_frequency * 0.3,
            4,
        )


def compute_scores(
    mem: Memory,
    recall_age_days: float | None = None,
) -> MemoryQualityScores:
    """Compute quality scores based on memory metadata.

    Args:
        mem: The memory record.
        recall_age_days: Days since last recall (None to compute from mem).

    Returns:
        MemoryQualityScores with computed fields.
    """
    from datetime import datetime

    now = datetime.now(UTC).replace(tzinfo=None)

    # Usefulness: importance * recall_frequency * recency_factor
    recall_freq = min(mem.recall_count / 20.0, 1.0) if mem.recall_count > 0 else 0.1
    days_since_created = (now - mem.created_at).total_seconds() / 86400
    recency_factor = max(0.1, 1.0 - days_since_created / 365)  # decays over a year
    usefulness = round(mem.importance * 0.5 + recall_freq * 0.3 + recency_factor * 0.2, 4)
    usefulness = max(0.0, min(1.0, usefulness))

    # Reliability: based on how consistently the memory has been recalled
    # Higher recall_count with older memory = more reliable signal
    if days_since_created < 1:
        reliability = 0.3  # too new to be reliable
    elif mem.recall_count == 0:
        reliability = 0.2  # never recalled, low reliability
    else:
        # More recalls per unit time = more reliable
        recalls_per_day = mem.recall_count / max(days_since_created, 1)
        reliability = min(recalls_per_day * 5, 1.0)

    # Success frequency: proportion of positive outcomes (recalled and useful)
    # Falls back to importance as a proxy when we have limited data
    if mem.recall_count > 0:
        success_freq = min(0.5 + usefulness * 0.5, 1.0)
    else:
        success_freq = mem.importance * 0.5

    return MemoryQualityScores(
        usefulness=usefulness,
        reliability=round(reliability, 4),
        success_frequency=round(success_freq, 4),
    )


def update_quality_scores(public_id: str) -> Memory | None:
    """Recalculate and persist quality scores for a single memory."""
    with sync_session_scope() as session:
        mem = session.exec(select(Memory).where(Memory.public_id == public_id)).first()
        if not mem:
            return None
        scores = compute_scores(mem)
        mem.usefulness_score = scores.usefulness
        mem.reliability_score = scores.reliability
        mem.success_frequency = scores.success_frequency
        session.add(mem)
        session.flush()
        session.refresh(mem)
        return mem


def update_all_quality_scores(batch_size: int = 100) -> int:
    """Recalculate quality scores for all memories.

    Returns the number updated.
    """
    updated = 0
    offset = 0
    while True:
        with sync_session_scope() as session:
            batch = session.exec(select(Memory).offset(offset).limit(batch_size)).all()
            if not batch:
                break
            for mem in batch:
                scores = compute_scores(mem)
                mem.usefulness_score = scores.usefulness
                mem.reliability_score = scores.reliability
                mem.success_frequency = scores.success_frequency
            offset += len(batch)
            updated += len(batch)
    logger.info("updated quality scores for %d memories", updated)
    return updated


@dataclass
class MemoryScoringSummary:
    """Aggregated scoring summary across all memories."""

    total: int = 0
    avg_importance: float = 0.0
    avg_usefulness: float = 0.0
    avg_reliability: float = 0.0
    avg_success_frequency: float = 0.0
    high_value_count: int = 0
    low_value_count: int = 0


def compute_scoring_summary() -> MemoryScoringSummary:
    """Compute aggregate scoring summary across all memories.

    Iterates all non-decayed memories and computes averages for
    importance, usefulness, reliability, and success frequency.
    Also counts high-value (overall > 0.7) and low-value (overall < 0.3) memories.

    Returns:
        A MemoryScoringSummary with aggregate statistics.
    """
    with sync_session_scope() as session:
        memories = session.exec(select(Memory).where(Memory.decayed == False)).all()

    if not memories:
        return MemoryScoringSummary()

    total = len(memories)
    total_importance = 0.0
    total_usefulness = 0.0
    total_reliability = 0.0
    total_success = 0.0
    high_value = 0
    low_value = 0

    for mem in memories:
        total_importance += mem.importance
        total_usefulness += mem.usefulness_score
        total_reliability += mem.reliability_score
        total_success += mem.success_frequency
        overall = (
            mem.usefulness_score * 0.4
            + mem.reliability_score * 0.3
            + mem.success_frequency * 0.3
        )
        if overall > 0.7:
            high_value += 1
        elif overall < 0.3:
            low_value += 1

    return MemoryScoringSummary(
        total=total,
        avg_importance=round(total_importance / total, 4),
        avg_usefulness=round(total_usefulness / total, 4),
        avg_reliability=round(total_reliability / total, 4),
        avg_success_frequency=round(total_success / total, 4),
        high_value_count=high_value,
        low_value_count=low_value,
    )


def score_new_content(
    content: str, source: str = ""
) -> tuple[float, float, float]:
    """Score new content before storage: importance, usefulness estimate, reliability estimate.

    Uses the ImportanceScorer for importance, then derives usefulness
    and reliability estimates from content characteristics.

    Args:
        content: The content to score.
        source: Optional source identifier.

    Returns:
        Tuple of (importance, usefulness_estimate, reliability_estimate).
    """
    from veyron.memory.importance import ImportanceScorer

    scorer = ImportanceScorer()
    importance = scorer.score(content, source=source)

    content_len = len(content.strip())
    usefulness = round(min(0.5 + importance * 0.3 + min(content_len / 1000, 0.2), 1.0), 4)
    reliability = round(0.3 + importance * 0.4, 4)

    return (importance, usefulness, reliability)
