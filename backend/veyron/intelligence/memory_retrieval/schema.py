"""Schema for the memory retrieval micro-model.

Memory retrieval is a ranking task: given a query (the user's request) and a
pool of candidate memories (their content text), predict which candidates are
most relevant. The model learns vocabulary and IDF weights over a corpus of
memory texts via TF-IDF, then ranks candidates by cosine similarity to the
query.

The model, trainer, evaluator, and inference singleton follow the standard
micro-model conventions with one adaptation: because retrieval is inherently
rank-based, evaluation uses precision@k, recall@k, and mean reciprocal rank
(MRR) instead of exact match.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryRetrievalExample:
    """A single training/evaluation example for memory retrieval.

    Attributes:
        query: The user request to retrieve memories for.
        candidate_memories: The pool of candidate memory texts to rank.
        relevant_indices: Indices into ``candidate_memories`` that are
            considered relevant ground truth (the targets the model should
            surface near the top).
        difficulty: ``"basic"``, ``"moderate"``, or ``"advanced"``.
        category: A ``MemoryCategory`` value the example is themed around
            (``USER``, ``PROJECT``, ``HISTORY``, ``SKILL``). Informational.
    """

    query: str
    candidate_memories: list[str] = field(default_factory=list)
    relevant_indices: list[int] = field(default_factory=list)
    difficulty: str = "basic"
    category: str = ""


@dataclass
class MemoryRetrievalPrediction:
    """Prediction output from the memory retrieval model.

    Attributes:
        query: The query that was ranked for.
        ranked_indices: Candidate indices in descending relevance order.
        scores: Cosine-similarity scores aligned with ``ranked_indices``.
        top_k: The top-k candidate indices (a prefix of ``ranked_indices``).
    """

    query: str
    ranked_indices: list[int] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    top_k: list[int] = field(default_factory=list)


# Default ``k`` values the benchmark reports metrics at. Tuned to match how the
# agent consumes memory context (the system prompt injects a small handful of
# memories) — see ``context.build_system_prompt``.
DEFAULT_K_VALUES: tuple[int, ...] = (1, 3, 5)
