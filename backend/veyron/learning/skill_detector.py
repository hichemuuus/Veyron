"""Skill detection — discover repeated workflow patterns from user history."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from veyron.intelligence.training.dataset import load_user_interactions

logger = logging.getLogger(__name__)

MIN_PATTERN_FREQUENCY = 3  # minimum occurrences to suggest a skill
PATTERN_TIME_WINDOW_MINUTES = 30  # max time between steps in a pattern


@dataclass
class DetectedSkill:
    name: str
    description: str
    steps: list[dict[str, Any]]
    frequency: int
    confidence: float
    source_pattern: str


class SkillDetector:
    """Detects repeated workflow patterns from user interaction history."""

    def __init__(self, min_frequency: int = MIN_PATTERN_FREQUENCY):
        self.min_frequency = min_frequency

    def detect_skills(self, interactions: list | None = None) -> list[DetectedSkill]:
        """Scan user interactions and detect repeated patterns."""
        if interactions is None:
            interactions = load_user_interactions()

        tool_sequences = self._extract_tool_sequences(interactions)
        patterns = self._find_repeated_patterns(tool_sequences)
        return self._build_skills(patterns)

    def detect_skills_from_tasks(self, task_history: list[dict]) -> list[DetectedSkill]:
        """Detect skills from a list of task dicts with 'request' and 'tools_used' keys."""
        tool_sequences: list[list[str]] = []
        for task in task_history:
            tools = task.get("tools_used", [])
            if isinstance(tools, list) and len(tools) >= 2:
                tool_names = [t.get("name", t) if isinstance(t, dict) else str(t) for t in tools]
                tool_sequences.append(tool_names)
        patterns = self._find_repeated_patterns(tool_sequences)
        return self._build_skills(patterns)

    def _extract_tool_sequences(self, interactions: list) -> list[list[str]]:
        """Extract ordered tool call sequences from user interactions."""
        sequences: list[list[str]] = []
        for ui in interactions:
            # UserInteraction uses selected_tools; fall back to metadata for other types
            tools = getattr(ui, "selected_tools", None)
            if not tools and hasattr(ui, "metadata"):
                tools = ui.metadata.get("tools_used", [])
            if not tools:
                tools = getattr(ui, "tools_used", [])
            if isinstance(tools, list) and len(tools) >= 2:
                sequences.append([t.get("name", t) if isinstance(t, dict) else str(t) for t in tools])
        return sequences

    def _find_repeated_patterns(self, sequences: list[list[str]]) -> list[tuple[tuple[str, ...], int]]:
        """Find sub-sequences that appear multiple times."""
        pattern_counts: Counter[tuple[str, ...]] = Counter()
        for seq in sequences:
            if len(seq) < 2:
                continue
            # Consider full sequence and consecutive sub-sequences
            pattern_counts[tuple(seq)] += 1
            for i in range(len(seq) - 1):
                sub = tuple(seq[i:i+2])
                pattern_counts[sub] += 1
            for i in range(len(seq) - 2):
                sub = tuple(seq[i:i+3])
                pattern_counts[sub] += 1

        repeated = [(p, c) for p, c in pattern_counts.items() if c >= self.min_frequency]
        repeated.sort(key=lambda x: (-len(x[0]), -x[1]))
        return repeated

    def _build_skills(self, patterns: list[tuple[tuple[str, ...], int]]) -> list[DetectedSkill]:
        """Convert detected patterns to skill objects."""
        skills: list[DetectedSkill] = []
        for pattern, count in patterns:
            steps = [{"step_type": "tool_call", "tool_name": t, "params": {}} for t in pattern]
            confidence = min(0.5 + (count - self.min_frequency) * 0.1, 0.95)
            name = self._generate_skill_name(pattern)
            skills.append(DetectedSkill(
                name=name,
                description=f"Automated workflow: {' → '.join(pattern)} (seen {count}x)",
                steps=steps,
                frequency=count,
                confidence=confidence,
                source_pattern=" → ".join(pattern),
            ))
        return skills

    def _generate_skill_name(self, pattern: tuple[str, ...]) -> str:
        """Generate a human-readable name from a tool pattern."""
        name_map = {
            "read_file": "Read",
            "write_file": "Write",
            "edit_file": "Edit",
            "terminal": "Run",
            "system_monitor": "Monitor",
            "project_analyzer": "Analyze",
            "filesystem_list": "List",
            "search_files": "Search",
            "grep": "Search",
        }
        parts = [name_map.get(t, t.replace("_", " ").title()) for t in pattern[:3]]
        name = " → ".join(parts)
        if len(pattern) > 3:
            name += f" +{len(pattern) - 3}"
        return name
