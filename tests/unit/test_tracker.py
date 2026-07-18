"""Tests for the ExecutionTracker."""

from __future__ import annotations

import pytest
from veyron.core.tracker import ExecutionTracker
from veyron.db.models import TaskStatus, TaskType


class TestExecutionTracker:
    """Tracker lifecycle and query tests."""

    @pytest.mark.asyncio
    async def test_start_and_complete_task(self, fresh_db, stub_provider):
        """Tracker should record task start and completion."""
        from uuid import uuid4

        from veyron.db.base import sync_session_scope
        from veyron.db.models import Task

        pid = uuid4().hex
        with sync_session_scope() as session:
            session.add(Task(public_id=pid, request="test task"))

        tracker = ExecutionTracker()
        await tracker.start_task(pid, "test task")

        from sqlmodel import select
        with sync_session_scope() as session:
            task = session.exec(select(Task).where(Task.public_id == pid)).first()
            assert task.status == TaskStatus.RUNNING
            assert task.started_at is not None

        await tracker.complete_task(pid, result="done")

        with sync_session_scope() as session:
            task = session.exec(select(Task).where(Task.public_id == pid)).first()
            assert task.status == TaskStatus.COMPLETED
            assert task.result == "done"
            assert task.finished_at is not None

    @pytest.mark.asyncio
    async def test_start_and_complete_step(self, fresh_db):
        """Tracker should record a step and mark it complete."""
        tracker = ExecutionTracker()
        pid = "test_task"

        step_id = await tracker.start_step(pid, TaskType.LLM_CALL, "test_step", step_index=1, input_preview="hello")

        assert step_id is not None

        await tracker.complete_step(step_id, output_preview="world")

        steps = await tracker.get_timeline(pid)
        assert len(steps) == 1
        assert steps[0]["name"] == "test_step"
        assert steps[0]["status"] == "completed"
        assert steps[0]["step_type"] == "llm_call"

    @pytest.mark.asyncio
    async def test_fail_step(self, fresh_db):
        """Tracker should record a step failure."""
        tracker = ExecutionTracker()
        pid = "test_task_fail"

        step_id = await tracker.start_step(pid, TaskType.TOOL_CALL, "bad_tool", step_index=1)
        await tracker.fail_step(step_id, "something broke", retry_count=2)

        steps = await tracker.get_timeline(pid)
        assert len(steps) == 1
        assert steps[0]["status"] == "failed"
        assert steps[0]["error"] == "something broke"
        assert steps[0]["retry_count"] == 2

    @pytest.mark.asyncio
    async def test_skip_step(self, fresh_db):
        """Tracker should record a skipped step."""
        tracker = ExecutionTracker()
        pid = "test_task_skip"

        step_id = await tracker.start_step(pid, TaskType.PLAN_STEP, "skip_me", step_index=1)
        await tracker.skip_step(step_id, reason="not needed")

        steps = await tracker.get_timeline(pid)
        assert steps[0]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_checkpoint(self, fresh_db):
        """Tracker should save and load checkpoints."""
        from uuid import uuid4

        from veyron.db.base import sync_session_scope
        from veyron.db.models import Task

        pid = uuid4().hex
        with sync_session_scope() as session:
            session.add(Task(public_id=pid, request="test"))

        tracker = ExecutionTracker()
        await tracker.save_checkpoint(pid, '{"step": 3}', step_index=3)

        data, index = await tracker.load_checkpoint(pid)
        assert data == '{"step": 3}'
        assert index == 3

    @pytest.mark.asyncio
    async def test_get_task_summary(self, fresh_db):
        """Tracker should return aggregated stats."""
        from uuid import uuid4

        from veyron.db.base import sync_session_scope
        from veyron.db.models import Task

        pid = uuid4().hex
        with sync_session_scope() as session:
            session.add(Task(public_id=pid, request="test"))

        tracker = ExecutionTracker()
        await tracker.start_task(pid, "test")
        await tracker.increment_tool_count(pid)
        await tracker.increment_tool_count(pid)

        summary = await tracker.get_task_summary(pid)
        assert summary["tool_count"] == 2
        assert summary["status"] == "running"

        await tracker.complete_task(pid, result="done")

        summary = await tracker.get_task_summary(pid)
        assert summary["status"] == "completed"

    @pytest.mark.asyncio
    async def test_increment_retry(self, fresh_db):
        """Tracker should track retry counts."""
        from uuid import uuid4

        from veyron.db.base import sync_session_scope
        from veyron.db.models import Task

        pid = uuid4().hex
        with sync_session_scope() as session:
            session.add(Task(public_id=pid, request="test"))

        tracker = ExecutionTracker()
        await tracker.increment_retry_count(pid)
        await tracker.increment_retry_count(pid)
        await tracker.increment_retry_count(pid)

        summary = await tracker.get_task_summary(pid)
        assert summary["retry_count"] == 3

    @pytest.mark.asyncio
    async def test_timeline_ordering(self, fresh_db):
        """Steps should be returned in order."""
        tracker = ExecutionTracker()
        pid = "ordered"

        for i in range(5):
            sid = await tracker.start_step(pid, TaskType.LLM_CALL, f"step_{i}", step_index=i)
            if i % 2 == 0:
                await tracker.complete_step(sid, "ok")
            else:
                await tracker.fail_step(sid, f"error_{i}")

        steps = await tracker.get_timeline(pid)
        assert len(steps) == 5
        for i, s in enumerate(steps):
            assert s["step_index"] == i
            if i % 2 == 0:
                assert s["status"] == "completed"
            else:
                assert s["status"] == "failed"

    @pytest.mark.asyncio
    async def test_timeline_limit(self, fresh_db):
        """Timeline should respect the limit parameter."""
        tracker = ExecutionTracker()
        pid = "limited"

        for i in range(10):
            sid = await tracker.start_step(pid, TaskType.LLM_CALL, f"s{i}", step_index=i)
            await tracker.complete_step(sid)

        steps = await tracker.get_timeline(pid, limit=3)
        assert len(steps) == 3
