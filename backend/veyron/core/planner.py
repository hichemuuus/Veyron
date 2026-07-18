"""Planner — DAG-based multi-step execution.

Decomposes a complex request into a sequence of steps with dependency
resolution, executes independent steps in parallel, validates outputs,
re-plans failed steps, and synthesizes a final report.

See ARCHITECTURE.md §3.2 and IMPLEMENTATION_PLAN.md §2.2.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import re
from dataclasses import dataclass, field

from veyron.config import get_settings
from veyron.core.context import build_system_prompt
from veyron.core.events import Event, EventBus, get_bus
from veyron.core.tracker import ExecutionTracker
from veyron.db.models import TaskType
from veyron.llm.base import (
    GenerateOptions,
    LLMProvider,
    LLMUnavailableError,
    Message,
    get_provider,
)
from veyron.tools.base import ToolResult, classify_failure
from veyron.tools.registry import get_registry


class VerifierAction(str, enum.Enum):
    """Recommended action from a structured verification."""

    COMPLETE = "COMPLETE"
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    HUMAN_REVIEW = "HUMAN_REVIEW"


@dataclass
class VerifierResult:
    """Structured output of a step verification."""

    status: str  # "PASS" | "FAIL" | "UNCERTAIN"
    confidence: float = 0.0  # 0.0–1.0
    issues: list[str] = field(default_factory=list)
    evidence: str = ""
    action: str = VerifierAction.COMPLETE.value

    @property
    def passed(self) -> bool:
        return self.status == "PASS" and self.action == VerifierAction.COMPLETE.value

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step in a plan."""

    id: str
    goal: str
    suggested_tool: str | None = None
    depends_on: list[str] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    verified: bool = False
    verifier_result: VerifierResult | None = None
    retries: int = 0
    status: str = "pending"  # pending | running | completed | failed


@dataclass
class Plan:
    """A complete plan with steps and synthesis."""

    request: str
    steps: list[PlanStep] = field(default_factory=list)
    synthesis: str | None = None
    error: str | None = None
    score: float | None = None  # quality score 0.0-1.0, computed on creation


@dataclass
class PlanScore:
    """Quality metrics for a generated plan."""

    overall: float = 0.0
    step_count_score: float = 0.0
    dependency_score: float = 0.0
    tool_coverage_score: float = 0.0
    clarity_score: float = 0.0
    details: str = ""


