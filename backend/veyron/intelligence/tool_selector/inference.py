"""Inference API for the tool selector micro-model.

Provides `predict_tools()` as the primary entrypoint. The function:
  1. Loads the model (lazily, on first call)
  2. Runs inference
  3. Returns ordered tool predictions with confidence scores

Falls back to an empty list if no trained model is available.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from veyron.config import DATA_DIR
from veyron.intelligence.observability import log_prediction, resolve_model_version
from veyron.intelligence.tool_selector.model import ToolSelectorModel
from veyron.intelligence.tool_selector.schema import ToolPrediction

logger = logging.getLogger(__name__)

_FALLBACK_MODEL_PATH = DATA_DIR / "models" / "tool_selector.pkl"

_model: ToolSelectorModel | None = None
_model_path: str | None = None


def _resolve_model_path() -> str | None:
    """Resolve model path from the Model Registry.

    Falls back to a hardcoded default if the registry is unavailable.
    """
    if _model_path is not None:
        return _model_path

    try:
        from veyron.intelligence.models.registry import get_registry

        registry = get_registry()
        result = registry.get_production_model("tool_selector")
        if result is not None:
            path = result["path"]
            if Path(path).exists():
                return path
            logger.warning("registry points to missing model: %s", path)
        else:
            logger.info("no production tool_selector in registry")
    except Exception as e:
        logger.error("model registry lookup failed: %s", e)
        logger.info("falling back to hardcoded model path")

    fallback = str(_FALLBACK_MODEL_PATH)
    if Path(fallback).exists():
        return fallback
    return None


def _load_model() -> ToolSelectorModel | None:
    global _model
    if _model is not None:
        return _model

    path = _resolve_model_path()
    if path is None:
        logger.info("no tool selector model found (registry + fallback exhausted)")
        return None

    try:
        model = ToolSelectorModel()
        model.load(path)
        _model = model
        logger.info("tool selector model loaded from %s", path)
        return model
    except Exception as e:
        logger.error("failed to load tool selector model from %s: %s", path, e)
        return None


def predict_tools(
    text: str,
    top_k: int | None = None,
    model_path: str | None = None,
) -> list[ToolPrediction]:
    """Predict required tools for a user request.

    Args:
        text: The user's request text.
        top_k: If set, returns only the top-k predictions.
        model_path: Optional path to a trained model pickle.

    Returns:
        Ordered list of ToolPrediction with confidence scores.
        Empty list if no model is available.
    """
    global _model_path
    if model_path is not None:
        _model_path = model_path

    model = _load_model()
    if model is not None and model.fitted:
        start = time.perf_counter()
        if top_k is not None:
            result = model.predict_top_k(text, k=top_k)
        else:
            result = model.predict_with_confidence(text)
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            log_prediction(
                model_name="tool_selector",
                model_version=resolve_model_version("tool_selector"),
                input_text=text,
                predicted_output=", ".join(str(r.tool_name) for r in result[:5]),
                confidence=result[0].confidence if result else 0.0,
                latency_ms=latency_ms,
            )
        except Exception:
            pass
        return result

    return []


def predict_tool_names(
    text: str,
    confidence_threshold: float | None = None,
    model_path: str | None = None,
) -> list[str]:
    """Predict required tool names (strings only) for a user request.

    Args:
        text: The user's request text.
        confidence_threshold: Override the model's default threshold.
        model_path: Optional path to a trained model pickle.

    Returns:
        List of tool names above the confidence threshold.
        Empty list if no model is available.
    """
    global _model_path
    if model_path is not None:
        _model_path = model_path
    model = _load_model()
    if model is not None and model.fitted:
        start = time.perf_counter()
        if confidence_threshold is not None:
            old = model._confidence_threshold
            model._confidence_threshold = confidence_threshold
            result = model.predict(text)
            model._confidence_threshold = old
        else:
            result = model.predict(text)
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            log_prediction(
                model_name="tool_selector",
                model_version=resolve_model_version("tool_selector"),
                input_text=text,
                predicted_output=", ".join(result[:5]),
                confidence=0.0,
                latency_ms=latency_ms,
            )
        except Exception:
            pass
        return result
    return []


def reset_model() -> None:
    global _model, _model_path
    _model = None
    _model_path = None
