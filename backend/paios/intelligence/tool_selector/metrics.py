"""Evaluation metrics for the tool-selection model.

Defines how to measure prediction quality before the model is trained.
"""

from __future__ import annotations

from typing import Any

from paios.intelligence.tool_selector.schema import ToolPrediction, ToolSelectionResult


class ToolSelectionMetrics:
    """Compute evaluation metrics for tool selection predictions."""

    @staticmethod
    def tool_precision_at_k(
        predicted: list[str],
        expected: list[str],
        k: int | None = None,
    ) -> float:
        """Precision@k: fraction of predicted tools (top-k) that are relevant."""
        if k is not None:
            predicted = predicted[:k]
        if not predicted:
            return 0.0
        relevant = sum(1 for t in predicted if t in expected)
        return relevant / len(predicted)

    @staticmethod
    def tool_recall_at_k(
        predicted: list[str],
        expected: list[str],
        k: int | None = None,
    ) -> float:
        """Recall@k: fraction of expected tools found in top-k predictions."""
        if k is not None:
            predicted = predicted[:k]
        if not expected:
            return 0.0
        found = sum(1 for t in expected if t in predicted)
        return found / len(expected)

    @staticmethod
    def tool_f1_at_k(predicted: list[str], expected: list[str], k: int | None = None) -> float:
        """F1@k: harmonic mean of precision and recall."""
        p = ToolSelectionMetrics.tool_precision_at_k(predicted, expected, k)
        r = ToolSelectionMetrics.tool_recall_at_k(predicted, expected, k)
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    @staticmethod
    def exact_match(predicted: list[str], expected: list[str]) -> bool:
        """Exact match: the predicted tool list equals the expected list."""
        return predicted == expected

    @staticmethod
    def missing_parameters_penalty(prediction: ToolPrediction) -> float:
        """Penalty score based on missing parameters (0 = perfect, 1 = all missing)."""
        if not prediction.predicted_params and not prediction.missing_parameters:
            return 0.0
        total = len(prediction.predicted_params) + len(prediction.missing_parameters)
        if total == 0:
            return 0.0
        return len(prediction.missing_parameters) / total

    @classmethod
    def evaluate_all(
        cls,
        predictions: list[ToolSelectionResult],
        ground_truth: list[list[str]],
    ) -> dict[str, Any]:
        """Compute all metrics across a set of predictions."""
        n = len(predictions)
        if n == 0:
            return {}

        precisions_p1 = [cls.tool_precision_at_k(p.result, gt, k=1) for p, gt in zip(predictions, ground_truth) for result in [p.predictions]]
        # Flatten: for each request, compare predicted tool names vs ground truth.
        all_predicted = [[tp.tool_name for tp in p.predictions] for p in predictions]

        p1 = [cls.tool_precision_at_k(preds, gt, k=1) for preds, gt in zip(all_predicted, ground_truth)]
        r5 = [cls.tool_recall_at_k(preds, gt, k=5) for preds, gt in zip(all_predicted, ground_truth)]
        exact = [cls.exact_match(preds, gt) for preds, gt in zip(all_predicted, ground_truth)]

        return {
            "precision@1": round(sum(p1) / n, 4) if n > 0 else 0.0,
            "recall@5": round(sum(r5) / n, 4) if n > 0 else 0.0,
            "exact_match_rate": round(sum(exact) / n, 4) if n > 0 else 0.0,
            "total_examples": n,
        }
