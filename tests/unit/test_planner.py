"""Tests for the Planner module."""

from __future__ import annotations

import json

import pytest

from paios.core.planner import (
    Plan,
    PlanStep,
    Planner,
    VerifierAction,
    VerifierResult,
    _format_tool_list,
    _parse_verifier_result,
)
from paios.llm.base import GenerateChunk, set_provider


class TestPlanStep:
    def test_default_values(self):
        step = PlanStep(id="step_1", goal="Test goal")
        assert step.status == "pending"
        assert step.retries == 0
        assert step.verified is False
        assert step.result is None
        assert step.error is None

    def test_full_initialization(self):
        step = PlanStep(id="step_1", goal="Test goal", suggested_tool="system_monitor", status="running")
        assert step.id == "step_1"
        assert step.suggested_tool == "system_monitor"
        assert step.status == "running"


class TestPlan:
    def test_default_values(self):
        plan = Plan(request="Test request")
        assert plan.steps == []
        assert plan.synthesis is None
        assert plan.error is None

    def test_with_steps(self):
        steps = [PlanStep(id="s1", goal="Goal 1"), PlanStep(id="s2", goal="Goal 2")]
        plan = Plan(request="Test", steps=steps)
        assert len(plan.steps) == 2


class TestPlanner:
    @pytest.mark.asyncio
    async def test_parse_steps_json(self):
        planner = Planner()

        text = """[
            {"id": "step_1", "goal": "Check CPU usage", "tool": "system_monitor"},
            {"id": "step_2", "goal": "List project files", "tool": "filesystem_read"}
        ]"""

        steps = planner._parse_steps(text)
        assert len(steps) == 2
        assert steps[0].goal == "Check CPU usage"
        assert steps[0].suggested_tool == "system_monitor"
        assert steps[1].goal == "List project files"
        assert steps[1].suggested_tool == "filesystem_read"

    @pytest.mark.asyncio
    async def test_parse_steps_list_format(self):
        planner = Planner()

        text = """Plan:
        1. Check CPU usage [tool: system_monitor]
        2. List project files
        3. Generate summary"""

        steps = planner._parse_steps(text)
        assert len(steps) == 3
        assert "Check CPU usage" in steps[0].goal
        assert steps[0].suggested_tool == "system_monitor"
        assert "List project files" in steps[1].goal
        assert steps[1].suggested_tool is None

    @pytest.mark.asyncio
    async def test_parse_steps_empty(self):
        planner = Planner()
        steps = planner._parse_steps("No steps here")
        assert steps == []

    @pytest.mark.asyncio
    async def test_parse_steps_invalid_json(self):
        planner = Planner()
        text = """This is just some text without any recognizable step format."""
        steps = planner._parse_steps(text)
        assert steps == []

    @pytest.mark.asyncio
    async def test_format_tool_list(self):
        result = _format_tool_list()
        assert "filesystem_read" in result
        assert "system_monitor" in result
        assert "terminal" in result

    @pytest.mark.asyncio
    async def test_plan_and_execute_with_provider_error(self):
        """Planner should return error when provider raises an exception."""

        class ErrorProvider:
            name = "error"

            async def is_available(self):
                return True

            async def generate_stream(self, messages, opts):
                raise RuntimeError("provider error")
                if False:  # pragma: no cover
                    yield

            async def embed(self, text):
                return [0.0, 0.0, 0.0]

        planner = Planner(provider=ErrorProvider())
        plan = await planner.plan_and_execute("Do something")
        assert plan.error is not None
        assert "plan generation failed" in plan.error

    @pytest.mark.asyncio
    async def test_plan_generation_with_stub(self, fresh_db, settings_with_sandbox):
        """Test full planner pipeline with a stub provider that returns steps."""

        class StepsProvider:
            name = "steps"
            call_count = 0

            async def is_available(self):
                return True

            async def generate_stream(self, messages, opts):
                self.call_count += 1
                if self.call_count == 1:
                    text = """[
                        {"id": "step_1", "goal": "Check system", "tool": "system_monitor"},
                        {"id": "step_2", "goal": "List files", "tool": "filesystem_read"}
                    ]"""
                    yield GenerateChunk(text=text, done=True, finish_reason="stop")
                elif self.call_count == 2:
                    yield GenerateChunk(text="CPU: 25%, RAM: 60%", done=True, finish_reason="stop")
                elif self.call_count == 3:
                    yield GenerateChunk(text="PASS", done=True, finish_reason="stop")
                elif self.call_count == 4:
                    yield GenerateChunk(tool_call={
                        "id": "call_1",
                        "name": "filesystem_read",
                        "arguments": {"operation": "list_dir", "path": "."},
                    })
                elif self.call_count == 5:
                    yield GenerateChunk(text="Directory listing: hello.txt", done=True, finish_reason="stop")
                elif self.call_count == 6:
                    yield GenerateChunk(text="PASS", done=True, finish_reason="stop")
                else:
                    yield GenerateChunk(
                        text="System is healthy with 25% CPU and 60% RAM usage.",
                        done=True,
                        finish_reason="stop",
                    )

            async def embed(self, text):
                return [0.0, 0.0, 0.0]

        provider = StepsProvider()
        set_provider(provider)
        planner = Planner(provider=provider)

        plan = await planner.plan_and_execute("Analyze my system")
        assert plan.error is None
        assert len(plan.steps) == 2
        assert plan.synthesis is not None

    @pytest.mark.asyncio
    async def test_verify_passes(self):
        """Verifier should return True when LLM says PASS."""

        class PassProvider:
            name = "pass"

            async def is_available(self):
                return True

            async def generate_stream(self, messages, opts):
                yield GenerateChunk(text="PASS", done=True, finish_reason="stop")

            async def embed(self, text):
                return [0.0, 0.0, 0.0]

        planner = Planner(provider=PassProvider())
        result = await planner._verify("Check CPU", "CPU: 25%", "test")
        assert result.passed is True
        assert result.status == "PASS"
        assert result.action == "COMPLETE"

    @pytest.mark.asyncio
    async def test_verify_fails(self):
        """Verifier should return False when LLM says FAIL."""

        class FailProvider:
            name = "fail"

            async def is_available(self):
                return True

            async def generate_stream(self, messages, opts):
                yield GenerateChunk(text="FAIL", done=True, finish_reason="stop")

            async def embed(self, text):
                return [0.0, 0.0, 0.0]

        planner = Planner(provider=FailProvider())
        result = await planner._verify("Check CPU", "Nothing found", "test")
        assert result.passed is False
        assert result.status == "FAIL"
        assert result.action == "REPLAN"

    @pytest.mark.asyncio
    async def test_verify_error_returns_true(self):
        """Verifier should optimistically pass when LLM errors."""

        class ErrorProvider:
            name = "error"

            async def is_available(self):
                return True

            async def generate_stream(self, messages, opts):
                raise RuntimeError("verifier error")
                if False:  # pragma: no cover
                    yield

            async def embed(self, text):
                return [0.0, 0.0, 0.0]

        planner = Planner(provider=ErrorProvider())
        result = await planner._verify("Check CPU", "CPU: 25%", "test")
        assert result.passed is True  # Optimistically passes.
        assert result.confidence == 0.5
        assert "verifier error" in result.issues[0]

    @pytest.mark.asyncio
    async def test_verify_with_none_result(self):
        planner = Planner()
        result = await planner._verify("Check CPU", None, "test")
        assert result.passed is False
        assert result.action == "REPLAN"
        assert "no result produced" in result.issues


