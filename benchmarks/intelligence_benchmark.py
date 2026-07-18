"""Phase 11.5 Intelligence Evaluation — unified, reproducible benchmark.

Compares micro-model pipeline vs heuristic baseline across:
  - Tool selection precision/recall
  - Intent classification accuracy
  - Task success rate (when LLM available)
  - Latency impact
  - Regression detection vs previous run

Usage:
    python -m benchmarks.intelligence_benchmark [--dataset PATH] [--output DIR]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from veyron.config import DATA_DIR
from veyron.intelligence.intent.inference import ClassifierResult, classify_intent, reset_model
from veyron.intelligence.tool_selector.model import ToolSelectorModel
from veyron.llm.micro.router import route

logger = logging.getLogger(__name__)

BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = BENCHMARK_DIR / "datasets" / "intelligence_benchmark.json"
MODELS_DIR = DATA_DIR / "models"
REPORTS_DIR = DATA_DIR / "reports"


# ── Data containers ───────────────────────────────────────────────────────────


@dataclass
class BenchmarkConfig:
    dataset_path: str | Path = DEFAULT_DATASET
    models_dir: str | Path = MODELS_DIR
    output_dir: str | Path = REPORTS_DIR
    skip_task_success: bool = True  # True = skip agent-based tests (no LLM)


@dataclass
class ModeReport:
    """Metrics collected for a single mode run."""

    mode: str  # "micro_model" | "baseline"
    timestamp: str = ""
    tool_selection: dict[str, Any] = field(default_factory=dict)
    intent_classification: dict[str, Any] = field(default_factory=dict)
    task_success: dict[str, Any] = field(default_factory=dict)
    latency: dict[str, Any] = field(default_factory=dict)
    regression: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "timestamp": self.timestamp,
            "tool_selection": self.tool_selection,
            "intent_classification": self.intent_classification,
            "task_success": self.task_success,
            "latency": self.latency,
            "regression": self.regression,
            "errors": self.errors,
        }


@dataclass
class ComparisonReport:
    """Side-by-side comparison of micro-model vs baseline."""

    micro_model: dict[str, Any]
    baseline: dict[str, Any]
    delta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "micro_model": self.micro_model,
            "baseline": self.baseline,
            "delta": self.delta,
        }


# ── Data loading ──────────────────────────────────────────────────────────────


def load_dataset(path: str | Path) -> dict[str, Any]:
    """Load the curated benchmark dataset from JSON."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Benchmark dataset not found at {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    logger.info("Loaded benchmark dataset from %s (%d tool, %d task, %d reg)",
                path,
                len(data.get("tool_selection", [])),
                len(data.get("task_success", [])),
                len(data.get("regression", [])))
    return data


# ── Model loading ─────────────────────────────────────────────────────────────


def _load_intent_model(models_dir: str | Path):
    """Load intent classifier; return None if unavailable."""
    path = Path(models_dir) / "intent_classifier.pkl"
    if not path.exists():
        logger.warning("Intent model not found at %s", path)
        return None
    from veyron.intelligence.intent.model import IntentModel
    model = IntentModel()
    model.load(str(path))
    return model


def _load_tool_selector(models_dir: str | Path):
    """Load tool selector; return None if unavailable."""
    path = Path(models_dir) / "tool_selector.pkl"
    if not path.exists():
        logger.warning("Tool selector model not found at %s", path)
        return None
    model = ToolSelectorModel()
    model.load(str(path))
    return model


# ── Heuristic helpers ─────────────────────────────────────────────────────────


def _heuristic_intent_from_domain(domain: str) -> str:
    domain_map = {
        "system": "system_management",
        "filesystem": "file_operation",
        "terminal": "tool_execution",
        "project": "project_analysis",
    }
    return domain_map.get(domain, "conversation")


def _domain_to_expected_tools(domain: str) -> list[str]:
    mapping = {
        "system": ["system_monitor"],
        "filesystem": ["filesystem_read"],
        "terminal": ["terminal"],
        "project": ["project_analyzer"],
    }
    return mapping.get(domain, [])


