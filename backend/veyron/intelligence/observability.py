"""Observability utilities for ML inference tracking.

Provides ``log_prediction()`` for writing prediction records to the database
and ``resolve_model_version()`` for looking up version strings from the
Model Registry.
"""

from __future__ import annotations

import logging

from veyron.db.base import sync_session_scope
from veyron.db.models import PredictionLog

logger = logging.getLogger(__name__)

_REGISTRY_CACHE: dict[str, str] = {}


def resolve_model_version(model_type: str) -> str:
    """Return the version string for the production *model_type* from the
    Model Registry.  Cached after first lookup.  Returns ``""`` on failure."""
    cached = _REGISTRY_CACHE.get(model_type)
    if cached is not None:
        return cached

    try:
        from veyron.intelligence.models.registry import get_registry

        registry = get_registry()
        result = registry.get_production_model(model_type)
        if result is not None:
            version = result["metadata"].get("version", "") or ""
            _REGISTRY_CACHE[model_type] = version
            return version
    except Exception:
        logger.debug("failed to resolve version for %s", model_type, exc_info=True)

    _REGISTRY_CACHE[model_type] = ""
    return ""


def log_prediction(
    model_name: str,
    model_version: str,
    input_text: str,
    predicted_output: str,
    confidence: float,
    latency_ms: float,
    confidence_threshold: float = 0.6,
) -> None:
    """Persist a prediction record to the database.

    If *confidence* is below *confidence_threshold* the record is flagged
    for human review (``needs_review=True``).

    This is designed to be non-fatal: all exceptions are caught, logged at
    **warning** level, and silently swallowed so callers never need to wrap
    the call.
    """
    try:
        with sync_session_scope() as session:
            record = PredictionLog(
                model_name=model_name,
                model_version=model_version,
                input_text=input_text[:500],
                predicted_output=str(predicted_output)[:500],
                confidence=round(confidence, 4),
                latency_ms=round(latency_ms, 2),
                needs_review=confidence < confidence_threshold,
            )
            session.add(record)
    except Exception as e:
        logger.warning("failed to log prediction: %s", e)
