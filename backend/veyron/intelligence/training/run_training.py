"""Training entrypoint — loads synthetic data, trains v2 micro-models, saves artifacts.

Usage:
    python -m veyron.intelligence.training.run_training
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mlflow

from veyron.config import DATA_DIR, get_settings
from veyron.intelligence.models.registry import get_registry
from veyron.intelligence.models.schema import (
    STATUS_CANDIDATE,
    ModelMetadata,
)
from veyron.intelligence.training.dataset import (
    load_llm_generated_data,
    load_real_corrections,
    merge_llm_data,
    merge_real_corrections,
)
from veyron.intelligence.training.preparation.splitter import load_jsonl_as_examples
from veyron.intelligence.training.trainer_v2 import TrainingPipelineV2

logger = logging.getLogger(__name__)

SYNTHETIC_DATA_PATH = DATA_DIR / "training" / "synthetic_training_data.jsonl"
MODEL_VERSION = "2.0.0"
MLFLOW_TRACKING_URI = "sqlite:///mlflow.db"
MLFLOW_EXPERIMENT = "veyron_intelligence"


def _auto_promote_model(
    model_type: str,
    model_name: str,
    version: str,
    path: str,
    metrics: dict[str, float],
    primary_metric: str,
    improvement_threshold: float = 0.01,
) -> None:
    """Compare new model vs production and promote if better.

    Must be called inside an active MLflow run. Logs comparison metrics
    and the promotion decision to MLflow.
    """
    if not get_settings().model.auto_promote_models:
        logger.info("auto_promote_models=False, skipping promotion check for %s", model_type)
        mlflow.log_metric("auto_promote_skipped", 1)
        return

    registry = get_registry()
    current = registry.get_production(model_type)
    new_score = metrics.get(primary_metric, 0.0)

    if current is None:
        logger.info("No existing production %s model — promoting new model", model_type)
        registry.register(ModelMetadata(
            name=model_name,
            version=version,
            model_type=model_type,
            metrics=metrics,
            path=path,
            status=STATUS_CANDIDATE,
        ))
        registry.promote(model_type, version)
        mlflow.log_metric("promoted_to_production", 1)
        logger.info("Promoted %s v%s to production", model_type, version)
        return

    current_score = current.metrics.get(primary_metric, 0.0)
    improvement = new_score - current_score

    mlflow.log_metrics({
        f"current_{primary_metric}": current_score,
        f"new_{primary_metric}": new_score,
        f"{primary_metric}_improvement": improvement,
        "improvement_threshold": improvement_threshold,
    })

    logger.info(
        "Comparing %s %s: current=%.4f, new=%.4f (need > %.4f to promote)",
        model_type, primary_metric, current_score, new_score,
        current_score + improvement_threshold,
    )

    if new_score > current_score + improvement_threshold:
        logger.info("New %s model is better — promoting to production", model_type)
        registry.register(ModelMetadata(
            name=model_name,
            version=version,
            model_type=model_type,
            metrics=metrics,
            path=path,
            status=STATUS_CANDIDATE,
        ))
        registry.promote(model_type, version)
        mlflow.log_metric("promoted_to_production", 1)
        logger.info("Promoted %s v%s to production", model_type, version)
    else:
        logger.info("New %s model is NOT better — archiving as candidate", model_type)
        registry.register(ModelMetadata(
            name=model_name,
            version=version,
            model_type=model_type,
            metrics=metrics,
            path=path,
            status=STATUS_CANDIDATE,
        ))
        mlflow.log_metric("promoted_to_production", 0)
        logger.info("Registered %s v%s as candidate (not promoted)", model_type, version)


def compute_dataset_hash(dataset_path: Path) -> str:
    """Compute SHA-256 hash of the full dataset file contents."""
    sha256 = hashlib.sha256()
    with open(dataset_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_dataset_md5(dataset_path: Path) -> str:
    """Compute MD5 hash of the full dataset file contents."""
    md5 = hashlib.md5()
    with open(dataset_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            md5.update(chunk)
    return md5.hexdigest()


def run_training(output_dir: str | Path | None = None) -> dict[str, Any]:
    """Load synthetic data, train intent classifier v2 and tool selector v2, save artifacts.

    Args:
        output_dir: Directory to save models, reports, and metadata. Defaults to
            ``DATA_DIR / "models"``.

    Returns:
        A metadata dictionary containing timestamps, dataset hash, metrics,
        and saved file paths.
    """
    logger.info("=" * 60)
    logger.info("Veyron v2 Training Pipeline")
    logger.info("=" * 60)

    # ── 0. Initialize MLflow ─────────────────────────────────────────────────
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    logger.info("MLflow tracking URI: %s", MLFLOW_TRACKING_URI)
    logger.info("MLflow experiment: %s", MLFLOW_EXPERIMENT)

    out = Path(output_dir) if output_dir else (DATA_DIR / "models")
    out.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory: %s", out)

    # ── 1. Load dataset ──────────────────────────────────────────────────────
    logger.info("Loading synthetic training data from %s", SYNTHETIC_DATA_PATH)
    if not SYNTHETIC_DATA_PATH.is_file():
        raise FileNotFoundError(
            f"Synthetic training data not found at {SYNTHETIC_DATA_PATH}. "
            f"Run `python -m veyron.intelligence.training.generate_dataset` first."
        )
    dataset = load_jsonl_as_examples(str(SYNTHETIC_DATA_PATH))
    logger.info("Loaded %d synthetic training examples", len(dataset))

    corrections = load_real_corrections()
    if corrections:
        dataset = merge_real_corrections(dataset, corrections)
        logger.info("Merged %d real corrections → %d total examples (after dedup)",
                    len(corrections), len(dataset))
    else:
        logger.info("No real corrections found")

    llm_data = load_llm_generated_data()
    if llm_data is not None:
        dataset = merge_llm_data(dataset, llm_data)
        logger.info("Dataset after LLM merge: %d total examples", len(dataset))
    else:
        logger.info("No LLM-generated data to merge")

    dataset_summary = dataset.summary()
    logger.info("Dataset summary: %d total, %d successful, %d categories, sources=%s",
                dataset_summary["total"], dataset_summary.get("successful", 0),
                len(dataset_summary.get("categories", [])),
                dataset_summary.get("sources", {}))

    # ── 2. Compute dataset hashes ────────────────────────────────────────────
    logger.info("Computing dataset content hashes (SHA-256 + MD5)...")
    dataset_hash = compute_dataset_hash(SYNTHETIC_DATA_PATH)
    dataset_md5 = compute_dataset_md5(SYNTHETIC_DATA_PATH)
    logger.info("Dataset SHA-256: %s", dataset_hash)
    logger.info("Dataset MD5:     %s", dataset_md5)

    # ── 3. Train intent classifier ───────────────────────────────────────────
    pipeline = TrainingPipelineV2(output_dir=out)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    logger.info("Training intent classifier v2 ...")
    with mlflow.start_run(run_name=f"intent_classifier_{ts}") as intent_run:
        intent_model, intent_report = pipeline.train_intent(dataset, seed=42)

        mlflow.log_params({
            "model_type": "intent_classifier",
            "model_version": MODEL_VERSION,
            "seed": 42,
            "dataset_hash": dataset_hash,
            "dataset_md5": dataset_md5,
            "dataset_size": len(dataset),
            "real_corrections_count": len(corrections),
            "num_categories": dataset_summary.get("category_count", 0),
        })
        mlflow.log_metrics({
            "accuracy": intent_report.accuracy,
            "macro_precision": intent_report.macro_precision,
            "macro_recall": intent_report.macro_recall,
            "macro_f1": intent_report.macro_f1,
            "avg_confidence": intent_report.avg_confidence,
        })

        intent_path = out / f"intent_classifier_{ts}.pkl"
        intent_model.save(str(intent_path))
        mlflow.log_artifact(str(intent_path), artifact_path="model")
        latest = out / "intent_classifier.pkl"
        if latest.exists():
            latest.unlink()
        import shutil
        shutil.copy(str(intent_path), str(latest))

        _auto_promote_model(
            model_type="intent_classifier",
            model_name="intent_classifier",
            version=f"v{MODEL_VERSION}-{ts}",
            path=str(intent_path),
            metrics={
                "accuracy": intent_report.accuracy,
                "macro_f1": intent_report.macro_f1,
                "macro_precision": intent_report.macro_precision,
                "macro_recall": intent_report.macro_recall,
            },
            primary_metric="macro_f1",
        )

        logger.info("Intent classifier trained — accuracy=%.4f, macro_f1=%.4f",
                    intent_report.accuracy, intent_report.macro_f1)
        logger.info("MLflow run ID: %s", intent_run.info.run_id)

    # ── 4. Train tool selector ───────────────────────────────────────────────
    logger.info("Training tool selector v2 ...")
    with mlflow.start_run(run_name=f"tool_selector_{ts}") as ts_run:
        ts_model, ts_report = pipeline.train_tool_selector(dataset, seed=42)

        mlflow.log_params({
            "model_type": "tool_selector",
            "model_version": MODEL_VERSION,
            "seed": 42,
            "dataset_hash": dataset_hash,
            "dataset_md5": dataset_md5,
            "dataset_size": len(dataset),
            "real_corrections_count": len(corrections),
        })
        mlflow.log_metrics({
            "precision_at_1": ts_report.precision_at_1,
            "precision_at_3": ts_report.precision_at_3,
            "recall_at_1": ts_report.recall_at_1,
            "recall_at_3": ts_report.recall_at_3,
            "f1_at_3": ts_report.f1_at_3,
            "exact_match_rate": ts_report.exact_match_rate,
        })

        ts_path = out / f"tool_selector_{ts}.pkl"
        ts_model.save(str(ts_path))
        mlflow.log_artifact(str(ts_path), artifact_path="model")
        latest_ts = out / "tool_selector.pkl"
        if latest_ts.exists():
            latest_ts.unlink()
        import shutil
        shutil.copy(str(ts_path), str(latest_ts))

        _auto_promote_model(
            model_type="tool_selector",
            model_name="tool_selector",
            version=f"v{MODEL_VERSION}-{ts}",
            path=str(ts_path),
            metrics={
                "precision_at_1": ts_report.precision_at_1,
                "precision_at_3": ts_report.precision_at_3,
                "recall_at_1": ts_report.recall_at_1,
                "recall_at_3": ts_report.recall_at_3,
                "f1_at_3": ts_report.f1_at_3,
                "exact_match_rate": ts_report.exact_match_rate,
            },
            primary_metric="precision_at_1",
        )

        logger.info("Tool selector trained — precision@1=%.4f, recall@3=%.4f",
                    ts_report.precision_at_1, ts_report.recall_at_3)
        logger.info("MLflow run ID: %s", ts_run.info.run_id)

    # ── 5. Save evaluation reports ───────────────────────────────────────────
    saved_reports = pipeline.save_reports(
        intent_report=intent_report,
        ts_report=ts_report,
        output_dir=out,
    )
    for name, path in saved_reports.items():
        logger.info("  Saved %s -> %s", name, path)

    # ── 6. Build metadata ────────────────────────────────────────────────────
    training_timestamp = datetime.now(UTC).isoformat()
    intent_metrics = intent_report.to_dict()
    ts_metrics = ts_report.to_dict()

    metadata: dict[str, Any] = {
        "training_timestamp": training_timestamp,
        "dataset_hash": dataset_hash,
        "dataset_md5": dataset_md5,
        "dataset_path": str(SYNTHETIC_DATA_PATH),
        "dataset_size": len(dataset),
        "model_version": MODEL_VERSION,
        "models": {
            "intent_classifier_v2": {
                "path": str(intent_path),
                "metrics": intent_metrics,
            },
            "tool_selector_v2": {
                "path": str(ts_path),
                "metrics": ts_metrics,
            },
        },
        "reports": {name: str(path) for name, path in saved_reports.items()},
        "mlflow": {
            "tracking_uri": MLFLOW_TRACKING_URI,
            "experiment": MLFLOW_EXPERIMENT,
            "intent_run_id": intent_run.info.run_id,
            "tool_selector_run_id": ts_run.info.run_id,
        },
    }

    # ── 7. Save metadata JSON ────────────────────────────────────────────────
    metadata_path = out / "training_metadata_v2.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str)
    logger.info("Saved training metadata to %s", metadata_path)

    # ── 8. Save VERSION file ─────────────────────────────────────────────────
    version_path = out / "VERSION"
    version_lines = [
        f"model_version={MODEL_VERSION}",
        f"training_timestamp={training_timestamp}",
        f"dataset_hash={dataset_hash}",
        f"dataset_size={len(dataset)}",
        f"intent_accuracy={intent_report.accuracy:.4f}",
        f"intent_macro_f1={intent_report.macro_f1:.4f}",
        f"tool_selector_precision_at_1={ts_report.precision_at_1:.4f}",
        f"tool_selector_recall_at_3={ts_report.recall_at_3:.4f}",
        "",
    ]
    with open(version_path, "w", encoding="utf-8") as f:
        f.write("\n".join(version_lines))
    logger.info("Saved VERSION file to %s", version_path)

    # ── Summary ──────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Training complete!")
    logger.info("  Intent classifier  : accuracy=%.4f  macro_f1=%.4f",
                intent_report.accuracy, intent_report.macro_f1)
    logger.info("  Tool selector      : precision@1=%.4f  recall@3=%.4f",
                ts_report.precision_at_1, ts_report.recall_at_3)
    logger.info("  Models saved to    : %s", out)
    logger.info("  Metadata           : %s", metadata_path)
    logger.info("  VERSION file       : %s", version_path)
    logger.info("  MLflow             : %s", MLFLOW_TRACKING_URI)
    logger.info("=" * 60)

    return metadata


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    run_training()
