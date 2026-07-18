"""User profile generation — build user profiles from memories and interactions.

Generates and maintains a user profile based on stored memories,
interaction history, and importance-scored content.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlmodel import select, delete, update, func
from veyron.db.models import Memory, MemoryCategory
from veyron.memory.importance import ImportanceScorer

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """Aggregated user profile derived from memories and interactions."""

    preferences: dict[str, Any] = field(default_factory=dict)
    frequent_actions: list[str] = field(default_factory=list)
    common_tools: list[str] = field(default_factory=list)
    known_projects: list[str] = field(default_factory=list)
    skill_patterns: list[str] = field(default_factory=list)
    memory_categories: dict[str, int] = field(default_factory=dict)
    interaction_count: int = 0
    last_updated: str = ""


class UserProfileGenerator:
    """Generates and maintains user profiles from memories and interactions."""

    def __init__(self, store: Any | None = None):
        from veyron.memory.store import MemoryStore, get_memory_store

        self.store: MemoryStore = store or get_memory_store()
        self.scorer = ImportanceScorer()

    def generate(self) -> UserProfile:
        """Generate user profile from memories and interactions.

        Scans all non-decayed memories, categorizes them, extracts
        preferences, frequent actions, common tools, known projects,
        and skill patterns.

        Returns:
            A populated UserProfile instance.
        """
        from veyron.db.base import sync_session_scope
        from veyron.db.models import Memory

        profile = UserProfile()
        profile.last_updated = datetime.now(UTC).replace(tzinfo=None).isoformat()

        with sync_session_scope() as session:
            memories = (
                session.exec(
                    select(Memory)
                    .where(Memory.decayed == False)
                    .order_by(Memory.importance.desc())
                )
                .all()
            )

        profile.interaction_count = len(memories)

        category_counts: dict[str, int] = {}
        preference_keywords = {"prefer", "like", "use", "favorite", "default"}
        action_keywords = {"run", "execute", "build", "deploy", "test", "create"}
        tool_keywords = {"tool", "command", "script", "cli", "plugin"}
        project_keywords = {"project", "repo", "repository", "app", "service"}

        for mem in memories:
            cat = mem.category.value if hasattr(mem.category, "value") else str(mem.category)
            category_counts[cat] = category_counts.get(cat, 0) + 1

            content_lower = mem.content.lower()

            if any(kw in content_lower for kw in preference_keywords):
                profile.preferences[mem.public_id] = mem.content[:100]

            if any(kw in content_lower for kw in action_keywords):
                profile.frequent_actions.append(mem.content[:80])

            if any(kw in content_lower for kw in tool_keywords):
                profile.common_tools.append(mem.content[:80])

            if any(kw in content_lower for kw in project_keywords):
                profile.known_projects.append(mem.content[:80])

            if mem.category == MemoryCategory.SKILL:
                profile.skill_patterns.append(mem.content[:100])

        profile.memory_categories = dict(
            sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
        )

        profile.frequent_actions = profile.frequent_actions[:20]
        profile.common_tools = list(set(profile.common_tools))[:20]
        profile.known_projects = list(set(profile.known_projects))[:20]
        profile.skill_patterns = profile.skill_patterns[:20]

        return profile

    def update_from_interaction(self, request: str, tools_used: list[str]) -> None:
        """Update profile incrementally from a single interaction.

        Stores a new memory entry for the interaction and updates
        the profile's interaction count.

        Args:
            request: The user request text.
            tools_used: List of tool names used in the interaction.
        """
        importance = self.scorer.score(request, source="interaction")
        self.store.store(
            category=MemoryCategory.HISTORY,
            content=f"User request: {request} | Tools: {', '.join(tools_used)}",
            importance=importance,
            tags="interaction, " + ", ".join(tools_used),
        )

    def to_dict(self, profile: UserProfile) -> dict:
        """Serialize a UserProfile to a dictionary.

        Args:
            profile: The UserProfile to serialize.

        Returns:
            Dict representation of the profile.
        """
        return {
            "preferences": profile.preferences,
            "frequent_actions": profile.frequent_actions,
            "common_tools": profile.common_tools,
            "known_projects": profile.known_projects,
            "skill_patterns": profile.skill_patterns,
            "memory_categories": profile.memory_categories,
            "interaction_count": profile.interaction_count,
            "last_updated": profile.last_updated,
        }

    def save_profile(self, profile: UserProfile) -> str:
        """Save profile as a memory entry.

        Serializes the profile to JSON and stores it as a PROFILE memory.

        Args:
            profile: The UserProfile to save.

        Returns:
            The public_id of the stored memory.
        """
        import json

        content = json.dumps(self.to_dict(profile), indent=2)
        mem = self.store.store(
            category=MemoryCategory.PROFILE,
            content=content,
            importance=0.9,
            tags="user_profile, auto_generated",
        )
        return mem.public_id
