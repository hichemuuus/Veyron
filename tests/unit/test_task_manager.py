"""Tests for the Task Management System."""

from __future__ import annotations

import pytest

from paios.core.task_manager import TaskManager, get_task_manager, reset_task_manager
from paios.db.base import sync_session_scope
from paios.db.models import Task, TaskStatus


@pytest.fixture(autouse=True)
def fresh_mgr():
    reset_task_manager()
    yield
    reset_task_manager()


class TestTaskManager:
    def test_create_task(self, fresh_db):
        mgr = get_task_manager()
        pid = mgr.create_task("test request")
        assert pid is not None
        assert len(pid) > 0

        info = mgr.get_task(pid)
        assert info is not None
        assert info.request == "test request"
        assert info.status == TaskStatus.CREATED

    def test_get_task_nonexistent(self, fresh_db):
        mgr = get_task_manager()
        info = mgr.get_task("nonexistent")
        assert info is None

    def test_list_tasks(self, fresh_db):
        mgr = get_task_manager()
        pid1 = mgr.create_task("first")
        pid2 = mgr.create_task("second")
        tasks = mgr.list_tasks()
        assert len(tasks) >= 2
        pids = [t.public_id for t in tasks]
        assert pid1 in pids
        assert pid2 in pids

    def test_list_tasks_with_status_filter(self, fresh_db):
        mgr = get_task_manager()
        mgr.create_task("task a")
        pid_b = mgr.create_task("task b")
        # Change status of task b.
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == pid_b).first()
            task.status = TaskStatus.RUNNING
            session.add(task)

        created = mgr.list_tasks(status="created")
        assert all(t.status == TaskStatus.CREATED for t in created)
        running = mgr.list_tasks(status="running")
        assert len(running) == 1
        assert running[0].public_id == pid_b

    def test_cancel_task(self, fresh_db):
        mgr = get_task_manager()
        pid = mgr.create_task("to cancel")
        # Set to running so it can be cancelled.
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == pid).first()
            task.status = TaskStatus.RUNNING
            session.add(task)

        info = mgr.cancel_task(pid)
        assert info is not None
        assert info.status == TaskStatus.CANCELLED

    def test_cancel_nonexistent(self, fresh_db):
        mgr = get_task_manager()
        info = mgr.cancel_task("nonexistent")
        assert info is None

    def test_pause_and_resume(self, fresh_db):
        mgr = get_task_manager()
        pid = mgr.create_task("to pause")
        with sync_session_scope() as session:
            task = session.query(Task).filter(Task.public_id == pid).first()
            task.status = TaskStatus.RUNNING
            session.add(task)

        info = mgr.pause_task(pid)
        assert info.status == TaskStatus.PAUSED

        info = mgr.resume_task(pid)
        assert info.status == TaskStatus.CREATED

    def test_delete_task(self, fresh_db):
        mgr = get_task_manager()
        pid = mgr.create_task("to delete")
        assert mgr.delete_task(pid) is True
        assert mgr.get_task(pid) is None

    def test_delete_nonexistent(self, fresh_db):
        mgr = get_task_manager()
        assert mgr.delete_task("nonexistent") is False

    def test_get_progress(self, fresh_db):
        mgr = get_task_manager()
        pid = mgr.create_task("progress test")
        progress = mgr.get_progress(pid)
        assert progress is not None
        assert progress.percent == 0.0

    def test_get_history(self, fresh_db):
        mgr = get_task_manager()
        pid = mgr.create_task("history test")
        history = mgr.get_history(pid)
        assert isinstance(history, list)
