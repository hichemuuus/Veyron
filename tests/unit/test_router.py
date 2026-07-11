"""Tests for the heuristic intent router."""

from __future__ import annotations

from paios.llm.micro.router import Intent, route


class TestRouter:
    def test_simple_request_returns_react(self):
        intent = route("Show my CPU usage")
        assert intent.mode == "react"
        assert intent.domain in ("system", "general")
        assert intent.confidence > 0.5

    def test_short_request_is_react(self):
        intent = route("List files")
        assert intent.mode == "react"

    def test_long_request_is_plan(self):
        intent = route("Analyze my project and prepare a detailed report about its architecture " * 3)
        assert intent.mode == "plan"

    def test_analysis_pattern(self):
        intent = route("Analyze this codebase for issues")
        assert intent.mode == "plan"

    def test_domain_detection_system(self):
        intent = route("What is my CPU and memory usage?")
        assert intent.domain == "system"

    def test_domain_detection_filesystem(self):
        intent = route("List files in the current directory")
        assert intent.domain == "filesystem"

    def test_domain_detection_project(self):
        intent = route("Tell me about this project's architecture")
        assert intent.domain == "project"

    def test_domain_detection_terminal(self):
        intent = route("Run git status")
        assert intent.domain == "terminal"

    def test_general_domain_fallback(self):
        intent = route("Hello, how are you?")
        assert intent.domain == "general"

    def test_multi_step_pattern(self):
        intent = route("First check disk, then analyze memory, finally show processes")
        assert intent.mode == "plan"

    def test_report_generation_pattern(self):
        intent = route("Generate a summary report of system health")
        assert intent.mode == "plan"

    def test_intent_fields(self):
        intent = route("Check system performance")
        assert isinstance(intent, Intent)
        assert hasattr(intent, "mode")
        assert hasattr(intent, "domain")
        assert hasattr(intent, "confidence")
        assert 0.0 <= intent.confidence <= 1.0