# ── Benchmarks ────────────────────────────────────────────────────────────────


def _run_tool_selection_benchmark(
    test_cases: list[dict[str, Any]],
    tool_selector: ToolSelectorModel | None,
    mode: str,
) -> dict[str, Any]:
    """Evaluate tool selection predictions.

    In 'micro_model' mode, uses the trained ToolSelectorModel.
    In 'baseline' mode, uses heuristic domain→tool mapping.
    """
    results: list[bool] = []
    latencies: list[float] = []
    details: list[dict[str, Any]] = []

    for tc in test_cases:
        expected = set(tc.get("expected_tools", []))

        start = time.perf_counter()

        if mode == "micro_model" and tool_selector is not None:
            predicted = set(tool_selector.predict(tc["request"]))
        elif mode == "baseline":
            heuristic = route(tc["request"])
            predicted = set(_domain_to_expected_tools(heuristic.domain))
        else:
            predicted = set()

        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

        match = predicted == expected
        results.append(match)

        details.append({
            "id": tc.get("id", ""),
            "request": tc["request"][:80],
            "expected": sorted(expected),
            "predicted": sorted(predicted),
            "match": match,
        })

    n = len(results)
    correct = sum(results)
    return {
        "total": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n > 0 else 0.0,
        "avg_latency_ms": round(sum(latencies) / n, 3) if n > 0 else 0.0,
        "details": details,
    }


def _run_intent_benchmark(
    test_cases: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    """Evaluate intent classification.

    In 'micro_model' mode, uses classify_intent().
    In 'baseline' mode, uses heuristic route().
    """
    results: list[bool] = []
    latencies: list[float] = []
    confidences: list[float] = []
    details: list[dict[str, Any]] = []

    if mode == "micro_model":
        reset_model()

    for tc in test_cases:
        request = tc["request"]
        expected_tools = set(tc.get("expected_tools", []))
        start = time.perf_counter()

        if mode == "micro_model":
            result: ClassifierResult = classify_intent(request)
            heuristic_result = route(request)
            predicted_tools = set(_domain_to_expected_tools(heuristic_result.domain))
        else:
            heuristic_result = route(request)
            predicted_tools = set(_domain_to_expected_tools(heuristic_result.domain))
            result = ClassifierResult(
                category=_heuristic_intent_from_domain(heuristic_result.domain),
                confidence=heuristic_result.confidence,
            )

        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)
        confidences.append(result.confidence)

        match = predicted_tools == expected_tools
        results.append(match)

        details.append({
            "id": tc.get("id", ""),
            "request": request[:80],
            "expected_tools": sorted(expected_tools),
            "predicted_tools": sorted(predicted_tools),
            "match": match,
            "category": result.category,
            "confidence": round(result.confidence, 4),
        })

    n = len(results)
    correct = sum(results)
    return {
        "total": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n > 0 else 0.0,
        "avg_confidence": round(sum(confidences) / n, 3) if n > 0 else 0.0,
        "avg_latency_ms": round(sum(latencies) / n, 3) if n > 0 else 0.0,
        "details": details,
    }


