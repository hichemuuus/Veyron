"""Memory store — persistent long-term memory for the agent.

Provides CRUD and retrieval for episodic and semantic memories.
Phase 4: SQL-based search (keyword + importance/recency/quality ranking).
Phase 5: Lifecycle management (decay, dedup, merge), quality scoring,
         write policy (agent decides what to remember).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from paios.db.base import sync_session_scope
from paios.db.models import Memory, MemoryCategory
from paios.memory.lifecycle import apply_decay, content_hash, find_duplicates, has_duplicate, run_maintenance
from paios.memory.scoring import compute_scores, update_quality_scores

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MemoryStore:
    """Persistent memory store backed by SQLModel + SQLite.

    Thread-safe per-session (each operation opens its own scope).
    """

    def store(
        self,
        category: MemoryCategory | str,
        content: str,
        importance: float = 0.5,
        tags: str = "",
        source_task: str | None = None,
    ) -> Memory:
        """Create a new memory record.

        Args:
            category: MemoryCategory enum value or string.
            content: The memory content (free-form text).
            importance: 0.0–1.0 importance scale.
            tags: Comma-separated tags.
            source_task: Optional task public_id that created this memory.

        Returns:
            The persisted Memory record.
        """
        cat = MemoryCategory(category) if isinstance(category, str) else category

        # Input validation: guard against prompt injection via memory content.
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        content = content.strip()
        if len(content) == 0:
            raise ValueError("content cannot be empty")
        if len(content) > 100_000:
            raise ValueError("content exceeds maximum length (100,000 chars)")
        # Reject null bytes that could confuse LLM tokenizers.
        if "\x00" in content:
            raise ValueError("content contains null bytes")

        h = content_hash(content)
        mem = Memory(
            public_id=str(uuid4()),
            category=cat,
            content=content,
            importance=max(0.0, min(1.0, importance)),
            tags=tags,
            content_hash=h,
            source_task=source_task,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        with sync_session_scope() as session:
            session.add(mem)
            session.flush()
            session.refresh(mem)
            logger.debug("stored memory %s (category=%s)", mem.public_id, cat.value)
            return mem

    def get(self, public_id: str) -> Memory | None:
        """Retrieve a memory by public_id."""
        with sync_session_scope() as session:
            return session.query(Memory).filter(Memory.public_id == public_id).first()

    def update(
        self,
        public_id: str,
        content: str | None = None,
        importance: float | None = None,
        tags: str | None = None,
    ) -> Memory | None:
        """Update an existing memory record."""
        with sync_session_scope() as session:
            mem = session.query(Memory).filter(Memory.public_id == public_id).first()
            if not mem:
                return None
            if content is not None:
                mem.content = content
            if importance is not None:
                mem.importance = max(0.0, min(1.0, importance))
            if tags is not None:
                mem.tags = tags
            mem.updated_at = _utcnow()
            session.add(mem)
            session.flush()
            session.refresh(mem)
            return mem

    def delete(self, public_id: str) -> bool:
        """Delete a memory. Returns True if deleted, False if not found."""
        with sync_session_scope() as session:
            mem = session.query(Memory).filter(Memory.public_id == public_id).first()
            if not mem:
                return False
            session.delete(mem)
            return True

    # ── Write policy ────────────────────────────────────────────────────────

    def should_store(
        self,
        content: str,
        importance: float = 0.5,
        min_importance: float = 0.15,
    ) -> tuple[bool, str]:
        """Determine whether a piece of information is worth storing.

        Returns (should_store, reason).
        """
        if not content or not content.strip():
            return (False, "empty content")

        if importance < min_importance:
            return (False, f"importance {importance} below threshold {min_importance}")

        if has_duplicate(content):
            return (False, "duplicate content already exists")

        if len(content) < 10:
            return (False, "content too short")

        return (True, "worth storing")

    # ── Duplicate detection ─────────────────────────────────────────────────

    def find_duplicates(self, content: str) -> list[Memory]:
        """Find exact duplicates by content hash."""
        from paios.memory.lifecycle import find_duplicates as _find_dupes

        return _find_dupes(content)

    # ── Maintenance ─────────────────────────────────────────────────────────

    def run_maintenance(self, half_life_days: int = 30, cleanup: bool = True) -> dict[str, int]:
        """Run full memory lifecycle maintenance.

        Returns stats dict with 'decayed' and 'deleted' counts.
        """
        return run_maintenance(half_life_days=half_life_days, cleanup=cleanup)

    def search(
        self,
        query: str,
        category: MemoryCategory | str | None = None,
        tags: str | None = None,
        limit: int = 5,
    ) -> list[Memory]:
        """Search memories by text content with optional category/tag filter.

        Results are ranked by a simple relevance score: keyword match bonus
        + importance + recency.
        """
        with sync_session_scope() as session:
            q = session.query(Memory)
            if category:
                cat = MemoryCategory(category) if isinstance(category, str) else category
                q = q.filter(Memory.category == cat)
            if tags:
                for tag in tags.split(","):
                    tag = tag.strip()
                    if tag:
                        q = q.filter(Memory.tags.contains(tag))
            # Exclude decayed memories.
            q = q.filter(Memory.decayed == False)
            memories = q.all()

        if not query.strip():
            # Sort by importance + quality scores.
            def _sort_key(m: Memory) -> tuple:
                return (m.importance * 0.4 + m.usefulness_score * 0.3 + m.reliability_score * 0.3, m.created_at)

            return sorted(memories, key=_sort_key, reverse=True)[:limit]

        query_lower = query.lower()
        scored: list[tuple[float, Memory]] = []
        now = _utcnow()

        for mem in memories:
            if query_lower not in mem.content.lower():
                continue
            score = mem.importance * 0.4 + mem.usefulness_score * 0.3 + mem.reliability_score * 0.3
            count = mem.content.lower().count(query_lower)
            score += 0.05 * count
            # Recency bonus (memories within last hour get a boost).
            delta_hours = (now - mem.created_at).total_seconds() / 3600
            if delta_hours < 1:
                score += 0.2
            elif delta_hours < 24:
                score += 0.1
            # Recall frequency bonus.
            score += min(mem.recall_count * 0.01, 0.1)
            scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:limit]]

    def recall(self, public_id: str) -> Memory | None:
        """Mark a memory as recalled (updates recall_count, last_recalled_at, and quality scores)."""
        with sync_session_scope() as session:
            mem = session.query(Memory).filter(Memory.public_id == public_id).first()
            if not mem:
                return None
            mem.recall_count += 1
            mem.last_recalled_at = _utcnow()
            session.add(mem)
            session.flush()
            session.refresh(mem)
        # Update quality scores outside the scope to avoid state conflict.
        return update_quality_scores(public_id)

    def recent(self, category: MemoryCategory | str | None = None, limit: int = 5) -> list[Memory]:
        """Return most recently created memories."""
        with sync_session_scope() as session:
            q = session.query(Memory)
            if category:
                cat = MemoryCategory(category) if isinstance(category, str) else category
                q = q.filter(Memory.category == cat)
            return q.order_by(Memory.created_at.desc()).limit(limit).all()

    def important(self, threshold: float = 0.7, limit: int = 5) -> list[Memory]:
        """Return memories above an importance threshold, ordered by importance desc."""
        with sync_session_scope() as session:
            return (
                session.query(Memory)
                .filter(Memory.importance >= threshold)
                .order_by(Memory.importance.desc(), Memory.created_at.desc())
                .limit(limit)
                .all()
            )

    def build_context(self, query: str = "", limit: int = 5) -> str:
        """Build a context string for system prompt injection.

        Searches relevant memories and formats them as bullet points.
        """
        if query.strip():
            memories = self.search(query, limit=limit)
        else:
            memories = self.important(limit=limit)
            if not memories:
                memories = self.recent(limit=limit)

        if not memories:
            return ""

        parts: list[str] = []
        for mem in memories:
            cat = mem.category.value if hasattr(mem.category, "value") else str(mem.category)
            parts.append(f"- [{cat}] {mem.content} (importance={mem.importance})")
        return "Relevant memories:\n" + "\n".join(parts)

    def count(self) -> int:
        """Return total memory count."""
        with sync_session_scope() as session:
            return session.query(Memory).count()


# Module-level singleton for convenience.
_default_store: MemoryStore | None = None
_store_lock = threading.Lock()


def get_memory_store() -> MemoryStore:
    global _default_store
    if _default_store is None:
        with _store_lock:
            if _default_store is None:
                _default_store = MemoryStore()
    return _default_store


def reset_memory_store() -> None:
    global _default_store
    _default_store = None
