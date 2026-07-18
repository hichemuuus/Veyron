"""ReAct agent loop.

Each iteration: observe → think → act → loop. Emits events at each step so the
UI can visualize the agent thinking in real time.

See ARCHITECTURE.md §3.1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from veyron.config import get_settings
from veyron.core.context import initial_messages, trim_history
from veyron.core.events import Event, EventBus, get_bus
from veyron.core.intelligence import classify_request
from veyron.core.planner import Planner
from veyron.core.reflection import ReflectionEngine
from veyron.core.tracker import ExecutionTracker
from sqlalchemy import select
from veyron.db.base import async_session_scope
from veyron.db.models import Task, TaskStatus, TaskType
from veyron.intelligence.training.dataset import UserInteraction, save_user_interaction
from veyron.intelligence.training.quality import QualityScorer
from veyron.llm.base import (
    GenerateOptions,
    LLMProvider,
    LLMUnavailableError,
    Message,
    get_provider,
)
from veyron.llm.micro.router import Intent
from veyron.tools.base import ToolContext, ToolResult
from veyron.tools.registry import get_registry

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    """Final outcome of an agent run."""

    answer: str
    iterations: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    intent: Intent | None = None
    needs_clarification: bool = False
    clarification_question: str = ""


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
        except TimeoutError:
            logger.error("task %s timed out after %ss", task_public_id, total_timeout)
            await self._fail(task_public_id, f"timed out after {total_timeout}s")
            await self.tracker.complete_task(task_public_id, error=f"timed out after {total_timeout}s")
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
        await self._set_task_mode(task_public_id, intent.mode)
        await self.tracker.start_task(task_public_id, request, mode=intent.mode)

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
                await self._fail(task_public_id, "cancelled")
                return AgentRunResult(answer="", iterations=0, error="cancelled", intent=intent)
            result = await self._run_planner(request, task_public_id, intent)
            await self.tracker.complete_task(task_public_id, error=result.error)
            return result

        # ReAct loop for simple requests.
        return await self._run_react(request, task_public_id, intent)

    async def _run_react(self, request: str, task_public_id: str, intent: Intent) -> AgentRunResult:
        """Standard ReAct loop for non-plan requests and planner fallback."""
        max_iters = self.max_iterations
        registry = get_registry()
        settings = get_settings()
        if settings.model.filter_tools_by_prediction and intent.predicted_tools:
            tool_schemas = registry.schemas_for(names=intent.predicted_tools)
            logger.info(
                "filtered tools to %d/%d (predicted: %s)",
                len(tool_schemas),
                len(registry._tools),
                intent.predicted_tools,
            )
        else:
            tool_schemas = registry.schemas_for()
        messages = initial_messages(request, tool_schemas)

        tool_calls: list[dict[str, Any]] = []

        for iteration in range(1, max_iters + 1):
            if self._is_cancelled(task_public_id):
                await self._fail(task_public_id, "cancelled")
                await self.tracker.complete_task(task_public_id, error="cancelled")
                return AgentRunResult(answer="", iterations=iteration, error="cancelled", intent=intent)

            await self.bus.publish(
                Event(
                    type="agent.iteration",
                    topic=task_public_id,
                    payload={"iteration": iteration, "max": max_iters},
                )
            )

            await self.tracker.save_checkpoint(
                task_public_id,
                checkpoint_data=json.dumps(
                    {"iteration": iteration, "tool_calls_count": len(tool_calls)},
                    default=str,
                ),
                step_index=iteration,
            )

            llm_step_id = await self.tracker.start_step(
                task_public_id,
                TaskType.LLM_CALL,
                name=f"iteration_{iteration}",
                step_index=iteration,
                input_preview=request[:200],
            )

            try:
                assistant_text, tool_call = await self._generate(
                    messages, task_public_id, iteration, tool_schemas=tool_schemas
                )
            except LLMUnavailableError as e:
                if llm_step_id is not None:
                    await self.tracker.fail_step(llm_step_id, error=str(e))
                await self._fail(task_public_id, f"model unavailable: {e}")
                await self.tracker.complete_task(task_public_id, error=f"model unavailable: {e}")
                return AgentRunResult(answer="", iterations=iteration, error=str(e), intent=intent)

            if llm_step_id is not None:
                await self.tracker.complete_step(llm_step_id, output_preview=assistant_text[:200])

            if tool_call is not None:
                tc_name = tool_call.get("name", "")
                tc_args = tool_call.get("arguments", {})
                tool_calls.append(tool_call)

                tool_step_id = await self.tracker.start_step(
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

                messages.append(
                    Message(
                        role="assistant",
                        content=assistant_text,
                        tool_calls=[tool_call],
                    )
                )

                tool = registry.get(tc_name)
                if tool is None:
                    result = ToolResult(ok=False, error=f"unknown tool: {tc_name}")
                else:
                    ctx = ToolContext(task_public_id=task_public_id)
                    result = await tool.safe_run(ctx, **tc_args)

                await self.tracker.increment_tool_count(task_public_id)
                if tool_step_id is not None:
                    if result.ok:
                        await self.tracker.complete_step(tool_step_id, output_preview=result.as_llm_text(500)[:200])
                    else:
                        await self.tracker.fail_step(tool_step_id, error=result.error or "tool failed")

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

            # Detect clarifying questions — if the LLM asks a question instead of
            # giving a final answer, return it as a clarification request so the
            # calling layer can respond.
            stripped = assistant_text.strip()
            _is_clarification = bool(
                stripped.endswith("?")
                and len(stripped) < 300
                and iteration <= 2
                and "I need" in stripped
                or "could you" in stripped.lower()
                or "would you like" in stripped.lower()
                or "which" in stripped.lower().split()[:1]
            )

            if _is_clarification:
                await self.bus.publish(
                    Event(
                        type="agent.clarification",
                        topic=task_public_id,
                        payload={"question": assistant_text, "iterations": iteration},
                    )
                )
                await self._complete(task_public_id, assistant_text)
                await self.tracker.complete_task(task_public_id, result=assistant_text)
                await self._save_interaction(request, task_public_id, intent, True, answer=assistant_text)
                return AgentRunResult(
                    answer=assistant_text,
                    iterations=iteration,
                    tool_calls=tool_calls,
                    intent=intent,
                    needs_clarification=True,
                    clarification_question=assistant_text,
                )

            await self.bus.publish(
                Event(
                    type="agent.answer",
                    topic=task_public_id,
                    payload={"answer": assistant_text, "iterations": iteration},
                )
            )
            await self._complete(task_public_id, assistant_text)
            await self.tracker.complete_task(task_public_id, result=assistant_text)
            await self._save_interaction(request, task_public_id, intent, True, answer=assistant_text)
            self._maybe_reflect(request, task_public_id, mode="react")
            return AgentRunResult(
                answer=assistant_text, iterations=iteration, tool_calls=tool_calls, intent=intent
            )

        msg = f"reached max iterations ({max_iters}) without a final answer"
        await self.bus.publish(
            Event(type="agent.exhausted", topic=task_public_id, payload={"max": max_iters})
        )
        await self._fail(task_public_id, msg)
        await self.tracker.complete_task(task_public_id, error=msg)
        await self._save_interaction(request, task_public_id, intent, False, error=msg)
        self._maybe_reflect(request, task_public_id, mode="react", success=False, error=msg)
        return AgentRunResult(answer="", iterations=max_iters, tool_calls=tool_calls, error=msg, intent=intent)

    async def _run_planner(
        self, request: str, task_public_id: str, intent: Intent
    ) -> AgentRunResult:
        """Delegate complex requests to the Planner.

        When micro-models are enabled, the planning model is consulted first.
        If confident that no plan is needed, falls back to the ReAct loop.
        If confident that planning is needed, estimated steps and categories
        are passed as metadata to inform the planner. Low-confidence predictions
        fall through to the existing planner unchanged.
        """
        if self._is_cancelled(task_public_id):
            return AgentRunResult(answer="", iterations=0, error="cancelled", intent=intent)

        settings = get_settings()
        if settings.model.micro_models_enabled:
            try:
                from veyron.intelligence.planning.inference import predict_plan
                pred = predict_plan(
                    request,
                    intent_category=intent.intent_category or "",
                    complexity="complex",
                )
                if pred.confidence >= settings.model.micro_model_confidence_threshold:
                    if not pred.requires_plan:
                        logger.info("Plan not required, falling back to ReAct loop.")
                        return await self._run_react(request, task_public_id, intent)
                    await self.tracker.start_task(
                        task_public_id,
                        request,
                        mode="plan",
                        model_used="planning",
                    )
                    await self.tracker.save_checkpoint(
                        task_public_id,
                        checkpoint_data=f'{{"planning_hint": "estimated_steps={pred.estimated_steps}"}}',
                        step_index=0,
                    )
            except Exception:
                logger.debug("planning model unavailable", exc_info=True)

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
            await self._fail(task_public_id, plan.error)
            return AgentRunResult(
                answer="",
                iterations=0,
                error=plan.error,
                intent=intent,
            )

        answer = plan.synthesis or "Plan completed but no synthesis was generated."
        iterations = sum(1 for s in plan.steps if s.result is not None)
        await self._complete(task_public_id, answer)
        await self._save_interaction(request, task_public_id, intent, True, answer=answer)
        self._maybe_reflect(request, task_public_id, mode="plan")

        return AgentRunResult(
            answer=answer,
            iterations=iterations,
            error=plan.error,
            intent=intent,
        )

    async def _generate(
        self,
        messages: list[Message],
        topic: str,
        iteration: int,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        """Stream a generation; return (text, tool_call_or_None).

        Emits 'agent.thinking' events with text deltas for live UI display.
        """
        opts = GenerateOptions(
            temperature=get_settings().model.temperature,
            max_tokens=get_settings().model.max_tokens,
            tools=tool_schemas if tool_schemas is not None else get_registry().schemas_for(),
            allow_tools=True,
        )
        messages = trim_history(messages)
        accumulated = ""
        tool_call: dict[str, Any] | None = None

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

    async def _set_task_mode(self, task_public_id: str, mode: str) -> None:
        if task_public_id == "system":
            return
        try:
            async with async_session_scope() as session:
                result = await session.execute(select(Task).where(Task.public_id == task_public_id))
                task = result.scalar_one_or_none()
                if task is not None:
                    task.mode = "react" if mode == "react" else "plan"
                    task.status = TaskStatus.RUNNING
                    task.started_at = task.started_at or datetime.now(UTC)
                    task.updated_at = datetime.now(UTC)
        except Exception as e:
            logger.warning("failed to set task mode: %s", e)

    async def _complete(self, task_public_id: str, answer: str) -> None:
        if task_public_id == "system":
            return
        try:
            async with async_session_scope() as session:
                result = await session.execute(select(Task).where(Task.public_id == task_public_id))
                task = result.scalar_one_or_none()
                if task is not None:
                    task.status = TaskStatus.COMPLETED
                    task.result = answer
                    task.finished_at = datetime.now(UTC)
                    task.updated_at = datetime.now(UTC)
            get_bus().publish_nowait(
                Event(
                    type="task.completed",
                    topic=task_public_id,
                    payload={"public_id": task_public_id},
                )
            )
        except Exception as e:
            logger.warning("failed to complete task: %s", e)

    async def _fail(self, task_public_id: str, error: str) -> None:
        if task_public_id == "system":
            return
        try:
            async with async_session_scope() as session:
                result = await session.execute(select(Task).where(Task.public_id == task_public_id))
                task = result.scalar_one_or_none()
                if task is not None:
                    task.status = TaskStatus.FAILED
                    task.error = error
                    task.finished_at = datetime.now(UTC)
                    task.updated_at = datetime.now(UTC)
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

        Always reflects on failures. On success, samples at
        reflection_sample_rate to reduce LLM overhead.
        Does not block the agent response.
        """
        settings = get_settings()
        if not settings.security.reflection_enabled:
            return
        if task_public_id == "system":
            return
        if success and random.random() >= settings.model.reflection_sample_rate:
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

    # --- User interaction capture ----------------------------------------

    async def _save_interaction(
        self,
        request: str,
        task_public_id: str,
        intent: Intent | None,
        success: bool,
        answer: str = "",
        error: str | None = None,
    ) -> None:
        """Capture a user interaction for training feedback.

        Serialises the interaction to the daily JSONL file for later use
        by the training feedback loop. Non-blocking; failures are logged
        at DEBUG level. Captures latency breakdown, router confidence,
        and step-by-step execution details.
        """
        if task_public_id == "system":
            return
        if not request:
            return
        try:
            timeline = await self.tracker.get_timeline(task_public_id)
            summary = await self.tracker.get_task_summary(task_public_id)
            tool_call_steps = [s for s in timeline if s.get("step_type") == "tool_call"]
            llm_steps = [s for s in timeline if s.get("step_type") == "llm_call"]

            llm_latency_ms = sum(s.get("duration_ms", 0) or 0 for s in llm_steps)
            tool_latency_ms = sum(s.get("duration_ms", 0) or 0 for s in tool_call_steps)

            qs = QualityScorer()
            score = qs.score({
                "success": success,
                "total_steps": summary["total_steps"],
                "retry_count": summary["retry_count"],
                "tools_used": [s.get("name", "") for s in tool_call_steps],
                "duration_ms": summary["total_duration_ms"],
                "tool_calls_count": len(tool_call_steps),
            })
            interaction = UserInteraction(
                request=request,
                detected_intent=intent.intent_category if intent else "",
                selected_tools=[s.get("name", "") for s in tool_call_steps],
                parameters={},
                result=answer or error or "",
                quality_score=score.overall,
                task_id=task_public_id,
                mode=intent.mode if intent else "react",
                success=success,
                metadata={
                    "domain": intent.domain if intent else "",
                    "confidence": intent.confidence if intent else 0.0,
                    "duration_ms": summary["total_duration_ms"],
                    "total_steps": summary["total_steps"],
                    "retry_count": summary["retry_count"],
                    "tool_calls_count": len(tool_call_steps),
                    "llm_latency_ms": llm_latency_ms,
                    "tool_latency_ms": tool_latency_ms,
                    "error": error,
                    "intent_mode": intent.mode if intent else "react",
                    "intent_category": intent.intent_category if intent else "",
                },
            )
            save_user_interaction(interaction)
            logger.debug("saved interaction for task %s", task_public_id)
        except Exception as e:
            logger.warning("failed to save user interaction: %s", e)


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
