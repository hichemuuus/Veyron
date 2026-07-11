"""ReAct agent loop.

Each iteration: observe → think → act → loop. Emits events at each step so the
UI can visualize the agent thinking in real time.

See ARCHITECTURE.md §3.1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from paios.config import get_settings
from paios.core.context import initial_messages, trim_history
from paios.core.events import Event, EventBus, get_bus
from paios.core.tracker import ExecutionTracker
from paios.core.reflection import ReflectionEngine
from paios.db.base import sync_session_scope
from paios.db.models import Task, TaskStatus, TaskType
from paios.llm.base import (
    GenerateOptions,
    LLMProvider,
    LLMUnavailableError,
    Message,
    get_provider,
)
from paios.core.intelligence import classify_request
from paios.llm.micro.router import Intent
from paios.tools.base import ToolContext, ToolResult
from paios.tools.registry import get_registry

from paios.core.planner import Planner

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    """Final outcome of an agent run."""

    answer: str
    iterations: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    intent: Optional[Intent] = None


class Agent:
    """The ReAct agent. Stateless between runs; state lives in the DB."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        bus: EventBus | None = None,
        tracker: ExecutionTracker | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self.provider = provider or get_provider()
        self.bus = bus or get_bus()
        self.tracker = tracker or ExecutionTracker(bus=self.bus)
        self.max_iterations = max_iterations or get_settings().security.agent_max_iterations
        self._cancelled: set[str] = set()
        self._background_tasks: set[asyncio.Task] = set()
        self.reflection_engine = ReflectionEngine(provider=self.provider, tracker=self.tracker)

    def cancel(self, task_public_id: str) -> None:
        """Request cancellation of a running task."""
        self._cancelled.add(task_public_id)
        # Cancel any background reflection tasks tied to this task.
        for t in list(self._background_tasks):
            t.cancel()
        logger.info("cancellation requested for task %s", task_public_id)

    def _is_cancelled(self, task_public_id: str) -> bool:
        return task_public_id in self._cancelled

    def _cleanup_cancelled(self, task_public_id: str) -> None:
        """Remove a completed/cancelled task from the cancellation set."""
        self._cancelled.discard(task_public_id)

    async def run(self, request: str, task_public_id: str = "system") -> AgentRunResult:
        """Run the ReAct loop on a request. Streams events to the bus."""
        # Input sanitization.
        if "\x00" in request:
            return AgentRunResult(answer="", iterations=0, error="request contains null bytes")
        if len(request) > 100_000:
            return AgentRunResult(answer="", iterations=0, error="request too long")

        # Enforce a total wall-clock timeout to prevent indefinite execution.
        total_timeout = 300  # 5 minutes max for any single run
        try:
            return await asyncio.wait_for(
                self._run_with_timeout(request, task_public_id),
                timeout=total_timeout,
            )
        except asyncio.TimeoutError:
            logger.error("task %s timed out after %ss", task_public_id, total_timeout)
            self._fail(task_public_id, f"timed out after {total_timeout}s")
            self.tracker.complete_task(task_public_id, error=f"timed out after {total_timeout}s")
            return AgentRunResult(answer="", iterations=0, error=f"timed out after {total_timeout}s", intent=None)

    async def _run_with_timeout(self, request: str, task_public_id: str) -> AgentRunResult:
        """Inner run method (wrapped by run() for timeout enforcement)."""
        intent = classify_request(request)
        await self.bus.publish(
            Event(
                type="task.intent",
                topic=task_public_id,
                payload={"mode": intent.mode, "domain": intent.domain, "confidence": intent.confidence},
            )
        )
        self._set_task_mode(task_public_id, intent.mode)
        self.tracker.start_task(task_public_id, request, mode=intent.mode)

        await self.bus.publish(
            Event(
                type="task.started",
                topic=task_public_id,
                payload={"mode": intent.mode, "domain": intent.domain},
            )
        )

        # Route "plan" intents to the Planner for multi-step execution.
        if intent.mode == "plan":
            if self._is_cancelled(task_public_id):
                self._fail(task_public_id, "cancelled")
                return AgentRunResult(answer="", iterations=0, error="cancelled", intent=intent)
            result = await self._run_planner(request, task_public_id, intent)
            self.tracker.complete_task(task_public_id, error=result.error)
            return result

        # ReAct loop for simple requests.
        max_iters = self.max_iterations
        registry = get_registry()
        tool_schemas = registry.schemas_for()
        messages = initial_messages(request, tool_schemas)

        tool_calls: list[dict[str, Any]] = []

        for iteration in range(1, max_iters + 1):
            if self._is_cancelled(task_public_id):
                self._fail(task_public_id, "cancelled")
                self.tracker.complete_task(task_public_id, error="cancelled")
                return AgentRunResult(answer="", iterations=iteration, error="cancelled", intent=intent)

            await self.bus.publish(
                Event(
                    type="agent.iteration",
                    topic=task_public_id,
                    payload={"iteration": iteration, "max": max_iters},
                )
            )

            # Save checkpoint after each iteration for resume capability.
            self.tracker.save_checkpoint(
                task_public_id,
                checkpoint_data=json.dumps(
                    {"iteration": iteration, "tool_calls_count": len(tool_calls)},
                    default=str,
                ),
                step_index=iteration,
            )

            # Start LLM call step.
            llm_step_id = self.tracker.start_step(
                task_public_id,
                TaskType.LLM_CALL,
                name=f"iteration_{iteration}",
                step_index=iteration,
                input_preview=request[:200],
            )

            # Generate the next assistant message.
            try:
                assistant_text, tool_call = await self._generate(messages, task_public_id, iteration)
            except LLMUnavailableError as e:
                if llm_step_id is not None:
                    self.tracker.fail_step(llm_step_id, error=str(e))
                self._fail(task_public_id, f"model unavailable: {e}")
                self.tracker.complete_task(task_public_id, error=f"model unavailable: {e}")
                return AgentRunResult(answer="", iterations=iteration, error=str(e), intent=intent)

            if llm_step_id is not None:
                self.tracker.complete_step(llm_step_id, output_preview=assistant_text[:200])

            # Branch: tool call or final answer.
            if tool_call is not None:
                tc_name = tool_call.get("name", "")
                tc_args = tool_call.get("arguments", {})
                tool_calls.append(tool_call)

                tool_step_id = self.tracker.start_step(
                    task_public_id,
                    TaskType.TOOL_CALL,
                    name=tc_name,
                    step_index=iteration,
                    input_preview=json.dumps(tc_args, default=str)[:200],
                )

                await self.bus.publish(
                    Event(
                        type="tool.request",
                        topic=task_public_id,
                        payload={"tool": tc_name, "arguments": tc_args, "iteration": iteration},
                    )
                )

                # Append the assistant's tool-call intent to the conversation.
                messages.append(
                    Message(
                        role="assistant",
                        content=assistant_text,
                        tool_calls=[tool_call],
                    )
                )

                # Execute the tool.
                tool = registry.get(tc_name)
                if tool is None:
                    result = ToolResult(ok=False, error=f"unknown tool: {tc_name}")
                else:
                    ctx = ToolContext(task_public_id=task_public_id)
                    result = await tool.safe_run(ctx, **tc_args)

                self.tracker.increment_tool_count(task_public_id)
                if tool_step_id is not None:
                    if result.ok:
                        self.tracker.complete_step(tool_step_id, output_preview=result.as_llm_text(500)[:200])
                    else:
                        self.tracker.fail_step(tool_step_id, error=result.error or "tool failed")

                result_text = result.as_llm_text(get_settings().security.max_tool_output_chars)
                await self.bus.publish(
                    Event(
                        type="tool.result",
                        topic=task_public_id,
                        payload={
                            "tool": tc_name,
                            "ok": result.ok,
                            "output_preview": result_text[:400],
                            "duration_ms": result.duration_ms,
                            "iteration": iteration,
                        },
                    )
                )
                messages.append(Message(role="tool", content=result_text, tool_name=tc_name))
                continue

            # No tool call → final answer.
            await self.bus.publish(
                Event(
                    type="agent.answer",
                    topic=task_public_id,
                    payload={"answer": assistant_text, "iterations": iteration},
                )
            )
            self._complete(task_public_id, assistant_text)
            self.tracker.complete_task(task_public_id, result=assistant_text)
            self._maybe_reflect(request, task_public_id, mode="react")
            return AgentRunResult(
                answer=assistant_text, iterations=iteration, tool_calls=tool_calls, intent=intent
            )

        # Out of iterations.
        msg = f"reached max iterations ({max_iters}) without a final answer"
        await self.bus.publish(
            Event(type="agent.exhausted", topic=task_public_id, payload={"max": max_iters})
        )
        self._fail(task_public_id, msg)
        self.tracker.complete_task(task_public_id, error=msg)
        self._maybe_reflect(request, task_public_id, mode="react", success=False, error=msg)
        return AgentRunResult(answer="", iterations=max_iters, tool_calls=tool_calls, error=msg, intent=intent)

    async def _run_planner(
        self, request: str, task_public_id: str, intent: Intent
    ) -> AgentRunResult:
        """Delegate complex requests to the Planner."""
        if self._is_cancelled(task_public_id):
            return AgentRunResult(answer="", iterations=0, error="cancelled", intent=intent)

        planner = Planner(provider=self.provider, bus=self.bus, tracker=self.tracker)

        await self.bus.publish(
            Event(
                type="plan.start",
                topic=task_public_id,
                payload={"request": request},
            )
        )

        plan = await planner.plan_and_execute(request, topic=task_public_id)

        if plan.error:
            self._fail(task_public_id, plan.error)
            return AgentRunResult(
                answer="",
                iterations=0,
                error=plan.error,
                intent=intent,
            )

        answer = plan.synthesis or "Plan completed but no synthesis was generated."
        iterations = sum(1 for s in plan.steps if s.result is not None)
        self._complete(task_public_id, answer)
        self._maybe_reflect(request, task_public_id, mode="plan")

        return AgentRunResult(
            answer=answer,
            iterations=iterations,
            error=plan.error,
            intent=intent,
        )

    async def _generate(
        self, messages: list[Message], topic: str, iteration: int
    ) -> tuple[str, Optional[dict[str, Any]]]:
        """Stream a generation; return (text, tool_call_or_None).

        Emits 'agent.thinking' events with text deltas for live UI display.
        """
        opts = GenerateOptions(
            temperature=get_settings().model.temperature,
            max_tokens=get_settings().model.max_tokens,
            tools=get_registry().schemas_for(),
            allow_tools=True,
        )
        messages = trim_history(messages)
        accumulated = ""
        tool_call: Optional[dict[str, Any]] = None

        try:
            async for chunk in self.provider.generate_stream(messages, opts):
                if chunk.tool_call is not None:
                    tool_call = chunk.tool_call
                    await self.bus.publish(
                        Event(
                            type="agent.thinking",
                            topic=topic,
                            payload={"iteration": iteration, "tool_call": chunk.tool_call},
                        )
                    )
                if chunk.text:
                    accumulated += chunk.text
                    # Emit a throttled thinking delta (avoid flooding the bus).
                    if len(accumulated) % 40 < len(chunk.text):
                        await self.bus.publish(
                            Event(
                                type="agent.thinking",
                                topic=topic,
                                payload={"iteration": iteration, "delta": chunk.text[-120:]},
                            )
                        )
                if chunk.done:
                    break
        except LLMUnavailableError:
            raise
        except Exception as e:
            logger.error("generation failed at iteration %d: %s", iteration, e)
            raise LLMUnavailableError(f"generation failed: {e}") from e

        return accumulated, tool_call

    # --- Task persistence ------------------------------------------------

    def _set_task_mode(self, task_public_id: str, mode: str) -> None:
        if task_public_id == "system":
            return
        try:
            with sync_session_scope() as session:
                task = session.query(Task).where(Task.public_id == task_public_id).first()
                if task is not None:
                    task.mode = "react" if mode == "react" else "plan"
                    task.status = TaskStatus.RUNNING
                    task.started_at = task.started_at or datetime.now(timezone.utc)
                    task.updated_at = datetime.now(timezone.utc)
                    session.add(task)
        except Exception as e:
            logger.warning("failed to set task mode: %s", e)

    def _complete(self, task_public_id: str, answer: str) -> None:
        if task_public_id == "system":
            return
        try:
            with sync_session_scope() as session:
                task = session.query(Task).where(Task.public_id == task_public_id).first()
                if task is not None:
                    task.status = TaskStatus.COMPLETED
                    task.result = answer
                    task.finished_at = datetime.now(timezone.utc)
                    task.updated_at = datetime.now(timezone.utc)
                    session.add(task)
            get_bus().publish_nowait(
                Event(
                    type="task.completed",
                    topic=task_public_id,
                    payload={"public_id": task_public_id},
                )
            )
        except Exception as e:
            logger.warning("failed to complete task: %s", e)

    def _fail(self, task_public_id: str, error: str) -> None:
        if task_public_id == "system":
            return
        try:
            with sync_session_scope() as session:
                task = session.query(Task).where(Task.public_id == task_public_id).first()
                if task is not None:
                    task.status = TaskStatus.FAILED
                    task.error = error
                    task.finished_at = datetime.now(timezone.utc)
                    task.updated_at = datetime.now(timezone.utc)
                    session.add(task)
            get_bus().publish_nowait(
                Event(
                    type="task.failed",
                    topic=task_public_id,
                    payload={"public_id": task_public_id, "error": error},
                )
            )
        except Exception as e:
            logger.warning("failed to fail task: %s", e)

    def _maybe_reflect(
        self,
        request: str,
        task_public_id: str,
        mode: str = "react",
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """Run reflection in the background if enabled.

        Does not block the agent response.
        """
        if not get_settings().security.reflection_enabled:
            return
        if task_public_id == "system":
            return
        task = asyncio.create_task(
            self._reflect_async(request, task_public_id, mode, success, error)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _reflect_async(
        self,
        request: str,
        task_public_id: str,
        mode: str,
        success: bool,
        error: str | None,
    ) -> None:
        """Run reflection and store resulting memories."""
        try:
            ref = await self.reflection_engine.reflect(
                request=request,
                task_public_id=task_public_id,
                mode=mode,
                success=success,
                error=error,
            )
            self.reflection_engine.store_reflection_memories(ref)
        except Exception as e:
            logger.warning("reflection failed for %s: %s", task_public_id, e)


# Process-wide agent.
_agent: Agent | None = None
_agent_lock = threading.Lock()


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                _agent = Agent()
    return _agent


def reset_agent() -> None:
    global _agent
    _agent = None
