"""Subprocess entrypoint for training — spawned by the scheduler.

Saves the scheduler from blocking the event loop during model training.
Usage (spawned by scheduler):
    python -m veyron.intelligence.training.subprocess_train
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from veyron.config import DATA_DIR
from veyron.intelligence.training.dataset import (
    USER_INTERACTIONS_DIR,
    TrainingDataset,
    load_user_interactions,
)
from veyron.intelligence.training.retrain import RetrainingOrchestrator

logger = logging.getLogger("subprocess_train")

_LOCK_FILE = DATA_DIR / "training.lock"


def _release_lock() -> None:
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink()
    except Exception:
        pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--interactions-dir",
        type=str,
        default=str(USER_INTERACTIONS_DIR),
        help="Directory with user interaction JSONL files",
    )
    parser.add_argument(
        "--model-types",
        type=str,
        nargs="*",
        default=["intent_classifier", "tool_selector", "intent_router", "error_recovery", "planning", "memory_retrieval"],
        help="Model types to retrain",
    )
    args = parser.parse_args()

    interactions_dir = Path(args.interactions_dir)
    if not interactions_dir.is_dir():
        logger.error("interactions directory not found: %s", interactions_dir)
        _release_lock()
        sys.exit(1)

    logger.info("Loading user interactions from %s", interactions_dir)
    interactions = load_user_interactions(interactions_dir)
    logger.info("Loaded %d interactions", len(interactions))

    if not interactions:
        logger.info("No interactions to train on; exiting")
        _release_lock()
        return

    dataset = TrainingDataset([ui.to_training_example() for ui in interactions])
    dataset = dataset.deduplicate()
    logger.info("Training dataset: %d examples after dedup", len(dataset))

    orchestrator = RetrainingOrchestrator()
    model_types = args.model_types
    errors: list[str] = []

    for model_type in model_types:
        try:
            result = orchestrator.promote_if_better(dataset, model_type)
            if result.success and result.promoted:
                logger.info("Promoted %s to version %s", model_type, result.metadata.version)
            elif result.success:
                logger.info("%s: no promotion (candidate not better)", model_type)
            else:
                errors.append(f"{model_type}: {result.error}")
        except Exception as e:
            errors.append(f"{model_type}: {e}")
            logger.exception("training failed for %s", model_type)

    if errors:
        logger.warning("Training completed with %d error(s): %s", len(errors), "; ".join(errors))

    _release_lock()
    logger.info("Training subprocess complete")


if __name__ == "__main__":
    main()
