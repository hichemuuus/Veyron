"""Benchmarks for skill detection — tests pattern recognition."""

from __future__ import annotations

import pytest
from veyron.learning.skill_detector import SkillDetector, DetectedSkill


class TestSkillDetectionBenchmarks:

    def test_detect_repeated_pattern(self):
        detector = SkillDetector(min_frequency=2)
        tasks = [
            {"request": "test", "tools_used": [{"name": "read_file"}, {"name": "write_file"}]},
            {"request": "test2", "tools_used": [{"name": "read_file"}, {"name": "write_file"}]},
            {"request": "test3", "tools_used": [{"name": "terminal"}, {"name": "read_file"}]},
        ]
        skills = detector.detect_skills_from_tasks(tasks)
        assert len(skills) >= 1
        assert any("read_file" in s.source_pattern and "write_file" in s.source_pattern for s in skills)

    def test_no_pattern_with_single_occurrence(self):
        detector = SkillDetector(min_frequency=2)
        tasks = [
            {"request": "test", "tools_used": [{"name": "read_file"}, {"name": "write_file"}]},
            {"request": "test2", "tools_used": [{"name": "terminal"}, {"name": "grep"}]},
        ]
        skills = detector.detect_skills_from_tasks(tasks)
        for s in skills:
            assert s.frequency >= 2

    def test_confidence_scaling(self):
        detector = SkillDetector(min_frequency=2)
        tasks = [
            {"request": "t1", "tools_used": [{"name": "a"}, {"name": "b"}]},
            {"request": "t2", "tools_used": [{"name": "a"}, {"name": "b"}]},
            {"request": "t3", "tools_used": [{"name": "a"}, {"name": "b"}]},
            {"request": "t4", "tools_used": [{"name": "a"}, {"name": "b"}]},
            {"request": "t5", "tools_used": [{"name": "a"}, {"name": "b"}]},
        ]
        skills = detector.detect_skills_from_tasks(tasks)
        high_freq = [s for s in skills if s.frequency >= 5]
        if high_freq:
            assert high_freq[0].confidence > 0.7

    def test_skill_name_generation(self):
        detector = SkillDetector()
        tasks = [
            {"request": "t1", "tools_used": [{"name": "read_file"}, {"name": "write_file"}, {"name": "terminal"}]},
            {"request": "t2", "tools_used": [{"name": "read_file"}, {"name": "write_file"}, {"name": "terminal"}]},
            {"request": "t3", "tools_used": [{"name": "read_file"}, {"name": "write_file"}, {"name": "terminal"}]},
        ]
        skills = detector.detect_skills_from_tasks(tasks)
        assert len(skills) > 0
        assert any("Read" in s.name for s in skills)

    def test_empty_task_list(self):
        detector = SkillDetector()
        skills = detector.detect_skills_from_tasks([])
        assert len(skills) == 0
