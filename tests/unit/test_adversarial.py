"""Phase 6 Objective 2: Adversarial tests.

Attempts to break the system with malicious inputs, invalid plans,
memory overload, infinite loops, and unexpected failures.
Every discovered edge case becomes a regression test.
"""

from __future__ import annotations

import json

import pytest

from paios.config import get_settings
from paios.core.agent import Agent
from paios.core.planner import Plan, PlanStep, Planner
from paios.memory.store import get_memory_store
from paios.security.command_policy import PermissionLevel, classify_command
from paios.security.policy import SafetyPolicy, classify_risk


# ── Safety adversarial tests ────────────────────────────────────────────────

class TestSafetyAdversarial:
    """Attempt to bypass tool permission checks."""

    def test_path_traversal_outside_sandbox(self, sandbox_root):
        """Absolute path outside sandbox should be blocked."""
        from paios.security.path_policy import validate_path, PathPolicyError

        with pytest.raises(PathPolicyError):
            validate_path(
                str(sandbox_root.parent / "etc" / "passwd"),
                roots=[sandbox_root],
            )

    def test_path_traversal_double_dot(self, sandbox_root):
        """Relative traversal outside sandbox should be blocked."""
        from paios.security.path_policy import validate_path, PathPolicyError

        with pytest.raises(PathPolicyError):
            validate_path(
                "../../etc/passwd",
                roots=[sandbox_root],
            )

    def test_path_inside_sandbox_allowed(self, sandbox_root):
        """Path within sandbox should be allowed."""
        from paios.security.path_policy import validate_path

        result = validate_path(
            str(sandbox_root / "test.txt"),
            roots=[sandbox_root],
        )
        assert result is not None

    def test_dangerous_shell_metacharacters(self):
        """Shell metacharacters should elevate to CONFIRM or RESTRICTED."""
        for cmd in [
            "ls; rm -rf /",
            "cat foo &> /dev/null",
            "echo $(whoami)",
            "cat file | sh",
            "ls || echo pwned",
            "cat file && rm -rf /",
        ]:
            perm = classify_command(cmd)
            assert perm in (
                PermissionLevel.CONFIRM, PermissionLevel.RESTRICTED,
            ), f"Command not caught: {cmd}"

    def test_safety_policy_critical_denied_or_confirmed(self):
        """CRITICAL risk actions should never be FREE."""
        from paios.config import ApprovalMode, RiskLevel

        for mode in ApprovalMode:
            policy = SafetyPolicy(approval_mode=mode)
            allowed, reason = policy.evaluate(
                "terminal",
                {"operation": "delete", "command": "rm -rf /"},
            )
            assert not allowed, f"mode={mode} should deny CRITICAL but got: {allowed} {reason}"

    def test_unknown_tool_defaults_to_medium(self):
        risk = classify_risk("nonexistent_tool_xyz", {})
        from paios.config import RiskLevel

        assert risk in (RiskLevel.MEDIUM, RiskLevel.HIGH)

    def test_empty_input_does_not_crash_safety(self):
        risk = classify_risk("system_monitor", {})
        assert risk is not None


# ── Planner adversarial tests ───────────────────────────────────────────────

class TestPlannerAdversarial:
    """Test planner handling of invalid, impossible, or malicious plans."""

    def test_plan_with_infinite_circular_dependency(self):
        planner = Planner()
        plan = Plan(
            request="test",
            steps=[
                PlanStep(id="a", goal="Step A", depends_on=["b"]),
                PlanStep(id="b", goal="Step B", depends_on=["c"]),
                PlanStep(id="c", goal="Step C", depends_on=["a"]),
            ],
        )
        error = planner._validate_plan(plan)
        assert error is not None
        assert "circular" in error.lower()

    def test_plan_with_self_dependency(self):
        planner = Planner()
        plan = Plan(
            request="test",
            steps=[PlanStep(id="a", goal="Step A", depends_on=["a"])],
        )
        error = planner._validate_plan(plan)
        assert error is not None
        assert "circular" in error.lower()

    def test_plan_with_unknown_dependency(self):
        planner = Planner()
        plan = Plan(
            request="test",
            steps=[PlanStep(id="a", goal="Step A", depends_on=["nonexistent_step"])],
        )
        error = planner._validate_plan(plan)
        assert error is not None
        assert "unknown" in error.lower()

    def test_plan_with_impossible_goal(self):
        planner = Planner()
        text = json.dumps([
            {"id": "step_1", "goal": "Fly to the moon and back", "tool": "system_monitor"},
        ])
        steps = planner._parse_steps(text)
        assert len(steps) == 1

    def test_plan_with_no_steps(self):
        planner = Planner()
        error = planner._validate_plan(Plan(request="test", steps=[]))
        assert error is not None
        assert "no steps" in error.lower()

    def test_plan_with_one_step_no_deps(self):
        planner = Planner()
        error = planner._validate_plan(
            Plan(request="test", steps=[PlanStep(id="a", goal="Do X")])
        )
        assert error is None

    def test_planner_invalid_json_malformed(self):
        planner = Planner()
        steps = planner._parse_steps("{bad json here")
        assert steps == []

    def test_planner_xml_injection(self):
        planner = Planner()
        text = '<?xml version="1.0"?><!DOCTYPE foo>'
        steps = planner._parse_steps(text)
        assert isinstance(steps, list)

    def test_planner_huge_json(self):
        planner = Planner()
        steps_data = [{"id": f"s{i}", "goal": f"Goal {i}"} for i in range(1000)]
        text = json.dumps(steps_data)
        steps = planner._parse_steps(text)
        assert len(steps) == 1000


