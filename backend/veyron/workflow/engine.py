"""Workflow execution engine."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from string import Template
from typing import Any

from veyron.tools.base import ToolContext
from veyron.tools.registry import get_registry
from veyron.workflow.models import (
    FailurePolicy,
    StepType,
    WorkflowDefinition,
    WorkflowExecutionResult,
    WorkflowStep,
)

logger = logging.getLogger(__name__)


def resolve_template(template: str, variables: dict[str, Any]) -> str:
    """Resolve $variable references in a template string."""
    try:
        return Template(template).safe_substitute(variables)
    except Exception:
        return template


class WorkflowEngine:
    """Executes reusable workflow definitions."""

    def __init__(self):
        self._registry = get_registry()

    async def execute(
        self,
        workflow: WorkflowDefinition,
        variables: dict[str, Any] | None = None,
        task_public_id: str = "workflow",
    ) -> WorkflowExecutionResult:
        """Execute a workflow with given variables."""
        resolved_vars: dict[str, Any] = dict(variables or {})
        step_results: list[dict[str, Any]] = []
        completed = 0
        failed = 0
        outputs: dict[str, Any] = {}
        start = time.perf_counter()
        ctx = ToolContext(task_public_id=task_public_id)

        for step_index, step in enumerate(workflow.steps):
            # Condition check
            if step.condition:
                condition_resolved = resolve_template(step.condition, {**resolved_vars, **outputs})
                if not self._evaluate_condition(condition_resolved):
                    logger.info("workflow step %d skipped (condition false): %s", step_index, step.name)
                    step_results.append({"step": step_index, "name": step.name, "status": "skipped"})
                    completed += 1
                    continue

            # Resolve variables in params
            resolved_params: dict[str, Any] = {}
            for k, v in step.params.items():
                if isinstance(v, str):
                    resolved_params[k] = resolve_template(v, {**resolved_vars, **outputs})
                else:
                    resolved_params[k] = v

            # Execute step with retries
            step_ok = False
            step_error = ""
            step_duration = 0
            max_attempts = 1 + step.retry_count

            for attempt in range(max_attempts):
                step_start = time.perf_counter()
                try:
                    if step.step_type == StepType.TOOL_CALL:
                        tool = self._registry.get(step.tool_name)
                        if tool is None:
                            raise ValueError(f"tool not found: {step.tool_name}")
                        result = await tool.safe_run(ctx, **resolved_params)
                        step_ok = result.ok
                        step_error = result.error or ""
                        if result.ok and result.data:
                            outputs[step.name] = result.data
                        step_results.append({
                            "step": step_index,
                            "name": step.name,
                            "tool": step.tool_name,
                            "status": "completed" if step_ok else "failed",
                            "output": result.output if step_ok else result.error,
                        })
                    elif step.step_type == StepType.WAIT:
                        wait_secs = float(resolved_params.get("seconds", 1))
                        await asyncio.sleep(wait_secs)
                        step_ok = True
                        step_results.append({"step": step_index, "name": step.name, "status": "completed"})
                    else:
                        step_results.append({"step": step_index, "name": step.name, "status": "skipped", "error": f"unsupported step type: {step.step_type}"})
                        step_ok = True  # skip unknown types
                except Exception as e:
                    step_ok = False
                    step_error = f"{type(e).__name__}: {e}"
                    step_results.append({"step": step_index, "name": step.name, "status": "failed", "error": step_error})

                step_duration = int((time.perf_counter() - step_start) * 1000)

                if step_ok:
                    completed += 1
                    break

                if attempt < max_attempts - 1:
                    logger.info("workflow step %d retrying (%d/%d): %s", step_index, attempt + 1, max_attempts, step_error)
                    await asyncio.sleep(step.retry_delay_ms / 1000)

            if not step_ok:
                failed += 1
                if step.failure_policy == FailurePolicy.ABORT:
                    total_duration = int((time.perf_counter() - start) * 1000)
                    return WorkflowExecutionResult(
                        success=False,
                        workflow_name=workflow.name,
                        total_steps=len(workflow.steps),
                        completed_steps=completed,
                        failed_steps=failed,
                        duration_ms=total_duration,
                        step_results=step_results,
                        error=step_error,
                    )
                elif step.failure_policy == FailurePolicy.SKIP:
                    completed += 1
                    continue
                elif step.failure_policy == FailurePolicy.IGNORE:
                    completed += 1
                    continue

        total_duration = int((time.perf_counter() - start) * 1000)
        return WorkflowExecutionResult(
            success=failed == 0,
            workflow_name=workflow.name,
            total_steps=len(workflow.steps),
            completed_steps=completed,
            failed_steps=failed,
            duration_ms=total_duration,
            step_results=step_results,
            outputs=outputs,
        )

    def _evaluate_condition(self, condition: str) -> bool:
        """Evaluate a simple condition string. Supports: $var == 'value', $var != 'value', $var."""
        condition = condition.strip()
        if not condition:
            return True
        if condition.startswith("not "):
            return not self._evaluate_simple(condition[4:])
        return self._evaluate_simple(condition)

    def _evaluate_simple(self, condition: str) -> bool:
        if "==" in condition:
            parts = condition.split("==", 1)
            return parts[0].strip().strip("'\"") == parts[1].strip().strip("'\"")
        if "!=" in condition:
            parts = condition.split("!=", 1)
            return parts[0].strip().strip("'\"") != parts[1].strip().strip("'\"")
        if condition.lower() == "true":
            return True
        if condition.lower() == "false":
            return False
        return bool(condition)
