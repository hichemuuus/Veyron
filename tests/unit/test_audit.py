"""Tests for the audit log."""

from __future__ import annotations

from paios.security.audit import AUDIT_DIR, read_recent, record


class TestAudit:
    def test_record_and_read(self, isolated_data_dir):
        rid = record(action="test.action", subject="test_subj", permission="free", outcome="success")
        assert rid is not None

        entries = read_recent(limit=10)
        assert len(entries) == 1
        assert entries[0]["action"] == "test.action"
        assert entries[0]["subject"] == "test_subj"
        assert entries[0]["permission"] == "free"
        assert entries[0]["outcome"] == "success"

    def test_multiple_records(self, isolated_data_dir):
        ids = []
        for i in range(5):
            rid = record(action=f"action.{i}", subject="subj", permission="free", outcome="success")
            ids.append(rid)

        entries = read_recent(limit=10)
        assert len(entries) == 5

    def test_read_recent_limit(self, isolated_data_dir):
        for i in range(10):
            record(action=f"action.{i}", subject="subj", permission="free", outcome="success")

        entries = read_recent(limit=3)
        assert len(entries) == 3

    def test_read_recent_newest_first(self, isolated_data_dir):
        record(action="first", subject="subj", permission="free", outcome="success")
        record(action="second", subject="subj", permission="free", outcome="success")
        record(action="third", subject="subj", permission="free", outcome="success")

        entries = read_recent(limit=10)
        assert entries[0]["action"] == "third"
        assert entries[-1]["action"] == "first"

    def test_record_with_reason_and_detail(self, isolated_data_dir):
        rid = record(
            action="restricted.action",
            subject="task_1",
            permission="restricted",
            inputs={"command": "rm -rf /"},
            outcome="denied",
            reason="too dangerous",
            detail="user declined",
        )
        entries = read_recent(limit=10)
        assert len(entries) == 1
        assert entries[0]["reason"] == "too dangerous"
        assert entries[0]["detail"] == "user declined"
        assert entries[0]["inputs"]["command"] == "rm -rf /"

    def test_empty_read_returns_empty_list(self):
        entries = read_recent(limit=10)
        assert entries == []

    def test_read_recent_with_no_files(self, isolated_data_dir):
        # No audit files written yet.
        entries = read_recent(limit=10)
        assert entries == []