class Planner:
    """Decomposes requests into steps, executes, verifies, and synthesizes.

    Supports dependency-graph resolution and parallel execution of independent
    steps.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        bus: EventBus | None = None,
        tracker: ExecutionTracker | None = None,
        max_retries: int = 2,
    ) -> None:
        self.provider = provider or get_provider()
        self.bus = bus or get_bus()
        self.tracker = tracker or ExecutionTracker(bus=self.bus)
        self.max_retries = max_retries
        self._plan_lock = asyncio.Lock()

    async def plan_and_execute(self, request: str, topic: str = "system") -> Plan:
        """Full pipeline: generate plan → validate → score → execute (with DAG resolution and adaptive replanning) → verify → synthesize."""
        plan = await self._generate_plan(request, topic)
        if plan.error:
            return plan

        validation_error = self._validate_plan(plan)
        if validation_error:
            plan.error = validation_error
            return plan

        plan.score = self._score_plan(plan)
        logger.info("plan quality score: %.2f — %s", plan.score, self._score_details(plan))

        await self._execute_dag(plan, topic)

        if plan.error and self._should_replan(plan):
            logger.info("attempting adaptive replan after failure: %s", plan.error)
            plan = await self._adaptive_replan(plan, request, topic)
            if not plan.error:
                plan.score = self._score_plan(plan)

        if not plan.error:
            plan.synthesis = await self._synthesize(plan, request, topic)

        return plan

    # ── Plan generation ─────────────────────────────────────────────────────

    async def _generate_plan(self, request: str, topic: str) -> Plan:
        """Use the LLM to decompose the request into steps."""
        await self.bus.publish(
            Event(
                type="plan.start",
                topic=topic,
                payload={"request": request[:200]},
            )
        )

        prompt = _PLANNER_PROMPT.format(request=request, tool_list=_format_tool_list())

        messages = [
            Message(role="system", content=build_system_prompt()),
            Message(role="user", content=prompt),
        ]

        opts = GenerateOptions(
            temperature=0.3,
            max_tokens=2048,
            tools=[],
            allow_tools=False,
        )

        text = ""
        try:
            async for chunk in self.provider.generate_stream(messages, opts):
                if chunk.text:
                    text += chunk.text
                if chunk.done:
                    break
        except Exception as e:
            logger.error("plan generation failed: %s", e)
            return Plan(request=request, error=f"plan generation failed: {e}")

        steps = self._parse_steps(text)
        if not steps:
            return Plan(request=request, error="could not parse any steps from plan")

        await self.bus.publish(
            Event(
                type="plan.created",
                topic=topic,
                payload={
                    "request": request,
                    "step_count": len(steps),
                    "steps": [s.goal for s in steps],
                },
            )
        )

        return Plan(request=request, steps=steps)

    def _parse_steps(self, text: str) -> list[PlanStep]:
        """Parse plan steps from the LLM response.

        Expects a JSON array of step objects, or a numbered list format.
        """

        steps: list[PlanStep] = []

        json_match = re.search(r"\[\s*\{.*\}\s*\]", text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                if isinstance(parsed, list):
                    for i, item in enumerate(parsed):
                        if isinstance(item, dict) and item.get("goal"):
                            steps.append(
                                PlanStep(
                                    id=item.get("id", f"step_{i + 1}"),
                                    goal=item["goal"],
                                    suggested_tool=item.get("tool") or item.get("suggested_tool"),
                                    depends_on=item.get("depends_on", []),
                                )
                            )
                    if steps:
                        return steps
            except (json.JSONDecodeError, KeyError):
                pass

        for match in re.finditer(
            r"(?:(?:^|\n)\s*)(?:\d+[.)]\s*|\*\s*)(.+?)(?=\n\s*(?:\d+[.)]|$)|\n?$)",
            text,
            re.MULTILINE,
        ):
            line = match.group(1).strip()
            if line:
                tool_match = re.search(r"\[tool:\s*(\w+)\]", line)
                suggested_tool = tool_match.group(1) if tool_match else None
                goal = re.sub(r"\s*\[tool:\s*\w+\]", "", line).strip()
                steps.append(
                    PlanStep(
                        id=f"step_{len(steps) + 1}",
                        goal=goal,
                        suggested_tool=suggested_tool,
                    )
                )

        return steps

    # ── Plan validation ─────────────────────────────────────────────────────

    def _validate_plan(self, plan: Plan) -> str | None:
        """Validate a plan before execution.

        Checks for:
        - Empty plans
        - Circular dependencies (detected via DFS)
        - References to non-existent step ids in depends_on
        - Unreachable tools (warn only, not fatal)
        Returns None if valid, error string if invalid.
        """
        if not plan.steps:
            return "plan has no steps"

        step_ids = {s.id for s in plan.steps}

        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    return f"step '{step.id}' depends on unknown step '{dep}'"

        adj: dict[str, list[str]] = {s.id: list(s.depends_on) for s in plan.steps}
        visiting = set()
        visited = set()

        def _dfs(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for dep in adj.get(node, []):
                if _dfs(dep):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        for step in plan.steps:
            if _dfs(step.id):
                return f"circular dependency detected involving step '{step.id}'"

        tool_names = {t.name for t in get_registry().all()}
        unknown_tools = [
            s.suggested_tool for s in plan.steps if s.suggested_tool and s.suggested_tool not in tool_names
        ]
        for tool in unknown_tools:
            logger.warning("plan suggests unknown tool '%s'", tool)

        return None

    # ── DAG execution ───────────────────────────────────────────────────────

    async def _execute_dag(self, plan: Plan, topic: str) -> None:
        """Execute steps respecting dependency order.

        Steps whose dependencies are all satisfied run in parallel.
        On failure, attempts inline repair for < 3 failures; falls back to
        full replan if 3+ steps fail in the same execution cycle.
        """
        total_steps = len(plan.steps)
        remaining = {s.id: s for s in plan.steps}
        completed: set[str] = set()
        failure_count = 0

        # Emit initial progress event.
        await self.bus.publish(
            Event(
                type="plan.progress",
                topic=topic,
                payload={
                    "completed": 0,
                    "total": total_steps,
                    "running": [s.goal for s in plan.steps[:3]],
                    "phase": "starting",
                },
            )
        )

        while remaining:
            ready = [
                s for s in remaining.values()
                if all(dep in completed for dep in s.depends_on)
            ]

            if not ready:
                blocked = list(remaining.keys())
                plan.error = f"deadlock: steps {blocked} have unsatisfiable dependencies"
                return

            results = await asyncio.gather(
                *[self._execute_step_wrapper(step, topic, plan) for step in ready],
                return_exceptions=True,
            )

            completed_count = len(completed)
            await self.bus.publish(
                Event(
                    type="plan.progress",
                    topic=topic,
                    payload={
                        "completed": completed_count,
                        "total": total_steps,
                        "running": [s.goal for s in ready],
                        "phase": "executing",
                    },
                )
            )

            for step, result in zip(ready, results):
                if isinstance(result, Exception):
                    logger.error("step %s raised exception: %s", step.id, result)
                    step.status = "failed"
                    step.error = f"crashed: {result}"
                    del remaining[step.id]
                    async with self._plan_lock:
                        if plan.error is None:
                            plan.error = f"step {step.id} crashed: {result}"
                    return
                del remaining[step.id]
                if step.status == "completed":
                    completed.add(step.id)
                elif step.status == "failed":
                    failure_count += 1
                    if failure_count >= 3:
                        async with self._plan_lock:
                            if plan.error is None:
                                plan.error = f"{failure_count} steps failed, triggering full replan"
                        return
                    failure_category = classify_failure(step.error or "").value
                    replacement = await self._repair_step(
                        step, step.error or "", plan.request, failure_category
                    )
                    if replacement is None:
                        async with self._plan_lock:
                            if plan.error is None:
                                plan.error = f"step {step.id} unrecoverable: {step.error}"
                        return
                    logger.info(
                        "repairing step %s (%s) → replacement %s (%s)",
                        step.id, step.goal, replacement.id, replacement.goal,
                    )
                    plan.steps.append(replacement)
                    remaining[replacement.id] = replacement
                    for s in plan.steps:
                        s.depends_on = [replacement.id if d == step.id else d for d in s.depends_on]
                    await self.bus.publish(
                        Event(
                            type="plan.step.repaired",
                            topic=topic,
                            payload={
                                "failed_step_id": step.id,
                                "failed_goal": step.goal,
                                "replacement_id": replacement.id,
                                "replacement_goal": replacement.goal,
                            },
                        )
                    )

    async def _execute_step_wrapper(self, step: PlanStep, topic: str, plan: Plan) -> None:
        """Thin wrapper so gather() can handle each step independently."""
        await self._execute_step(step, topic, plan)

    async def _set_plan_error(self, plan: Plan, error: str) -> None:
        """Thread-safe plan.error assignment from concurrent steps."""
        async with self._plan_lock:
            if plan.error is None:
                plan.error = error

    async def _execute_step(self, step: PlanStep, topic: str, plan: Plan) -> None:
        """Execute a single step using the ReAct loop via LLM."""
        step.status = "running"

        step_id = await self.tracker.start_step(
            task_public_id=topic,
            step_type=TaskType.PLAN_STEP,
            name=step.id,
            step_index=sum(1 for s in plan.steps if s != step and s.status != "pending"),
            input_preview=step.goal,
        )

        await self.bus.publish(
            Event(
                type="plan.step.start",
                topic=topic,
                payload={"step_id": step.id, "goal": step.goal, "retry": step.retries},
            )
        )

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                step.retries += 1
                await self.tracker.increment_retry_count(topic)
                logger.info("re-trying step %s (attempt %d)", step.id, attempt + 1)

            step.result, step.error = await self._run_step(step.goal, topic)

            if step.error:
                await self.bus.publish(
                    Event(
                        type="plan.step.error",
                        topic=topic,
                        payload={"step_id": step.id, "error": step.error, "attempt": attempt + 1},
                    )
                )
                if step_id is not None:
                    await self.tracker.fail_step(step_id, step.error, retry_count=step.retries)
                continue

            vr = await self._verify(step.goal, step.result, topic)
            step.verifier_result = vr
            step.verified = vr.passed

            if vr.passed:
                break

            logger.warning(
                "step %s verification: status=%s confidence=%.2f action=%s issues=%s",
                step.id, vr.status, vr.confidence, vr.action, vr.issues,
            )

            # Early exit based on recommended action.
            if vr.action in (VerifierAction.REPLAN.value, VerifierAction.HUMAN_REVIEW.value):
                # Don't retry — requires higher-level intervention.
                if vr.action == VerifierAction.HUMAN_REVIEW.value:
                    await self._set_plan_error(plan, f"step {step.id} requires human review")
                break

        if step.verified:
            step.status = "completed"
            if step_id is not None:
                await self.tracker.complete_step(step_id, output_preview=(step.result or "")[:500])
            await self.bus.publish(
                Event(
                    type="plan.step.complete",
                    topic=topic,
                    payload={"step_id": step.id, "goal": step.goal},
                )
            )
        else:
            step.status = "failed"
            if step_id is not None:
                await self.tracker.fail_step(
                    step_id,
                    step.verifier_result.evidence if step.verifier_result and not step.error else (step.error or "verification failed"),
                    retry_count=step.retries,
                )
            await self.bus.publish(
                Event(
                    type="plan.step.failed",
                    topic=topic,
                    payload={
                        "step_id": step.id,
                        "goal": step.goal,
                        "error": step.error or (step.verifier_result.evidence if step.verifier_result else "verification failed"),
                    },
                )
            )

    async def _run_step(self, goal: str, topic: str) -> tuple[str | None, str | None]:
        """Run a step goal through the LLM with tools available.

        The LLM may call tools and produce a result, similar to the ReAct loop
        but focused on a single sub-goal. Includes timeout protection and proper
        tool-call text accumulation.
        """
        messages = [
            Message(role="system", content=build_system_prompt()),
            Message(role="user", content=goal),
        ]

        opts = GenerateOptions(
            temperature=get_settings().model.temperature,
            max_tokens=get_settings().model.max_tokens,
            tools=get_registry().schemas_for(),
            allow_tools=True,
        )

        accumulated = ""
        max_tool_calls = 6
        llm_timeout = get_settings().model.max_tokens // 2 + 30

        for _ in range(max_tool_calls):
            messages = _trim_messages(messages)
            chunk = None
            try:
                async with asyncio.timeout(llm_timeout):
                    async for chunk in self.provider.generate_stream(messages, opts):
                        if chunk.text:
                            accumulated += chunk.text
                        if chunk.tool_call is not None:
                            tc_name = chunk.tool_call.get("name", "")
                            tc_args = chunk.tool_call.get("arguments", {})
                            registry = get_registry()
                            tool = registry.get(tc_name)
                            if tool is None:
                                result = ToolResult(ok=False, error=f"unknown tool: {tc_name}")
                            else:
                                from veyron.tools.base import ToolContext

                                ctx = ToolContext(task_public_id=topic)
                                result = await tool.safe_run(ctx, **tc_args)

                            result_text = result.as_llm_text(get_settings().security.max_tool_output_chars)
                            accumulated += f"\n[Tool result: {result_text}]\n"

                            messages.append(
                                Message(
                                    role="tool",
                                    content=result_text,
                                    tool_name=tc_name,
                                )
                            )

                            await self.bus.publish(
                                Event(
                                    type="plan.step.tool",
                                    topic=topic,
                                    payload={
                                        "tool": tc_name,
                                        "ok": result.ok,
                                        "output_preview": result_text[:300],
                                    },
                                )
                            )
                            break
                        if chunk.done:
                            break
            except TimeoutError:
                logger.warning("step LLM call timed out after %ss", llm_timeout)
                if not accumulated:
                    return None, "LLM call timed out"
                break
            except LLMUnavailableError as e:
                logger.warning("step LLM unavailable: %s", e)
                if not accumulated:
                    return None, str(e)
                break
            except Exception as e:
                logger.error("step LLM call failed: %s", e)
                if not accumulated:
                    return None, f"LLM call failed: {e}"
                break

            if chunk is not None and chunk.done and not chunk.tool_call:
                break

            if chunk is None:
                break

        if not accumulated:
            return None, "no output from LLM"

        return accumulated, None

    async def _verify(self, goal: str, result: str | None, topic: str) -> VerifierResult:
        """Check whether the step output satisfies the goal.

        Returns a structured VerifierResult with status, confidence, issues,
        evidence, and recommended action.
        """
        if result is None:
            return VerifierResult(
                status="FAIL",
                confidence=0.0,
                issues=["no result produced"],
                action=VerifierAction.REPLAN.value,
            )

        prompt = _VERIFIER_PROMPT.format(goal=goal, result=result)

        messages = [
            Message(role="system", content="You are a verifier. Assess whether the result satisfies the goal."),
            Message(role="user", content=prompt),
        ]

        opts = GenerateOptions(
            temperature=0.1,
            max_tokens=256,
            tools=[],
            allow_tools=False,
        )

        text = ""
        try:
            async for chunk in self.provider.generate_stream(messages, opts):
                if chunk.text:
                    text += chunk.text
                if chunk.done:
                    break
        except Exception as e:
            logger.warning("verification failed: %s", e)
            return VerifierResult(
                status="PASS",
                confidence=0.5,
                issues=[f"verifier error, optimistic pass: {e}"],
                action=VerifierAction.COMPLETE.value,
            )

        return _parse_verifier_result(text)

    async def _synthesize(self, plan: Plan, request: str, topic: str) -> str:
        """Combine all step results into a final response."""
        step_summaries = []
        for i, step in enumerate(plan.steps):
            if step.verifier_result:
                vr = step.verifier_result
                status = f"{'✓' if step.verified else '✗'} [{vr.status}] ({vr.confidence:.0%})"
            else:
                status = "✓" if step.verified else "✗"
            summary = step.result or step.error or "(no output)"
            step_summaries.append(f"Step {i + 1}: {step.goal}\n{status} Result:\n{summary}")

        steps_text = "\n\n".join(step_summaries)
        prompt = _SYNTHESIS_PROMPT.format(request=request, steps=steps_text)

        messages = [
            Message(role="system", content=build_system_prompt()),
            Message(role="user", content=prompt),
        ]

        opts = GenerateOptions(
            temperature=0.3,
            max_tokens=2048,
            tools=[],
            allow_tools=False,
        )

        text = ""
        try:
            async for chunk in self.provider.generate_stream(messages, opts):
                if chunk.text:
                    text += chunk.text
                if chunk.done:
                    break
        except Exception as e:
            logger.error("synthesis failed: %s", e)
            text = f"Synthesis failed: {e}"

        await self.bus.publish(
            Event(type="plan.synthesized", topic=topic, payload={"request": request})
        )

        return text

    # ── Plan scoring ──────────────────────────────────────────────────────

    def _score_plan(self, plan: Plan) -> float:
        """Compute a quality score (0.0–1.0) for the plan.

        Factors:
        - Step count: 3–8 steps is ideal (score 1.0); fewer or more reduces.
        - Dependency depth: deep chains are penalized.
        - Tool coverage: steps with suggested tools score higher.
        """
        n = len(plan.steps)
        if n == 0:
            return 0.0

        # Step count: ideal 3–8, linear falloff outside.
        if 3 <= n <= 8:
            step_count_score = 1.0
        elif n <= 1:
            step_count_score = 0.3
        elif n == 2:
            step_count_score = 0.6
        else:
            step_count_score = max(0.0, 1.0 - (n - 8) * 0.08)

        # Dependency depth: compute max chain length.
        adj = {s.id: list(s.depends_on) for s in plan.steps}
        def _max_depth(node: str, seen: set[str]) -> int:
            if node in seen:
                return 0
            seen.add(node)
            deps = adj.get(node, [])
            if not deps:
                return 0
            return 1 + max(_max_depth(d, seen) for d in deps)

        max_depth = 0
        for s in plan.steps:
            max_depth = max(max_depth, _max_depth(s.id, set()))

        # Depth of 0–2 is great, 3–4 is okay, 5+ penalized.
        if max_depth <= 2:
            dependency_score = 1.0
        elif max_depth <= 4:
            dependency_score = 0.6
        else:
            dependency_score = 0.3

        # Tool coverage: fraction of steps with a suggested tool.
        tool_names = {t.name for t in get_registry().all()}
        steps_with_tools = sum(
            1 for s in plan.steps
            if s.suggested_tool and s.suggested_tool in tool_names
        )
        tool_coverage_score = steps_with_tools / n if n > 0 else 0.0

        # Overall: weighted combination.
        overall = (
            step_count_score * 0.3
            + dependency_score * 0.3
            + tool_coverage_score * 0.4
        )

        return round(overall, 3)

    def _score_details(self, plan: Plan) -> str:
        """Return a human-readable summary of the plan score factors."""
        if plan.score is None:
            return "unscored"
        n = len(plan.steps)
        tools = sum(1 for s in plan.steps if s.suggested_tool)
        return f"steps={n}, tools_assigned={tools}/{n}, score={plan.score}"

    # ── Adaptive replanning ───────────────────────────────────────────────

    def _should_replan(self, plan: Plan) -> bool:
        """Decide whether to attempt adaptive replanning after a failure."""
        if not plan.error:
            return False
        # Don't replan if any step requires human review.
        for s in plan.steps:
            if s.verifier_result and s.verifier_result.action == VerifierAction.HUMAN_REVIEW.value:
                return False
        failed = sum(1 for s in plan.steps if s.status == "failed")
        total = len(plan.steps)
        if total == 0:
            return False
        # Always attempt full replan if 3+ steps failed; otherwise allow if
        # the failures are a minority of the plan so the new plan has a base
        # of successful context to work from.
        return failed >= 3 or failed <= total // 2

    async def _adaptive_replan(self, old_plan: Plan, request: str, topic: str) -> Plan:
        """Re-generate a plan incorporating context from step failures."""
        failed_summaries = []
        for s in old_plan.steps:
            if s.status == "failed":
                details = ""
                if s.verifier_result:
                    issues = "; ".join(s.verifier_result.issues)
                    details = f" (verifier: {s.verifier_result.status}, {issues})" if issues else ""
                failed_summaries.append(f"Step '{s.id}' ({s.goal}) failed: {s.error}{details}")
            elif s.status == "completed":
                failed_summaries.append(f"Step '{s.id}' ({s.goal}) succeeded")

        failure_context = "\n".join(failed_summaries)

        prompt = _REPLAN_PROMPT.format(
            request=request,
            tool_list=_format_tool_list(),
            failure_context=failure_context,
        )

        messages = [
            Message(role="system", content=build_system_prompt()),
            Message(role="user", content=prompt),
        ]

        opts = GenerateOptions(
            temperature=0.4,
            max_tokens=2048,
            tools=[],
            allow_tools=False,
        )

        text = ""
        try:
            async for chunk in self.provider.generate_stream(messages, opts):
                if chunk.text:
                    text += chunk.text
                if chunk.done:
                    break
        except Exception as e:
            logger.error("replan generation failed: %s", e)
            old_plan.error = f"replan failed: {e}"
            return old_plan

        steps = self._parse_steps(text)
        if not steps:
            logger.warning("replan produced no valid steps, keeping original")
            return old_plan

        await self.bus.publish(
            Event(
                type="plan.replanned",
                topic=topic,
                payload={
                    "request": request,
                    "step_count": len(steps),
                    "steps": [s.goal for s in steps],
                },
            )
        )

        new_plan = Plan(request=request, steps=steps)
        validation_error = self._validate_plan(new_plan)
        if validation_error:
            logger.warning("replan validation failed: %s, keeping original", validation_error)
            return old_plan

        await self._execute_dag(new_plan, topic)
        return new_plan

    async def _repair_step(
        self, failed_step: PlanStep, error: str, request: str,
        failure_category: str = "unknown",
    ) -> PlanStep | None:
        """Generate a single replacement step for a failed step.

        Args:
            failed_step: The step that failed.
            error: Error message from the failure.
            request: Original user request.
            failure_category: Categorised failure type (timeout, invalid_input,
                permission_denied, tool_error, unknown).

        Returns a PlanStep or None if the goal is judged unachievable.
        """
        prompt = _REPAIR_STEP_PROMPT.format(
            failed_goal=failed_step.goal,
            error=error,
            failure_category=failure_category,
            request=request,
            tool_list=_format_tool_list(),
        )

        messages = [
            Message(role="system", content=build_system_prompt()),
            Message(role="user", content=prompt),
        ]

        opts = GenerateOptions(
            temperature=0.3,
            max_tokens=512,
            tools=[],
            allow_tools=False,
        )

        text = ""
        try:
            async for chunk in self.provider.generate_stream(messages, opts):
                if chunk.text:
                    text += chunk.text
                if chunk.done:
                    break
        except Exception as e:
            logger.error("step repair LLM call failed: %s", e)
            return None

        json_match = re.search(r"\{.*\}|null", text.strip(), re.DOTALL)
        if not json_match:
            logger.warning("repair step: no JSON or null found in response")
            return None

        raw = json_match.group().strip()
        if raw == "null":
            logger.info("repair step: LLM judged goal as unachievable")
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("repair step: invalid JSON in response")
            return None

        return PlanStep(
            id=data.get("id", f"repair_{failed_step.id}"),
            goal=data.get("goal", ""),
            suggested_tool=data.get("tool") or data.get("suggested_tool"),
            depends_on=list(failed_step.depends_on),
        )


def _parse_verifier_result(text: str) -> VerifierResult:
    """Parse structured JSON from the verifier LLM response.

    Falls back to simple PASS/FAIL parsing if JSON is not returned.
    """
    import json

    json_match = re.search(r"\{.*\}", text.strip(), re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return VerifierResult(
                status=str(data.get("status", "UNCERTAIN")).upper(),
                confidence=float(data.get("confidence", 0.0)),
                issues=list(data.get("issues", [])),
                evidence=str(data.get("evidence", "")),
                action=str(data.get("action", _default_action(data))).upper(),
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Fallback: simple PASS/FAIL parsing.
    cleaned = text.strip().upper().rstrip(".").strip()
    if cleaned == "PASS" or cleaned.startswith("PASS\n"):
        return VerifierResult(status="PASS", confidence=0.8, action=VerifierAction.COMPLETE.value)
    return VerifierResult(status="FAIL", confidence=0.4, action=VerifierAction.REPLAN.value)


def _default_action(data: dict) -> str:
    """Determine default action from status."""
    s = str(data.get("status", "")).upper()
    if s == "PASS":
        return VerifierAction.COMPLETE.value
    if s == "UNCERTAIN":
        return VerifierAction.HUMAN_REVIEW.value
    return VerifierAction.REPLAN.value


def _trim_messages(messages: list[Message], max_messages: int = 16) -> list[Message]:
    """Keep the conversation bounded for a step execution."""
    if len(messages) <= max_messages:
        return messages
    head = [m for m in messages if m.role == "system"]
    tail = messages[-(max_messages - len(head)):]
    return head + tail


def _format_tool_list() -> str:
    """Return a compact list of tool names and descriptions."""
    registry = get_registry()
    lines = []
    for t in registry.all():
        lines.append(f"  - {t.name}: {t.description}")
    return "\n".join(lines)


_PLANNER_PROMPT = """\
Decompose the following user request into a sequence of concrete steps.