class TestPlanValidation:
    """Plan validation (DAG, circular deps, unknown steps/tools)."""

    def test_validate_empty_plan(self):
        planner = Planner()
        plan = Plan(request="test", steps=[])
        error = planner._validate_plan(plan)
        assert error is not None
        assert "no steps" in error

    def test_validate_unknown_dependency(self):
        planner = Planner()
        steps = [
            PlanStep(id="step_1", goal="First"),
            PlanStep(id="step_2", goal="Second", depends_on=["step_99"]),
        ]
        plan = Plan(request="test", steps=steps)
        error = planner._validate_plan(plan)
        assert error is not None
        assert "unknown step" in error

    def test_validate_circular_dependency(self):
        planner = Planner()
        steps = [
            PlanStep(id="step_1", goal="First", depends_on=["step_2"]),
            PlanStep(id="step_2", goal="Second", depends_on=["step_1"]),
        ]
        plan = Plan(request="test", steps=steps)
        error = planner._validate_plan(plan)
        assert error is not None
        assert "circular" in error

    def test_validate_self_dependency(self):
        planner = Planner()
        steps = [
            PlanStep(id="step_1", goal="First", depends_on=["step_1"]),
        ]
        plan = Plan(request="test", steps=steps)
        error = planner._validate_plan(plan)
        assert error is not None
        assert "circular" in error

    def test_validate_valid_plan(self):
        planner = Planner()
        steps = [
            PlanStep(id="step_1", goal="First"),
            PlanStep(id="step_2", goal="Second", depends_on=["step_1"]),
            PlanStep(id="step_3", goal="Third", depends_on=["step_1"]),
            PlanStep(id="step_4", goal="Fourth", depends_on=["step_2", "step_3"]),
        ]
        plan = Plan(request="test", steps=steps)
        error = planner._validate_plan(plan)
        assert error is None

    def test_validate_no_deps(self):
        planner = Planner()
        steps = [
            PlanStep(id="step_1", goal="First"),
            PlanStep(id="step_2", goal="Second"),
        ]
        plan = Plan(request="test", steps=steps)
        error = planner._validate_plan(plan)
        assert error is None

    def test_parse_steps_with_depends_on(self):
        """Parse step JSON that includes depends_on."""
        planner = Planner()
        text = """[
            {"id": "a", "goal": "Check CPU", "tool": "system_monitor"},
            {"id": "b", "goal": "Analyze processes", "depends_on": ["a"]}
        ]"""
        steps = planner._parse_steps(text)
        assert len(steps) == 2
        assert steps[0].id == "a"
        assert steps[1].depends_on == ["a"]


