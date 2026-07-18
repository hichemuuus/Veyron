"""Memory retrieval model — ranks candidate memories by relevance to a query.

Uses TF-IDF vectorization (word n-grams, sublinear TF) + cosine similarity,
matching the micro-model stack used by ``tool_selector``. No external embedding service is required.

The model is fit on a corpus of memory texts: this teaches the vectorizer the
vocabulary and IDF weights. At inference time, the query and each candidate are
projected into the same TF-IDF space and ranked by cosine similarity. This is a
learned ranking over the *current* candidate pool, so it generalises to memories
that did not exist at training time — only the vocabulary/IDF weighting is
learned.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryRetrievalModel:
    """TF-IDF + cosine-similarity ranker for memory retrieval.

    Conventions match the other micro-models: a ``fitted`` property, ``fit``,
    ``predict``, ``save``, and ``load``. State is pickled as a dict so future
    field additions stay backward-compatible (loaded with ``.get()``).
    """

    def __init__(self) -> None:
        self._vectorizer: Any = None
        self._fitted: bool = False
        # Cached vocabulary size for diagnostics; not load-bearing.
        self._vocab_size: int = 0

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def fitted(self) -> bool:
        return self._fitted

    @property
    def vocab_size(self) -> int:
        return self._vocab_size

    # ── Training ────────────────────────────────────────────────────────────

    def fit(self, corpus: list[str]) -> None:
        """Fit the TF-IDF vectorizer on a corpus of memory texts.

        Args:
            corpus: Memory texts (and/or queries) used to learn vocabulary and
                inverse-document-frequency weights. Duplicates are fine.
        """
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = [t for t in corpus if isinstance(t, str) and t.strip()]
        if not texts:
            self._vectorizer = None
            self._fitted = False
            self._vocab_size = 0
            return

        # n-gram range (1,2): unigrams catch exact topic words ("database"),
        # bigrams catch multi-word concepts ("connection pool"). Matches the
        # flavour of the other micro-models while keeping the matrix small.
        self._vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),
            sublinear_tf=True,
            stop_words="english",
        )
        self._vectorizer.fit(texts)
        self._vocab_size = len(self._vectorizer.vocabulary_)
        self._fitted = True
        logger.info(
            "memory retrieval model fitted on %d texts (%d vocabulary terms)",
            len(texts),
            self._vocab_size,
        )

    # ── Inference ───────────────────────────────────────────────────────────

    def rank(
        self, query: str, candidates: list[str]
    ) -> list[tuple[int, float]]:
        """Rank candidate memories against a query.

        Returns a list of ``(candidate_index, score)`` tuples sorted by score
        descending. Candidates with zero similarity are still returned (at the
        tail) so callers can take a stable top-k.
        """
        if not self._fitted or self._vectorizer is None:
            raise RuntimeError("model not fitted")

        if not candidates:
            return []

        # Project query + candidates into the shared TF-IDF space.
        texts = [query] + list(candidates)
        try:
            mat = self._vectorizer.transform(texts)
        except ValueError:
            # Empty vocabulary on transform (all OOV tokens) — degenerate case.
            return [(i, 0.0) for i in range(len(candidates))]

        from sklearn.metrics.pairwise import cosine_similarity

        query_vec = mat[0]
        cand_vecs = mat[1:]
        sims = cosine_similarity(query_vec, cand_vecs).ravel()

        ranked = sorted(
            ((i, float(sims[i])) for i in range(len(candidates))),
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked

    def predict(
        self, query: str, candidates: list[str], top_k: int = 5
    ) -> list[int]:
        """Return the top-k candidate indices ranked by relevance."""
        if top_k <= 0:
            return []
        ranked = self.rank(query, candidates)
        return [idx for idx, _ in ranked[:top_k]]

    # ── Persistence ─────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Serialise the fitted model to disk."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "vectorizer": self._vectorizer,
            "vocab_size": self._vocab_size,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        logger.info("memory retrieval model saved to %s", path)

    def load(self, path: str | Path) -> None:
        """Load a previously saved model from disk."""
        path = Path(path)
        with open(path, "rb") as f:
            data = pickle.load(f)
        # .get() for backward-compatibility with older pickles.
        self._vectorizer = data.get("vectorizer")
        self._vocab_size = data.get("vocab_size", 0)
        self._fitted = self._vectorizer is not None
        logger.info("memory retrieval model loaded from %s", path)
