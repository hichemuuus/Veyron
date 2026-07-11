"""Training pipeline for the tool selection model.

Trains a multi-label classifier that predicts required tools from text.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from paios.config import DATA_DIR
from paios.intelligence.tool_selector.dataset import ToolSelectionDataset
from paios.intelligence.tool_selector.metrics import ToolSelectionMetrics
from paios.intelligence.tool_selector.model import ToolSelectorModel

logger = logging.getLogger(__name__)


def train_tool_selector(
    dataset: ToolSelectionDataset | None = None,
    test_ratio: float = 0.2,
    seed: int = 42,
    model: ToolSelectorModel | None = None,
    output_dir: str | Path | None = None,
) -> tuple[ToolSelectorModel, dict[str, Any]]:
    """Train a tool selector model and evaluate.

    Args:
        dataset: Training data. If None, generates seed dataset.
        test_ratio: Fraction held out for evaluation.
        seed: Random seed.
        model: Optional pre-configured model.
        output_dir: Directory to save model and metrics.

    Returns:
        (trained ToolSelectorModel, metrics dict).
    """
    if dataset is None:
        logger.info("no dataset provided, generating seed dataset")
        dataset = ToolSelectionDataset.generate_seed()
        logger.info("seed dataset: %d examples", len(dataset))

    logger.info("training on %d examples", len(dataset))

    # Simple train/test split (no stratification needed for multi-label).
    from paios.intelligence.intent.dataset import IntentDataset

    rng = __import__("random").Random(seed)
    indices = list(range(len(dataset)))
    rng.shuffle(indices)
    split = max(1, int(len(indices) * (1 - test_ratio)))
    train_indices = indices[:split]
    test_indices = indices[split:]

    train_examples = [dataset[i] for i in train_indices]
    test_examples = [dataset[i] for i in test_indices]

    train_texts = [ex.text for ex in train_examples]
    train_targets = [ex.expected_tools for ex in train_examples]
    test_texts = [ex.text for ex in test_examples]
    test_targets = [ex.expected_tools for ex in test_examples]

    logger.info("train: %d, test: %d", len(train_texts), len(test_texts))

    if model is None:
        model = ToolSelectorModel()

    model.fit(train_texts, train_targets)

    metrics = _evaluate(model, test_texts, test_targets) or {
        "precision@1": 0.0, "precision@3": 0.0,
        "recall@1": 0.0, "recall@3": 0.0,
        "f1@3": 0.0, "exact_match_rate": 0.0,
        "total_examples": 0,
    }
    logger.info(
        "precision@1: %.3f, recall@3: %.3f, exact_match: %.3f",
        metrics["precision@1"],
        metrics["recall@3"],
        metrics["exact_match_rate"],
    )

    # Save model and report.
    output_path = Path(output_dir) if output_dir else (DATA_DIR / "models")
    output_path.mkdir(parents=True, exist_ok=True)

    model_path = output_path / "tool_selector.pkl"
    model.save(str(model_path))
    metrics["model_path"] = str(model_path)

    report_path = output_path / "tool_selector_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info("tool selector report saved to %s", report_path)

    return model, metrics


def _evaluate(
    model: ToolSelectorModel,
    texts: list[str],
    targets: list[list[str]],
) -> dict[str, Any]:
    """Evaluate tool selector predictions with per-tool and calibration metrics."""
    n = len(texts)
    if n == 0:
        return {}

    all_predicted = [model.predict(text) for text in texts]
    all_probs = [model.predict_with_confidence(text) for text in texts]

    p1 = [ToolSelectionMetrics.tool_precision_at_k(pred, tgt, k=1) for pred, tgt in zip(all_predicted, targets)]
    p3 = [ToolSelectionMetrics.tool_precision_at_k(pred, tgt, k=3) for pred, tgt in zip(all_predicted, targets)]
    r1 = [ToolSelectionMetrics.tool_recall_at_k(pred, tgt, k=1) for pred, tgt in zip(all_predicted, targets)]
    r3 = [ToolSelectionMetrics.tool_recall_at_k(pred, tgt, k=3) for pred, tgt in zip(all_predicted, targets)]
    exact = [ToolSelectionMetrics.exact_match(pred, tgt) for pred, tgt in zip(all_predicted, targets)]

    f1_list = [ToolSelectionMetrics.tool_f1_at_k(pred, tgt, k=3) for pred, tgt in zip(all_predicted, targets)]

    # Per-tool metrics.
    from collections import defaultdict
    tool_tp: dict[str, int] = defaultdict(int)
    tool_fp: dict[str, int] = defaultdict(int)
    tool_fn: dict[str, int] = defaultdict(int)
    for pred, tgt, probs in zip(all_predicted, targets, all_probs):
        pred_set = set(pred)
        tgt_set = set(tgt)
        for t in model.tool_names:
            if t in pred_set and t in tgt_set:
                tool_tp[t] += 1
            elif t in pred_set and t not in tgt_set:
                tool_fp[t] += 1
            elif t not in pred_set and t in tgt_set:
                tool_fn[t] += 1

    per_tool: dict[str, dict[str, float]] = {}
    for t in model.tool_names:
        tp = tool_tp.get(t, 0)
        fp = tool_fp.get(t, 0)
        fn = tool_fn.get(t, 0)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        per_tool[t] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}

    # Confidence calibration buckets.
    bucket_size = 0.1
    buckets: dict[str, dict[str, float | int]] = {}
    for probs, tgt in zip(all_probs, targets):
        for p in probs:
            bucket_key = f"{p.confidence - (p.confidence % bucket_size):.1f}-{p.confidence - (p.confidence % bucket_size) + bucket_size:.1f}"
            if bucket_key not in buckets:
                buckets[bucket_key] = {"count": 0, "correct": 0, "total_confidence": 0.0}
            buckets[bucket_key]["count"] += 1  # type: ignore[operator]
            buckets[bucket_key]["total_confidence"] += p.confidence  # type: ignore[operator]
            if p.tool_name in tgt:
                buckets[bucket_key]["correct"] += 1  # type: ignore[operator]

    calibration = [
        {
            "bucket": k,
            "count": int(v["count"]),
            "accuracy": round(v["correct"] / v["count"], 4) if v["count"] > 0 else 0.0,
            "avg_confidence": round(v["total_confidence"] / v["count"], 4) if v["count"] > 0 else 0.0,
        }
        for k, v in sorted(buckets.items())
    ]

    return {
        "precision@1": round(sum(p1) / n, 4),
        "precision@3": round(sum(p3) / n, 4),
        "recall@1": round(sum(r1) / n, 4),
        "recall@3": round(sum(r3) / n, 4),
        "f1@3": round(sum(f1_list) / n, 4),
        "exact_match_rate": round(sum(exact) / n, 4),
        "per_tool": per_tool,
        "calibration": calibration,
        "total_examples": n,
    }
