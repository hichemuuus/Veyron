"""SQLModel table definitions.

Initial Phase-1 schema:
  - Task: agent task lifecycle
  - Memory: long-term memory (structured half; Phase 2 adds the vector half)
  - AuditEvent: append-only security audit trail
  - ToolInvocation: log of every tool call
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return a naive datetime in UTC, matching SQLite storage format."""
    return datetime.now(UTC).replace(tzinfo=None)


class TaskStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    AGENT_ITERATION = "agent_iteration"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    PLAN_STEP = "plan_step"
    PLAN_VERIFICATION = "plan_verification"
    PLAN_SYNTHESIS = "plan_synthesis"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Task(SQLModel, table=True):
    """An agent task. Created by every /api/agent call."""

    id: int | None = Field(default=None, primary_key=True)
    # Stable client-facing id (used in event streams and WebSocket topics).
    public_id: str = Field(index=True, unique=True)
    request: str
    status: TaskStatus = Field(default=TaskStatus.CREATED, index=True)
    # Final answer once completed.
    result: str | None = None
    # Error message if failed.
    error: str | None = None
    # Mode: react (simple) or plan (complex). Set by the intent router.
    mode: str = Field(default="react")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Checkpoint / execution tracking.
    checkpoint_data: str | None = None
    checkpoint_step: int = Field(default=0)
    model_used: str | None = None
    tool_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    total_steps: int = Field(default=0)
    completed_steps: int = Field(default=0)


class MemoryCategory(str, Enum):
    USER = "user"
    PROJECT = "project"
    HISTORY = "history"
    SKILL = "skill"
    REFLECTION = "reflection"
    PROFILE = "profile"
    WORKFLOW = "workflow"


class ReflectionCategory(str, Enum):
    TASK_REFLECTION = "task_reflection"
    MEMORY_REFLECTION = "memory_reflection"
    SKILL_REFLECTION = "skill_reflection"
    WORKFLOW_REFLECTION = "workflow_reflection"
    SYSTEM_REFLECTION = "system_reflection"


class Memory(SQLModel, table=True):
    """A long-term memory record. Vector embedding stored in Chroma (Phase 2)."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    category: MemoryCategory = Field(index=True)
    content: str
    # 0.0–1.0; drives retrieval ranking and decay.
    importance: float = Field(default=0.5)
    # Free-form tags.
    tags: str = Field(default="")
    # Chroma collection id once embedded.
    embedding_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )
    last_recalled_at: datetime | None = None
    recall_count: int = Field(default=0)
    # Quality scores (0.0–1.0).
    usefulness_score: float = Field(default=0.5)
    reliability_score: float = Field(default=0.5)
    success_frequency: float = Field(default=0.5)
    # Whether the memory has decayed below retrieval threshold.
    decayed: bool = Field(default=False)
    # Content hash for duplicate detection.
    content_hash: str = Field(default="")
    # Source: which task/reflection created this memory.
    source_task: str | None = None


class AuditEvent(SQLModel, table=True):
    """Append-only record of a privileged action.

    Also mirrored to backend/data/audit/ as JSON for tamper-evident storage.
    """

    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=_utcnow, index=True)
    action: str  # e.g. "tool.invoke", "security.confirm"
    subject: str  # who/what triggered it (task public_id, user, system)
    permission: str  # FREE | CONFIRM | RESTRICTED
    # JSON-serialized inputs.
    inputs: str = Field(default="{}")
    outcome: str = Field(default="pending")  # pending | approved | denied | success | error
    # User-supplied reason for RESTRICTED actions.
    reason: str | None = None
    detail: str | None = None


class ToolInvocation(SQLModel, table=True):
    """One execution of a tool."""

    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=_utcnow, index=True)
    task_public_id: str | None = Field(default=None, index=True)
    tool_name: str = Field(index=True)
    permission: str
    # JSON-serialized inputs and result.
    inputs: str = Field(default="{}")
    result: str = Field(default="")
    ok: bool = Field(default=True)
    duration_ms: int = Field(default=0)
    error: str | None = None


class ExecutionStep(SQLModel, table=True):
    """One step inside a task execution (iteration, LLM call, tool call, plan step, etc.)."""

    id: int | None = Field(default=None, primary_key=True)
    task_public_id: str = Field(index=True)
    step_index: int = Field(default=0)
    step_type: TaskType
    name: str  # tool name, step goal, etc.
    status: StepStatus = Field(default=StepStatus.PENDING)
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None
    duration_ms: int = Field(default=0)
    input_preview: str = Field(default="")
    output_preview: str = Field(default="")
    error: str | None = None
    retry_count: int = Field(default=0)
    metadata_json: str = Field(default="{}")  # extra structured data


class EvaluationMetric(SQLModel, table=True):
    """Stored metrics from an evaluation run."""

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True)
    category: str = Field(default="general", index=True)
    success: bool = Field(default=False)
    duration_ms: int = Field(default=0)
    iterations: int = Field(default=0)
    tool_calls_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    replan_count: int = Field(default=0)
    memory_count: int = Field(default=0)
    memory_usefulness_avg: float = Field(default=0.0)
    error: str | None = None
    details_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=_utcnow)


class ReflectionRecord(SQLModel, table=True):
    """Persistent reflection record for learning analytics."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    task_public_id: str = Field(default="", index=True)
    category: ReflectionCategory = Field(default=ReflectionCategory.TASK_REFLECTION)
    success: bool = Field(default=True)
    confidence: float = Field(default=0.5)
    planning_quality: float = Field(default=0.5)
    tool_selection_quality: float = Field(default=0.5)
    parameter_quality: float = Field(default=0.5)
    memory_usefulness: float = Field(default=0.5)
    mistake_count: int = Field(default=0)
    improvement_count: int = Field(default=0)
    tool_issue_count: int = Field(default=0)
    summary: str = Field(default="")
    improvement_notes: str = Field(default="")
    extra_data: str = Field(default="{}")
    created_at: datetime = Field(default_factory=_utcnow)


