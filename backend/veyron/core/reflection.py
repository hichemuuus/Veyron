"""Agent reflection — structured post-task analysis.

After completing a task, the agent optionally analyzes:
- What worked and what failed
- Which tools caused problems
- Whether the plan was efficient
- What knowledge should be stored as memories

Reflection output is structured and can be stored as memories for
future improvement.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from veyron.core.events import Event, get_bus
from veyron.core.tracker import ExecutionTracker
from veyron.db.base import sync_session_scope
from veyron.db.models import ReflectionCategory, ReflectionRecord
from veyron.llm.base import GenerateOptions, LLMProvider, Message, get_provider
from veyron.memory.store import get_memory_store
from sqlmodel import select, delete, update, func

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    """Structured output from agent self-reflection."""

    success: bool = True
    mistakes: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    memories_to_store: list[dict[str, Any]] = field(default_factory=list)
    tool_issues: list[str] = field(default_factory=list)
    plan_efficiency: float = 0.5  # 0.0 (terrible) to 1.0 (perfect)
    summary: str = ""
    confidence: float = 0.5  # how confident the reflection is
    planning_quality: float = 0.5  # how good the planning was
    tool_selection_quality: float = 0.5  # how well tools were selected
    parameter_quality: float = 0.5  # how accurate parameter prediction was
    memory_usefulness: float = 0.5  # whether retrieved memories were useful
    improvement_notes: str = ""  # free-form improvement notes


_REFLECTION_PROMPT = """\
You are an AI agent reflecting on a just-completed task.

Task request: {request}

Execution summary:
- Mode: {mode}
- Total steps/iterations: {iterations}
- Tool calls made: {tool_calls_count}
- Tool names called: {tool_names}
- Retry count: {retry_count}
- Final outcome: {outcome}
- Error (if any): {error}

Please analyze honestly and critically, focusing on what can be learned.

Return a JSON object with these fields:
- "success": true/false — did the task succeed?
- "mistakes": [string list] — what went wrong, specifically? Include both tool-level and reasoning-level issues.
- "improvements": [string list] — how could this be done better next time? Be concrete (e.g. "use a different tool", "ask for clarification first").
- "memories_to_store": [list of objects with "content" (str), "importance" (0-1 float), "category" ("user"/"project"/"history"/"skill")]
  — what knowledge from this task should be remembered for future tasks?
