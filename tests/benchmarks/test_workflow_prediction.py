"""Benchmarks for workflow prediction — tests workflow engine execution."""

from __future__ import annotations

import pytest
from veyron.workflow.engine import WorkflowEngine, resolve_template
from veyron.workflow.models import (
    FailurePolicy,
    WorkflowDefinition,
    WorkflowExecutionResult,
    WorkflowStep,
)


class TestWorkflowEngineBenchmarks:

    def test_resolve_template(self):
        result = resolve_template("Hello $name", {"name": "World"})
        assert result == "Hello World"

    def test_resolve_template_no_vars(self):
        result = resolve_template("Hello World", {})
        assert result == "Hello World"

    def test_resolve_template_missing_var(self):
        result = resolve_template("Hello $name", {})
        assert "$name" in result  # Template.safe_substitute leaves unresolved

    def test_workflow_definition_creation(self):
        wf = WorkflowDefinition(
            name="test_workflow",
            description="A test workflow",
            steps=[
                WorkflowStep(name="step1", tool_name="read_file", params={"path": "/tmp/test.txt"}),
                WorkflowStep(name="step2", tool_name="system_monitor", params={"operation": "overview"}),
            ],
        )
        assert len(wf.steps) == 2
        assert wf.steps[0].tool_name == "read_file"

    def test_workflow_with_variables(self):
        wf = WorkflowDefinition(
            name="var_workflow",
            variables=["path", "name"],
            steps=[
                WorkflowStep(name="read", tool_name="read_file", params={"path": "$path"}),
                WorkflowStep(name="greet", tool_name="hello_world", params={"name": "$name"}),
            ],
        )
        assert wf.variables == ["path", "name"]

    def test_condition_evaluation_true(self):
        engine = WorkflowEngine()
        assert engine._evaluate_condition("true") is True
        assert engine._evaluate_condition("'a' == 'a'") is True
        assert engine._evaluate_condition("") is True

    def test_condition_evaluation_false(self):
        engine = WorkflowEngine()
        assert engine._evaluate_condition("false") is False
        assert engine._evaluate_condition("'a' == 'b'") is False
        assert engine._evaluate_condition("not true") is False
