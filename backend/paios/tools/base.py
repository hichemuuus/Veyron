"""Tool base class and result models.

Every capability the agent can invoke is a Tool subclass with:
  - a name and description
  - a permission level (FREE / CONFIRM / RESTRICTED)
  - a Pydantic input schema (auto-converted to JSON Schema for the LLM)
  - an async run() method

Tools are self-registering: subclass Tool, and the registry discovers them.
Adding a tool never touches the agent. See ARCHITECTURE.md §5.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional, Type
from uuid import uuid4

from pydantic import BaseModel, Field

from paios.security.command_policy import PermissionLevel
from paios.security.policy import classify_risk, get_safety_policy

logger = logging.getLogger(__name__)


class FailureCategory(str, enum.Enum):
    """Categorisation of tool execution failures."""

    TIMEOUT = "timeout"
    INVALID_INPUT = "invalid_input"
    PERMISSION_DENIED = "permission_denied"
    TOOL_ERROR = "tool_error"
    UNKNOWN = "unknown"


def classify_failure(error: str) -> FailureCategory:
    """Classify a tool failure from its error message."""
    err_lower = error.lower()
    if any(kw in err_lower for kw in ("timeout", "timed out")):
        return FailureCategory.TIMEOUT
    if any(kw in err_lower for kw in ("invalid input", "validation error", "model_validate")):
        return FailureCategory.INVALID_INPUT
    if any(kw in err_lower for kw in ("permission", "denied", "not allowed", "unauthorized")):
        return FailureCategory.PERMISSION_DENIED
    if any(kw in err_lower for kw in ("error", "exception", "failed", "unavailable")):
        return FailureCategory.TOOL_ERROR
    return FailureCategory.UNKNOWN


class ToolResult(BaseModel):
    """Result of a tool invocation."""

    ok: bool = True
    # Primary output (string or structured data). String for the LLM's benefit.
    output: Any = None
    # Structured data for the UI (optional; rendered as cards/charts).
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0

    def as_llm_text(self, max_chars: int = 8000) -> str:
        """Render a text representation suitable for feeding back to the LLM."""
        if not self.ok:
            return f"ERROR: {self.error}"
        if isinstance(self.output, str):
            text = self.output
        else:
            import json

            text = json.dumps(self.output, default=str, indent=2)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated, {len(text)} total chars]"
        return text


class ToolContext(BaseModel):
    """Per-invocation context passed to tools.

    Carries the task id (for event topic), confirmation hook, and audit subject.
    Tools should NOT import the global manager directly; they use ctx to request
    confirmations, which keeps them testable.
    """

    task_public_id: str = "system"
    # Caller may inject a confirmation coroutine for testing.
    confirm: Optional[Any] = None  # callable(**kwargs) -> (bool, reason|None)


class Tool(ABC):
    """Base class for all PAIOS tools.

    Subclasses define:
      name, description, permission, Inputs (Pydantic model), and run().
    """

    # --- Class-level metadata (overridden by subclasses) ---
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    permission: ClassVar[PermissionLevel] = PermissionLevel.CONFIRM
    # Pydantic model describing the tool's inputs.
    Inputs: ClassVar[Type[BaseModel]] = BaseModel
    # Reliability settings.
    max_retries: ClassVar[int] = 0
    retry_delay_ms: ClassVar[int] = 500
    timeout_ms: ClassVar[int] = 0  # 0 = no timeout

    @abstractmethod
    async def run(self, ctx: ToolContext, **inputs: Any) -> ToolResult:
        """Execute the tool. Subclasses implement this."""
        ...

    # --- Helpers -----------------------------------------------------------

    @classmethod
    def schema_for_llm(cls) -> dict[str, Any]:
        """Return a JSON-Schema description of this tool, for the LLM.

        Uses the Pydantic model's JSON schema. Kept minimal: name, description,
        and the input schema.
        """
        schema = cls.Inputs.model_json_schema()
        # Strip Pydantic internal keys the LLM doesn't need.
        schema.pop("title", None)
        return {
            "name": cls.name,
            "description": cls.description,
            "permission": cls.permission.value,
            "parameters": schema,
        }

    async def safe_run(self, ctx: ToolContext, **inputs: Any) -> ToolResult:
        """Validate inputs against the schema, then run() with timing, retry, timeout, and safety check.

        Catches exceptions and converts them to ToolResult(ok=False).
        Respects max_retries, retry_delay_ms, and timeout_ms class vars.
        """
        # Validate inputs.
        try:
            validated = cls_self_validate(self, inputs)
        except Exception as e:
            return ToolResult(ok=False, error=f"invalid inputs: {e}")

        # Safety/risk evaluation.
        policy = get_safety_policy()
        allowed, reason = policy.evaluate(self.name, validated, self.permission)
        if not allowed:
            return ToolResult(ok=False, error=reason)
        if reason.startswith("confirm:") and ctx.confirm is not None:
            confirmed, confirm_reason = await ctx.confirm(
                tool=self.name, inputs=validated, risk=reason.split(":")[1],
            )
            if not confirmed:
                return ToolResult(
                    ok=False,
                    error=f"action denied by user: {confirm_reason or 'cancelled'}",
                )
            logger.info("tool %s confirmed by user", self.name)

        last_result: ToolResult | None = None
        attempts = 1 + self.max_retries

        for attempt in range(attempts):
            start = time.perf_counter()
            try:
                coro = self.run(ctx, **validated)
                if self.timeout_ms > 0:
                    coro = asyncio.wait_for(coro, timeout=self.timeout_ms / 1000)

                result = await coro
                if result.duration_ms == 0:
                    result.duration_ms = int((time.perf_counter() - start) * 1000)
                if result.ok:
                    return result
                last_result = result
            except asyncio.TimeoutError:
                duration = int((time.perf_counter() - start) * 1000)
                last_result = ToolResult(
                    ok=False,
                    error=f"TIMEOUT after {self.timeout_ms}ms",
                    duration_ms=duration,
                )
                logger.warning("tool %s timed out (attempt %d/%d)", self.name, attempt + 1, attempts)
            except Exception as e:
                duration = int((time.perf_counter() - start) * 1000)
                last_result = ToolResult(ok=False, error=f"{type(e).__name__}: {e}", duration_ms=duration)

            if attempt < attempts - 1:
                logger.info("retrying tool %s (attempt %d/%d)", self.name, attempt + 1, attempts)
                await asyncio.sleep(self.retry_delay_ms / 1000)

        return last_result or ToolResult(ok=False, error="unknown error")


def cls_self_validate(tool: Tool, inputs: dict[str, Any]) -> dict[str, Any]:
    """Validate a dict against the tool's Inputs model, returning a plain dict."""
    model_class = type(tool).Inputs
    if model_class is BaseModel:
        # Default Inputs — accept anything.
        return inputs
    model = model_class.model_validate(inputs)
    return model.model_dump(exclude_none=True)
