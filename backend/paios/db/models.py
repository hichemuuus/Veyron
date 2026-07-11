"""SQLModel table definitions.

Initial Phase-1 schema:
  - Task: agent task lifecycle
  - Memory: long-term memory (structured half; Phase 2 adds the vector half)
  - AuditEvent: append-only security audit trail
  - ToolInvocation: log of every tool call
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return a naive datetime in UTC, matching SQLite storage format."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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

    id: Optional[int] = Field(default=None, primary_key=True)
    # Stable client-facing id (used in event streams and WebSocket topics).
    public_id: str = Field(index=True, unique=True)
    request: str
    status: TaskStatus = Field(default=TaskStatus.CREATED, index=True)
    # Final answer once completed.
    result: Optional[str] = None
    # Error message if failed.
    error: Optional[str] = None
    # Mode: react (simple) or plan (complex). Set by the intent router.
    mode: str = Field(default="react")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    # Checkpoint / execution tracking.
    checkpoint_data: Optional[str] = None
    checkpoint_step: int = Field(default=0)
    model_used: Optional[str] = None
    tool_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    total_steps: int = Field(default=0)
    completed_steps: int = Field(default=0)


class MemoryCategory(str, Enum):
    USER = "user"
    PROJECT = "project"
    HISTORY = "history"
    SKILL = "skill"


class Memory(SQLModel, table=True):
    """A long-term memory record. Vector embedding stored in Chroma (Phase 2)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)
    category: MemoryCategory = Field(index=True)
    content: str
    # 0.0–1.0; drives retrieval ranking and decay.
    importance: float = Field(default=0.5)
    # Free-form tags.
    tags: str = Field(default="")
    # Chroma collection id once embedded.
    embedding_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_recalled_at: Optional[datetime] = None
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
    source_task: Optional[str] = None


class AuditEvent(SQLModel, table=True):
    """Append-only record of a privileged action.

    Also mirrored to backend/data/audit/ as JSON for tamper-evident storage.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=_utcnow, index=True)
    action: str  # e.g. "tool.invoke", "security.confirm"
    subject: str  # who/what triggered it (task public_id, user, system)
    permission: str  # FREE | CONFIRM | RESTRICTED
    # JSON-serialized inputs.
    inputs: str = Field(default="{}")
    outcome: str = Field(default="pending")  # pending | approved | denied | success | error
    # User-supplied reason for RESTRICTED actions.
    reason: Optional[str] = None
    detail: Optional[str] = None


class ToolInvocation(SQLModel, table=True):
    """One execution of a tool."""

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=_utcnow, index=True)
    task_public_id: Optional[str] = Field(default=None, index=True)
    tool_name: str = Field(index=True)
    permission: str
    # JSON-serialized inputs and result.
    inputs: str = Field(default="{}")
    result: str = Field(default="")
    ok: bool = Field(default=True)
    duration_ms: int = Field(default=0)
    error: Optional[str] = None


class ExecutionStep(SQLModel, table=True):
    """One step inside a task execution (iteration, LLM call, tool call, plan step, etc.)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    task_public_id: str = Field(index=True)
    step_index: int = Field(default=0)
    step_type: TaskType
    name: str  # tool name, step goal, etc.
    status: StepStatus = Field(default=StepStatus.PENDING)
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    duration_ms: int = Field(default=0)
    input_preview: str = Field(default="")
    output_preview: str = Field(default="")
    error: Optional[str] = None
    retry_count: int = Field(default=0)
    metadata_json: str = Field(default="{}")  # extra structured data


class EvaluationMetric(SQLModel, table=True):
    """Stored metrics from an evaluation run."""

    id: Optional[int] = Field(default=None, primary_key=True)
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
    error: Optional[str] = None
    details_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=_utcnow)
