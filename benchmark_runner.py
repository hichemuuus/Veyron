#!/usr/bin/env python3
"""Veyron Benchmark Runner — automated evaluation pipeline.

Runs the benchmark suite, collects metrics, detects regressions,
and generates comprehensive reports.

Usage:
    python benchmark_runner.py [--dataset BENCHMARK_DATASET.json] [--run-id ID]
                               [--max-concurrency 3] [--mode quick|full]
                               [--output-dir reports]

Examples:
    python benchmark_runner.py --mode quick --max-concurrency 5
    python benchmark_runner.py --dataset my_tasks.json --run-id v1.1-test
    python benchmark_runner.py --mode full --output-dir ./benchmark_results
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmark_runner")


def _load_tasks(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tasks = data.get("tasks", [])
    logger.info("Loaded %d tasks from %s", len(tasks), path)
    return tasks


def _filter_tasks(
    tasks: list[dict[str, Any]],
    categories: list[str] | None = None,
    max_count: int = 0,
) -> list[dict[str, Any]]:
    filtered = tasks
    if categories:
        filtered = [t for t in filtered if t.get("category") in categories]
    if max_count > 0:
        filtered = filtered[:max_count]
    return filtered


async def _run_benchmark(args: argparse.Namespace) -> None:
    from veyron.db.base import init_db

    init_db()

    from veyron.evaluation.evaluator_v2 import BenchmarkRunner, BenchmarkTask
    from veyron.evaluation.reporting import SummaryReport
    from veyron.evaluation.regression import detect_regressions, get_latest_baseline_run_id

    # Load tasks.
    raw_tasks = _load_tasks(args.dataset)
    categories = args.categories.split(",") if args.categories else None
    filtered = _filter_tasks(raw_tasks, categories, args.max_tasks)

    if not filtered:
        logger.error("No tasks matched the filters")
        sys.exit(1)

    # Convert to BenchmarkTask objects.
    tasks = [BenchmarkTask.from_dict(t) for t in filtered]
    logger.info("Running %d tasks (concurrency=%d)", len(tasks), args.max_concurrency)

    # Run the benchmark.
    run_id = args.run_id or f"bench_{int(time.time())}"
    runner = BenchmarkRunner()
    metrics = await runner.run_suite(
        tasks,
        run_id=run_id,
        max_concurrency=args.max_concurrency,
        include_memory_metrics=True,
        detect_hallucinations=True,
    )

    # Generate report.
    report = SummaryReport(metrics, run_id=run_id)
    markdown = report.to_markdown()
    report_dict = report.to_dict()

    # Save outputs.
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"benchmark_report_{run_id}.md"
    md_path.write_text(markdown, encoding="utf-8")
    logger.info("Report saved to %s", md_path)

    json_path = output_dir / f"benchmark_results_{run_id}.json"
    json_path.write_text(report.to_json(), encoding="utf-8")
    logger.info("Results saved to %s", json_path)

    # Print summary.
    summary = report_dict.get("summary", {})
    print("\n" + "=" * 60)
    print(f"BENCHMARK COMPLETE — {run_id}")
    print("=" * 60)
    print(f"  Tasks:       {summary.get('total', 0)}")
    print(f"  Passed:      {summary.get('passed', 0)} ({summary.get('pass_rate', 0)*100:.1f}%)")
    print(f"  Failed:      {summary.get('failed', 0)}")
    print(f"  Clarified:   {summary.get('clarification_rate', 0)*100:.1f}%")
    print(f"  Hallucinated: {summary.get('hallucination_rate', 0)*100:.1f}%")
    print()

    planner = report_dict.get("planner", {})
    print(f"  Avg plan length:    {planner.get('avg_plan_length', 0)}")
    print(f"  Dep correctness:    {planner.get('avg_dependency_correctness', 0)*100:.1f}%")
    print(f"  Unnecessary steps:  {planner.get('avg_unnecessary_steps', 0)}")

    latency = report_dict.get("latency", {})
    print(f"\n  Avg total latency:  {latency.get('avg_total_ms', 0):.0f}ms")
    print(f"  Avg LLM latency:    {latency.get('avg_llm_ms', 0):.0f}ms")
    print(f"  Avg tool latency:   {latency.get('avg_tool_ms', 0):.0f}ms")

    failures = report_dict.get("failures", {})
    print(f"\n  Failures: {failures.get('total', 0)}")
    for cat, count in failures.get("distribution", {}).items():
        if cat != "none":
            print(f"    {cat}: {count}")

    # Detect regressions against baseline.
    if not args.skip_regression:
        latest_baseline = get_latest_baseline_run_id()
        if latest_baseline and latest_baseline != run_id:
            print(f"\n  Checking regressions against baseline: {latest_baseline}")
            regressions = detect_regressions(
                current_run_id=run_id,
                baseline_run_id=latest_baseline,
            )
            if regressions:
                print(f"  Found {len(regressions)} regressions:")
                for reg in regressions:
                    icon = "🔴" if reg["severity"] == "critical" else "🟡"
                    direction = "⬆" if reg["delta"] > 0 else "⬇"
                    print(
                        f"    {icon} {reg['metric']}: "
                        f"{reg['baseline_value']:.3f} → {reg['current_value']:.3f} "
                        f"({direction} {abs(reg['delta']):.3f})"
                    )
            else:
                print("  No regressions detected.")

    print("=" * 60)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Veyron Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dataset", default="BENCHMARK_DATASET.json",
        help="Path to benchmark dataset JSON file",
    )
    parser.add_argument("--run-id", help="Unique identifier for this run")
    parser.add_argument(
        "--max-concurrency", type=int, default=3,
        help="Maximum parallel tasks (default: 3)",
    )
    parser.add_argument(
        "--categories",
        help="Comma-separated category filter (e.g. code_debugging,system_diagnostics)",
    )
    parser.add_argument(
        "--max-tasks", type=int, default=0,
        help="Maximum number of tasks to run (0 = all)",
    )
    parser.add_argument(
        "--mode", choices=["quick", "full"], default="quick",
        help="quick=10 tasks, full=all tasks",
    )
    parser.add_argument(
        "--output-dir", default="reports",
        help="Output directory for reports",
    )
    parser.add_argument(
        "--skip-regression", action="store_true",
        help="Skip regression detection against baseline",
    )

    args = parser.parse_args()

    if args.mode == "quick" and args.max_tasks == 0:
        args.max_tasks = 10

    asyncio.run(_run_benchmark(args))


if __name__ == "__main__":
    main()
