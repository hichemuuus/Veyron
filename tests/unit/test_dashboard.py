"""Tests for the dashboard API endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from paios.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestDashboard:
    """Tests for GET /api/dashboard."""

    def test_dashboard_returns_expected_keys(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_tasks" in data
        assert "completed_tasks" in data
        assert "failed_tasks" in data
        assert "total_tasks" in data
        assert "recent_tasks" in data
        assert "system" in data
        assert "timestamp" in data

    def test_dashboard_task_counts_are_integers(self, client):
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert isinstance(data["active_tasks"], int)
        assert isinstance(data["completed_tasks"], int)
        assert isinstance(data["failed_tasks"], int)
        assert isinstance(data["total_tasks"], int)

    def test_dashboard_total_is_sum(self, client):
        resp = client.get("/api/dashboard")
        data = resp.json()
        expected = data["active_tasks"] + data["completed_tasks"] + data["failed_tasks"]
        assert data["total_tasks"] == expected

    def test_dashboard_recent_tasks_is_list(self, client):
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert isinstance(data["recent_tasks"], list)

    def test_dashboard_system_has_overview_keys(self, client):
        resp = client.get("/api/dashboard")
        data = resp.json()
        system = data.get("system", {})
        assert "cpu_percent" in system or "cpu" in system

    def test_dashboard_timestamp_is_isoformat(self, client):
        resp = client.get("/api/dashboard")
        data = resp.json()
        ts = data.get("timestamp", "")
        assert "T" in ts
        assert ts.endswith("+00:00") or "+" in ts

    def test_dashboard_recent_task_fields(self, client):
        resp = client.get("/api/dashboard")
        data = resp.json()
        if data["recent_tasks"]:
            task = data["recent_tasks"][0]
            assert "public_id" in task
            assert "request" in task
            assert "status" in task
            assert "created_at" in task

    def test_dashboard_after_creating_task(self, client):
        create_resp = client.post("/api/agent", json={"request": "test dashboard task"})
        assert create_resp.status_code == 200
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["total_tasks"] >= 1
        # The created task should be in recent_tasks.
        pids = [t["public_id"] for t in data["recent_tasks"]]
        assert create_resp.json()["public_id"] in pids
