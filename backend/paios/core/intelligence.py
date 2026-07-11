"""Intelligence layer — routes requests through micro-models before falling back to the LLM.

Phase 2 upgrade: predicts complexity, planning needs, and LLM escalation
in addition to intent category.

Flow:
  1. If micro_models_enabled, run intent classifier.
  2. If confidence >= threshold, use the classified intent and metadata
     to decide routing:
       - Simple + no tool → direct answer (bypass LLM entirely)
       - Tool needed but no planning → ReAct loop
       - Planning needed → Planner delegation
       - Low confidence/complex → fall through to LLM
  3. If micro_models_disabled or low confidence, use heuristic router.
"""

from __future__ import annotations

import logging

from paios.config import get_settings
from paios.intelligence.intent.inference import (
    ClassifierResult,
    classify_intent,
    should_use_llm,
)
from paios.intelligence.intent.dataset import CATEGORY_TO_DOMAIN, CATEGORY_TO_MODE
from paios.llm.micro.router import Intent, route as heuristic_route

logger = logging.getLogger(__name__)

# Confidence thresholds for routing decisions.
_HIGH_CONFIDENCE = 0.8  # Bypass LLM entirely for simple requests.
_MEDIUM_CONFIDENCE = 0.6  # Use micro-model routing but still allow LLM for complex tasks.


def _classifier_to_intent(result: ClassifierResult) -> Intent:
    """Convert a ClassifierResult to the canonical Intent dataclass."""
    mode = CATEGORY_TO_MODE.get(result.category, "react")
    domain = CATEGORY_TO_DOMAIN.get(result.category, "general")

    # Override mode based on complexity and planning needs.
    if result.requires_planning or result.complexity == "complex":
        mode = "plan"

    return Intent(
        mode=mode,
        domain=domain,
        confidence=result.confidence,
        intent_category=result.category,
    )


def classify_request(request: str) -> Intent:
    """Classify a user request, returning an Intent for routing.

    The upgraded classifier also predicts complexity, tool needs, and
    whether LLM escalation is required. This information is used to
    decide routing:
      - High confidence + simple + no planning → ReAct (bypass LLM)
      - High confidence + planning needed → Planner
      - Low confidence → fall through to heuristic router

    Args:
        request: The user's natural-language request.

    Returns:
        An Intent dataclass compatible with the existing agent routing.
    """
    settings = get_settings()

    if settings.model.micro_models_enabled:
        result = classify_intent(request)

        threshold = settings.model.micro_model_confidence_threshold

        if not should_use_llm(result, threshold=threshold):
            logger.debug(
                "micro-model classified '%s' as '%s' (conf=%.3f, complexity=%s, plan=%s, llm=%s)",
                request[:60],
                result.category,
                result.confidence,
                result.complexity,
                result.requires_planning,
                result.requires_llm,
            )

            # Even with high confidence, simple requests that need a tool
            # still go through ReAct (not Planner). The micro-model handles
            # intent; the agent handles execution.
            return _classifier_to_intent(result)

        logger.info(
            "micro-model confidence too low (%.3f < %.2f) for '%s' — falling through",
            result.confidence,
            threshold,
            request[:60],
        )

    return heuristic_route(request)
