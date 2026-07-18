"""Benchmark runner — evaluates v2 micro-models against v1 models and heuristic baseline.

Measures intent accuracy, tool selector precision@1/@3, latency, and estimated LLM calls avoided.
Saves structured reports to ``backend/data/reports/``.

Usage:
    python -m veyron.intelligence.training.run_benchmark
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from veyron.config import DATA_DIR
from veyron.intelligence.intent.model import IntentModel
from veyron.intelligence.tool_selector.model import ToolSelectorModel
from veyron.intelligence.training.benchmark_v2 import BenchmarkReportV2, BenchmarkV2
from veyron.intelligence.training.dataset import TEST_DATA_PATH, TRAIN_DATA_PATH
from veyron.intelligence.training.preparation.splitter import load_jsonl_as_examples
from veyron.intelligence.training.trainer_v2 import TrainingPipelineV2

logger = logging.getLogger(__name__)

SYNTHETIC_DATA_PATH = DATA_DIR / "training" / "synthetic_training_data.jsonl"
MODELS_DIR = DATA_DIR / "models"
REPORTS_DIR = DATA_DIR / "reports"


def load_v2_models() -> tuple[IntentModel, ToolSelectorModel]:
    """Load the latest v2 models from the models directory.

    Returns:
        (intent_model, tool_selector_model).

    Raises:
        FileNotFoundError: if either model file is not found.
    """
    intent_path = MODELS_DIR / "intent_classifier.pkl"
    ts_path = MODELS_DIR / "tool_selector.pkl"

    if not intent_path.exists():
        raise FileNotFoundError(f"intent model not found at {intent_path}")
    if not ts_path.exists():
        raise FileNotFoundError(f"tool selector model not found at {ts_path}")

    intent_model = IntentModel()
    intent_model.load(str(intent_path))
    logger.info("Loaded intent model from %s", intent_path)

    ts_model = ToolSelectorModel()
    ts_model.load(str(ts_path))
    logger.info("Loaded tool selector model from %s", ts_path)

    return intent_model, ts_model


def run_benchmark(dataset_path: str | Path | None = None) -> BenchmarkReportV2:
    """Run the full v2 benchmark on a strict holdout set.

    Performs a stratified 80/20 holdout split, trains v1 models on the
    training fold, and evaluates all models (v2 + v1 + heuristic) on
    the test fold only.

    Args:
        dataset_path: Path to the full JSONL dataset. Defaults to synthetic data.

    Returns:
        A BenchmarkReportV2 with all measurements.
    """
    from veyron.intelligence.training.dataset import prepare_holdout_split

    logger.info("Preparing holdout split (80/20 stratified) ...")
    train_path, test_path = prepare_holdout_split(dataset_path)

    logger.info("Loading holdout test set from %s", test_path)
    logger.info("Evaluating on holdout set: %s", test_path.name)
    test_dataset = load_jsonl_as_examples(str(test_path))
    logger.info("Loaded %d test examples", len(test_dataset))

    logger.info("Loading holdout train set from %s", train_path)
    train_dataset = load_jsonl_as_examples(str(train_path))
    logger.info("Loaded %d train examples", len(train_dataset))

    # Load v2 models from disk.
    logger.info("Loading v2 models from %s", MODELS_DIR)
    v2_intent, v2_ts = load_v2_models()

    # Train v1 models on training fold only (no test leakage).
    logger.info("Training v1 models on training fold ...")
    pipeline = TrainingPipelineV2()
    v1_intent, _ = pipeline.train_intent(train_dataset, seed=42)
    v1_ts_model = ToolSelectorModel()
    train_texts = [ex.request for ex in train_dataset.examples if ex.request]
    train_targets = [ex.tools_used for ex in train_dataset.examples if ex.request]
    v1_ts_model.fit(train_texts, train_targets)

    # Run benchmark against the holdout test set only.
    logger.info("Running v2 benchmark on holdout test set ...")
    benchmark = BenchmarkV2()
    report = benchmark.run(
        dataset=test_dataset,
        v2_intent_model=v2_intent,
        v1_intent_model=v1_intent,
        v2_ts_model=v2_ts,
        v1_ts_model=v1_ts_model,
    )

    return report


def save_reports(report: BenchmarkReportV2) -> dict[str, Path]:
    """Save benchmark reports to the reports directory.

    Args:
        report: The benchmark report to save.

    Returns:
        Dict mapping report names to file paths.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    saved: dict[str, Path] = {}

    # Full JSON report.
    json_path = REPORTS_DIR / f"benchmark_report_v2_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, default=str)
    saved["json_report"] = json_path
    logger.info("Saved JSON report to %s", json_path)

    # Text report.
    text_path = REPORTS_DIR / f"benchmark_report_v2_{timestamp}.txt"
    text_content = BenchmarkV2.print_report(report)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text_content)
    saved["text_report"] = text_path
    logger.info("Saved text report to %s", text_path)

    # Latest symlink / copy.
    latest_json = REPORTS_DIR / "benchmark_report_v2_latest.json"
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    saved["latest_report"] = latest_json

    return saved


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run Veyron v2 benchmark")
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Path to the JSONL dataset (default: synthetic_training_data.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory for reports (default: backend/data/reports)",
    )
    args = parser.parse_args()

    if args.output:
        global REPORTS_DIR
        REPORTS_DIR = Path(args.output)

    report = run_benchmark(dataset_path=args.dataset)

    print()
    print(BenchmarkV2.print_report(report))

    saved = save_reports(report)
    print(f"\nReports saved to: {REPORTS_DIR}")
    for name, path in saved.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    main()