class TestPlanScoring:
    """Tests for plan quality scoring."""

    def test_score_plan_empty(self):
        planner = Planner()
        plan = Plan(request="test", steps=[])
        score = planner._score_plan(plan)
        assert score == 0.0

    def test_score_plan_ideal(self):
        planner = Planner()
        steps = [
            PlanStep(id="s1", goal="Check CPU", suggested_tool="system_monitor"),
            PlanStep(id="s2", goal="List files", suggested_tool="filesystem_read"),
            PlanStep(id="s3", goal="Analyze", depends_on=["s1", "s2"]),
        ]
        plan = Plan(request="test", steps=steps)
        score = planner._score_plan(plan)
        assert 0.5 <= score <= 1.0

    def test_score_plan_low_tool_coverage(self):
        planner = Planner()
        steps = [
            PlanStep(id="s1", goal="Do something vague"),
            PlanStep(id="s2", goal="Do another vague thing"),
        ]
        plan = Plan(request="test", steps=steps)
        score = planner._score_plan(plan)
        assert score < 0.7

    def test_score_plan_many_steps(self):
        planner = Planner()
        steps = [PlanStep(id=f"s{i}", goal=f"Step {i}") for i in range(20)]
        plan = Plan(request="test", steps=steps)
        score = planner._score_plan(plan)
        assert score < 0.6

    def test_score_details(self):
        planner = Planner()
        steps = [
            PlanStep(id="s1", goal="Check", suggested_tool="system_monitor"),
        ]
        plan = Plan(request="test", steps=steps)
        plan.score = planner._score_plan(plan)
        details = planner._score_details(plan)
        assert "steps=" in details
        assert "score=" in details


class TestAdaptiveReplan:
    """Tests for adaptive replanning logic."""

    def test_should_replan_no_error(self):
        planner = Planner()
        plan = Plan(request="test", steps=[PlanStep(id="s1", goal="G1")])
        assert planner._should_replan(plan) is False

    def test_should_replan_with_error_but_no_failures(self):
        planner = Planner()
        plan = Plan(request="test", steps=[PlanStep(id="s1", goal="G1", status="completed")])
        plan.error = "something went wrong"
        assert planner._should_replan(plan) is True

    def test_should_replan_majority_failed(self):
        planner = Planner()
        plan = Plan(
            request="test",
            steps=[
                PlanStep(id="s1", goal="G1", status="failed"),
                PlanStep(id="s2", goal="G2", status="failed"),
                PlanStep(id="s3", goal="G3", status="completed"),
            ],
        )
        plan.error = "two steps failed"
        assert planner._should_replan(plan) is False

    @pytest.mark.asyncio
    async def test_adaptive_replan_with_stub_provider(self, stub_provider, fresh_db):
        provider = stub_provider(
            responses=[
                json.dumps([
                    {"id": "alt_1", "goal": "Try a different approach", "tool": "system_monitor"},
                ])
            ]
        )
        planner = Planner(provider=provider)
        old = Plan(
            request="test retry",
            steps=[PlanStep(id="s1", goal="Original step", status="failed", error="timeout")],
        )
        new = await planner._adaptive_replan(old, "test retry", "test_topic")
        assert len(new.steps) >= 1
        assert new.steps[0].goal == "Try a different approach"

    @pytest.mark.asyncio
    async def test_adaptive_replan_fallback_on_empty(self, stub_provider, fresh_db):
        provider = stub_provider(responses=["invalid output with no json"])
        planner = Planner(provider=provider)
        old = Plan(
            request="test",
            steps=[PlanStep(id="s1", goal="G1", status="failed", error="error")],
        )
        new = await planner._adaptive_replan(old, "test", "t")
        # Should return the original plan if no valid steps parsed.
        assert new is old


