"""Memory merging — find and merge similar memories.

Uses lifecycle similarity detection and merge operations to
consolidate related information and reduce memory fragmentation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import select, delete, update, func
from veyron.db.models import Memory
from veyron.memory.lifecycle import find_similar, merge_memories, similarity_ratio
from veyron.memory.store import get_memory_store

logger = logging.getLogger(__name__)


@dataclass
class MergePlan:
    """Describes a proposed merge of multiple memories into one."""

    primary_id: str
    secondary_ids: list[str]
    merged_content: str
    merged_importance: float
    merged_tags: list[str]
    reason: str


class MemoryMerger:
    """Finds similar memories and produces/executes merge plans."""

    def find_and_merge_similar(
        self, threshold: float = 0.75, max_merges: int = 10
    ) -> list[MergePlan]:
        """Find similar memories and produce merge plans.

        Scans all non-decayed memories, groups similar ones by content
        similarity, and returns merge plans for the top candidates.

        Args:
            threshold: Similarity ratio threshold (0.0–1.0).
            max_merges: Maximum number of merge plans to produce.

        Returns:
            List of MergePlan instances.
        """
        from veyron.db.base import sync_session_scope
        from veyron.db.models import Memory

        plans: list[MergePlan] = []
        processed: set[str] = set()

        with sync_session_scope() as session:
            all_mems = (
                session.exec(
                    select(Memory)
                    .where(Memory.decayed == False)
                    .order_by(Memory.importance.desc())
                )
                .all()
            )

        for primary in all_mems:
            if primary.public_id in processed:
                continue
            similar = find_similar(primary.content, threshold=threshold, limit=5)
            similar = [s for s in similar if s.public_id not in processed and s.public_id != primary.public_id]
            if not similar:
                continue

            secondary_ids = [s.public_id for s in similar]
            merged_content = primary.content
            merged_importance = primary.importance
            merged_tags = set(t.strip() for t in primary.tags.split(",") if t.strip())

            for s in similar:
                merged_importance = max(merged_importance, s.importance)
                merged_tags.update(t.strip() for t in s.tags.split(",") if t.strip())

            plan = MergePlan(
                primary_id=primary.public_id,
                secondary_ids=secondary_ids,
                merged_content=merged_content,
                merged_importance=round(merged_importance, 4),
                merged_tags=sorted(merged_tags),
                reason=f"similar content (threshold={threshold})",
            )
            plans.append(plan)
            processed.add(primary.public_id)
            for s in similar:
                processed.add(s.public_id)

            if len(plans) >= max_merges:
                break

        return plans

    def execute_merge(self, plan: MergePlan) -> Memory | None:
        """Execute a merge plan using lifecycle.merge_memories.

        Args:
            plan: The MergePlan to execute.

        Returns:
            The merged Memory record, or None if the primary was not found.
        """
        return merge_memories(
            primary_id=plan.primary_id,
            secondary_ids=plan.secondary_ids,
            new_content=plan.merged_content,
        )

    def suggest_merge(self, content: str) -> MergePlan | None:
        """Suggest a merge for new content against existing memories.

        Checks if the given content is similar to any existing memory
        and returns a merge plan if a suitable candidate is found.

        Args:
            content: The new content to check.

        Returns:
            A MergePlan if a similar memory is found, else None.
        """
        similar = find_similar(content, threshold=0.75, limit=1)
        if not similar:
            return None

        primary = similar[0]
        merged_tags = set(t.strip() for t in primary.tags.split(",") if t.strip())
        merged_importance = max(primary.importance, 0.5)

        return MergePlan(
            primary_id=primary.public_id,
            secondary_ids=[],
            merged_content=primary.content,
            merged_importance=round(merged_importance, 4),
            merged_tags=sorted(merged_tags),
            reason=f"suggested merge for similar content (similarity to {primary.public_id})",
        )
