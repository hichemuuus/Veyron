"""Inference API for the intent router micro-model.

Provides ``route_request()`` as the primary entrypoint. Uses per-field
confidence thresholds to decide which predictions to trust:

  - mode confidence >= 0.65   → use model prediction
  - domain confidence >= 0.50 → use model prediction
  - intent confidence >= 0.50 → use model prediction

Fields below threshold are marked for heuristic fallback by the caller.
Returns ``requires_llm=True`` if too many fields are uncertain.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from veyron.intelligence.observability import log_prediction, resolve_model_version
from veyron.intelligence.intent_router.model import IntentRouterModel
from veyron.intelligence.intent_router.schema import (
    DOMAIN_THRESHOLD,
    INTENT_THRESHOLD,
    MODE_THRESHOLD,
    IntentRouterPrediction,
)

logger = logging.getLogger(__name__)

from veyron.config import DATA_DIR

_model: IntentRouterModel | None = None
_model_path: str | None = None

_FALLBACK_MODEL_PATH = DATA_DIR / "models" / "intent_router.pkl"


def _resolve_model_path() -> str | None:
    """Resolve model path from the Model Registry.

    Falls back to a hardcoded default if the registry is unavailable.
    """
    if _model_path is not None:
        return _model_path

    try:
        from veyron.intelligence.models.registry import get_registry

        registry = get_registry()
        result = registry.get_production_model("intent_router")
        if result is not None:
            path = result["path"]
            if Path(path).exists():
                return path
            logger.warning("registry points to missing model: %s", path)
        else:
            logger.info("no production intent_router in registry")
    except Exception as e:
        logger.error("model registry lookup failed: %s", e)
        logger.info("falling back to hardcoded model path")

    fallback = str(_FALLBACK_MODEL_PATH)
    if Path(fallback).exists():
        return fallback
    return None


def _load_model() -> IntentRouterModel | None:
    global _model
    if _model is not None:
        return _model

    path = _resolve_model_path()
    if path is None:
        logger.info("no intent router model found (registry + fallback exhausted)")
        return None

    try:
        model = IntentRouterModel()
        model.load(path)
        _model = model
        logger.info("intent router model loaded from %s", path)
        return model
    except Exception as e:
        logger.error("failed to load intent router model from %s: %s", path, e)
        return None


def route_request(
    request: str,
    model_path: str | None = None,
) -> IntentRouterPrediction:
    """Route a user request through the trained model with per-field fallback.

    Args:
        request: The user's request text.
        model_path: Optional custom path to a trained model pickle.

    Returns:
        IntentRouterPrediction with per-field predictions and confidences.
        ``requires_llm`` is True when the model is unavailable or confidence
        is too low across multiple fields.
    """
    global _model_path
    if model_path is not None:
        _model_path = model_path

    if not request or not request.strip():
        return IntentRouterPrediction(
            request=request,
            requires_llm=True,
            fallback_fields=["mode", "domain", "intent_category"],
        )

    model = _load_model()
    if model is None or not model.fitted:
        return IntentRouterPrediction(
            request=request,
            requires_llm=True,
            fallback_fields=["mode", "domain", "intent_category"],
        )

    start = time.perf_counter()
    confidences = model.predict_with_confidence(request)
    latency_ms = (time.perf_counter() - start) * 1000

    mode_pred, mode_conf = confidences.get("mode", ("react", 0.0))
    domain_pred, domain_conf = confidences.get("domain", ("general", 0.0))
    intent_pred, intent_conf = confidences.get("intent_category", ("conversation", 0.0))

    fallback_fields: list[str] = []
    if mode_conf < MODE_THRESHOLD:
        fallback_fields.append("mode")
    if domain_conf < DOMAIN_THRESHOLD:
        fallback_fields.append("domain")
    if intent_conf < INTENT_THRESHOLD:
        fallback_fields.append("intent_category")

    requires_llm = len(fallback_fields) >= 2 or (
        len(fallback_fields) == 1 and mode_conf < MODE_THRESHOLD
    )

    try:
        log_prediction(
            model_name="intent_router",
            model_version=resolve_model_version("intent_router"),
            input_text=request,
            predicted_output=f"mode={mode_pred}, domain={domain_pred}, intent={intent_pred}",
            confidence=min(mode_conf, domain_conf, intent_conf),
            latency_ms=latency_ms,
        )
    except Exception:
        pass

    return IntentRouterPrediction(
        request=request,
        mode=mode_pred,
        mode_confidence=mode_conf,
        domain=domain_pred,
        domain_confidence=domain_conf,
        intent_category=intent_pred,
        intent_confidence=intent_conf,
        requires_llm=requires_llm,
        fallback_fields=fallback_fields,
    )


def reset_model() -> None:
    """Clear the cached model (primarily for tests)."""
    global _model, _model_path
    _model = None
    _model_path = None
