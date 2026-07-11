"""Benchmark runner — evaluates the agent against task suites and produces reports.

Usage:
    python -m benchmarks.runner [--suite basic,intermediate,advanced] [--output benchmarks/data/report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from benchmarks.tasks import ADVANCED_TASKS, BASIC_TASKS, INTERMEDIATE_TASKS, ALL_TASKS
from paios.core.agent import Agent
from paios.core.evaluator import EvalTask, Evaluator
from paios.db.base import init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("benchmarks")


def _resolve_tasks(suite_names: list[str]) -> list[EvalTask]:
    suites = {
        "basic": BASIC_TASKS,
        "intermediate": INTERMEDIATE_TASKS,
        "advanced": ADVANCED_TASKS,
        "all": ALL_TASKS,
    }
    tasks: list[EvalTask] = []
    for name in suite_names:
        resolved = suites.get(name)
        if resolved is None:
            print(f"Unknown suite: {name}. Choose from: {', '.join(suites.keys())}", file=sys.stderr)
            sys.exit(1)
        tasks.extend(resolved)
    return tasks


async def run_benchmarks(
    suite_names: list[str],
    output: str | None = None,
    agent: Agent | None = None,
) -> dict[str, Any]:
    """Run the benchmark suite and return results."""
    tasks = _resolve_tasks(suite_names)
    if not tasks:
        print("No tasks selected.", file=sys.stderr)
        return {"error": "no tasks"}

    init_db()
    evaluator = Evaluator(agent=agent or Agent())
    logger.info("Starting benchmark: %d tasks across suites %s", len(tasks), suite_names)

    start = time.monotonic()
    results = await evaluator.run_suite(tasks, include_memory_metrics=True)
    elapsed = time.monotonic() - start

    report_text = evaluator.print_report(results)
    summary = evaluator.summary_report(results)
    summary["total_duration_sec"] = round(elapsed, 2)
    summary["tasks_per_sec"] = round(len(results) / elapsed, 2) if elapsed > 0 else 0

    # Per-task breakdown
    task_details = []
    for r in results:
        task_details.append({
            "task_id": r.task_id,
            "category": r.category,
            "success": r.success,
            "duration_ms": r.duration_ms,
            "iterations": r.iterations,
            "tool_calls_count": r.tool_calls_count,
            "retry_count": r.retry_count,
            "replan_count": r.replan_count,
            "memory_count": r.memory_count,
            "memory_usefulness_avg": r.memory_usefulness_avg,
            "error": r.error,
        })
    summary["tasks"] = task_details

    # Print report
    print()
    print(report_text)
    print()
    print(f"Total duration: {elapsed:.1f}s  ({len(results)} tasks, {summary['tasks_per_sec']:.2f} tasks/sec)")
    print()

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2, default=str))
        print(f"Results written to {out_path}")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="PAIOS Benchmark Runner")
    parser.add_argument(
        "--suite",
        default="basic",
        help="Comma-separated suite names: basic,intermediate,advanced,all (default: basic)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write JSON results (e.g. benchmarks/data/report.json)",
    )
    args = parser.parse_args()

    suite_names = [s.strip() for s in args.suite.split(",")]
    asyncio.run(run_benchmarks(suite_names, output=args.output))


if __name__ == "__main__":
    main()
