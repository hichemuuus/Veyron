"""Importance scoring — scores information for long-term storage.

Determines how valuable a piece of information is for retention
based on keyword analysis, content length, recall frequency, and source.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ImportanceScorer:
    """Scores importance of information for long-term storage."""

    def __init__(self):
        self.keywords_high = {
            "security", "password", "api_key", "credential", "authentication",
            "configuration", "important", "critical", "warning", "error",
            "project", "architecture", "decision", "requirement",
        }
        self.keywords_medium = {
            "preference", "setting", "workflow", "pattern", "habit",
            "location", "file", "directory", "command", "tool",
        }

    def score(self, content: str, source: str = "", recall_count: int = 0) -> float:
        """Score importance from 0.0 to 1.0 based on content analysis.

        Args:
            content: The memory content text.
            source: Source identifier (e.g. "reflection", "user_profile").
            recall_count: Number of times this content has been recalled.

        Returns:
            Importance score between 0.0 and 1.0.
        """
        score = 0.3  # base

        content_lower = content.lower()
        for kw in self.keywords_high:
            if kw in content_lower:
                score += 0.15
        for kw in self.keywords_medium:
            if kw in content_lower:
                score += 0.08

        length_bonus = min(len(content.strip()) / 500, 0.2)
        score += length_bonus

        recall_bonus = min(recall_count * 0.02, 0.1)
        score += recall_bonus

        if source in ("reflection", "user_profile"):
            score += 0.1

        return round(min(score, 1.0), 4)

    def batch_score(self, items: list[dict]) -> list[float]:
        """Score multiple items in batch.

        Args:
            items: List of dicts with "content" and optional "source" keys.

        Returns:
            List of importance scores.
        """
        return [
            self.score(item.get("content", ""), item.get("source", ""))
            for item in items
        ]