def _run_task_success_benchmark(
    test_cases: list[dict[str, Any]],
    skip: bool = True,
) -> dict[str, Any]:
    """Evaluate task success by running the Agent.

    Skipped when no LLM is available (default).  When run, uses the
    existing Evaluator to measure pass/fail per task.
    """
    if skip:
        return {
            "available": False,
            "total": len(test_cases),
            "note": "Task success tests skipped — no LLM available. "
                    "Set VEYRON_SKIP_TASK_SUCCESS=0 to enable with a working LLM.",
        }

    from veyron.core.evaluator import EvalTask, Evaluator

    evaluator = Evaluator()
    tasks = [
        EvalTask(
            id=tc["id"],
            prompt=tc["prompt"],
            category=tc.get("category", "general"),
            expected_tools=tc.get("expected_tools", []),
            min_steps=tc.get("min_steps", 1),
            max_steps=tc.get("max_steps", 20),
        )
        for tc in test_cases
    ]

    import asyncio
    results = asyncio.run(evaluator.run_suite(tasks))

    passed = sum(1 for r in results if r.success)
    return {
        "available": True,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "avg_duration_ms": round(sum(r.duration_ms for r in results) / len(results), 1) if results else 0.0,
        "details": [
            {
                "task_id": r.task_id,
                "success": r.success,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in results
        ],
    }



def _run_latency_benchmark(
    test_cases: list[dict[str, Any]],
    tool_selector: ToolSelectorModel | None,
    mode: str,
) -> dict[str, Any]:
    """Measure per-operation latencies across all prediction types."""
    metrics: dict[str, list[float]] = {
        "intent": [],
        "tool_selection": [],
    }

    # Reset model cache once, not per-sample.
    if mode == "micro_model":
        reset_model()

    for tc in test_cases:
        request = tc["request"]

        if mode == "micro_model":
            start = time.perf_counter()
            classify_intent(request)
            metrics["intent"].append((time.perf_counter() - start) * 1000)
        else:
            start = time.perf_counter()
            route(request)
            metrics["intent"].append((time.perf_counter() - start) * 1000)

        if mode == "micro_model" and tool_selector is not None:
            start = time.perf_counter()
            tool_selector.predict(request)
            metrics["tool_selection"].append((time.perf_counter() - start) * 1000)

    summary = {}
    for key, values in metrics.items():
        if values:
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            summary[key] = {
                "samples": n,
                "avg_ms": round(sum(sorted_vals) / n, 3),
                "min_ms": round(sorted_vals[0], 3),
                "max_ms": round(sorted_vals[-1], 3),
                "median_ms": round(sorted_vals[n // 2], 3),
                "p99_ms": round(sorted_vals[int(n * 0.99)], 3),
            }
        else:
            summary[key] = {"samples": 0, "note": "not measured in this mode"}
    return summary


def _detect_regressions(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compare current report against previous to detect regressions.

    Args:
        current: Current mode report dict.
        previous: Previous mode report dict, or None.
        thresholds: Metric → max allowed degradation. Defaults:
            accuracy: -0.05, pass_rate: -0.05, latency: +0.20 (20% slower)

    Returns:
        Dict with regressions found.
    """
    if previous is None:
        return {"found": False, "note": "No previous report to compare against", "items": []}

    thresholds = thresholds or {
        "accuracy": -0.05,
        "pass_rate": -0.05,
        "latency_pct": 0.20,
    }

    regressions: list[dict[str, Any]] = []

    for section in ("tool_selection", "intent_classification", "task_success"):
        for key in ("accuracy", "pass_rate", "avg_latency_ms"):
            cur_val = current.get(section, {}).get(key)
            prev_val = previous.get(section, {}).get(key)
            if cur_val is None or prev_val is None:
                continue
            if isinstance(cur_val, (int, float)) and isinstance(prev_val, (int, float)):
                if key in ("accuracy", "pass_rate"):
                    delta = cur_val - prev_val
                    if delta < thresholds.get(key, -0.05):
                        regressions.append({
                            "section": section,
                            "metric": key,
                            "previous": prev_val,
                            "current": cur_val,
                            "delta": round(delta, 4),
                            "threshold": thresholds.get(key, -0.05),
                            "severity": "regression",
                        })

    for section in ("latency",):
        for op_key, op_vals in current.get(section, {}).items():
            prev_vals = previous.get(section, {}).get(op_key, {})
            if not op_vals or not prev_vals:
                continue
            cur_avg = op_vals.get("avg_ms")
            prev_avg = prev_vals.get("avg_ms")
            if cur_avg and prev_avg and prev_avg > 0:
                pct_change = (cur_avg - prev_avg) / prev_avg
                if pct_change > thresholds.get("latency_pct", 0.20):
                    regressions.append({
                        "section": f"latency.{op_key}",
                        "metric": "avg_ms",
                        "previous": prev_avg,
                        "current": cur_avg,
                        "pct_change": round(pct_change, 4),
                        "threshold": thresholds.get("latency_pct", 0.20),
                        "severity": "performance_regression",
                    })

    return {
        "found": len(regressions) > 0,
        "count": len(regressions),
        "items": regressions,
    }


# ── Report helpers ────────────────────────────────────────────────────────────


def _load_previous_report(output_dir: str | Path) -> dict[str, Any] | None:
    """Load the latest benchmark report for regression comparison."""
    path = Path(output_dir) / "intelligence_benchmark_latest.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load previous report: %s", e)
        return None


def _save_report(
    report: dict[str, Any],
    output_dir: str | Path,
    suffix: str = "",
) -> Path:
    """Save report to disk and update the 'latest' symlink copy."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"intelligence_benchmark_{timestamp}{suffix}.json"
    path = output_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Saved report to %s", path)

    latest = output_dir / "intelligence_benchmark_latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Updated latest report at %s", latest)

    return path


# ── Mode runner ───────────────────────────────────────────────────────────────


def run_mode(
    dataset: dict[str, Any],
    config: BenchmarkConfig,
    mode: str,
    previous_report: dict[str, Any] | None = None,
) -> ModeReport:
    """Run the full benchmark for a single mode."""
    report = ModeReport(mode=mode, timestamp=datetime.now(UTC).isoformat())
    logger.info("=" * 60)
    logger.info("Running benchmark in '%s' mode", mode)
    logger.info("=" * 60)

    tool_selector = _load_tool_selector(config.models_dir) if mode == "micro_model" else None

    # 1. Tool selection.
    ts_cases = dataset.get("tool_selection", [])
    if ts_cases:
        logger.info("Running tool selection benchmark (%d cases)...", len(ts_cases))
        report.tool_selection = _run_tool_selection_benchmark(ts_cases, tool_selector, mode)
        logger.info("  Accuracy: %.2f%%", report.tool_selection.get("accuracy", 0) * 100)

    # 2. Intent classification.
    all_cases = ts_cases + dataset.get("regression", [])
    seen_requests: set[str] = set()
    unique_cases: list[dict[str, Any]] = []
    for tc in all_cases:
        req = tc.get("request", "")
        if req and req not in seen_requests:
            seen_requests.add(req)
            unique_cases.append(tc)
    if unique_cases:
        logger.info("Running intent classification benchmark (%d unique requests)...", len(unique_cases))
        report.intent_classification = _run_intent_benchmark(unique_cases, mode)
        logger.info("  Accuracy: %.2f%%", report.intent_classification.get("accuracy", 0) * 100)

    # 3. Task success.
    task_cases = dataset.get("task_success", [])
    if task_cases:
        logger.info("Running task success benchmark (%d cases, skip=%s)...",
                    len(task_cases), config.skip_task_success)
        report.task_success = _run_task_success_benchmark(task_cases, skip=config.skip_task_success)
        if report.task_success.get("available", False):
            logger.info("  Pass rate: %.2f%%", report.task_success.get("pass_rate", 0) * 100)

    # 4. Latency.
    if unique_cases:
        logger.info("Running latency measurements (%d samples)...", len(unique_cases))
        report.latency = _run_latency_benchmark(unique_cases, tool_selector, mode)
        for op, vals in report.latency.items():
            if vals.get("samples", 0) > 0:
                logger.info("  %s: avg=%.3fms (n=%d)", op, vals["avg_ms"], vals["samples"])

    # 5. Regression detection.
    if previous_report is not None:
        prev_mode = previous_report.get(mode)
        if prev_mode:
            logger.info("Detecting regressions against previous run...")
            report.regression = _detect_regressions(report.to_dict(), prev_mode)
            if report.regression.get("found", False):
                logger.warning("  Found %d regression(s)!", report.regression["count"])
                for item in report.regression["items"]:
                    logger.warning("    %s: %s %s->%s",
                                   item["section"], item["metric"],
                                   item["previous"], item["current"])
            else:
                logger.info("  No regressions detected.")
        else:
            report.regression = {"found": False, "note": f"No previous '{mode}' mode data available", "items": []}

    return report


# ── Main orchestration ────────────────────────────────────────────────────────


def run_benchmark(config: BenchmarkConfig | None = None) -> ComparisonReport:
    """Run the full intelligence benchmark (micro-model + baseline comparison).

    Args:
        config: Benchmark configuration. Uses defaults if None.

    Returns:
        A ComparisonReport with both mode reports and delta analysis.
    """
    if config is None:
        config = BenchmarkConfig()

    dataset = load_dataset(config.dataset_path)
    previous_report = _load_previous_report(config.output_dir)

    # Run both modes.
    mm_report = run_mode(dataset, config, mode="micro_model", previous_report=previous_report)
    baseline_report = run_mode(dataset, config, mode="baseline", previous_report=previous_report)

    # Build delta comparison.
    delta: dict[str, Any] = {}

    for section in ("tool_selection", "intent_classification", "task_success"):
        mm = mm_report.to_dict().get(section, {})
        bl = baseline_report.to_dict().get(section, {})

        if section == "task_success":
            mm_pass = mm.get("pass_rate", 0)
            bl_pass = bl.get("pass_rate", 0)
            if not mm.get("available", False) and not bl.get("available", False):
                delta[section] = {"note": "task success tests skipped (no LLM)"}
            else:
                delta[section] = {
                    "pass_rate_delta": round(mm_pass - bl_pass, 4),
                }
        else:
            mm_acc = mm.get("accuracy", 0)
            bl_acc = bl.get("accuracy", 0)
            delta[section] = {
                "accuracy_delta": round(mm_acc - bl_acc, 4),
            }

    # Latency delta.
    mm_lat = mm_report.to_dict().get("latency", {})
    bl_lat = baseline_report.to_dict().get("latency", {})
    latency_delta: dict[str, Any] = {}
    for op in mm_lat:
        mm_avg = mm_lat[op].get("avg_ms", 0)
        bl_avg = bl_lat.get(op, {}).get("avg_ms", 0)
        if mm_avg and bl_avg:
            latency_delta[op] = {
                "micro_model_avg_ms": mm_avg,
                "baseline_avg_ms": bl_avg,
                "delta_ms": round(mm_avg - bl_avg, 3),
                "delta_pct": round((mm_avg - bl_avg) / bl_avg * 100, 1),
            }
        elif mm_avg and not bl_avg:
            latency_delta[op] = {"micro_model_avg_ms": mm_avg, "note": "baseline not measured"}
    delta["latency"] = latency_delta

    return ComparisonReport(
        micro_model=mm_report.to_dict(),
        baseline=baseline_report.to_dict(),
        delta=delta,
    )


def print_comparison(report: ComparisonReport) -> None:
    """Print a human-readable comparison report."""
    mm = report.micro_model
    bl = report.baseline
    delta = report.delta

    lines = [
        "=" * 66,
        "INTELLIGENCE BENCHMARK — PHASE 11.5",
        "=" * 66,
        f"  Micro-model mode:  {mm.get('timestamp', '?')[:19]}",
        f"  Baseline mode:     {bl.get('timestamp', '?')[:19]}",
        "",
    ]

    for section, label in [
        ("tool_selection", "Tool Selection"),
        ("intent_classification", "Intent Classification"),
        ("task_success", "Task Success"),
    ]:
        mm_s = mm.get(section, {})
        bl_s = bl.get(section, {})
        d = delta.get(section, {})

        lines.append(f"-- {label} {'-' * (55 - len(label))}")

        if section == "task_success":
            for mode_name, mode_s in [("Micro-model", mm_s), ("Baseline", bl_s)]:
                avail = mode_s.get("available", False)
                if avail:
                    lines.append(f"  {mode_name}:     {mode_s.get('passed', 0)}/{mode_s.get('total', 0)} passed  "
                                 f"({mode_s.get('pass_rate', 0):.2%})  "
                                 f"avg={mode_s.get('avg_duration_ms', 0):.0f}ms")
                else:
                    lines.append(f"  {mode_name}:     SKIPPED (no LLM)")
            if d:
                lines.append(f"  Delta:         {d.get('pass_rate_delta', 'N/A')}")

        else:
            for mode_name, mode_s in [("Micro-model", mm_s), ("Baseline", bl_s)]:
                lines.append(f"  {mode_name}:     {mode_s.get('correct', 0)}/{mode_s.get('total', 0)} correct  "
                             f"({mode_s.get('accuracy', 0):.2%})  "
                             f"avg={mode_s.get('avg_latency_ms', 0):.3f}ms")
            if d:
                acc_delta = d.get("accuracy_delta", "N/A")
                arrow = "+" if isinstance(acc_delta, (int, float)) and acc_delta >= 0 else "-"
                lines.append(f"  Delta:         {arrow} {acc_delta}")

    lines.append("")
    lines.append("-- Latency Comparison ---------------------------------------------")
    lat_d = delta.get("latency", {})
    if lat_d:
        lines.append(f"  {'Operation':<25} {'Micro':>9} {'Baseline':>9} {'Delta':>9} {'%':>7}")
        lines.append("  " + "-" * 61)
        for op, vals in sorted(lat_d.items()):
            mm_avg = vals.get("micro_model_avg_ms")
            bl_avg = vals.get("baseline_avg_ms")
            d_ms = vals.get("delta_ms")
            d_pct = vals.get("delta_pct")
            if mm_avg is not None and bl_avg is not None and d_ms is not None:
                d_pct_s = f"{d_pct:+.1f}%" if isinstance(d_pct, float) else "?"
                lines.append(f"  {op:<25} {mm_avg:>9.3f} {bl_avg:>9.3f} {d_ms:>9.3f} {d_pct_s:>7}")
            else:
                lines.append(f"  {op:<25} {'N/A':>9} {'N/A':>9} {'N/A':>9} {'N/A':>7}")
    else:
        lines.append("  (no comparable latency data)")

    lines.append("")
    lines.append("-- Regression Check -----------------------------------------------")
    for mode_name in ("micro_model", "baseline"):
        reg = (mm if mode_name == "micro_model" else bl).get("regression", {})
        if reg.get("found", False):
            lines.append(f"  {mode_name}: {reg['count']} regression(s) detected!")
            for item in reg["items"]:
                lines.append(f"    !! {item['section']}.{item['metric']}: "
                             f"{item['previous']} -> {item['current']}")
        else:
            lines.append(f"  {mode_name}: {reg.get('note', 'No regressions')}")

    lines.append("")
    lines.append("=" * 66)
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 11.5 Intelligence Benchmark")
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(DEFAULT_DATASET),
        help=f"Path to benchmark dataset JSON (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(REPORTS_DIR),
        help=f"Output directory for reports (default: {REPORTS_DIR})",
    )
    parser.add_argument(
        "--skip-task-success",
        action="store_true",
        default=True,
        help="Skip agent-based task success tests (default: true, no LLM)",
    )
    parser.add_argument(
        "--no-skip-task-success",
        action="store_false",
        dest="skip_task_success",
        help="Enable task success tests (requires working LLM)",
    )
    args = parser.parse_args()

    config = BenchmarkConfig(
        dataset_path=args.dataset,
        output_dir=args.output,
        skip_task_success=args.skip_task_success,
    )

    report = run_benchmark(config)
    print_comparison(report)

    # Save full report.
    full_output = {
        "micro_model": report.micro_model,
        "baseline": report.baseline,
        "delta": report.delta,
    }
    _save_report(full_output, config.output_dir)
    print(f"\nFull report saved to: {Path(config.output_dir) / 'intelligence_benchmark_latest.json'}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    main()
