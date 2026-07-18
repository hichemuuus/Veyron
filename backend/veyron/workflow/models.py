"""Workflow data models — runtime representations (not DB models)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class StepType:
    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    CONDITION = "condition"
    WAIT = "wait"
    SUB_WORKFLOW = "sub_workflow"


class FailurePolicy:
    ABORT = "abort"
    SKIP = "skip"
    RETRY = "retry"
    IGNORE = "ignore"


@dataclass
class WorkflowStep:
    """A single step inside a workflow."""
    step_type: str = StepType.TOOL_CALL
    name: str = ""
    tool_name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    condition: str = ""  # empty = always execute
    retry_count: int = 0
    retry_delay_ms: int = 500
    failure_policy: str = FailurePolicy.ABORT
    timeout_ms: int = 30000
    variables: dict[str, str] = field(default_factory=dict)  # template vars: name -> source


@dataclass
class WorkflowDefinition:
    """Complete workflow definition."""
    name: str
    description: str = ""
    version: str = "1.0"
    tags: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)


@dataclass
class WorkflowExecutionResult:
    """Result of executing a workflow."""
    success: bool
    workflow_name: str
    total_steps: int
    completed_steps: int
    failed_steps: int
    duration_ms: int
    step_results: list[dict[str, Any]] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str = ""
