"""Training pipeline for the memory retrieval model.

Fits the TF-IDF ranker on a corpus of memory texts, evaluates rank quality on a
held-out split (precision@k, recall@k, MRR), and persists the model + a JSON
report.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from veyron.config import DATA_DIR
from veyron.intelligence.memory_retrieval.dataset import MemoryRetrievalDataset
from veyron.intelligence.memory_retrieval.evaluation import MemoryRetrievalEvaluator
from veyron.intelligence.memory_retrieval.model import MemoryRetrievalModel

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = DATA_DIR / "models"


def train_memory_retrieval(
    dataset: MemoryRetrievalDataset | None = None,
    model: MemoryRetrievalModel | None = None,
    output_dir: str | Path | None = None,
    test_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[MemoryRetrievalModel, dict[str, Any]]:
    """Train a memory retrieval model and produce rank-quality metrics.

    Args:
        dataset: Training data. If None, generates the synthetic dataset.
        model: Optional pre-configured model.
        output_dir: Directory to save the model and report.
        test_ratio: Fraction of examples held out for evaluation.
        seed: Random seed for the train/test split.

    Returns:
        (trained MemoryRetrievalModel, metrics dict).
    """
    if dataset is None:
        dataset = MemoryRetrievalDataset.generate_synthetic(seed=seed)
        logger.info("generated %d synthetic examples", len(dataset))

    # Shuffle + split at the *example* level. The vectorizer is fit on the
    # train split's corpus (queries + memories) so vocabulary is learned without
    # peeking at held-out queries.
    indices = list(range(len(dataset.examples)))
    rng = random.Random(seed)
    rng.shuffle(indices)
    split = max(1, int(len(indices) * (1 - test_ratio)))
    train_indices = indices[:split]
    test_indices = indices[split:] or indices[:1]  # guarantee a non-empty test set

    train_examples = [dataset.examples[i] for i in train_indices]
    test_examples = [dataset.examples[i] for i in test_indices]

    logger.info("train: %d, test: %d", len(train_examples), len(test_examples))

    if model is None:
        model = MemoryRetrievalModel()

    # Fit on the union of train queries + candidate memories.
    train_corpus: list[str] = []
    for ex in train_examples:
        train_corpus.append(ex.query)
        train_corpus.extend(ex.candidate_memories)
    model.fit(train_corpus)

    # Evaluate on the held-out examples using case dicts (the benchmark shape).
    test_cases = [
        {
            "id": f"mr_train_{i}",
            "query": ex.query,
            "candidate_memories": ex.candidate_memories,
            "relevant_indices": ex.relevant_indices,
            "difficulty": ex.difficulty,
            "category": ex.category,
        }
        for i, ex in enumerate(test_examples)
    ]
    evaluator = MemoryRetrievalEvaluator()
    metrics = evaluator.evaluate_model(model, test_cases)
    logger.info(
        "memory retrieval -> mrr=%.3f, precision@3=%.3f, recall@3=%.3f",
        metrics.get("mrr", 0.0),
        metrics.get("precision@3", 0.0),
        metrics.get("recall@3", 0.0),
    )

    output_path = Path(output_dir) if output_dir else DEFAULT_MODEL_DIR
    output_path.mkdir(parents=True, exist_ok=True)

    model_path = output_path / "memory_retrieval.pkl"
    model.save(str(model_path))
    metrics["model_path"] = str(model_path)
    metrics["vocab_size"] = model.vocab_size

    report_path = output_path / "memory_retrieval_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info("training report saved to %s", report_path)

    return model, metrics
