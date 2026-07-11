"""Micro-model benchmark — compares heuristic routing vs micro-model routing.

Measures:
  - Routing accuracy (intent classification vs heuristic baseline)
  - Tool selection accuracy (tool selector vs heuristic mapping)
  - LLM call avoidance (requests handled without LLM fallback)
  - Latency improvement (micro-model vs LLM-based routing)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paios.config import DATA_DIR, get_settings
from paios.intelligence.intent.dataset import CATEGORY_TO_DOMAIN, CATEGORY_TO_MODE, IntentDataset
from paios.intelligence.intent.inference import ClassifierResult, classify_intent, reset_model
from paios.intelligence.tool_selector.dataset import ToolSelectionDataset
from paios.intelligence.tool_selector.model import ToolSelectorModel
from paios.llm.micro.router import route

logger = logging.getLogger(__name__)

EVAL_DATA_DIR = DATA_DIR / "eval_data"


@dataclass
class BenchmarkResult:
    """Single benchmark measurement."""

    category: str
    micro_model_category: str
    heuristic_category: str
    micro_model_confidence: float
    micro_model_match: bool
    heuristic_match: bool
    micro_model_latency_ms: float
    heuristic_latency_ms: float
    micro_model_avoids_llm: bool
    expected_tools: list[str] = field(default_factory=list)
    predicted_tools: list[str] = field(default_factory=list)
    tool_selection_match: bool = False


@dataclass
class BenchmarkReport:
    """Aggregated benchmark results."""

    total: int = 0
    micro_model_accuracy: float = 0.0
    heuristic_accuracy: float = 0.0
    micro_model_faster: bool = False
    avg_micro_model_latency_ms: float = 0.0
    avg_heuristic_latency_ms: float = 0.0
    llm_calls_avoided: int = 0
    llm_call_savings_pct: float = 0.0
    tool_selection_precision: float = 0.0
    tool_selection_recall: float = 0.0
    per_category: dict[str, dict[str, Any]] = field(default_factory=dict)


class MicroModelBenchmark:
    """Compare micro-model routing against heuristic baseline."""

    def __init__(self) -> None:
        self.results: list[BenchmarkResult] = []

    def _run_intent_comparison(
        self, dataset: IntentDataset
    ) -> None:
        """Compare micro-model and heuristic routing on an intent dataset."""
        for ex in dataset.examples:
            text = ex["text"]
            expected = ex["intent"]

            # Micro-model classification.
            reset_model()
            start = time.perf_counter()
            mm_result: ClassifierResult = classify_intent(text)
            mm_latency = (time.perf_counter() - start) * 1000

            mm_category = mm_result.category
            mm_confidence = mm_result.confidence
            mm_avoids_llm = not mm_result.requires_llm

            # Heuristic routing.
            start = time.perf_counter()
            heuristic_intent = route(text)
            heuristic_latency = (time.perf_counter() - start) * 1000

            heuristic_category = heuristic_intent.intent_category or "unknown"
            if heuristic_category == "unknown":
                heuristic_category = self._heuristic_intent_from_domain(heuristic_intent.domain)

            # Expected tools based on category.
            expected_tools = self._category_to_expected_tools(expected)

            self.results.append(BenchmarkResult(
                category=expected,
                micro_model_category=mm_category,
                heuristic_category=heuristic_category,
                micro_model_confidence=mm_confidence,
                micro_model_match=mm_category == expected,
                heuristic_match=heuristic_category == expected,
                micro_model_latency_ms=round(mm_latency, 3),
                heuristic_latency_ms=round(heuristic_latency, 3),
                micro_model_avoids_llm=mm_avoids_llm,
                expected_tools=expected_tools,
            ))

    def _run_tool_selection_comparison(
        self, dataset: ToolSelectionDataset
    ) -> None:
        """Compare tool selector predictions against expected tools."""
        try:
            model = ToolSelectorModel()
            model_path = DATA_DIR / "models" / "tool_selector.pkl"
            if not model_path.exists():
                logger.warning("tool selector model not found at %s", model_path)
                return
            model.load(str(model_path))
        except Exception as e:
            logger.warning("failed to load tool selector model: %s", e)
            return

        for ex in dataset.examples:
            start = time.perf_counter()
            predicted = model.predict(ex.text)
            _latency = (time.perf_counter() - start) * 1000  # noqa: F841

            expected_set = set(ex.expected_tools)
            predicted_set = set(predicted)
            match = predicted_set == expected_set

            # Update the matching result.
            for r in self.results:
                if r.category == ex.intent_category:
                    r.predicted_tools = predicted
                    r.tool_selection_match = match
                    break

    def _heuristic_intent_from_domain(self, domain: str) -> str:
        """Map heuristic router domain back to intent category."""
        domain_map = {
            "system": "system_management",
            "filesystem": "file_operation",
            "terminal": "tool_execution",
            "project": "project_analysis",
        }
        return domain_map.get(domain, "conversation")

    def _category_to_expected_tools(self, category: str) -> list[str]:
        """Map intent category to expected tools."""
        mapping = {
            "file_operation": ["filesystem_read"],
            "system_management": ["system_monitor"],
            "tool_execution": ["terminal"],
            "project_analysis": ["project_analyzer"],
        }
        return mapping.get(category, [])

    def run(
        self,
        intent_test_size: int = 200,
        tool_selector_test_size: int = 100,
    ) -> BenchmarkReport:
        """Run the full benchmark."""
        logger.info("=" * 60)
        logger.info("Running micro-model benchmark")
        logger.info("=" * 60)

        # Generate test datasets (using a fixed seed for reproducibility).
        intent_dataset = IntentDataset.generate_expanded(target_per_category=20, seed=99)
        _, intent_test = intent_dataset.train_test_split(test_ratio=0.5, seed=99)
        # Trim to requested size.
        import random
        rng = random.Random(99)
        intent_indices = list(range(len(intent_test)))
        rng.shuffle(intent_indices)
        intent_test = IntentDataset(
            [intent_test[i] for i in intent_indices[:intent_test_size]]
        )

        ts_dataset = ToolSelectionDataset.generate_expanded(target=500, seed=99)
        ts_indices = list(range(len(ts_dataset)))
        rng.shuffle(ts_indices)
        ts_test = ToolSelectionDataset(
            [ts_dataset[i] for i in ts_indices[:tool_selector_test_size]]
        )

        self._run_intent_comparison(intent_test)
        self._run_tool_selection_comparison(ts_test)

        return self._generate_report()

    def _generate_report(self) -> BenchmarkReport:
        """Aggregate results into a report."""
        n = len(self.results)
        if n == 0:
            return BenchmarkReport()

        mm_correct = sum(1 for r in self.results if r.micro_model_match)
        heuristic_correct = sum(1 for r in self.results if r.heuristic_match)
        llm_avoided = sum(1 for r in self.results if r.micro_model_avoids_llm)
        mm_latencies = [r.micro_model_latency_ms for r in self.results]
        heuristic_latencies = [r.heuristic_latency_ms for r in self.results]

        tool_matches = sum(1 for r in self.results if r.tool_selection_match)
        tool_total = sum(1 for r in self.results if r.expected_tools)

        per_category: dict[str, dict[str, Any]] = {}
        for r in self.results:
            if r.category not in per_category:
                per_category[r.category] = {"total": 0, "mm_correct": 0, "heuristic_correct": 0}
            per_category[r.category]["total"] += 1
            if r.micro_model_match:
                per_category[r.category]["mm_correct"] += 1
            if r.heuristic_match:
                per_category[r.category]["heuristic_correct"] += 1

        for cat, d in per_category.items():
            d["mm_accuracy"] = round(d["mm_correct"] / d["total"], 4) if d["total"] > 0 else 0.0
            d["heuristic_accuracy"] = round(d["heuristic_correct"] / d["total"], 4) if d["total"] > 0 else 0.0

        report = BenchmarkReport(
            total=n,
            micro_model_accuracy=round(mm_correct / n, 4),
            heuristic_accuracy=round(heuristic_correct / n, 4),
            micro_model_faster=sum(mm_latencies) < sum(heuristic_latencies),
            avg_micro_model_latency_ms=round(sum(mm_latencies) / n, 3),
            avg_heuristic_latency_ms=round(sum(heuristic_latencies) / n, 3),
            llm_calls_avoided=llm_avoided,
            llm_call_savings_pct=round(llm_avoided / n * 100, 1),
            tool_selection_precision=round(tool_matches / tool_total, 4) if tool_total > 0 else 0.0,
            tool_selection_recall=0.0,
            per_category=per_category,
        )

        return report

    @staticmethod
    def print_report(report: BenchmarkReport) -> str:
        """Format benchmark report as a string."""
        lines = [
            "=" * 60,
            "MICRO-MODEL BENCHMARK REPORT",
            "=" * 60,
            f"Total samples: {report.total}",
            "",
            "--- Routing Accuracy ---",
            f"  Micro-model intent accuracy:  {report.micro_model_accuracy:.2%}",
            f"  Heuristic router accuracy:    {report.heuristic_accuracy:.2%}",
            f"  Micro-model wins:             {'YES' if report.micro_model_accuracy > report.heuristic_accuracy else 'NO'}",
            "",
            "--- Latency ---",
            f"  Micro-model avg latency:      {report.avg_micro_model_latency_ms:.3f}ms",
            f"  Heuristic router avg latency: {report.avg_heuristic_latency_ms:.3f}ms",
            f"  Micro-model faster overall:   {'YES' if report.micro_model_faster else 'NO'}",
            "",
            "--- LLM Efficiency ---",
            f"  LLM calls avoided:            {report.llm_calls_avoided} / {report.total} ({report.llm_call_savings_pct:.1f}%)",
            "",
            "--- Tool Selection ---",
            f"  Precision:                    {report.tool_selection_precision:.2%}",
            "",
            "--- Per-Category ---",
        ]

        for cat, d in sorted(report.per_category.items()):
            lines.append(
                f"  {cat:25s}  mm={d['mm_accuracy']:.2%}  heuristic={d['heuristic_accuracy']:.2%}  "
                f"({d['mm_correct']}/{d['total']})"
            )

        lines.append("=" * 60)
        return "\n".join(lines)

    @staticmethod
    def save_report(report: BenchmarkReport, path: str | Path | None = None) -> Path:
        """Save benchmark report as JSON."""
        output_path = Path(path) if path else (DATA_DIR / "models" / "benchmark_report.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "total": report.total,
            "micro_model_accuracy": report.micro_model_accuracy,
            "heuristic_accuracy": report.heuristic_accuracy,
            "avg_micro_model_latency_ms": report.avg_micro_model_latency_ms,
            "avg_heuristic_latency_ms": report.avg_heuristic_latency_ms,
            "llm_calls_avoided": report.llm_calls_avoided,
            "llm_call_savings_pct": report.llm_call_savings_pct,
            "tool_selection_precision": report.tool_selection_precision,
            "per_category": report.per_category,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("benchmark report saved to %s", output_path)
        return output_path
