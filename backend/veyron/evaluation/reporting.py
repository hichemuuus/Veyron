"""Report generation — comprehensive structured reports from benchmark runs.

Produces markdown reports, JSON exports, and summary dicts for API consumption.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from veyron.evaluation.evaluator_v2 import TaskMetrics, format_benchmark_results

logger = logging.getLogger(__name__)


class SummaryReport:
    """Generate comprehensive benchmark reports in multiple formats."""

    def __init__(self, metrics: list[TaskMetrics], run_id: str = ""):
        self.metrics = metrics
        self.run_id = run_id
        self.stats = format_benchmark_results(metrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "task_count": len(self.metrics),
            **self.stats,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        """Generate a comprehensive markdown report."""
        s = self.stats
        summary = s.get("summary", {})

        lines = [
            "# Benchmark Report",
            "",
            f"**Run ID:** {self.run_id or '(auto)'}",
            f"**Tasks:** {summary.get('total', 0)}",
            f"**Date:** {__import__('datetime').datetime.now().isoformat()}",
            "",
            "## 1. Overall Score",
            "",
            f"- **Success Rate:** {summary.get('pass_rate', 0) * 100:.1f}% "
            f"({summary.get('passed', 0)}/{summary.get('total', 0)})",
            f"- **Clarification Rate:** {summary.get('clarification_rate', 0) * 100:.1f}%",
            f"- **Hallucination Rate:** {summary.get('hallucination_rate', 0) * 100:.1f}%",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ]

        for key, val in summary.items():
            if isinstance(val, float):
                lines.append(f"| {key} | {val:.3f} |")
            else:
                lines.append(f"| {key} | {val} |")

        lines += [
            "",
            "## 2. Planner Quality",
            "",
        ]
        planner = s.get("planner", {})
        for key, val in planner.items():
            if isinstance(val, float):
                lines.append(f"- **{key}:** {val:.3f}")
            else:
                lines.append(f"- **{key}:** {val}")

        lines += [
            "",
            "## 3. Memory Quality",
            "",
        ]
        mem = s.get("memory", {})
        for key, val in mem.items():
            lines.append(f"- **{key}:** {val}")

        lines += [
            "",
            "## 4. Tool Accuracy",
            "",
        ]
        tools = s.get("tools", {})
        for key, val in tools.items():
            if isinstance(val, float):
                lines.append(f"- **{key}:** {val:.3f}")
            else:
                lines.append(f"- **{key}:** {val}")

        lines += [
            "",
            "## 5. Latency Analysis",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ]
        latency = s.get("latency", {})
        for key, val in latency.items():
            lines.append(f"| {key} | {val} |")

        lines += [
            "",
            "## 6. Failure Breakdown",
            "",
        ]
        failures = s.get("failures", {})
        lines.append(f"- **Total Failures:** {failures.get('total', 0)}")
        lines.append("- **Distribution:**")
        for cat, count in failures.get("distribution", {}).items():
            lines.append(f"  - {cat}: {count}")
        lines.append("")

        lines += [
            "",
            "## 7. Category Scores",
            "",
            "| Category | Passed | Total | Rate |",
            "|----------|--------|-------|------|",
        ]
        for cat, cs in sorted(s.get("categories", {}).items()):
            lines.append(f"| {cat} | {cs['passed']} | {cs['total']} | {cs['rate']*100:.1f}% |")

        lines += [
            "",
            "## 8. Tool Statistics",
            "",
            "| Tool | Executions | Success Rate | Avg Latency | Reliability |",
            "|------|-----------|-------------|-------------|-------------|",
        ]
        for ts in s.get("tool_stats", []):
            lines.append(
                f"| {ts['tool_name']} | {ts['total_executions']} | "
                f"{ts['success_rate']*100:.1f}% | {ts['avg_latency_ms']:.0f}ms | "
                f"{ts['reliability_score']:.3f} |"
            )

        lines += [
            "",
            "## 9. Failure Statistics",
            "",
        ]
        fs = s.get("failure_stats", {})
        lines.append(f"- **Total Failure Records:** {fs.get('total', 0)}")
        lines.append(f"- **Recovery Rate:** {fs.get('recovery_rate', 0) * 100:.1f}%")
        lines.append("- **By Category:**")
        for cat, count in sorted(fs.get("by_category", {}).items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  - {cat}: {count}")
        lines.append("- **Top Patterns:**")
        for pattern, count in sorted(fs.get("top_patterns", {}).items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  - '{pattern}': {count} occurrences")
        lines.append("")

        return "\n".join(lines)

    def print(self) -> None:
        print(self.to_markdown())
