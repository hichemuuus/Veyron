"""Memory retrieval — ranks candidate memories by relevance to a query.

This package provides:
  - MemoryRetrievalModel: TF-IDF + cosine-similarity ranker
  - train_memory_retrieval(): training pipeline
  - retrieve_memories(): inference API
  - MemoryRetrievalEvaluator: rank-aware evaluation (precision@k, recall@k, MRR)
  - MemoryRetrievalDataset: dataset container + synthetic generator

Follows the standard micro-model conventions: singleton inference, pickle
persistence, graceful empty fallback, and the ``evaluate_model(model,
test_cases)`` contract expected by the Phase 11.5 benchmark.
"""

from veyron.intelligence.memory_retrieval.dataset import (
    MemoryRetrievalDataset as MemoryRetrievalDataset,
)
from veyron.intelligence.memory_retrieval.evaluation import (
    MemoryRetrievalEvaluator as MemoryRetrievalEvaluator,
)
from veyron.intelligence.memory_retrieval.inference import reset_model as reset_memory_model
from veyron.intelligence.memory_retrieval.inference import retrieve_memories as retrieve_memories
from veyron.intelligence.memory_retrieval.model import MemoryRetrievalModel as MemoryRetrievalModel
from veyron.intelligence.memory_retrieval.schema import (
    MemoryRetrievalExample as MemoryRetrievalExample,
)
from veyron.intelligence.memory_retrieval.schema import (
    MemoryRetrievalPrediction as MemoryRetrievalPrediction,
)
from veyron.intelligence.memory_retrieval.trainer import (
    train_memory_retrieval as train_memory_retrieval,
)
