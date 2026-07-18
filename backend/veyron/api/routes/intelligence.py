"""Intelligence dashboard API endpoint — exposes micro-model metrics."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sqlmodel import select, delete, update, func
from veyron.config import DATA_DIR, get_settings
from veyron.intelligence.intent.inference import _load_model as _load_intent_model
from veyron.intelligence.intent.inference import classify_intent
from veyron.intelligence.tool_selector.inference import _load_model as _load_ts_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _get_training_dataset_size() -> int:
    syn_path = DATA_DIR / "training" / "synthetic_training_data.jsonl"
    return _count_jsonl_lines(syn_path)


def _get_user_interaction_count() -> int:
    ui_dir = DATA_DIR / "training" / "user_interactions"
    if not ui_dir.exists():
        return 0
    total = 0
    for p in ui_dir.glob("*.jsonl"):
        total += _count_jsonl_lines(p)
    return total


def _measure_inference_latency() -> dict:
    """Measure avg inference latency for intent classifier and tool selector."""
    test_requests = [
        "how much cpu is being used",
        "list files in the current directory",
        "run npm test",
        "analyze this project",
    ]
    ic_latencies: list[float] = []
    ts_latencies: list[float] = []

    for req in test_requests:
        start = time.perf_counter()
        classify_intent(req)
        ic_latencies.append((time.perf_counter() - start) * 1000)

    from veyron.intelligence.tool_selector.inference import predict_tool_names

    for req in test_requests:
        start = time.perf_counter()
        predict_tool_names(req)
        ts_latencies.append((time.perf_counter() - start) * 1000)

    return {
        "intent_classifier_ms": round(sum(ic_latencies) / len(ic_latencies), 3) if ic_latencies else 0,
        "tool_selector_ms": round(sum(ts_latencies) / len(ts_latencies), 3) if ts_latencies else 0,
    }


class ReviewCorrection(BaseModel):
    correct_intent: str = Field(..., min_length=1, max_length=200)


@router.get("/review_queue")
async def review_queue() -> list[dict]:
    """Return the last 50 prediction logs awaiting human review."""
    from veyron.db.base import sync_session_scope
    from veyron.db.models import PredictionLog

    with sync_session_scope() as session:
        logs = (
            session.exec(
                select(PredictionLog)
                .where(PredictionLog.needs_review == True, PredictionLog.user_correction == None)
                .order_by(PredictionLog.id.desc())
                .limit(50)
            )
            .all()
        )
        return [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "model_name": log.model_name,
                "model_version": log.model_version,
                "input_text": log.input_text,
                "predicted_output": log.predicted_output,
                "confidence": log.confidence,
                "latency_ms": log.latency_ms,
            }
            for log in logs
        ]


@router.post("/review/{log_id}")
async def submit_review(log_id: int, correction: ReviewCorrection) -> dict:
    """Submit a human correction for a reviewed prediction log entry."""
    from veyron.db.base import sync_session_scope
    from veyron.db.models import PredictionLog

    with sync_session_scope() as session:
        log_entry = session.exec(select(PredictionLog).where(PredictionLog.id == log_id)).first()
        if log_entry is None:
            raise HTTPException(status_code=404, detail="prediction log not found")
        log_entry.user_correction = correction.correct_intent
        log_entry.needs_review = False
        session.add(log_entry)
    return {"status": "ok", "log_id": log_id, "corrected_to": correction.correct_intent}


@router.get("/logs")
async def prediction_logs() -> list[dict]:
    """Return the last 50 prediction log entries in reverse chronological order."""
    from veyron.db.base import sync_session_scope
    from veyron.db.models import PredictionLog

    with sync_session_scope() as session:
        logs = (
            session.exec(
                select(PredictionLog)
                .order_by(PredictionLog.id.desc())
                .limit(50)
            )
            .all()
        )
        return [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "model_name": log.model_name,
                "model_version": log.model_version,
                "input_text": log.input_text,
                "predicted_output": log.predicted_output,
                "confidence": log.confidence,
                "latency_ms": log.latency_ms,
            }
            for log in logs
        ]


@router.get("/metrics")
async def intelligence_metrics() -> dict:
    """Expose micro-model usage, LLM avoidance, latency, versions, dataset sizes."""
    ic_model = _load_intent_model()
    ts_model = _load_ts_model()

    settings = get_settings()

    latency = _measure_inference_latency()
    train_size = _get_training_dataset_size()

    return {
        "micro_models_enabled": settings.model.micro_models_enabled,
        "confidence_threshold": settings.model.micro_model_confidence_threshold,
        "models_loaded": {
            "intent_classifier": ic_model is not None,
            "tool_selector": ts_model is not None,
        },
        "inference_latency_ms": latency,
        "training_dataset_size": train_size,
        "user_interaction_count": _get_user_interaction_count(),
        "model_version": None,
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