class WorkflowStepModel(SQLModel, table=True):
    """A single step within a reusable workflow."""

    id: int | None = Field(default=None, primary_key=True)
    workflow_public_id: str = Field(index=True)
    step_index: int = Field(default=0)
    step_type: str = Field(default="tool_call")
    name: str = Field(default="")
    tool_name: str = Field(default="")
    params_json: str = Field(default="{}")
    condition: str = Field(default="")
    retry_count: int = Field(default=0)
    retry_delay_ms: int = Field(default=500)
    failure_policy: str = Field(default="abort")
    created_at: datetime = Field(default_factory=_utcnow)


class Workflow(SQLModel, table=True):
    """A reusable workflow definition."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    name: str = Field(default="", index=True)
    description: str = Field(default="")
    version: str = Field(default="1.0")
    tags: str = Field(default="")
    variable_names: str = Field(default="[]")
    step_count: int = Field(default=0)
    use_count: int = Field(default=0)
    avg_duration_ms: float = Field(default=0.0)
    success_rate: float = Field(default=1.0)
    source: str = Field(default="manual")
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class Skill(SQLModel, table=True):
    """A learned skill from repeated workflow detection."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    name: str = Field(default="", index=True)
    description: str = Field(default="")
    pattern_steps: str = Field(default="[]")
    frequency: int = Field(default=1)
    confidence: float = Field(default=0.5)
    last_used_at: datetime | None = None
    suggested_workflow_id: str | None = None
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class PluginRegistration(SQLModel, table=True):
    """Registered external plugin metadata."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    version: str = Field(default="1.0.0")
    description: str = Field(default="")
    author: str = Field(default="")
    entry_point: str = Field(default="")
    tool_names: str = Field(default="[]")
    command_names: str = Field(default="[]")
    workflow_names: str = Field(default="[]")
    settings_json: str = Field(default="{}")
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class LearningEvent(SQLModel, table=True):
    """Audit trail for learning system events."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    event_type: str = Field(default="learning", index=True)
    category: str = Field(default="reflection", index=True)
    summary: str = Field(default="")
    details_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=_utcnow)


