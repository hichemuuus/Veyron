"""Tests for the memory store — CRUD, search, context injection."""

from __future__ import annotations

import pytest

from paios.db.models import MemoryCategory
from paios.memory.store import MemoryStore, get_memory_store, reset_memory_store

pytestmark = pytest.mark.usefixtures("fresh_db")


@pytest.fixture(autouse=True)
def _reset_memory():
    reset_memory_store()
    yield
    reset_memory_store()




class TestMemoryStore:
    """Memory store CRUD operations."""

    def test_store_and_get(self):
        store = get_memory_store()
        mem = store.store(MemoryCategory.USER, "Hello world", importance=0.8, tags="greeting")
        assert mem.public_id
        assert mem.content == "Hello world"
        assert mem.importance == 0.8
        assert mem.category == MemoryCategory.USER

        retrieved = store.get(mem.public_id)
        assert retrieved is not None
        assert retrieved.public_id == mem.public_id

    def test_get_nonexistent(self):
        store = get_memory_store()
        assert store.get("nonexistent") is None

    def test_store_clamps_importance(self):
        store = get_memory_store()
        mem = store.store(MemoryCategory.PROJECT, "test", importance=1.5)
        assert mem.importance == 1.0
        mem2 = store.store(MemoryCategory.PROJECT, "test2", importance=-0.5)
        assert mem2.importance == 0.0

    def test_update_content(self):
        store = get_memory_store()
        mem = store.store(MemoryCategory.USER, "original")
        updated = store.update(mem.public_id, content="updated")
        assert updated is not None
        assert updated.content == "updated"
        assert updated.importance == 0.5

    def test_update_nonexistent(self):
        store = get_memory_store()
        assert store.update("nonexistent", content="x") is None

    def test_delete(self):
        store = get_memory_store()
        mem = store.store(MemoryCategory.SKILL, "delete me")
        assert store.delete(mem.public_id) is True
        assert store.get(mem.public_id) is None

    def test_delete_nonexistent(self):
        store = get_memory_store()
        assert store.delete("nonexistent") is False

    def test_count(self):
        store = get_memory_store()
        assert store.count() == 0
        store.store(MemoryCategory.HISTORY, "a")
        store.store(MemoryCategory.HISTORY, "b")
        assert store.count() == 2


class TestMemorySearch:
    """Memory text search and ranking."""

    @pytest.fixture(autouse=True)
    def _seed_memories(self, fresh_db):
        self.store = get_memory_store()
        self.store.store(MemoryCategory.USER, "User likes Python", importance=0.9, tags="lang")
        self.store.store(MemoryCategory.USER, "User likes Rust", importance=0.7, tags="lang")
        self.store.store(MemoryCategory.PROJECT, "Project uses FastAPI", importance=0.5, tags="tech")
        self.store.store(MemoryCategory.SKILL, "Skill: React components", importance=0.3, tags="frontend")

    def test_search_by_content(self):
        results = self.store.search("Python", limit=10)
        assert len(results) == 1
        assert "Python" in results[0].content

    def test_search_by_category(self):
        results = self.store.search("likes", category=MemoryCategory.USER, limit=10)
        assert len(results) == 2

    def test_search_empty_query_returns_recent(self):
        results = self.store.search("", limit=10)
        # Should return all sorted by importance desc, created_at desc
        assert len(results) == 4

    def test_search_returns_empty_for_no_match(self):
        results = self.store.search("zzz_nonexistent", limit=10)
        assert len(results) == 0

    def test_search_ranking_by_importance(self):
        results = self.store.search("likes", limit=10)
        # Higher importance should come first
        assert "Python" in results[0].content

    def test_search_with_tags(self):
        results = self.store.search("likes", tags="lang", limit=10)
        assert len(results) == 2

    def test_recall_updates_count(self):
        all_mems = self.store.search("", limit=1)
        mem = all_mems[0]
        assert mem.recall_count == 0
        recalled = self.store.recall(mem.public_id)
        assert recalled is not None
        assert recalled.recall_count == 1
        assert recalled.last_recalled_at is not None

    def test_recent(self):
        results = self.store.recent(limit=3)
        assert len(results) == 3

    def test_important(self):
        results = self.store.important(threshold=0.6, limit=10)
        assert len(results) == 2  # importance 0.9 and 0.7


class TestMemoryContext:
    """Memory context injection."""

    def setup_method(self):
        self.store = get_memory_store()

    def test_build_context_empty(self):
        ctx = self.store.build_context("")
        assert ctx == ""

    def test_build_context_with_data(self):
        self.store.store(MemoryCategory.USER, "User prefers dark mode", importance=0.8)
        ctx = self.store.build_context("dark mode")
        assert "dark mode" in ctx
        assert "USER" in ctx or "user" in ctx

    def test_build_context_falls_back_to_important(self):
        self.store.store(MemoryCategory.USER, "Important context", importance=0.95)
        ctx = self.store.build_context("")
        assert "Important context" in ctx

    def test_build_context_respects_limit(self):
        for i in range(5):
            self.store.store(MemoryCategory.USER, f"memory {i}", importance=0.5)
        ctx = self.store.build_context("memory", limit=2)
        count = ctx.count("memory")
        assert count <= 2 or count == 0


class TestMemorySingleton:
    """Module-level get_memory_store / reset."""

    def teardown_method(self):
        reset_memory_store()

    def test_singleton(self):
        s1 = get_memory_store()
        s2 = get_memory_store()
        assert s1 is s2

    def test_reset(self):
        s1 = get_memory_store()
        reset_memory_store()
        s2 = get_memory_store()
        assert s1 is not s2