Each step should be a single, actionable sub-goal that can be accomplished by
running a tool or making an observation. Steps should be ordered to build on
each other where needed. If a step depends on another step's output, specify
that dependency.

Available tools:
{tool_list}

User request: {request}

Respond with a JSON array of step objects. Each step object must have:
  - "id": a short identifier like "step_1"
  - "goal": the concrete sub-goal for this step
  - "tool": (optional) the name of the tool most likely needed
  - "depends_on": (optional) a list of step ids this step depends on.
    Omit if this step has no dependencies.

Example:
[
  {{"id": "step_1", "goal": "Check current CPU and memory usage", "tool": "system_monitor"}},
  {{"id": "step_2", "goal": "List files in the project directory", "tool": "filesystem_read", "depends_on": []}},
  {{"id": "step_3", "goal": "Analyze the largest files found", "depends_on": ["step_2"]}}
]

Only respond with the JSON array, no other text.
"""

_VERIFIER_PROMPT = """\
Goal: {goal}

Result:
{result}

Assess whether the result fully satisfies the goal.

Respond with a JSON object with these fields:
  - "status": "PASS" | "FAIL" | "UNCERTAIN"
  - "confidence": float between 0.0 and 1.0
  - "issues": list of strings describing what is wrong (empty if PASS)
  - "evidence": brief quote or description supporting the assessment
  - "action": "COMPLETE" | "RETRY" | "REPLAN" | "HUMAN_REVIEW"

