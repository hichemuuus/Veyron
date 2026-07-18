"""Benchmarks for learning progress — integration tests across learning components."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from veyron.db.base import sync_session_scope
from veyron.db.models import (
    BenchmarkRun,
    LearningEvent,
    ModelVersion,
    ReflectionRecord,
    Skill,
    Workflow,
)
from veyron.learning.skill_detector import SkillDetector


pytestmark = pytest.mark.usefixtures("fresh_db")


class TestLearningProgressBenchmarks:

    def test_learning_event_creation(self):
        pid = str(uuid4())
        with sync_session_scope() as session:
            event = LearningEvent(
                public_id=pid,
                event_type="test",
                category="benchmark",
                summary="Test learning event",
                details_json=json.dumps({"key": "value"}),
            )
            session.add(event)
            session.flush()
            retrieved = session.query(LearningEvent).filter(LearningEvent.public_id == pid).first()
            assert retrieved is not None
            assert retrieved.summary == "Test learning event"

    def test_benchmark_run_creation(self):
        pid = str(uuid4())
        with sync_session_scope() as session:
            run = BenchmarkRun(
                public_id=pid,
                benchmark_name="test_benchmark",
                model_type="intent_classifier",
                model_version="v1",
                metrics_json=json.dumps({"accuracy": 0.95, "f1": 0.92}),
                score=0.93,
                regressions=json.dumps([]),
                duration_ms=100,
            )
            session.add(run)
            session.flush()
            retrieved = session.query(BenchmarkRun).filter(BenchmarkRun.public_id == pid).first()
            assert retrieved is not None
            assert retrieved.score == 0.93

    def test_model_version_tracking(self):
        with sync_session_scope() as session:
            v1 = ModelVersion(
                model_type="intent_classifier", version="v1", status="production",
                dataset_size=100, metrics_json=json.dumps({"acc": 0.9}), path="/models/v1",
            )
            v2 = ModelVersion(
                model_type="intent_classifier", version="v2", status="candidate",
                dataset_size=150, metrics_json=json.dumps({"acc": 0.92}), path="/models/v2",
                parent_version="v1",
            )
            session.add_all([v1, v2])
            session.flush()
            models = session.query(ModelVersion).filter(ModelVersion.model_type == "intent_classifier").all()
            assert len(models) == 2

    def test_reflection_record_persistence(self):
        pid = str(uuid4())
        with sync_session_scope() as session:
            rec = ReflectionRecord(
                public_id=pid,
                task_public_id="task_001",
                success=True,
                confidence=0.85,
                planning_quality=0.8,
                tool_selection_quality=0.9,
                parameter_quality=0.85,
                memory_usefulness=0.7,
                mistake_count=1,
                improvement_count=2,
                summary="Test reflection",
            )
            session.add(rec)
            session.flush()
            retrieved = session.query(ReflectionRecord).filter(ReflectionRecord.public_id == pid).first()
            assert retrieved is not None
            assert retrieved.confidence == 0.85
            assert retrieved.planning_quality == 0.8

    def test_skill_store_query(self):
        with sync_session_scope() as session:
            s = Skill(
                public_id=str(uuid4()),
                name="test_skill",
                description="A test skill",
                pattern_steps=json.dumps([{"tool_name": "read_file"}]),
                frequency=5,
                confidence=0.8,
            )
            session.add(s)
            session.flush()
            skills = session.query(Skill).filter(Skill.enabled == True).all()
            assert len(skills) >= 1

    def test_workflow_store_query(self):
        with sync_session_scope() as session:
            w = Workflow(
                public_id=str(uuid4()),
                name="test_workflow",
                description="A test workflow",
                version="1.0",
                step_count=2,
                use_count=10,
                success_rate=0.95,
            )
            session.add(w)
            session.flush()
            workflows = session.query(Workflow).filter(Workflow.enabled == True).all()
            assert len(workflows) >= 1

    def test_detector_with_db_integration(self):
        """Test skill detector with tools_used field format."""
        detector = SkillDetector(min_frequency=1)
        tasks = [
            {"request": "read and write", "tools_used": ["read_file", "write_file"]},
            {"request": "read and write again", "tools_used": ["read_file", "write_file"]},
        ]
        skills = detector.detect_skills_from_tasks(tasks)
        assert len(skills) >= 1