class TestVerifierResult:
    """Tests for structured verifier result parsing."""

    def test_parse_json_pass(self):
        text = '{"status": "PASS", "confidence": 0.95, "issues": [], "evidence": "CPU is 25% as expected", "action": "COMPLETE"}'
        vr = _parse_verifier_result(text)
        assert vr.status == "PASS"
        assert vr.confidence == 0.95
        assert vr.issues == []
        assert vr.action == "COMPLETE"
        assert vr.passed is True

    def test_parse_json_fail(self):
        text = '{"status": "FAIL", "confidence": 0.3, "issues": ["result is empty"], "evidence": "no data found", "action": "REPLAN"}'
        vr = _parse_verifier_result(text)
        assert vr.status == "FAIL"
        assert vr.confidence == 0.3
        assert len(vr.issues) == 1
        assert vr.action == "REPLAN"
        assert vr.passed is False

    def test_parse_json_uncertain(self):
        text = '{"status": "UNCERTAIN", "confidence": 0.5, "issues": ["partial match"], "evidence": "some data ok", "action": "HUMAN_REVIEW"}'
        vr = _parse_verifier_result(text)
        assert vr.status == "UNCERTAIN"
        assert vr.confidence == 0.5
        assert vr.action == "HUMAN_REVIEW"

    def test_parse_fallback_pass(self):
        vr = _parse_verifier_result("PASS")
        assert vr.status == "PASS"
        assert vr.confidence == 0.8
        assert vr.action == "COMPLETE"

    def test_parse_fallback_fail(self):
        vr = _parse_verifier_result("FAIL")
        assert vr.status == "FAIL"
        assert vr.confidence == 0.4
        assert vr.action == "REPLAN"

    def test_parse_invalid_json_fallback(self):
        vr = _parse_verifier_result("{invalid json here")
        assert vr.status == "FAIL"
        assert vr.confidence == 0.4

    def test_parse_empty_text(self):
        vr = _parse_verifier_result("")
        assert vr.status == "FAIL"

    def test_parse_retry_action(self):
        text = '{"status": "FAIL", "confidence": 0.6, "issues": ["minor formatting issue"], "evidence": "data present but messy", "action": "RETRY"}'
        vr = _parse_verifier_result(text)
        assert vr.action == "RETRY"
        assert vr.passed is False

    @pytest.mark.asyncio
    async def test_verify_with_structured_pass(self):
        """Verifier should parse structured JSON PASS correctly."""

        class StructuredProvider:
            name = "struct"
            async def is_available(self): return True
            async def generate_stream(self, messages, opts):
                yield GenerateChunk(
                    text='{"status": "PASS", "confidence": 0.9, "issues": [], "evidence": "all good", "action": "COMPLETE"}',
                    done=True, finish_reason="stop",
                )
            async def embed(self, text): return [0.0, 0.0, 0.0]

        planner = Planner(provider=StructuredProvider())
        vr = await planner._verify("Check", "OK", "test")
        assert vr.passed is True
        assert vr.confidence == 0.9

    @pytest.mark.asyncio
    async def test_verify_with_structured_human_review(self):
        class HumanReviewProvider:
            name = "human"
            async def is_available(self): return True
            async def generate_stream(self, messages, opts):
                yield GenerateChunk(
                    text='{"status": "UNCERTAIN", "confidence": 0.4, "issues": ["ambiguous output"], "evidence": "needs expert review", "action": "HUMAN_REVIEW"}',
                    done=True, finish_reason="stop",
                )
            async def embed(self, text): return [0.0, 0.0, 0.0]

        planner = Planner(provider=HumanReviewProvider())
        vr = await planner._verify("Check", "Ambiguous", "test")
        assert vr.passed is False
        assert vr.action == "HUMAN_REVIEW"

    def test_plan_step_verifier_result_field(self):
        step = PlanStep(id="s1", goal="Test")
        assert step.verifier_result is None
        vr = VerifierResult(status="PASS", confidence=1.0, action=VerifierAction.COMPLETE.value)
        step.verifier_result = vr
        step.verified = vr.passed
        assert step.verified is True
        assert step.verifier_result.action == "COMPLETE"

    def test_should_replan_blocks_human_review(self):
        planner = Planner()
        plan = Plan(
            request="test",
            steps=[
                PlanStep(id="s1", goal="G1", status="failed", verifier_result=VerifierResult(
                    status="UNCERTAIN", action=VerifierAction.HUMAN_REVIEW.value,
                )),
            ],
        )
        plan.error = "step s1 failed"
        assert planner._should_replan(plan) is False
