"""Tests for the safety/policy module — risk classification and SafetyPolicy."""

from __future__ import annotations

import pytest

from paios.config import ApprovalMode, RiskLevel
from paios.security.command_policy import PermissionLevel
from paios.security.policy import SafetyPolicy, classify_risk, get_safety_policy, reset_safety_policy


class TestClassifyRisk:
    """Risk classification by tool name and inputs."""

    def test_known_tool_default(self):
        assert classify_risk("filesystem_read") == RiskLevel.LOW
        assert classify_risk("filesystem_write") == RiskLevel.HIGH
        assert classify_risk("terminal") == RiskLevel.HIGH
        assert classify_risk("memory_search") == RiskLevel.LOW
        assert classify_risk("memory_store") == RiskLevel.MEDIUM

    def test_unknown_tool_defaults_to_medium(self):
        assert classify_risk("unknown_tool") == RiskLevel.MEDIUM

    def test_keyword_escalation_delete(self):
        assert classify_risk("filesystem_write", {"operation": "delete_file"}) == RiskLevel.CRITICAL
        assert classify_risk("memory_store", {"operation": "delete_entry"}) == RiskLevel.CRITICAL

    def test_keyword_escalation_format(self):
        assert classify_risk("terminal", {"command": "format"}) == RiskLevel.CRITICAL

    def test_keyword_escalation_shutdown(self):
        assert classify_risk("terminal", {"command": "shutdown_system"}) == RiskLevel.CRITICAL

    def test_action_field_checked(self):
        assert classify_risk("terminal", {"action": "destroy"}) == RiskLevel.CRITICAL
        assert classify_risk("unknown_tool", {"action": "write_file"}) == RiskLevel.HIGH
        assert classify_risk("unknown_tool", {"action": "read_file"}) == RiskLevel.MEDIUM

    def test_no_escalation_for_lower_risk(self):
        # 'write' is HIGH keyword, but base_risk for write is already HIGH, so no escalation
        assert classify_risk("filesystem_write", {"operation": "write_data"}) == RiskLevel.HIGH

    def test_empty_inputs(self):
        assert classify_risk("terminal", {}) == RiskLevel.HIGH
        assert classify_risk("terminal", None) == RiskLevel.HIGH


class TestSafetyPolicyDefault:
    """SafetyPolicy in default CONFIRM mode."""

    def setup_method(self):
        self.policy = SafetyPolicy()

    def test_low_auto_approved(self):
        allowed, reason = self.policy.evaluate("filesystem_read", permission=PermissionLevel.FREE)
        assert allowed
        assert reason == "approved"

    def test_medium_requires_confirm(self):
        allowed, reason = self.policy.evaluate("memory_store", permission=PermissionLevel.CONFIRM)
        assert allowed
        assert reason.startswith("confirm:")

    def test_high_requires_confirm(self):
        allowed, reason = self.policy.evaluate("filesystem_write", permission=PermissionLevel.CONFIRM)
        assert allowed
        assert reason.startswith("confirm:")

    def test_critical_denied(self):
        allowed, reason = self.policy.evaluate("terminal", {"command": "format"}, permission=PermissionLevel.CONFIRM)
        assert not allowed
        assert "CRITICAL" in reason

    def test_restricted_denied(self):
        allowed, reason = self.policy.evaluate("terminal", permission=PermissionLevel.RESTRICTED)
        assert not allowed
        assert "RESTRICTED" in reason


class TestSafetyPolicyAutonomous:
    """SafetyPolicy in AUTONOMOUS mode."""

    def setup_method(self):
        self.policy = SafetyPolicy(approval_mode=ApprovalMode.AUTONOMOUS)

    def test_low_approved(self):
        allowed, reason = self.policy.evaluate("filesystem_read")
        assert allowed

    def test_medium_approved(self):
        allowed, reason = self.policy.evaluate("memory_store")
        assert allowed

    def test_high_approved(self):
        allowed, reason = self.policy.evaluate("filesystem_write")
        assert allowed

    def test_critical_denied(self):
        allowed, reason = self.policy.evaluate("terminal", {"command": "format"})
        assert not allowed

    def test_restricted_high_denied(self):
        allowed, reason = self.policy.evaluate(
            "filesystem_write", permission=PermissionLevel.RESTRICTED,
        )
        assert not allowed

    def test_restricted_low_allowed(self):
        allowed, reason = self.policy.evaluate(
            "filesystem_read", permission=PermissionLevel.RESTRICTED,
        )
        assert allowed


