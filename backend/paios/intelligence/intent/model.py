"""Intent classification model interface.

Supports sklearn-style classifiers (TF-IDF + LogisticRegression by default).
The model is serialised to a pickle file after training and loaded for inference.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class IntentModel:
    """Wrapper around a classifier that maps text → intent category + confidence.

    The underlying estimator must implement `fit()`, `predict()`, and
    `predict_proba()` (sklearn-compatible).
    """

    def __init__(self, estimator: Any | None = None) -> None:
        self._estimator = estimator
        self._classes: list[str] = []
        self._fitted = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    @property
    def classes(self) -> list[str]:
        return self._classes

    def fit(self, X: list[str], y: list[str]) -> None:
        """Fit the model on text samples and label strings."""
        if self._estimator is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline

            self._estimator = Pipeline([
                ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 3))),
                ("clf", LogisticRegression(max_iter=1000)),
            ])
        self._estimator.fit(X, y)
        self._classes = list(self._estimator.classes_)
        self._fitted = True

    def predict(self, text: str) -> str:
        """Return the single best predicted category."""
        if not self._fitted:
            raise RuntimeError("model not fitted")
        return str(self._estimator.predict([text])[0])

    def predict_proba(self, text: str) -> dict[str, float]:
        """Return a {category: confidence} dict for all classes."""
        if not self._fitted:
            raise RuntimeError("model not fitted")
        probs = self._estimator.predict_proba([text])[0]
        return dict(zip(self._classes, (round(float(p), 4) for p in probs)))

    def predict_with_confidence(self, text: str) -> tuple[str, float]:
        """Return (best_category, confidence)."""
        probs = self.predict_proba(text)
        best = max(probs, key=probs.get)
        return best, probs[best]

    def save(self, path: str | Path) -> None:
        """Serialise the fitted estimator to disk."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"estimator": self._estimator, "classes": self._classes}, f)
        logger.info("model saved to %s", path)

    def load(self, path: str | Path) -> None:
        """Load a previously saved estimator."""
        path = Path(path)
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._estimator = data["estimator"]
        self._classes = data["classes"]
        self._fitted = True
        logger.info("model loaded from %s", path)
