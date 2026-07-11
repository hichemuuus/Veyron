"""Memory lifecycle management — decay, deduplication, merge, and cleanup.

Extends the MemoryStore with automated maintenance operations:
- Importance decay over time (unrecalled memories fade)
- Duplicate detection via content hash
- Merge of semantically related memories
- Cleanup of decayed/below-threshold memories
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from paios.db.base import sync_session_scope
from paios.db.models import Memory, MemoryCategory

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.8  # content similarity ratio for merge candidate
DECAY_HALF_LIFE_DAYS = 30  # importance halves after this many days without recall
MIN_IMPORTANCE = 0.05  # floor below which a memory is marked decayed
CLEANUP_BATCH_SIZE = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def content_hash(content: str) -> str:
    """Return a stable hash of the memory content for exact duplicate detection."""
    return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()


def similarity_ratio(a: str, b: str) -> float:
    """Compute text similarity for merge candidate detection."""
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


# ── Decay ────────────────────────────────────────────────────────────────────


def apply_decay(
    mem: Memory,
    now: datetime | None = None,
    half_life_days: int = DECAY_HALF_LIFE_DAYS,
) -> float:
    """Compute decayed importance for a single memory.

    Decay is based on time since last recall (or creation if never recalled).
    Uses exponential decay: I' = I * 0.5^(days_since_recall / half_life)
    """
    if now is None:
        now = _utcnow()
    reference = mem.last_recalled_at or mem.created_at
    days_since = (now - reference).total_seconds() / 86400
    factor = 0.5 ** (days_since / half_life_days)
    decayed = mem.importance * factor
    return max(decayed, 0.0)


def decay_memories(
    half_life_days: int = DECAY_HALF_LIFE_DAYS,
    min_importance: float = MIN_IMPORTANCE,
    batch_size: int = CLEANUP_BATCH_SIZE,
) -> int:
    """Apply decay to all memories in the store.

    Returns the number of memories marked as decayed.
    """
    now = _utcnow()
    decayed_count = 0
    offset = 0
    while True:
        with sync_session_scope() as session:
            batch = (
                session.query(Memory)
                .filter(Memory.decayed == False)
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            for mem in batch:
                new_importance = apply_decay(mem, now, half_life_days)
                if new_importance < min_importance:
                    mem.decayed = True
                    logger.debug(
                        "memory %s decayed (importance fell to %.4f)", mem.public_id, new_importance
                    )
                    decayed_count += 1
                mem.importance = round(new_importance, 4)
                mem.updated_at = now
            offset += len(batch)
    logger.info("decay: %d memories marked decayed", decayed_count)
    return decayed_count


# ── Duplicate detection ──────────────────────────────────────────────────────


def find_duplicates(content: str) -> list[Memory]:
    """Find exact duplicates by content hash."""
    h = content_hash(content)
    with sync_session_scope() as session:
        return session.query(Memory).filter(Memory.content_hash == h).all()


def has_duplicate(content: str) -> bool:
    """Return True if an exact duplicate exists."""
    return len(find_duplicates(content)) > 0


def find_similar(content: str, threshold: float = SIMILARITY_THRESHOLD, limit: int = 5) -> list[Memory]:
    """Find semantically similar memories by text comparison."""
    h = content_hash(content)
    candidates: list[Memory] = []
    with sync_session_scope() as session:
        all_mems = session.query(Memory).filter(Memory.decayed == False).all()
    for mem in all_mems:
        if mem.content_hash == h:
            continue
        ratio = similarity_ratio(content, mem.content)
        if ratio >= threshold:
            candidates.append(mem)
    candidates.sort(key=lambda m: similarity_ratio(content, m.content), reverse=True)
    return candidates[:limit]


# ── Merge ────────────────────────────────────────────────────────────────────


def merge_memories(
    primary_id: str,
    secondary_ids: list[str],
    new_content: str | None = None,
) -> Memory | None:
    """Merge multiple memories into one. Keeps the primary, deletes secondaries.

    Combines importance (max of all), tags, and recall counts.
    """
    with sync_session_scope() as session:
        primary = session.query(Memory).filter(Memory.public_id == primary_id).first()
        if not primary:
            logger.warning("merge: primary memory %s not found", primary_id)
            return None

        max_importance = primary.importance
        total_recalls = primary.recall_count
        tags_set = set(t.strip() for t in primary.tags.split(",") if t.strip())

        for sec_id in secondary_ids:
            sec = session.query(Memory).filter(Memory.public_id == sec_id).first()
            if not sec:
                continue
            max_importance = max(max_importance, sec.importance)
            total_recalls += sec.recall_count
            tags_set.update(t.strip() for t in sec.tags.split(",") if t.strip())
            session.delete(sec)

        primary.importance = round(max_importance, 4)
        primary.recall_count = total_recalls
        primary.tags = ", ".join(sorted(tags_set))
        if new_content:
            primary.content = new_content
            primary.content_hash = content_hash(new_content)
        primary.updated_at = _utcnow()
        session.add(primary)
        session.flush()
        session.refresh(primary)
        logger.info("merged %d memories into %s", len(secondary_ids) + 1, primary_id)
        return primary


# ── Cleanup ──────────────────────────────────────────────────────────────────


def cleanup_decayed(batch_size: int = CLEANUP_BATCH_SIZE) -> int:
    """Permanently delete all decayed memories.

    Returns the number of memories deleted.
    """
    deleted = 0
    while True:
        with sync_session_scope() as session:
            batch = (
                session.query(Memory)
                .filter(Memory.decayed == True)
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            for mem in batch:
                session.delete(mem)
                deleted += 1
    logger.info("cleanup: deleted %d decayed memories", deleted)
    return deleted


def run_maintenance(
    half_life_days: int = DECAY_HALF_LIFE_DAYS,
    cleanup: bool = True,
) -> dict[str, int]:
    """Run full memory maintenance cycle.

    Returns stats dict.
    """
    stats: dict[str, int] = {}
    stats["decayed"] = decay_memories(half_life_days=half_life_days)
    if cleanup:
        stats["deleted"] = cleanup_decayed()
    return stats