class BenchmarkRun(SQLModel, table=True):
    """Record of a benchmark execution."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    benchmark_name: str = Field(index=True)
    model_type: str = Field(default="")
    model_version: str = Field(default="")
    metrics_json: str = Field(default="{}")
    score: float = Field(default=0.0)
    regressions: str = Field(default="[]")
    duration_ms: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utcnow)


class ModelVersion(SQLModel, table=True):
    """Version history for trained models."""

    id: int | None = Field(default=None, primary_key=True)
    model_type: str = Field(index=True)
    version: str = Field(default="")
    status: str = Field(default="candidate")
    dataset_size: int = Field(default=0)
    metrics_json: str = Field(default="{}")
    path: str = Field(default="")
    parent_version: str = Field(default="")
    created_at: datetime = Field(default_factory=_utcnow)


class PredictionLog(SQLModel, table=True):
    """Observability record for every ML model prediction."""

    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=_utcnow, index=True)
    model_name: str = Field(index=True)
    model_version: str = Field(default="")
    input_text: str = Field(default="")
    predicted_output: str = Field(default="")
    confidence: float = Field(default=0.0)
    latency_ms: float = Field(default=0.0)
    needs_review: bool = Field(default=False)
    user_correction: str | None = Field(default=None)


class FailureCategory(str, Enum):
    TIMEOUT = "timeout"
    TOOL_FAILURE = "tool_failure"
    PLANNER_FAILURE = "planner_failure"
    MEMORY_FAILURE = "memory_failure"
    HALLUCINATION = "hallucination"
    INVALID_INPUT = "invalid_input"
    PERMISSION_DENIED = "permission_denied"
    ENVIRONMENT_ISSUE = "environment_issue"
    LLM_ISSUE = "llm_issue"
    UNKNOWN = "unknown"


class FailureAnalysisRecord(SQLModel, table=True):
    """Structured record of a categorized failure for analytics."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    task_public_id: str = Field(index=True)
    failure_category: FailureCategory = Field(default=FailureCategory.UNKNOWN)
    error_message: str = Field(default="")
    tool_name: str | None = Field(default=None)
    plan_step_id: str | None = Field(default=None)
    context: str = Field(default="")
    recovered: bool = Field(default=False)
    repair_strategy: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class ToolStats(SQLModel, table=True):
    """Per-tool reliability and performance statistics."""

    id: int | None = Field(default=None, primary_key=True)
    tool_name: str = Field(index=True, unique=True)
    total_executions: int = Field(default=0)
    success_count: int = Field(default=0)
    failure_count: int = Field(default=0)
    total_latency_ms: int = Field(default=0)
    avg_latency_ms: float = Field(default=0.0)
    success_rate: float = Field(default=0.0)
    common_failures: str = Field(default="[]")  # JSON list of {reason, count}
    last_successful_at: datetime | None = None
    last_failed_at: datetime | None = None
    reliability_score: float = Field(default=0.5)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class BenchmarkResult(SQLModel, table=True):
    """Full result of a single benchmark task execution."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    run_id: str = Field(index=True)
    task_id: str = Field(index=True)
    category: str = Field(default="general")
    prompt: str = Field(default="")
    expected_outcome: str = Field(default="")
    expected_tools: str = Field(default="[]")
    expected_complexity: str = Field(default="simple")
    difficulty: str = Field(default="medium")

    # Agent metrics
    success: bool = Field(default=False)
    clarification_used: bool = Field(default=False)
    hallucination_detected: bool = Field(default=False)
    completion_status: str = Field(default="unknown")

    # Planner metrics
    plan_length: int = Field(default=0)
    unnecessary_steps: int = Field(default=0)
    dependency_correctness: float = Field(default=0.0)
    execution_order_score: float = Field(default=0.0)

    # Memory metrics
    memories_retrieved: int = Field(default=0)
    relevant_memories: int = Field(default=0)
    memory_precision: float = Field(default=0.0)
    memory_recall: float = Field(default=0.0)
    memory_latency_ms: float = Field(default=0.0)

    # Tool metrics
    tools_selected: str = Field(default="[]")
    expected_tools_match: float = Field(default=0.0)
    tool_execution_latency_ms: float = Field(default=0.0)
    tool_success_rate: float = Field(default=0.0)
    tool_retry_count: int = Field(default=0)

    # Performance
    total_latency_ms: int = Field(default=0)
    llm_latency_ms: int = Field(default=0)
    planner_latency_ms: int = Field(default=0)
    tool_latency_ms: int = Field(default=0)

    # Failures
    failure_category: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    retry_count: int = Field(default=0)
    replan_count: int = Field(default=0)

    # Iterations
    iterations: int = Field(default=0)
    tool_calls_count: int = Field(default=0)

    # Timing
    created_at: datetime = Field(default_factory=_utcnow)
    details_json: str = Field(default="{}")


class RegressionRecord(SQLModel, table=True):
    """Records of regressions detected between benchmark runs."""

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    baseline_run_id: str = Field(index=True)
    current_run_id: str = Field(index=True)
    metric_name: str = Field(index=True)
    baseline_value: float = Field(default=0.0)
    current_value: float = Field(default=0.0)
    delta: float = Field(default=0.0)
    severity: str = Field(default="info")  # info, warning, critical
    category: str = Field(default="general")
    details: str = Field(default="")
    created_at: datetime = Field(default_factory=_utcnow)
