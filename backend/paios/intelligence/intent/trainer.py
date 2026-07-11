"""Training pipeline for the intent classification model.

Provides a `train_model()` entrypoint that:
  1. Generates an expanded dataset (or loads one from JSONL)
  2. Splits into train/test
  3. Fits the IntentModel
  4. Evaluates with full metrics (precision, recall, F1, confusion matrix, calibration)
  5. Saves the trained model and metrics report
  6. Identifies weak categories
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from paios.config import DATA_DIR
from paios.intelligence.intent.dataset import IntentDataset
from paios.intelligence.intent.model import IntentModel

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = DATA_DIR / "models"


def train_model(
    dataset: IntentDataset | None = None,
    test_ratio: float = 0.2,
    seed: int = 42,
    model: IntentModel | None = None,
    output_dir: str | Path | None = None,
) -> tuple[IntentModel, dict[str, Any]]:
    """Train an intent classifier and produce full evaluation metrics.

    Args:
        dataset: Training data. If None, generates an expanded synthetic dataset.
        test_ratio: Fraction of data held out for evaluation.
        seed: Random seed for reproducibility.
        model: Optional pre-configured IntentModel. If None, creates a default one.
        output_dir: Directory to save model and metrics. If None, uses
            DATA_DIR/models/.

    Returns:
        (trained IntentModel, full metrics dict).
    """
    if dataset is None:
        logger.info("no dataset provided, generating expanded dataset")
        dataset = IntentDataset.generate_expanded(target_per_category=200, seed=seed)
        logger.info("expanded dataset: %d examples across %d categories", len(dataset), len(dataset.label_counts()))

    # Validate and deduplicate.
    dupes_removed = dataset.remove_duplicates()
    if dupes_removed > 0:
        logger.warning("removed %d duplicate examples", dupes_removed)

    logger.info("training on %d examples", len(dataset))
    bal = dataset.balance_report()
    logger.info("balance: min=%d, max=%d, ratio=%.2f", bal["min"], bal["max"], bal["imbalance_ratio"])

    train_set, test_set = dataset.train_test_split(test_ratio=test_ratio, seed=seed)
    logger.info("train: %d, test: %d", len(train_set), len(test_set))

    if model is None:
        model = IntentModel()

    model.fit(train_set.texts, train_set.labels)

    metrics = _full_evaluate(model, test_set, train_set.labels)
    logger.info("accuracy: %.3f (%d/%d correct)", metrics["accuracy"], metrics["correct"], metrics["total"])

    # Identify weak categories.
    weak = _identify_weak_categories(metrics)
    if weak:
        logger.warning("weak categories: %s", ", ".join(weak))
    metrics["weak_categories"] = weak

    # Save model and report.
    output_path = Path(output_dir) if output_dir else (DATA_DIR / "models")
    output_path.mkdir(parents=True, exist_ok=True)

    model_path = output_path / "intent_classifier.pkl"
    model.save(str(model_path))
    metrics["model_path"] = str(model_path)

    report_path = output_path / "training_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info("training report saved to %s", report_path)

    return model, metrics


def _full_evaluate(model: IntentModel, test_set: IntentDataset, train_labels: list[str]) -> dict[str, Any]:
    """Evaluate model on held-out data with full classification metrics."""
    correct = 0
    total = len(test_set)

    all_classes = sorted(set(train_labels))
    confusion: dict[str, dict[str, int]] = {c: {c2: 0 for c2 in all_classes} for c in all_classes}
    per_category: dict[str, dict[str, int]] = {}
    confidences: list[float] = []
    correctly_confident: list[bool] = []
    mistakes: list[dict[str, Any]] = []

    for ex in test_set:
        expected = ex["intent"]
        predicted, confidence = model.predict_with_confidence(ex["text"])
        confidences.append(confidence)
        if predicted == expected:
            correct += 1
            correctly_confident.append(True)
        else:
            correctly_confident.append(False)
            mistakes.append({
                "text": ex["text"][:80],
                "expected": expected,
                "predicted": predicted,
                "confidence": round(confidence, 4),
            })
        confusion[expected][predicted] += 1

        if expected not in per_category:
            per_category[expected] = {"correct": 0, "total": 0}
        per_category[expected]["total"] += 1
        if predicted == expected:
            per_category[expected]["correct"] += 1

    # Per-category metrics.
    category_metrics = {}
    for cat in sorted(all_classes):
        tp = confusion[cat][cat]
        fp = sum(confusion[other][cat] for other in all_classes if other != cat)
        fn = sum(confusion[cat][other] for other in all_classes if other != cat)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        support = per_category.get(cat, {}).get("total", 0)
        cat_acc = per_category.get(cat, {}).get("correct", 0) / support if support > 0 else 0.0
        category_metrics[cat] = {
            "accuracy": round(cat_acc, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "support": support,
            "correct": per_category.get(cat, {}).get("correct", 0),
        }

    # Macro averages.
    macro_precision = sum(m["precision"] for m in category_metrics.values()) / len(category_metrics)
    macro_recall = sum(m["recall"] for m in category_metrics.values()) / len(category_metrics)
    macro_f1 = sum(m["f1_score"] for m in category_metrics.values()) / len(category_metrics)

    # Confidence calibration (expected confidence vs actual accuracy).
    calibration_buckets = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    calibration: list[dict[str, Any]] = []
    for i in range(len(calibration_buckets) - 1):
        lo, hi = calibration_buckets[i], calibration_buckets[i + 1]
        bucket_conf = [c for c in confidences if lo <= c < hi]
        bucket_correct = [cc for c, cc in zip(confidences, correctly_confident) if lo <= c < hi]
        if bucket_conf:
            calibration.append({
                "bucket": f"{lo:.1f}-{hi:.1f}",
                "count": len(bucket_conf),
                "avg_confidence": round(sum(bucket_conf) / len(bucket_conf), 4),
                "accuracy": round(sum(bucket_correct) / len(bucket_conf), 4) if bucket_correct else 0.0,
            })

    # Common mistakes analysis.
    mistake_pairs: dict[str, int] = {}
    for m in mistakes:
        pair = "%s -> %s" % (m["expected"], m["predicted"])
        mistake_pairs[pair] = mistake_pairs.get(pair, 0) + 1
    sorted_mistakes = sorted(mistake_pairs.items(), key=lambda x: -x[1])
    common_mistakes = [{"from_to": pair, "count": count} for pair, count in sorted_mistakes[:10]]

    # Classification report.
    accuracy = correct / total if total > 0 else 0.0

    return {
        "accuracy": round(accuracy, 4),
        "correct": correct,
        "total": total,
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "macro_f1": round(macro_f1, 4),
        "per_category": category_metrics,
        "calibration": calibration,
        "confusion_matrix": {c1: {c2: confusion[c1][c2] for c2 in all_classes} for c1 in all_classes},
        "common_mistakes": common_mistakes,
        "mistake_examples": mistakes[:10],
    }


def _identify_weak_categories(metrics: dict[str, Any]) -> list[str]:
    """Return list of categories with F1 < 0.7."""
    weak: list[str] = []
    for cat, m in metrics.get("per_category", {}).items():
        if m.get("f1_score", 1.0) < 0.7:
            weak.append(cat)
    return weak
