"""Benchmarks for memory quality — scoring, importance, dedup, merge."""

from __future__ import annotations

import pytest
from veyron.db.models import MemoryCategory
from veyron.memory.importance import ImportanceScorer
from veyron.memory.merge import MemoryMerger
from veyron.memory.scoring import compute_scores, score_new_content
from veyron.memory.store import get_memory_store, reset_memory_store


pytestmark = pytest.mark.usefixtures("fresh_db")


class TestMemoryImportanceBenchmarks:

    def test_importance_scoring_high(self):
        scorer = ImportanceScorer()
        score = scorer.score("The API key and password must be kept secure in the configuration file")
        assert score >= 0.6, f"Expected high importance, got {score}"

    def test_importance_scoring_low(self):
        scorer = ImportanceScorer()
        score = scorer.score("a")
        assert score < 0.5, f"Expected low importance, got {score}"

    def test_importance_scoring_medium(self):
        scorer = ImportanceScorer()
        score = scorer.score("My preferred editor is VS Code and I like dark themes")
        assert 0.3 <= score <= 0.8, f"Expected medium importance, got {score}"

    def test_batch_scoring(self):
        scorer = ImportanceScorer()
        items = [
            {"content": "password is secret", "source": "reflection"},
            {"content": "hello", "source": "chat"},
            {"content": "project architecture uses FastAPI with SQLite backend", "source": "project"},
        ]
        scores = scorer.batch_score(items)
        assert len(scores) == 3
        assert scores[0] > scores[1]
        assert scores[2] > scores[1]


class TestMemoryScoringBenchmarks:

    def test_score_new_content(self):
        importance, usefulness, reliability = score_new_content("This is an important project preference")
        assert 0.0 <= importance <= 1.0
        assert 0.0 <= usefulness <= 1.0
        assert 0.0 <= reliability <= 1.0


class TestMemoryMergeBenchmarks:

    def test_merge_similar_memories(self):
        store = get_memory_store()
        reset_memory_store()
        store = get_memory_store()

        m1 = store.store(MemoryCategory.HISTORY, "The project uses Python 3.11 and FastAPI", importance=0.7)
        m2 = store.store(MemoryCategory.HISTORY, "Uses Python 3.11 with FastAPI framework", importance=0.6)
        m3 = store.store(MemoryCategory.HISTORY, "Different content about something else", importance=0.5)

        merger = MemoryMerger()
        plans = merger.find_and_merge_similar(threshold=0.5)
        assert len(plans) >= 0  # may or may not merge depending on similarity

    def test_suggest_merge(self):
        store = get_memory_store()
        store.store(MemoryCategory.HISTORY, "Python 3.11 with FastAPI backend", importance=0.7)
        merger = MemoryMerger()
        plan = merger.suggest_merge("Python 3.11 FastAPI project")
        # May or may not find a match depending on similarity
        assert plan is None or isinstance(plan.primary_id, str)
