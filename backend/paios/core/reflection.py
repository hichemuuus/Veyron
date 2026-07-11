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
from datetime import datetime, timezone
from typing import Any

from paios.config import get_settings
from paios.core.tracker import ExecutionTracker
from paios.llm.base import GenerateOptions, LLMProvider, Message, get_provider
from paios.memory.store import get_memory_store

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

Please analyze honestly and critically.

Return a JSON object with these fields:
- "success": true/false — did the task succeed?
- "mistakes": [string list] — what went wrong?
- "improvements": [string list] — how could this be done better next time?
- "memories_to_store": [list of objects with "content" (str), "importance" (0-1 float), "category" ("user"/"project"/"history"/"skill")]
  — what knowledge from this task should be remembered?
- "tool_issues": [string list] — did any tools cause problems? Which ones?
- "plan_efficiency": float 0-1 — how efficient was the execution?
- "summary": string — one-paragraph reflection summary
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
        summary = self.tracker.get_task_summary(task_public_id) if task_public_id != "system" else {}

        iterations = summary.get("total_steps", 0)
        tool_calls_count = summary.get("tool_count", 0)
        retry_count = summary.get("retry_count", 0)
        outcome = "Success" if success else "Failed"

        tool_names = ""
        if task_public_id != "system":
            timeline = self.tracker.get_timeline(task_public_id, limit=100)
            tool_names = ", ".join(
                sorted(
                    set(
                        s.get("name", "")
                        for s in timeline
                        if s.get("step_type") in ("tool_call", "plan_step")
                    )
                )
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
