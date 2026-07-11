"""Safety policy engine — risk classification, approval modes, and permission policies.

Extends the static permission system with dynamic risk assessment and
configurable approval requirements.

Risk levels:
  LOW       — read-only, informational (auto-approved)
  MEDIUM    — modifies state but safe (confirm if policy requires)
  HIGH      — destructive or dangerous (always confirm)
  CRITICAL  — irreversible, system-level (deny unless explicit override)

Approval modes:
  AUTONOMOUS — agent decides (respects risk + permission)
  CONFIRM    — user must approve MEDIUM+ actions
  SAFE       — deny everything HIGH+
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from paios.config import ApprovalMode, RiskLevel
from paios.security.command_policy import PermissionLevel

logger = logging.getLogger(__name__)


# ── Risk classifiers ─────────────────────────────────────────────────────────

_RISK_KEYWORDS: dict[str, RiskLevel] = {
    # CRITICAL keywords
    "delete": RiskLevel.CRITICAL,
    "format": RiskLevel.CRITICAL,
    "shutdown": RiskLevel.CRITICAL,
    "reboot": RiskLevel.CRITICAL,
    "destroy": RiskLevel.CRITICAL,
    "wipe": RiskLevel.CRITICAL,
    # HIGH keywords
    "write": RiskLevel.HIGH,
    "modify": RiskLevel.HIGH,
    "overwrite": RiskLevel.HIGH,
    "remove": RiskLevel.HIGH,
    "kill": RiskLevel.HIGH,
    "install": RiskLevel.HIGH,
    "network": RiskLevel.HIGH,
    "download": RiskLevel.HIGH,
    "upload": RiskLevel.HIGH,
    "exec": RiskLevel.HIGH,
    "spawn": RiskLevel.HIGH,
    # MEDIUM keywords
    "create": RiskLevel.MEDIUM,
    "update": RiskLevel.MEDIUM,
    "rename": RiskLevel.MEDIUM,
    "move": RiskLevel.MEDIUM,
    "copy": RiskLevel.MEDIUM,
    "append": RiskLevel.MEDIUM,
    "edit": RiskLevel.MEDIUM,
}

_TOOL_RISK_MAP: dict[str, RiskLevel] = {
    "filesystem_read": RiskLevel.LOW,
    "filesystem_write": RiskLevel.HIGH,
    "terminal": RiskLevel.HIGH,
    "system_monitor": RiskLevel.LOW,
    "project_analyzer": RiskLevel.LOW,
    "memory_search": RiskLevel.LOW,
    "memory_store": RiskLevel.MEDIUM,
}


def classify_risk(tool_name: str, inputs: dict[str, Any] | None = None) -> RiskLevel:
    """Classify the risk level of a tool invocation.

    Uses tool-specific defaults first, then inspects the operation name
    for risk keywords.
    """
    base_risk = _TOOL_RISK_MAP.get(tool_name, RiskLevel.MEDIUM)

    if not inputs:
        return base_risk

    operation = (
        inputs.get("operation")
        or inputs.get("action")
        or inputs.get("command")
        or ""
    )
    op_lower = str(operation).lower()

    for keyword, risk in _RISK_KEYWORDS.items():
        if keyword in op_lower and risk.severity > base_risk.severity:
            return risk

    return base_risk


# ── Safety policy engine ─────────────────────────────────────────────────────


class SafetyPolicy:
    """Evaluates whether a tool action should be allowed, confirmed, or denied.

    Combines:
    - Tool permission level (FREE/CONFIRM/RESTRICTED)
    - Dynamic risk classification
    - Approval mode (autonomous/confirm/safe)
    - Configurable risk thresholds
    """

    def __init__(
        self,
        approval_mode: ApprovalMode | str = ApprovalMode.CONFIRM,
        max_auto_risk: RiskLevel | str = RiskLevel.LOW,
        require_confirm_risk: RiskLevel | str = RiskLevel.MEDIUM,
    ) -> None:
        self.approval_mode = ApprovalMode(approval_mode) if isinstance(approval_mode, str) else approval_mode
        self.max_auto_risk = RiskLevel(max_auto_risk) if isinstance(max_auto_risk, str) else max_auto_risk
        self.require_confirm_risk = RiskLevel(require_confirm_risk) if isinstance(require_confirm_risk, str) else require_confirm_risk

    def evaluate(
        self,
        tool_name: str,
        inputs: dict[str, Any] | None = None,
        permission: PermissionLevel = PermissionLevel.CONFIRM,
    ) -> tuple[bool, str]:
        """Evaluate a tool action.

        Returns (allowed: bool, reason: str).
        If allowed is True, the action can proceed.
        If allowed is False, the action is denied.
        If the caller should request confirmation, reason starts with 'confirm:'.
        """
        risk = classify_risk(tool_name, inputs)

        if self.approval_mode == ApprovalMode.SAFE:
            if risk.severity >= RiskLevel.HIGH.severity:
                return (False, f"SAFE mode denies {risk.value} risk action '{tool_name}'")
            if permission == PermissionLevel.RESTRICTED:
                return (False, f"SAFE mode denies RESTRICTED action '{tool_name}'")
            return (True, "approved")

        if self.approval_mode == ApprovalMode.AUTONOMOUS:
            if risk.severity >= RiskLevel.CRITICAL.severity:
                return (False, f"AUTONOMOUS mode denies {risk.value} risk action '{tool_name}'")
            if permission == PermissionLevel.RESTRICTED and risk.severity >= RiskLevel.HIGH.severity:
                return (False, f"RESTRICTED+{risk.value} action denied in AUTONOMOUS mode")
            return (True, "approved")

        # CONFIRM mode (default)
        if permission == PermissionLevel.RESTRICTED:
            return (False, f"RESTRICTED action '{tool_name}' requires user approval")

        if risk.severity >= RiskLevel.CRITICAL.severity:
            return (False, f"CRITICAL risk action '{tool_name}' denied")

        if risk.severity >= self.require_confirm_risk.severity:
            return (True, f"confirm:{risk.value}:{tool_name}")

        return (True, "approved")


# ── Default instance ─────────────────────────────────────────────────────────

_default_policy: SafetyPolicy | None = None
_policy_lock = threading.Lock()


def get_safety_policy() -> SafetyPolicy:
    """Return the process-wide safety policy."""
    global _default_policy
    if _default_policy is None:
        with _policy_lock:
            if _default_policy is None:
                from paios.config import get_settings

                settings = get_settings().security
                _default_policy = SafetyPolicy(
                    approval_mode=getattr(settings, "approval_mode", ApprovalMode.CONFIRM),
                    max_auto_risk=getattr(settings, "max_auto_risk", RiskLevel.LOW),
                    require_confirm_risk=getattr(settings, "require_confirm_risk", RiskLevel.MEDIUM),
                )
    return _default_policy


def reset_safety_policy() -> None:
    """Test helper: clear cached policy."""
    global _default_policy
    _default_policy = None
