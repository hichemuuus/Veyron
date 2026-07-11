"""Tool selection model — predicts which tools are needed for a user request.

Maps text → ordered list of tool predictions with confidence scores.
Uses TF-IDF + multi-label classification (OneVsRest with LogisticRegression).
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

from paios.intelligence.tool_selector.schema import ToolPrediction

logger = logging.getLogger(__name__)


class ToolSelectorModel:
    """Multi-label classifier that predicts required tools from request text.

    Supports sklearn-compatible multi-label estimators. Defaults to a
    TF-IDF vectorizer + OneVsRest(LogisticRegression) pipeline.
    """

    def __init__(self, estimator: Any | None = None, confidence_threshold: float = 0.3) -> None:
        self._estimator = estimator
        self._tool_names: list[str] = []
        self._fitted = False
        self._confidence_threshold = confidence_threshold

    @property
    def fitted(self) -> bool:
        return self._fitted

    @property
    def tool_names(self) -> list[str]:
        return self._tool_names

    def fit(self, X: list[str], y: list[list[str]]) -> None:
        """Fit on text samples and multi-label tool targets.

        Args:
            X: List of input texts.
            y: List of tool-name lists (one per text).
        """
        all_tools: set[str] = set()
        for tools in y:
            all_tools.update(tools)
        self._tool_names = sorted(all_tools)

        if self._estimator is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.multiclass import OneVsRestClassifier
            from sklearn.pipeline import Pipeline

            self._estimator = Pipeline([
                ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 3), sublinear_tf=True)),
                ("clf", OneVsRestClassifier(LogisticRegression(max_iter=2000, C=1.5, class_weight="balanced"))),
            ])

        # Convert multi-label y to binary matrix.
        from sklearn.preprocessing import MultiLabelBinarizer

        self._mlb = MultiLabelBinarizer(classes=self._tool_names)
        y_bin = self._mlb.fit_transform(y)
        self._estimator.fit(X, y_bin)
        self._fitted = True

    def predict(self, text: str) -> list[str]:
        """Return sorted list of predicted tool names above confidence threshold.

        For OneVsRestClassifier, predict_proba returns a single array of
        shape (n_classes,) for a single sample, where each value is the
        positive-class probability.
        """
        if not self._fitted:
            raise RuntimeError("model not fitted")
        probs = self._estimator.predict_proba([text])[0]
        result = []
        for i, tool_name in enumerate(self._tool_names):
            prob = probs[i]
            if prob >= self._confidence_threshold:
                result.append((tool_name, prob))
        result.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in result]

    def predict_with_confidence(self, text: str) -> list[ToolPrediction]:
        """Return ordered list of ToolPredictions with confidence scores."""
        if not self._fitted:
            raise RuntimeError("model not fitted")
        probs = self._estimator.predict_proba([text])[0]
        predictions = [
            ToolPrediction(tool_name=tool, confidence=round(float(probs[i]), 4))
            for i, tool in enumerate(self._tool_names)
        ]
        predictions.sort(key=lambda p: p.confidence, reverse=True)
        return predictions

    def predict_top_k(self, text: str, k: int = 3) -> list[ToolPrediction]:
        """Return top-k tool predictions."""
        return self.predict_with_confidence(text)[:k]

    def save(self, path: str | Path) -> None:
        """Serialise to disk."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "estimator": self._estimator,
                "tool_names": self._tool_names,
                "mlb": self._mlb,
                "confidence_threshold": self._confidence_threshold,
            }, f)
        logger.info("tool selector model saved to %s", path)

    def load(self, path: str | Path) -> None:
        """Load from disk."""
        path = Path(path)
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._estimator = data["estimator"]
        self._tool_names = data["tool_names"]
        self._mlb = data["mlb"]
        self._confidence_threshold = data.get("confidence_threshold", 0.3)
        self._fitted = True
        logger.info("tool selector model loaded from %s", path)
