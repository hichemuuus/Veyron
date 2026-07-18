"""Memory summarization — summarize groups of related memories.

Provides extractive summarization for groups of memories and
tag frequency analysis across memory collections.
"""

from __future__ import annotations

import logging
from typing import Any

from veyron.db.models import Memory

logger = logging.getLogger(__name__)


class MemorySummarizer:
    """Summarizes groups of related memories."""

    def summarize_group(self, memories: list[Memory], max_length: int = 200) -> str:
        """Summarize a list of memories into a concise paragraph.

        Uses extractive summarization: picks the highest-importance content
        up to the max_length limit.

        Args:
            memories: List of Memory records to summarize.
            max_length: Maximum character length for the summary.

        Returns:
            A summary string, or empty string if memories is empty.
        """
        if not memories:
            return ""
        if len(memories) == 1:
            return memories[0].content[:max_length]

        sorted_mems = sorted(memories, key=lambda m: m.importance, reverse=True)
        parts: list[str] = []
        current = 0
        for m in sorted_mems:
            if current >= max_length:
                break
            excerpt = m.content[: max_length - current]
            parts.append(excerpt)
            current += len(excerpt)
        return " | ".join(parts)

    def summarize_tags(self, memories: list[Memory]) -> dict[str, int]:
        """Summarize tag frequency across memories.

        Args:
            memories: List of Memory records.

        Returns:
            Dict mapping tag names to their frequency, sorted descending.
        """
        tag_counts: dict[str, int] = {}
        for m in memories:
            for tag in m.tags.split(","):
                tag = tag.strip()
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
        return dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True))