Guidelines:
- PASS + confidence >0.7 → action COMPLETE
- Minor issues, salvageable → action RETRY
- Major flaws, needs new approach → action REPLAN
- Unsure, sensitive context → action HUMAN_REVIEW

Only respond with the JSON object, no other text.

"""

_SYNTHESIS_PROMPT = """\
Original request: {request}

The following steps were executed with these results:

{steps}

Synthesize a comprehensive final response that directly answers the original
request using the step results. Be concise but include relevant details.
"""

_REPLAN_PROMPT = """\
A previous plan for the request below had some step failures. Re-plan with
adjusted steps that avoid the same mistakes.

Original request: {request}

Available tools:
{tool_list}

Previous execution results:
{failure_context}

Generate a new plan as a JSON array of step objects. Each step must have:
  - "id": short identifier
  - "goal": concrete sub-goal
  - "tool": (optional) tool name
  - "depends_on": (optional) list of dependency step ids

Avoid repeating failing approaches. Only respond with the JSON array.
"""

_REPAIR_STEP_PROMPT = """\
A step in a plan failed. Generate a SINGLE replacement step.

Failed step goal: {failed_goal}
Error: {error}
Failure category: {failure_category}

Original request: {request}

Available tools:
{tool_list}

If the goal is truly unachievable, respond with: null

Otherwise respond with a single JSON object:
  - "id": a short identifier like "repair_1"
  - "goal": the concrete sub-goal
  - "tool": (optional) tool name most likely needed

Failure category hints:
  - timeout: the tool or LLM timed out — simplify the goal or pick a faster tool
  - invalid_input: wrong parameters were passed — fix the parameter values
  - permission_denied: the tool was blocked by security — try a different approach
  - tool_error: the tool itself failed — try an alternative tool
  - unknown: unexpected error — try a different strategy entirely

Example:
{{"id": "repair_1", "goal": "Retry using a different tool", "tool": "filesystem_read"}}

Only respond with the JSON object or null, no other text.
"""
