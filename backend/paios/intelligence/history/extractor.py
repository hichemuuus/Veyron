"""Agent history extraction pipeline.

Extracts training examples from execution logs, tracker timelines, and
eval results to create datasets for future retraining.

Sources:
  - ExecutionTracker timelines (step-by-step agent execution)
  - EvaluationMetric table (eval benchmark results)
  - ToolInvocation table (tool call history)
  - Audit logs (command execution records)

Output: JSONL files ready for dataset ingestion.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paios.config import DATA_DIR
from paios.db.base import sync_session_scope
from paios.db.models import EvaluationMetric, ExecutionStep, Task, ToolInvocation
from paios.intelligence.intent.dataset import IntentDataset

logger = logging.getLogger(__name__)


class HistoryExtractor:
    """Extract training data from agent execution history.

    Usage:
        extractor = HistoryExtractor()
        successful, failed = extractor.extract_from_tracker(limit=200)
        # successful: list of (user_request, tools_used, outcome)
        # failed: list of (user_request, error, tools_used)
    """

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else (DATA_DIR / "history")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_from_tracker(
        self, limit: int = 200
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract successful and failed examples from ExecutionTracker data.

        Returns:
            (successful_examples, failed_examples)
        """
        successful: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        try:
            with sync_session_scope() as session:
                tasks = (
                    session.query(Task)
                    .order_by(Task.created_at.desc())
                    .limit(limit)
                    .all()
                )

                for task in tasks:
                    if not task.request:
                        continue

                    # Get steps for this task.
                    steps = (
                        session.query(ExecutionStep)
                        .filter(ExecutionStep.task_public_id == task.public_id)
                        .order_by(ExecutionStep.step_index)
                        .all()
                    )

                    tools_used: list[str] = []
                    outcomes: list[str] = []
                    for step in steps:
                        if step.tool_name:
                            tools_used.append(step.tool_name)
                        if step.result_summary:
                            outcomes.append(step.result_summary)

                    example = {
                        "request": task.request,
                        "tools_used": tools_used,
                        "num_steps": len(steps),
                        "status": task.status.value if task.status else "unknown",
                        "created_at": str(task.created_at) if task.created_at else "",
                        "task_id": task.public_id,
                    }

                    if task.status and task.status.value in ("completed", "success"):
                        example["outcome"] = outcomes[-1] if outcomes else "completed"
                        successful.append(example)
                    elif task.status and task.status.value in ("failed", "error", "cancelled"):
                        example["error"] = outcomes[-1] if outcomes else task.status.value
                        example["outcome"] = "failed"
                        failed.append(example)

        except Exception as e:
            logger.warning("extraction from tracker failed: %s", e)

        return successful, failed

    def extract_from_eval_results(
        self, limit: int = 100
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract examples from EvaluationMetric table (benchmark runs).

        Returns:
            (successful_examples, failed_examples)
        """
        successful: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        try:
            with sync_session_scope() as session:
                results = (
                    session.query(EvaluationMetric)
                    .order_by(EvaluationMetric.created_at.desc())
                    .limit(limit)
                    .all()
                )

                for r in results:
                    details = {}
                    try:
                        if r.details_json:
                            details = json.loads(r.details_json)
                    except (json.JSONDecodeError, TypeError):
                        pass

                    expected_tools = details.get("expected_tools", [])

                    example = {
                        "task_id": r.task_id,
                        "category": r.category,
                        "success": r.success,
                        "duration_ms": r.duration_ms,
                        "iterations": r.iterations,
                        "tool_calls_count": r.tool_calls_count,
                        "expected_tools": expected_tools,
                        "error": r.error,
                        "created_at": str(r.created_at) if r.created_at else "",
                    }

                    if r.success:
                        successful.append(example)
                    else:
                        failed.append(example)

        except Exception as e:
            logger.warning("extraction from eval results failed: %s", e)

        return successful, failed

    def extract_from_tool_invocations(
        self, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Extract tool invocation patterns from ToolInvocation table."""
        examples: list[dict[str, Any]] = []

        try:
            with sync_session_scope() as session:
                invocations = (
                    session.query(ToolInvocation)
                    .order_by(ToolInvocation.created_at.desc())
                    .limit(limit)
                    .all()
                )

                for inv in invocations:
                    examples.append({
                        "tool_name": inv.tool_name,
                        "inputs": str(inv.inputs)[:200] if inv.inputs else "",
                        "success": inv.success,
                        "duration_ms": inv.duration_ms,
                        "error": inv.error,
                        "created_at": str(inv.created_at) if inv.created_at else "",
                    })

        except Exception as e:
            logger.warning("extraction from tool invocations failed: %s", e)

        return examples

    def generate_intent_dataset_from_history(
        self, successful: list[dict[str, Any]], failed: list[dict[str, Any]]
    ) -> IntentDataset:
        """Convert extracted history into an IntentDataset for retraining."""
        dataset = IntentDataset()

        from paios.intelligence.intent.dataset import CATEGORY_REQUIRES_PLANNING, CATEGORY_REQUIRES_TOOL

        for ex in successful:
            request = ex.get("request", "")
            if not request or len(request) < 3:
                continue

            intent = self._infer_intent_from_tools(ex.get("tools_used", []), request)
            dataset.add(
                request,
                intent,
                complexity="moderate",
                requires_tool=CATEGORY_REQUIRES_TOOL.get(intent, False),
                requires_planning=CATEGORY_REQUIRES_PLANNING.get(intent, False),
            )

        for ex in failed:
            request = ex.get("request", "")
            if not request or len(request) < 3:
                continue

            tools = ex.get("tools_used", [])
            intent = self._infer_intent_from_tools(tools, request)
            dataset.add(
                request,
                intent,
                complexity="complex",
                requires_tool=CATEGORY_REQUIRES_TOOL.get(intent, True),
                requires_planning=CATEGORY_REQUIRES_PLANNING.get(intent, True),
            )

        return dataset

    def _infer_intent_from_tools(self, tools: list[str], request: str) -> str:
        """Heuristically infer intent category from tools used and request text."""
        tool_intent_map: dict[str, str] = {
            "filesystem_read": "file_operation",
            "system_monitor": "system_management",
            "terminal": "tool_execution",
            "project_analyzer": "project_analysis",
        }

        if len(set(tools)) > 1:
            if "planning" in request.lower() or "first" in request.lower() or "then" in request.lower():
                return "planning_task"
            if "debug" in request.lower() or "bug" in request.lower() or "error" in request.lower():
                return "debugging"

        for tool in tools:
            if tool in tool_intent_map:
                return tool_intent_map[tool]

        request_lower = request.lower()
        if "?" in request or "what" in request_lower or "how" in request_lower or "why" in request_lower:
            return "question_answering"
        return "conversation"

    def save_to_jsonl(self, data: list[dict[str, Any]], filename: str) -> Path:
        """Save extracted data as a JSONL file."""
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        logger.info("saved %d records to %s", len(data), path)
        return path

    def run_full_extraction(
        self,
        tracker_limit: int = 200,
        eval_limit: int = 100,
        tool_limit: int = 200,
    ) -> dict[str, Any]:
        """Run all extraction pipelines and save results."""
        logger.info("=" * 60)
        logger.info("Running full history extraction")
        logger.info("=" * 60)

        result: dict[str, Any] = {}

        successful, failed = self.extract_from_tracker(limit=tracker_limit)
        result["tracker_successful"] = len(successful)
        result["tracker_failed"] = len(failed)
        if successful:
            self.save_to_jsonl(successful, "tracker_successful.jsonl")
        if failed:
            self.save_to_jsonl(failed, "tracker_failed.jsonl")

        eval_success, eval_failed = self.extract_from_eval_results(limit=eval_limit)
        result["eval_successful"] = len(eval_success)
        result["eval_failed"] = len(eval_failed)
        if eval_success:
            self.save_to_jsonl(eval_success, "eval_successful.jsonl")
        if eval_failed:
            self.save_to_jsonl(eval_failed, "eval_failed.jsonl")

        tool_examples = self.extract_from_tool_invocations(limit=tool_limit)
        result["tool_invocations"] = len(tool_examples)
        if tool_examples:
            self.save_to_jsonl(tool_examples, "tool_invocations.jsonl")

        intent_dataset = self.generate_intent_dataset_from_history(successful, failed)
        result["intent_examples_generated"] = len(intent_dataset)
        if len(intent_dataset) > 0:
            self.save_to_jsonl(
                [{"text": ex["text"], "intent": ex["intent"]} for ex in intent_dataset.examples],
                "history_intent_dataset.jsonl",
            )

        logger.info("Extraction complete: %s", json.dumps(result, default=str))
        return result
