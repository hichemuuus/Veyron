"""Inference API for the intent classifier.

Provides `classify_intent()` as the primary entrypoint. The function:
  1. Loads the model (lazily, on first call)
  2. Runs inference
  3. Returns a ClassifierResult with category, confidence, complexity,
     requires_planning, requires_llm, and all probabilities

Falls back to a simple keyword heuristic if no trained model is available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paios.config import get_settings
from paios.intelligence.intent.model import IntentModel
from paios.intelligence.intent.dataset import (
    CATEGORY_COMPLEXITY,
    CATEGORY_REQUIRES_PLANNING,
    CATEGORY_REQUIRES_TOOL,
    CATEGORY_TO_DOMAIN,
    CATEGORY_TO_MODE,
)
from paios.llm.micro.router import INTENT_CATEGORIES

logger = logging.getLogger(__name__)

# Default model path relative to DATA_DIR.
DEFAULT_MODEL_PATH = "models/intent_classifier.pkl"

# Lazy-loaded model singleton.
_model: IntentModel | None = None
_model_path: str | None = None


@dataclass
class ClassifierResult:
    """Result of intent classification with routing metadata."""

    category: str
    confidence: float
    complexity: str = "simple"  # "simple" | "moderate" | "complex"
    requires_tool: bool = False
    requires_planning: bool = False
    requires_llm: bool = True
    all_probabilities: dict[str, float] = field(default_factory=dict)
    model_used: str = "none"  # "micro_model" | "fallback"
    fallback_reason: str = ""


def _default_metadata(category: str) -> dict[str, Any]:
    """Return default metadata for a category."""
    return {
        "complexity": CATEGORY_COMPLEXITY.get(category, "simple"),
        "requires_tool": CATEGORY_REQUIRES_TOOL.get(category, False),
        "requires_planning": CATEGORY_REQUIRES_PLANNING.get(category, False),
    }


def _load_model() -> IntentModel | None:
    """Load the intent model from disk (lazily). Returns None if unavailable."""
    global _model
    if _model is not None:
        return _model

    path = _model_path or str(Path(get_settings().database_url.replace("sqlite:///", "")).parent / DEFAULT_MODEL_PATH)

    model_path = Path(path)
    if not model_path.exists():
        logger.info("no intent model found at %s", model_path)
        return None

    try:
        model = IntentModel()
        model.load(str(model_path))
        _model = model
        logger.info("intent model loaded from %s", path)
        return model
    except Exception as e:
        logger.warning("failed to load intent model: %s", e)
        return None


def _fallback_classify(text: str) -> ClassifierResult:
    """Simple keyword-based fallback when no trained model is available.

    Scores each category independently and returns the best match,
    rather than using first-match-wins.
    """
    text_lower = text.lower()

    category_keywords: dict[str, tuple[list[str], float]] = {
        "system_management": (["cpu", "ram", "memory", "disk", "process", "health", "uptime", "system"], 0.6),
        "planning_task": (["then", "first", "after", "finally", "step", "subsequently"], 0.55),
        "file_operation": (["list", "read", "file", "directory", "folder", "size", "find"], 0.6),
        "tool_execution": (["run", "execute", "command", "shell", "git", "test", "npm"], 0.6),
        "project_analysis": (["project", "codebase", "repo", "repository", "dependency", "analyze", "architecture"], 0.6),
        "debugging": (["debug", "bug", "error", "fix", "crash", "broken"], 0.55),
        "coding_task": (["write", "implement", "create", "function", "class", "algorithm", "code"], 0.55),
        "research": (["search", "find information", "research", "look up", "documentation"], 0.55),
        "conversation": (["hello", "hi", "hey", "thanks", "goodbye", "bye", "joke"], 0.6),
    }

    scores: dict[str, int] = {}
    for cat, (keywords, _) in category_keywords.items():
        scores[cat] = sum(1 for kw in keywords if kw in text_lower)

    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]

    if best_score == 0:
        result = ClassifierResult(
            category="question_answering",
            confidence=0.4,
            model_used="fallback",
            fallback_reason="no strong keyword match, defaulted to question_answering",
        )
    else:
        base_confidence = category_keywords[best_category][1]
        boosted = min(base_confidence + 0.05 * (best_score - 1), 0.85)
        result = ClassifierResult(
            category=best_category,
            confidence=round(boosted, 3),
            model_used="fallback",
            fallback_reason=f"keyword matched {best_category} (score={best_score})",
        )

    # Add metadata from the category defaults.
    meta = _default_metadata(result.category)
    result.complexity = meta["complexity"]
    result.requires_tool = meta["requires_tool"]
    result.requires_planning = meta["requires_planning"]
    result.requires_llm = result.confidence < get_settings().model.micro_model_confidence_threshold

    return result


def classify_intent(text: str, model_path: str | None = None) -> ClassifierResult:
    """Classify a user request into an intent category.

    Uses the trained micro-model if available, with keyword fallback otherwise.
    Returns the best category, confidence, and routing metadata.

    Args:
        text: The user's request text.
        model_path: Optional path to a trained model pickle. Defaults to
            intent_classifier.pkl alongside the database.

    Returns:
        ClassifierResult with the predicted category and routing metadata.
    """
    global _model_path
    if model_path is not None:
        _model_path = model_path

    model = _load_model()

    if model is not None and model.fitted:
        category, confidence = model.predict_with_confidence(text)
        all_probs = model.predict_proba(text)
        meta = _default_metadata(category)
        return ClassifierResult(
            category=category,
            confidence=confidence,
            complexity=meta["complexity"],
            requires_tool=meta["requires_tool"],
            requires_planning=meta["requires_planning"],
            requires_llm=confidence < get_settings().model.micro_model_confidence_threshold,
            all_probabilities=all_probs,
            model_used="micro_model",
        )

    return _fallback_classify(text)


def should_use_llm(result: ClassifierResult, threshold: float | None = None) -> bool:
    """Determine whether to fall through to the LLM based on confidence.

    Args:
        result: The classifier result.
        threshold: Confidence threshold. Uses config value if None.

    Returns:
        True if the request should be routed to the LLM.
    """
    if threshold is None:
        threshold = get_settings().model.micro_model_confidence_threshold
    return result.confidence < threshold


def reset_model() -> None:
    """Clear the cached model and path (for testing)."""
    global _model, _model_path
    _model = None
    _model_path = None