class TestSafetyPolicySafe:
    """SafetyPolicy in SAFE mode."""

    def setup_method(self):
        self.policy = SafetyPolicy(approval_mode=ApprovalMode.SAFE)

    def test_low_approved(self):
        allowed, reason = self.policy.evaluate("filesystem_read")
        assert allowed

    def test_medium_denied(self):
        # In SAFE mode, HIGH and above are denied. MEDIUM should be allowed
        allowed, reason = self.policy.evaluate("memory_store")
        assert allowed

    def test_high_denied(self):
        allowed, reason = self.policy.evaluate("filesystem_write")
        assert not allowed
        assert "SAFE" in reason

    def test_restricted_denied(self):
        allowed, reason = self.policy.evaluate(
            "memory_search", permission=PermissionLevel.RESTRICTED,
        )
        assert not allowed


class TestSafetyPolicyCustomThreshold:
    """Custom risk thresholds."""

    def test_require_confirm_high_only(self):
        policy = SafetyPolicy(
            approval_mode=ApprovalMode.CONFIRM,
            require_confirm_risk=RiskLevel.HIGH,
        )
        # MEDIUM should auto-approve
        allowed, reason = policy.evaluate("memory_store")
        assert allowed
        assert reason == "approved"

        # HIGH should require confirm
        allowed, reason = policy.evaluate("filesystem_write")
        assert allowed
        assert reason.startswith("confirm:")

    def test_max_auto_risk_medium(self):
        policy = SafetyPolicy(
            approval_mode=ApprovalMode.AUTONOMOUS,
            max_auto_risk=RiskLevel.MEDIUM,
        )
        # HIGH and below auto-approved
        assert policy.evaluate("filesystem_write")[0]
        # CRITICAL denied
        assert not policy.evaluate("terminal", {"command": "format"})[0]


class TestSafetyPolicyIntegration:
    """Integration with tool base — confirm hook and rejection."""

    async def test_safe_run_denies_critical(self):
        from paios.tools.base import Tool, ToolContext, ToolResult, cls_self_validate

        class DangerousTool(Tool):
            name = "dangerous"
            description = "dangerous"
            permission = PermissionLevel.CONFIRM

            async def run(self, ctx: ToolContext, **inputs) -> ToolResult:
                return ToolResult(output="done")

        tool = DangerousTool()
        ctx = ToolContext()
        result = await tool.safe_run(ctx, operation="delete_all")
        assert not result.ok
        assert "CRITICAL" in result.error

    async def test_safe_run_with_confirm_hook(self):
        from paios.tools.base import Tool, ToolContext, ToolResult

        class MediumTool(Tool):
            name = "memory_store"
            description = "store"
            permission = PermissionLevel.CONFIRM

            async def run(self, ctx: ToolContext, **inputs) -> ToolResult:
                return ToolResult(output="stored")

        tool = MediumTool()
        confirmed = False

        async def confirm_hook(**kwargs):
            nonlocal confirmed
            confirmed = True
            return (True, "ok")

        ctx = ToolContext(confirm=confirm_hook)
        result = await tool.safe_run(ctx)
        assert result.ok
        assert confirmed, "confirm hook should have been called"

    async def test_safe_run_confirm_hook_denies(self):
        from paios.tools.base import Tool, ToolContext, ToolResult

        class MediumTool(Tool):
            name = "memory_store"
            description = "store"
            permission = PermissionLevel.CONFIRM

            async def run(self, ctx: ToolContext, **inputs) -> ToolResult:
                return ToolResult(output="stored")

        tool = MediumTool()

        async def deny_hook(**kwargs):
            return (False, "user said no")

        ctx = ToolContext(confirm=deny_hook)
        result = await tool.safe_run(ctx)
        assert not result.ok
        assert "denied by user" in result.error

    async def test_low_risk_tool_skips_confirm(self):
        from paios.tools.base import Tool, ToolContext, ToolResult

        class SafeTool(Tool):
            name = "filesystem_read"
            description = "read"
            permission = PermissionLevel.FREE

            async def run(self, ctx: ToolContext, **inputs) -> ToolResult:
                return ToolResult(output="data")

        tool = SafeTool()
        ctx = ToolContext()
        result = await tool.safe_run(ctx)
        assert result.ok


class TestGetSafetyPolicy:
    """Process-wide default policy."""

    def teardown_method(self):
        reset_safety_policy()

    def test_default_policy_is_confirm(self):
        policy = get_safety_policy()
        assert policy.approval_mode == ApprovalMode.CONFIRM

    def test_policy_is_cached(self):
        p1 = get_safety_policy()
        p2 = get_safety_policy()
        assert p1 is p2

    def test_reset_creates_new_policy(self):
        p1 = get_safety_policy()
        reset_safety_policy()
        p2 = get_safety_policy()
        assert p1 is not p2
