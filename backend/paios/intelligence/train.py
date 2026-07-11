"""Training entrypoint — trains and saves all micro-models.

Usage:
    python -c "from paios.intelligence.train import train_all; train_all()"
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from paios.config import DATA_DIR
from paios.intelligence.intent.dataset import IntentDataset
from paios.intelligence.intent.trainer import train_model
from paios.intelligence.tool_selector.dataset import ToolSelectionDataset
from paios.intelligence.tool_selector.trainer import train_tool_selector

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("train")


def train_intent_classifier(output_dir: str | Path | None = None) -> None:
    """Generate expanded dataset, train the intent classifier, save model."""
    logger.info("=" * 60)
    logger.info("Training intent classifier")
    logger.info("=" * 60)

    out = Path(output_dir) if output_dir else (DATA_DIR / "models")

    dataset = IntentDataset.generate_expanded(target_per_category=200, seed=42)
    logger.info("Generated %d examples", len(dataset))
    bal = dataset.balance_report()
    logger.info("Balance: min=%d, max=%d, ratio=%.2f", bal["min"], bal["max"], bal["imbalance_ratio"])

    model, metrics = train_model(
        dataset=dataset,
        test_ratio=0.2,
        seed=42,
        output_dir=out,
    )

    logger.info("Intent classifier trained — accuracy=%.3f, macro_f1=%.3f", metrics["accuracy"], metrics["macro_f1"])
    logger.info("Model saved to %s", metrics.get("model_path"))

    weak = metrics.get("weak_categories", [])
    if weak:
        logger.warning("Weak categories (F1 < 0.7): %s", ", ".join(weak))


def train_tool_selector_model(output_dir: str | Path | None = None) -> None:
    """Train the tool selector model."""
    logger.info("=" * 60)
    logger.info("Training tool selector model")
    logger.info("=" * 60)

    out = Path(output_dir) if output_dir else (DATA_DIR / "models")

    dataset = ToolSelectionDataset.generate_expanded(target=500, seed=42)
    logger.info("Generated %d examples", len(dataset))

    model, metrics = train_tool_selector(
        dataset=dataset,
        test_ratio=0.2,
        seed=42,
        output_dir=out,
    )

    logger.info("Tool selector trained — precision@1=%.3f, recall@3=%.3f", metrics.get("precision@1", 0), metrics.get("recall@3", 0))
    logger.info("Model saved to %s", metrics.get("model_path"))


def train_all(output_dir: str | Path | None = None) -> None:
    """Train all micro-models."""
    train_intent_classifier(output_dir)
    print()
    train_tool_selector_model(output_dir)
    logger.info("All models trained successfully.")


if __name__ == "__main__":
    train_all()
