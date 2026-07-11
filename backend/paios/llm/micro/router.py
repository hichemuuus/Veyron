"""Heuristic intent router.

Decides whether a request takes the simple ReAct path or the complex Planner
path, plus a rough tool domain hint. This is the Phase-1 stand-in for the
Tier-1 trained classifier that arrives in Phase 2 (same interface).

Heuristics:
  - Explicit multi-step / analysis phrasing → complex.
  - Very short requests with a clear single action → simple.
  - Default → simple (ReAct loop handles most things fine).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


Mode = Literal["react", "plan"]

# Intent categories for the micro-model classifier.
INTENT_CATEGORIES = [
    "question_answering",
    "coding_task",
    "project_analysis",
    "file_operation",
    "tool_execution",
    "planning_task",
    "debugging",
    "system_management",
    "research",
    "conversation",
]


@dataclass
class Intent:
    mode: Mode
    # Rough domain hint, used to narrow tool schemas sent to the model.
    domain: str  # "system" | "filesystem" | "project" | "terminal" | "general"
    confidence: float
    # Micro-model intent category (None when using heuristic router).
    intent_category: str | None = None


_COMPLEX_PATTERNS = [
    r"\b(analyze|analyse|investigate|audit|review)\b",
    r"\b(prepare|generate|write|create) (a |an |the )?(report|summary|plan|proposal)\b",
    r"\b(plan|design|architect)\b",
    r"\b(step.by.step|multiple steps|break.?down)\b",
    r"\b(refactor|restructure|migrate)\b",
    r"\bthen\b.*\b(after|next|finally)\b",
]
_COMPLEX_RE = [re.compile(p, re.IGNORECASE) for p in _COMPLEX_PATTERNS]

_DOMAIN_KEYWORDS = {
    "system": ["cpu", "ram", "memory", "disk", "process", "performance", "health", "gpu", "usage"],
    "filesystem": ["file", "folder", "directory", "read", "list", "path", "contents", "find"],
    "project": ["project", "repo", "repository", "codebase", "todo", "stack", "framework", "architecture"],
    "terminal": ["run", "execute", "command", "shell", "git", "build", "test"],
}


def route(request: str) -> Intent:
    """Classify a user request."""
    text = request.lower()

    # Mode.
    complex_matches = sum(1 for r in _COMPLEX_RE if r.search(text))
    if complex_matches >= 1 or len(request.split()) > 24:
        mode: Mode = "plan"
        confidence = min(0.5 + 0.15 * complex_matches, 0.95)
    else:
        mode = "react"
        confidence = 0.8

    # Domain.
    scores = {d: 0 for d in _DOMAIN_KEYWORDS}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[domain] += 1
    best_domain = max(scores, key=scores.get) if any(scores.values()) else "general"
    if best_domain == "general":
        confidence *= 0.9

    return Intent(mode=mode, domain=best_domain, confidence=round(confidence, 3))
