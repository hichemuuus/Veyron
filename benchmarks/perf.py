"""Phase 6 Objective 3: Performance measurement.

Measures critical path latencies to identify optimization targets.
Run with: python -m benchmarks.perf
"""

from __future__ import annotations

import time
from pathlib import Path
from statistics import mean, median, stdev

from paios.core.planner import Plan, PlanStep, Planner
from paios.memory.store import get_memory_store, reset_memory_store
from paios.security.command_policy import classify_command
from paios.security.path_policy import validate_path
from paios.security.policy import classify_risk


def _measure(label: str, fn, iterations: int = 100, warmup: int = 10) -> dict:
    """Measure min/avg/median/max/p99 of a function call."""
    # Warmup
    for _ in range(warmup):
        fn()

    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)  # ms

    sorted_times = sorted(times)
    p99_idx = int(len(sorted_times) * 0.99)
    return {
        "label": label,
        "min_ms": round(min(times), 4),
        "max_ms": round(max(times), 4),
        "avg_ms": round(mean(times), 4),
        "median_ms": round(median(times), 4),
        "p99_ms": round(sorted_times[p99_idx], 4),
        "stdev_ms": round(stdev(times), 4) if len(times) > 1 else 0,
        "iterations": iterations,
    }


def measure_security() -> list[dict]:
    results = []

    results.append(_measure(
        "security.classify_command (free)",
        lambda: classify_command("ls -la /home/user"),
        iterations=200,
    ))

    results.append(_measure(
        "security.classify_command (restricted)",
        lambda: classify_command("rm -rf /"),
        iterations=200,
    ))

    results.append(_measure(
        "security.classify_command (metachar)",
        lambda: classify_command("cat file && echo done"),
        iterations=200,
    ))

    results.append(_measure(
        "security.classify_risk",
        lambda: classify_risk("terminal", {"command": "ls"}),
        iterations=200,
    ))

    return results


def measure_memory() -> list[dict]:
    from paios.db.base import init_db, reset_sync_engine
    from paios import config as config_module
    import tempfile

    # Isolate DB with a temp directory
    tmp = tempfile.mkdtemp()
    orig_data_dir = config_module.DATA_DIR
    config_module.DATA_DIR = Path(tmp)

    reset_sync_engine()
    init_db()
    store = get_memory_store()

    # Pre-store some data
    for i in range(50):
        store.store(category="history", content=f"performance test memory item number {i}", importance=0.5)

    results = []

    results.append(_measure(
        "memory.store",
        lambda: store.store(category="history", content="new performance measurement item", importance=0.5),
        iterations=50,
    ))

    results.append(_measure(
        "memory.search (empty)",
        lambda: store.search(""),
        iterations=100,
    ))

    results.append(_measure(
        "memory.search (specific)",
        lambda: store.search("performance test"),
        iterations=100,
    ))

    results.append(_measure(
        "memory.get",
        lambda: store.get("nonexistent-public-id-for-perf-measurement"),
        iterations=100,
    ))

    results.append(_measure(
        "memory.count",
        lambda: store.count(),
        iterations=100,
    ))

    reset_memory_store()
    config_module.DATA_DIR = orig_data_dir
    return results


def measure_planner() -> list[dict]:
    planner = Planner()
    results = []

    valid_plan = Plan(
        request="test performance",
        steps=[
            PlanStep(id="s1", goal="Check CPU", suggested_tool="system_monitor"),
            PlanStep(id="s2", goal="Check memory", suggested_tool="system_monitor", depends_on=["s1"]),
            PlanStep(id="s3", goal="Analyze", depends_on=["s2"]),
        ],
    )

    results.append(_measure(
        "planner.validate (valid)",
        lambda: planner._validate_plan(valid_plan),
        iterations=200,
    ))

    circular_plan = Plan(
        request="test",
        steps=[
            PlanStep(id="a", goal="A", depends_on=["b"]),
            PlanStep(id="b", goal="B", depends_on=["c"]),
            PlanStep(id="c", goal="C", depends_on=["a"]),
        ],
    )

    results.append(_measure(
        "planner.validate (circular)",
        lambda: planner._validate_plan(circular_plan),
        iterations=200,
    ))

    results.append(_measure(
        "planner.score",
        lambda: planner._score_plan(valid_plan),
        iterations=200,
    ))

    return results


def print_results(results: list[dict]) -> None:
    """Print performance results as a table."""
    print(f"{'Measurement':<45} {'Min':>8} {'Avg':>8} {'Median':>8} {'P99':>8} {'Max':>8}")
    print("-" * 93)
    for r in results:
        print(
            f"{r['label']:<45} {r['min_ms']:>8.4f} {r['avg_ms']:>8.4f} "
            f"{r['median_ms']:>8.4f} {r['p99_ms']:>8.4f} {r['max_ms']:>8.4f}"
        )
    print()


def main() -> None:
    print("=" * 93)
    print("PAIOS Performance Measurement")
    print("=" * 93)
    print()
    print("Security module...")
    results = measure_security()
    print_results(results)

    print("Memory module...")
    mem_results = measure_memory()
    print_results(mem_results)

    print("Planner module...")
    plan_results = measure_planner()
    print_results(plan_results)

    all_results = results + mem_results + plan_results
    print("=" * 93)
    print("Done. Measured %d operations." % len(all_results))
    print("=" * 93)


if __name__ == "__main__":
    main()
