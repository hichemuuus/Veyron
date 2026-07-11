"""Memory quality scoring — assess usefulness, reliability, and success frequency.

Each memory gets quality scores that influence retrieval ranking and
lifecycle decisions. Scores are updated based on usage patterns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from paios.db.base import sync_session_scope
from paios.db.models import Memory

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
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)

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
        mem = session.query(Memory).filter(Memory.public_id == public_id).first()
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
            batch = session.query(Memory).offset(offset).limit(batch_size).all()
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