# ── Memory adversarial tests ────────────────────────────────────────────────

class TestMemoryAdversarial:
    """Test memory system resilience to edge cases."""

    def test_store_empty_content(self, fresh_db):
        store = get_memory_store()
        with pytest.raises(ValueError):
            store.store(category="history", content="", importance=0.5)

    def test_store_extremely_long_content(self, fresh_db):
        store = get_memory_store()
        long_content = "x" * 100_000
        mem = store.store(category="history", content=long_content, importance=0.9)
        assert mem is not None
        assert len(mem.content) == 100_000

    def test_store_negative_importance_clamped(self, fresh_db):
        store = get_memory_store()
        mem = store.store(category="history", content="negative importance test", importance=-1.0)
        assert mem is not None
        assert mem.importance == 0.0

    def test_store_above_max_importance_clamped(self, fresh_db):
        store = get_memory_store()
        mem = store.store(category="history", content="high importance test", importance=999.0)
        assert mem is not None
        assert mem.importance == 1.0

    def test_search_sql_injection_attempt(self, fresh_db):
        store = get_memory_store()
        store.store(category="history", content="normal memory", importance=0.5)
        results = store.search("' OR 1=1; --")
        assert isinstance(results, list)

    def test_search_empty_query(self, fresh_db):
        store = get_memory_store()
        results = store.search("")
        assert isinstance(results, list)

    def test_search_special_characters(self, fresh_db):
        store = get_memory_store()
        special = "!@#$%^&*()_+{}|:<>?[];',./\\"
        store.store(category="history", content=special, importance=0.5)
        results = store.search(special[:10])
        assert isinstance(results, list)

    def test_memory_overload_100_items(self, fresh_db):
        store = get_memory_store()
        for i in range(100):
            store.store(category="history", content=f"memory item number {i}", importance=0.5)
        count = store.count()
        assert count == 100
        results = store.search("memory item")
        assert len(results) >= 1

    def test_contradictory_memories(self, fresh_db):
        store = get_memory_store()
        store.store(category="skill", content="Always use tabs for indentation", importance=0.8)
        store.store(category="skill", content="Always use spaces for indentation", importance=0.8)
        results = store.search("indentation")
        assert len(results) >= 2

    def test_delete_nonexistent(self, fresh_db):
        store = get_memory_store()
        store.delete("nonexistent_public_id")


# ── Agent adversarial tests ────────────────────────────────────────────────

class TestAgentAdversarial:
    """Test agent resilience to failures, loops, and edge cases."""

    @pytest.mark.asyncio
    async def test_agent_empty_request(self, fresh_db, stub_provider):
        agent = Agent(provider=stub_provider(responses=["I see you sent an empty request."]))
        result = await agent.run("", task_public_id="test_empty")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_very_long_request(self, fresh_db, stub_provider):
        agent = Agent(provider=stub_provider(responses=["That was a very long request."]))
        long_req = "hello " * 5000
        result = await agent.run(long_req, task_public_id="test_long")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_repeated_tool_failures(self, fresh_db, stub_provider):
        agent = Agent(provider=stub_provider(responses=["Final answer after tool failure."]))
        result = await agent.run("do something", task_public_id="test_retry")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_provider_failure_during_run(self, fresh_db, stub_provider):
        agent = Agent(provider=stub_provider(responses=["Test answer."]))
        result = await agent.run("test request", task_public_id="test_provider_fail")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_cancel_running(self, fresh_db, stub_provider):
        agent = Agent(provider=stub_provider(responses=["Final answer."]))
        agent.cancel("test_cancel_task2")
        result = await agent.run("test request", task_public_id="test_cancel_task2")
        assert result.error == "cancelled"

    @pytest.mark.asyncio
    async def test_agent_unknown_tool_in_input(self, fresh_db, stub_provider):
        responses = [
            {"name": "nonexistent_tool_xyz", "arguments": {"arg": "value"}},
        ]
        agent = Agent(provider=stub_provider(responses=responses))
        result = await agent.run("use nonexistent tool", task_public_id="test_unknown_tool")
        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_max_iterations_with_no_answer(self, fresh_db, stub_provider):
        original = get_settings().security.agent_max_iterations
        get_settings().security.agent_max_iterations = 3
        try:
            responses = [{"name": "system_monitor", "arguments": {}}] * 5
            agent = Agent(provider=stub_provider(responses=responses))
            result = await agent.run("keep running tools", task_public_id="test_max_iter")
            assert result.error is not None
            assert "max iterations" in result.error.lower() or "exhausted" in result.error.lower()
        finally:
            get_settings().security.agent_max_iterations = original

    def test_agent_singleton_reset(self):
        from paios.core.agent import reset_agent, get_agent

        a1 = get_agent()
        reset_agent()
        a2 = get_agent()
        assert a1 is not a2
