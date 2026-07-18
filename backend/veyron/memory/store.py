"""Memory store — persistent long-term memory for the agent.

Provides CRUD and retrieval for episodic and semantic memories.
Phase 4: SQL-based search (keyword + importance/recency/quality ranking).
Phase 5: Lifecycle management (decay, dedup, merge), quality scoring,
         write policy (agent decides what to remember).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import select, delete, update, func

from veyron.db.base import sync_session_scope
from veyron.db.models import Memory, MemoryCategory
from veyron.memory.lifecycle import (
    content_hash,
    has_duplicate,
    run_maintenance,
)
from veyron.memory.scoring import update_quality_scores
from veyron.memory.importance import ImportanceScorer
from veyron.memory.summarization import MemorySummarizer
# Lazy imports: UserProfile, UserProfileGenerator (avoid circular with merge/user_profile)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
            return session.exec(select(Memory).where(Memory.public_id == public_id)).first()

    def update(
        self,
        public_id: str,
        content: str | None = None,
        importance: float | None = None,
        tags: str | None = None,
    ) -> Memory | None:
        """Update an existing memory record."""
        with sync_session_scope() as session:
            mem = session.exec(select(Memory).where(Memory.public_id == public_id)).first()
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
            mem = session.exec(select(Memory).where(Memory.public_id == public_id)).first()
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
        from veyron.memory.lifecycle import find_duplicates as _find_dupes

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
        use_reranker: bool = True,
    ) -> list[Memory]:
        """Search memories by text content with optional category/tag filter.

        Filters are pushed to SQLite via SQLModel. Keyword matching uses
        ``ilike`` at the database level. A generous candidate pool is fetched
        by ``LIMIT``, then scored and reranked in Python.

        Two-stage pipeline:
        1. SQL candidate retrieval (filters + LIMIT)
        2. Optional model reranking (if model available)
        """
        candidate_pool_size = max(limit * 4, 20)

        with sync_session_scope() as session:
            stmt = select(Memory)
            if category:
                cat = MemoryCategory(category) if isinstance(category, str) else category
                stmt = stmt.where(Memory.category == cat)
            if tags:
                for tag in tags.split(","):
                    tag = tag.strip()
                    if tag:
                        stmt = stmt.where(Memory.tags.contains(tag))
            stmt = stmt.where(Memory.decayed == False)

            if query.strip():
                stmt = stmt.where(Memory.content.ilike(f"%{query}%"))

            memories = session.exec(stmt.order_by(Memory.importance.desc()).limit(candidate_pool_size)).all()

        if not memories:
            return []

        if not query.strip():
            def _sort_key(m: Memory) -> tuple:
                return (m.importance * 0.4 + m.usefulness_score * 0.3 + m.reliability_score * 0.3, m.created_at)

            return sorted(memories, key=_sort_key, reverse=True)[:limit]

        query_lower = query.lower()
        scored: list[tuple[float, Memory]] = []
        now = _utcnow()

        for mem in memories:
            score = mem.importance * 0.4 + mem.usefulness_score * 0.3 + mem.reliability_score * 0.3
            count = mem.content.lower().count(query_lower)
            score += 0.05 * count
            delta_hours = (now - mem.created_at).total_seconds() / 3600
            if delta_hours < 1:
                score += 0.2
            elif delta_hours < 24:
                score += 0.1
            score += min(mem.recall_count * 0.01, 0.1)
            scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        candidate_pool = scored[:candidate_pool_size]
        final_candidates = [mem for _, mem in candidate_pool]

        if use_reranker:
            try:
                from veyron.intelligence.memory_retrieval.inference import (
                    _load_model as _load_mr_model,
                )

                reranker = _load_mr_model()
                if reranker is not None and reranker.fitted:
                    candidate_texts = [mem.content for mem in final_candidates]
                    ranked_indices = reranker.predict(query, candidate_texts, top_k=limit)
                    final_candidates = [final_candidates[i] for i in ranked_indices if i < len(final_candidates)]
            except Exception:
                logger.debug("memory retrieval reranker unavailable, using heuristic ranking")

        return final_candidates[:limit]

    def recall(self, public_id: str) -> Memory | None:
        """Mark a memory as recalled (updates recall_count, last_recalled_at, and quality scores)."""
        with sync_session_scope() as session:
            mem = session.exec(select(Memory).where(Memory.public_id == public_id)).first()
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
            stmt = select(Memory)
            if category:
                cat = MemoryCategory(category) if isinstance(category, str) else category
                stmt = stmt.where(Memory.category == cat)
            return session.exec(stmt.order_by(Memory.created_at.desc()).limit(limit)).all()

    def important(self, threshold: float = 0.7, limit: int = 5) -> list[Memory]:
        """Return memories above an importance threshold, ordered by importance desc."""
        with sync_session_scope() as session:
            return session.exec(
                select(Memory)
                .where(Memory.importance >= threshold)
                .order_by(Memory.importance.desc(), Memory.created_at.desc())
                .limit(limit)
            ).all()

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

    # ── Importance scoring ──────────────────────────────────────────────────

    def get_importance_scorer(self) -> ImportanceScorer:
        """Return the importance scorer instance."""
        return ImportanceScorer()

    # ── Similarity search ────────────────────────────────────────────────────

    def find_similar_memories(
        self, content: str, threshold: float = 0.75, limit: int = 5
    ) -> list[Memory]:
        """Find semantically similar memories.

        Args:
            content: The content to compare against.
            threshold: Similarity ratio threshold (0.0–1.0).
            limit: Maximum number of results.

        Returns:
            List of similar Memory records.
        """
        from veyron.memory.lifecycle import find_similar as _find_similar

        return _find_similar(content, threshold=threshold, limit=limit)

    def merge_similar_memories(self, threshold: float = 0.75) -> list[str]:
        """Auto-merge similar memories.

        Finds similar memories and executes merge plans automatically.

        Args:
            threshold: Similarity ratio threshold (0.0–1.0).

        Returns:
            List of primary IDs that were merged.
        """
        from veyron.memory.merge import MemoryMerger

        merger = MemoryMerger()
        plans = merger.find_and_merge_similar(threshold=threshold, max_merges=10)
        merged_ids: list[str] = []
        for plan in plans:
            result = merger.execute_merge(plan)
            if result is not None:
                merged_ids.append(plan.primary_id)
        return merged_ids

    # ── Summarization ────────────────────────────────────────────────────────

    def get_summarizer(self) -> MemorySummarizer:
        """Return the summarizer instance."""
        return MemorySummarizer()

    def summarize_category(self, category: MemoryCategory) -> str:
        """Summarize all non-decayed memories in a category.

        Args:
            category: The MemoryCategory to summarize.

        Returns:
            A summary string of all memories in the category.
        """
        with sync_session_scope() as session:
            memories = session.exec(
                select(Memory)
                .where(Memory.category == category, Memory.decayed == False)
                .order_by(Memory.importance.desc())
            ).all()
        summarizer = self.get_summarizer()
        return summarizer.summarize_group(memories, max_length=500)

    # ── User profile ────────────────────────────────────────────────────────

    def get_user_profile_generator(self):
        """Return the user profile generator."""
        from veyron.memory.user_profile import UserProfileGenerator
        return UserProfileGenerator(store=self)

    def get_user_profile(self):
        """Get or generate the user profile.

        Searches for an existing PROFILE memory and deserializes it.
        If none exists, generates a fresh profile from all memories.

        Returns:
            A UserProfile instance, or None if generation fails.
        """
        import json

        from veyron.memory.user_profile import UserProfile

        with sync_session_scope() as session:
            existing = session.exec(
                select(Memory)
                .where(Memory.category == MemoryCategory.PROFILE, Memory.decayed == False)
                .order_by(Memory.created_at.desc())
            ).first()
        if existing:
            try:
                data = json.loads(existing.content)
                return UserProfile(
                    preferences=data.get("preferences", {}),
                    frequent_actions=data.get("frequent_actions", []),
                    common_tools=data.get("common_tools", []),
                    known_projects=data.get("known_projects", []),
                    skill_patterns=data.get("skill_patterns", []),
                    memory_categories=data.get("memory_categories", {}),
                    interaction_count=data.get("interaction_count", 0),
                    last_updated=data.get("last_updated", ""),
                )
            except (json.JSONDecodeError, TypeError):
                logger.warning("failed to parse existing profile memory, regenerating")

        generator = self.get_user_profile_generator()
        return generator.generate()

    # ── Extended statistics ─────────────────────────────────────────────────

    def get_memory_stats_extended(self) -> dict:
        """Extended statistics including category summaries, tag clouds, merge history.

        Returns:
            Dict with keys: total, by_category, avg_importance, tag_cloud,
            category_summaries, merge_count.
        """
        from veyron.memory.merge import MemoryMerger

        with sync_session_scope() as session:
            all_mems = session.exec(select(Memory).where(Memory.decayed == False)).all()
            total = len(all_mems)

        by_category: dict[str, int] = {}
        total_importance = 0.0
        tag_cloud: dict[str, int] = {}

        for mem in all_mems:
            cat = mem.category.value if hasattr(mem.category, "value") else str(mem.category)
            by_category[cat] = by_category.get(cat, 0) + 1
            total_importance += mem.importance
            for tag in mem.tags.split(","):
                tag = tag.strip()
                if tag:
                    tag_cloud[tag] = tag_cloud.get(tag, 0) + 1

        avg_importance = round(total_importance / max(len(all_mems), 1), 4)
        tag_cloud_sorted = dict(sorted(tag_cloud.items(), key=lambda x: x[1], reverse=True)[:30])

        summarizer = self.get_summarizer()
        category_summaries: dict[str, str] = {}
        for cat in MemoryCategory:
            cat_mems = [m for m in all_mems if m.category == cat]
            if cat_mems:
                category_summaries[cat.value] = summarizer.summarize_group(cat_mems, max_length=200)

        return {
            "total": len(all_mems),
            "by_category": by_category,
            "avg_importance": round(total_importance / max(len(all_mems), 1), 4),
            "tag_cloud": dict(sorted(tag_cloud.items(), key=lambda x: x[1], reverse=True)[:30]),
            "category_summaries": category_summaries,
        }

    def count(self) -> int:
        """Return total memory count."""
        with sync_session_scope() as session:
            return session.exec(select(func.count()).select_from(Memory)).first() or 0

    def get_memory_scoring_summary(self):
        """Return aggregate scoring summary across all memories."""
        from veyron.memory.scoring import compute_scoring_summary
        return compute_scoring_summary()

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
