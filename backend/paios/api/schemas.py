"""Shared API schemas and helpers for consistent frontend contract.

All API responses should use these schemas to ensure a uniform contract
for the frontend. See api/routes/ for per-resource route definitions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Generic response wrappers ──────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
    error_code: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Response wrapper for paginated lists."""
    items: list[dict[str, Any]]
    total: int
    offset: int = 0
    limit: int = 20


# ── Auth structure ─────────────────────────────────────────────────────

class AuthToken(BaseModel):
    """Placeholder for future auth token validation.
    
    Currently accepts any bearer token. Replace with real JWT/OAuth when
    auth is implemented.
    """
    sub: str = "anonymous"
    scopes: list[str] = Field(default_factory=list)


# ── Event payloads (documented for frontend consumption) ───────────────

EVENT_TYPES = {
    "task.created": "Task record created in DB",
    "task.started": "Task execution has begun (intent classified, first iteration started)",
    "task.intent": "Emitted when the intent router classifies a request",
    "task.completed": "Task completed successfully",
    "task.failed": "Task failed with an error",
    "task.paused": "Task was paused",
    "task.cancelled": "Task was cancelled",
    "agent.iteration": "Emitted at the start of each ReAct iteration",
    "agent.thinking": "Streaming text delta or tool call from the LLM",
    "agent.answer": "Final answer from the agent",
    "agent.exhausted": "Agent reached max iterations without answering",
    "tool.request": "Tool invocation requested by the agent",
    "tool.result": "Tool execution result",
    "plan.start": "Planner started decomposing a request",
    "plan.created": "Plan was generated from the LLM",
    "plan.step.start": "A plan step began execution",
    "plan.step.complete": "A plan step completed successfully",
    "plan.step.error": "A plan step encountered an error",
    "plan.step.failed": "A plan step failed after all retries",
    "plan.step.tool": "A tool was called during a plan step",
    "plan.replanned": "Plan was regenerated after failures",
    "plan.synthesized": "Final synthesis was generated",
    "confirmation.requested": "User confirmation is needed",
    "confirmation.responded": "User responded to a confirmation request",
}