- "tool_issues": [string list] — did any tools cause problems? Which ones and why?
- "plan_efficiency": float 0-1 — how efficient was the execution?
- "summary": string — one-paragraph reflection summary
- "confidence": float 0-1 — how confident are you in this reflection?
- "planning_quality": float 0-1 — how good was the planning for this task?
- "tool_selection_quality": float 0-1 — how well were tools selected for the job?
- "parameter_quality": float 0-1 — how accurate were the parameters passed to tools?
- "memory_usefulness": float 0-1 — were the retrieved memories actually useful?
- "improvement_notes": string — any additional free-form notes on what could be improved
"""


class ReflectionEngine:
    """Analyzes completed agent runs and produces structured reflections.

    Uses the LLM to generate insight, then optionally persists learnings
    as memories.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        tracker: ExecutionTracker | None = None,
    ) -> None:
        self.provider = provider or get_provider()
        self.tracker = tracker or ExecutionTracker()

    @staticmethod
    def _analyze_failure_patterns(
        timeline: list[dict],
    ) -> tuple[list[str], list[str], list[str]]:
        """Analyze timeline for tool failure patterns.

        Returns:
            (failure_patterns, tool_issues, improvement_hints)
        """
        failure_patterns: list[str] = []
        tool_issues: list[str] = []
        improvement_hints: list[str] = []

        # Count tool failures and successes.
        tool_stats: dict[str, dict[str, int]] = {}
        for entry in timeline:
            name = entry.get("name", "")
            step_type = entry.get("step_type", "")
            if step_type not in ("tool_call", "plan_step"):
                continue
            ok = entry.get("ok", entry.get("status") == "completed")
            if name not in tool_stats:
                tool_stats[name] = {"ok": 0, "fail": 0, "errors": []}
            if ok:
                tool_stats[name]["ok"] += 1
            else:
                tool_stats[name]["fail"] += 1
                err = entry.get("error", "") or entry.get("output_preview", "")[:100]
                if err:
                    tool_stats[name]["errors"].append(err)

        for name, stats in tool_stats.items():
            total = stats["ok"] + stats["fail"]
            if stats["fail"] >= 2:
                failure_patterns.append(
                    f"Tool '{name}' failed {stats['fail']}/{total} times"
                )
                tool_issues.append(name)
                improvement_hints.append(
                    f"Investigate why '{name}' keeps failing; "
                    f"check parameters or availability"
                )
            elif stats["fail"] == 1 and stats["ok"] == 0:
                failure_patterns.append(
                    f"Tool '{name}' never succeeded in this run"
                )

        # Detect sequential failure chains.
        chain = []
        for entry in timeline:
            step_type = entry.get("step_type", "")
            if step_type == "tool_call":
                ok = entry.get("ok", False)
                name = entry.get("name", "")
                if not ok:
                    chain.append(name)
                else:
                    if len(chain) >= 2:
                        improvement_hints.append(
                            f"Sequential failures: {', '.join(chain)} — "
                            f"these may share a root cause"
                        )
                        failure_patterns.append(
                            f"Chain of {len(chain)} consecutive tool failures: {', '.join(chain)}"
                        )
                    chain = []
        if len(chain) >= 2:
            improvement_hints.append(
                f"Trailing failures: {', '.join(chain)} — run ended mid-error-chain"
            )

        return failure_patterns, tool_issues, improvement_hints

    async def reflect(
        self,
        request: str,
        task_public_id: str = "system",
        mode: str = "react",
        success: bool = True,
        error: str | None = None,
    ) -> ReflectionResult:
        """Run reflection on a completed task.

        Gathers execution data from the tracker, sends to LLM for analysis,
        and returns structured reflection.
        """
        summary = await self.tracker.get_task_summary(task_public_id) if task_public_id != "system" else {}

        iterations = summary.get("total_steps", 0)
        tool_calls_count = summary.get("tool_count", 0)
        retry_count = summary.get("retry_count", 0)
        outcome = "Success" if success else "Failed"

        tool_names = ""
        failure_context = ""
        if task_public_id != "system":
            timeline = await self.tracker.get_timeline(task_public_id, limit=100)
            tool_names = ", ".join(
                sorted(
                    set(
                        s.get("name", "")
                        for s in timeline
                        if s.get("step_type") in ("tool_call", "plan_step")
                    )
                )
            )
            patterns, tool_issues, hints = self._analyze_failure_patterns(timeline)
            if patterns:
                failure_context = "Failure patterns detected:\n" + "\n".join(
                    f"  - {p}" for p in patterns
                )
            if hints:
                failure_context += "\n\nImprovement hints:\n" + "\n".join(
                    f"  - {h}" for h in hints
                )

        prompt = _REFLECTION_PROMPT.format(
            request=request[:500],
            mode=mode,
            iterations=iterations,
            tool_calls_count=tool_calls_count,
            tool_names=tool_names or "(none)",
            retry_count=retry_count,
            outcome=outcome,
            success=success,
            error=error or "(none)",
        )

        if failure_context:
            prompt += f"\n\n{failure_context}"

        messages = [
            Message(
                role="system",
                content="You are an AI agent performing honest self-reflection. Be critical.",
            ),
            Message(role="user", content=prompt),
        ]

        opts = GenerateOptions(
            temperature=0.3,
            max_tokens=1024,
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
            logger.warning("reflection LLM call failed: %s", e)
            return ReflectionResult(
                success=success,
                summary=f"Reflection unavailable: {e}",
            )

        result = self._parse_reflection(text)
        result.success = success

        try:
            await get_bus().publish(
                Event(
                    type="reflection.completed",
                    topic=task_public_id,
                    payload={
                        "task_public_id": task_public_id,
                        "success": result.success,
                        "summary": result.summary,
                        "confidence": result.confidence,
                        "planning_quality": result.planning_quality,
                        "tool_selection_quality": result.tool_selection_quality,
                        "parameter_quality": result.parameter_quality,
                        "memory_usefulness": result.memory_usefulness,
                        "mistake_count": len(result.mistakes),
                        "improvement_count": len(result.improvements),
                        "tool_issue_count": len(result.tool_issues),
                    },
                )
            )
        except Exception:
            logger.warning("failed to publish reflection.completed event", exc_info=True)

        return result

    def _parse_reflection(self, text: str) -> ReflectionResult:
        """Parse the LLM's reflection response into a structured result."""
        import re

        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return ReflectionResult(
                    success=data.get("success", True),
                    mistakes=data.get("mistakes", []),
                    improvements=data.get("improvements", []),
                    memories_to_store=data.get("memories_to_store", []),
                    tool_issues=data.get("tool_issues", []),
                    plan_efficiency=float(data.get("plan_efficiency", 0.5)),
                    summary=data.get("summary", ""),
                    confidence=float(data.get("confidence", 0.5)),
                    planning_quality=float(data.get("planning_quality", 0.5)),
                    tool_selection_quality=float(data.get("tool_selection_quality", 0.5)),
                    parameter_quality=float(data.get("parameter_quality", 0.5)),
                    memory_usefulness=float(data.get("memory_usefulness", 0.5)),
                    improvement_notes=data.get("improvement_notes", ""),
                )
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning("failed to parse reflection JSON: %s", e)

        return ReflectionResult(summary=text.strip()[:500])

    def store_reflection_memories(self, reflection: ReflectionResult) -> int:
        """Persist memories suggested by the reflection.

        Returns the number of memories stored.
        """
        store = get_memory_store()
        stored = 0
        for mem_data in reflection.memories_to_store:
            content = mem_data.get("content", "").strip()
            if not content:
                continue
            should_store, _ = store.should_store(
                content,
                importance=float(mem_data.get("importance", 0.5)),
            )
            if should_store:
                store.store(
                    category=mem_data.get("category", "history"),
                    content=content,
                    importance=float(mem_data.get("importance", 0.5)),
                    tags=mem_data.get("tags", "reflection"),
                )
                stored += 1
        logger.info("stored %d reflection memories", stored)
        return stored

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def save_reflection_record(
        result: ReflectionResult,
        task_public_id: str,
        category: str = "task_reflection",
    ) -> None:
        """Persist the reflection to the ReflectionRecord table.

        Generates a UUID for public_id and stores all quality metrics.
        """
        try:
            cat = ReflectionCategory(category)
        except ValueError:
            cat = ReflectionCategory.TASK_REFLECTION

        record = ReflectionRecord(
            public_id=uuid4().hex,
            task_public_id=task_public_id,
            category=cat,
            success=result.success,
            confidence=result.confidence,
            planning_quality=result.planning_quality,
            tool_selection_quality=result.tool_selection_quality,
            parameter_quality=result.parameter_quality,
            memory_usefulness=result.memory_usefulness,
            mistake_count=len(result.mistakes),
            improvement_count=len(result.improvements),
            tool_issue_count=len(result.tool_issues),
            summary=result.summary,
            improvement_notes=result.improvement_notes,
        )
        with sync_session_scope() as session:
            session.add(record)
        logger.info("saved reflection record %s for task %s", record.public_id, task_public_id)

    @staticmethod
    def get_reflection_history(task_public_id: str, limit: int = 10) -> list[dict]:
        """Retrieve past reflections for a task, most recent first."""
        with sync_session_scope() as session:
            records = (
                session.exec(
                    select(ReflectionRecord)
                    .where(ReflectionRecord.task_public_id == task_public_id)
                    .order_by(ReflectionRecord.created_at.desc())
                    .limit(limit)
                )
                .all()
            )
            return [
                {
                    "public_id": r.public_id,
                    "task_public_id": r.task_public_id,
                    "category": r.category.value if isinstance(r.category, ReflectionCategory) else str(r.category),
                    "success": r.success,
                    "confidence": r.confidence,
                    "planning_quality": r.planning_quality,
                    "tool_selection_quality": r.tool_selection_quality,
                    "parameter_quality": r.parameter_quality,
                    "memory_usefulness": r.memory_usefulness,
                    "mistake_count": r.mistake_count,
                    "improvement_count": r.improvement_count,
                    "tool_issue_count": r.tool_issue_count,
                    "summary": r.summary,
                    "improvement_notes": r.improvement_notes,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ]

    @staticmethod
    def get_recent_reflections(limit: int = 20) -> list[dict]:
        """Get recent reflections across all tasks, most recent first."""
        with sync_session_scope() as session:
            records = (
                session.exec(
                    select(ReflectionRecord)
                    .order_by(ReflectionRecord.created_at.desc())
                    .limit(limit)
                )
                .all()
            )
            return [
                {
                    "public_id": r.public_id,
                    "task_public_id": r.task_public_id,
                    "category": r.category.value if isinstance(r.category, ReflectionCategory) else str(r.category),
                    "success": r.success,
                    "confidence": r.confidence,
                    "planning_quality": r.planning_quality,
                    "tool_selection_quality": r.tool_selection_quality,
                    "parameter_quality": r.parameter_quality,
                    "memory_usefulness": r.memory_usefulness,
                    "mistake_count": r.mistake_count,
                    "improvement_count": r.improvement_count,
                    "tool_issue_count": r.tool_issue_count,
                    "summary": r.summary,
                    "improvement_notes": r.improvement_notes,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ]

    @staticmethod
    def get_reflection_stats() -> dict:
        """Return aggregate statistics over all stored reflections."""
        with sync_session_scope() as session:
            total = session.exec(select(func.count(ReflectionRecord.id))).first() or 0

            avg_row = session.exec(
                select(
                    func.avg(ReflectionRecord.confidence).label("avg_confidence"),
                    func.avg(ReflectionRecord.planning_quality).label("avg_planning_quality"),
                    func.avg(ReflectionRecord.tool_selection_quality).label("avg_tool_selection_quality"),
                    func.avg(ReflectionRecord.memory_usefulness).label("avg_memory_usefulness"),
                )
            ).first()

            by_category_rows = (
                session.exec(
                    select(
                        ReflectionRecord.category,
                        func.count(ReflectionRecord.id).label("count"),
                    )
                    .group_by(ReflectionRecord.category)
                )
                .all()
            )

            return {
                "total_reflections": total,
                "average_confidence": float(avg_row.avg_confidence or 0.0) if avg_row else 0.0,
                "average_planning_quality": float(avg_row.avg_planning_quality or 0.0) if avg_row else 0.0,
                "average_tool_selection_quality": float(avg_row.avg_tool_selection_quality or 0.0) if avg_row else 0.0,
                "average_memory_usefulness": float(avg_row.avg_memory_usefulness or 0.0) if avg_row else 0.0,
                "reflections_by_category": {
                    row.category.value if isinstance(row.category, ReflectionCategory) else str(row.category): row.count
                    for row in by_category_rows
                },
            }
