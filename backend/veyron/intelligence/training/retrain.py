"""Automatic retraining preparation — scheduler-ready architecture.

Provides:
  - TrainingTrigger: interface for triggering conditions
  - DatasetGrowthDetector: monitors new example count
  - BenchmarkComparator: compares candidate vs production before promotion
  - RetrainingOrchestrator: coordinates the full flow
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from veyron.config import DATA_DIR, get_settings
from veyron.db.base import sync_session_scope
from veyron.db.models import LearningEvent
from veyron.intelligence.models.registry import ModelRegistry
from veyron.intelligence.models.schema import (
    STATUS_CANDIDATE,
    ModelMetadata,
)
from veyron.intelligence.training.dataset import TrainingDataset
from veyron.intelligence.training.trainer_v2 import TrainingPipelineV2

logger = logging.getLogger(__name__)

REPORTS_DIR = DATA_DIR / "reports"
USER_INTERACTIONS_DIR = DATA_DIR / "training" / "user_interactions"


class TrainingTrigger(ABC):
    """Interface for retraining trigger conditions."""

    @abstractmethod
    def should_trigger(self) -> bool:
        ...

    @abstractmethod
    def describe(self) -> str:
        ...


@dataclass
class NewExampleTrigger(TrainingTrigger):
    """Triggers when new user interaction examples exceed a threshold."""

    min_new_examples: int = 100
    _last_count: int = 0

    def should_trigger(self) -> bool:
        current = self._count_interaction_files()
        new_count = current - self._last_count
        if new_count >= self.min_new_examples:
            self._last_count = current
            return True
        return False

    def describe(self) -> str:
        return f"new_example_threshold={self.min_new_examples}"

    @staticmethod
    def _count_interaction_files() -> int:
        if not USER_INTERACTIONS_DIR.exists():
            return 0
        return len(list(USER_INTERACTIONS_DIR.glob("*.jsonl")))

    def update_last_count(self) -> None:
        self._last_count = self._count_interaction_files()


class DatasetGrowthDetector:
    """Detects whether the training dataset has grown enough to justify retraining."""

    def __init__(self, min_growth_pct: float = 10.0) -> None:
        self.min_growth_pct = min_growth_pct

    def should_retrain(
        self,
        current_dataset_size: int,
        last_training_size: int,
    ) -> bool:
        if last_training_size <= 0:
            return current_dataset_size > 0
        growth = (current_dataset_size - last_training_size) / last_training_size * 100
        logger.debug(
            "dataset growth: %d -> %d (%.1f%%)",
            last_training_size, current_dataset_size, growth,
        )
        return growth >= self.min_growth_pct


class BenchmarkComparator:
    """Compares candidate model against production model before promotion."""

    def __init__(self) -> None:
        self.pipeline = TrainingPipelineV2()

    def compare(
        self,
        candidate_metrics: dict[str, float],
        production_metrics: dict[str, float] | None,
        model_type: str,
    ) -> BenchmarkComparisonResult:
        if production_metrics is None:
            return BenchmarkComparisonResult(
                is_better=True,
                reason="no production model to compare against",
                deltas={k: v for k, v in candidate_metrics.items()},
            )

        deltas: dict[str, float] = {}
        all_better_or_equal = True
        details: list[str] = []

        for key, candidate_val in candidate_metrics.items():
            prod_val = production_metrics.get(key, 0.0)
            delta = candidate_val - prod_val
            deltas[key] = round(delta, 4)

            higher_is_better = key not in ("latency_ms", "error_rate")
            if higher_is_better:
                if delta > 0:
                    details.append(f"{key}: +{delta:.4f}")
                elif delta < 0:
                    all_better_or_equal = False
                    details.append(f"{key}: {delta:.4f} (worse)")
            else:
                if delta < 0:
                    details.append(f"{key}: {delta:.4f} (improved)")
                elif delta > 0:
                    all_better_or_equal = False
                    details.append(f"{key}: +{delta:.4f} (worse)")

        return BenchmarkComparisonResult(
            is_better=all_better_or_equal,
            reason="; ".join(details) if details else "all metrics equal",
            deltas=deltas,
        )

    # ── Benchmark type support ──────────────────────────────────────────

    # Mapping of benchmark types to their expected metric keys.
    BENCHMARK_TYPE_METRICS: dict[str, list[str]] = {
        "reflection_quality": ["relevance", "coherence", "actionability"],
        "memory_quality": ["precision", "recall", "mrr"],
        "skill_detection": ["precision", "recall", "f1"],
        "workflow_prediction": ["accuracy", "step_completion", "efficiency"],
    }

    def compare_benchmark_type(
        self,
        candidate_metrics: dict[str, float],
        production_metrics: dict[str, float] | None,
        benchmark_type: str,
    ) -> BenchmarkComparisonResult:
        """Compare candidate vs production for a specific benchmark type."""
        expected = self.BENCHMARK_TYPE_METRICS.get(
            benchmark_type, list(candidate_metrics.keys())
        )
        filtered_candidate = {
            k: candidate_metrics[k] for k in expected if k in candidate_metrics
        }
        filtered_production = {
            k: production_metrics[k]
            for k in expected
            if production_metrics and k in production_metrics
        }
        return self.compare(
            filtered_candidate, filtered_production or None, benchmark_type,
        )


@dataclass
class BenchmarkComparisonResult:
    is_better: bool
    reason: str
    deltas: dict[str, float] = field(default_factory=dict)


@dataclass
class DatasetQualityInfo:
    """Quality assessment for a training dataset."""

    total_examples: int = 0
    unique_examples: int = 0
    duplicate_count: int = 0
    avg_confidence: float = 0.0
    label_distribution: dict[str, int] = field(default_factory=dict)
    suggested_actions: list[str] = field(default_factory=list)


class RetrainingOrchestrator:
    """Coordinates the full retraining flow: trigger -> validate -> train -> benchmark -> promote."""

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        trigger: TrainingTrigger | None = None,
        growth_detector: DatasetGrowthDetector | None = None,
        comparator: BenchmarkComparator | None = None,
    ) -> None:
        self.registry = registry or ModelRegistry()
        self.trigger = trigger
        self.growth_detector = growth_detector or DatasetGrowthDetector()
        self.comparator = comparator or BenchmarkComparator()
        self.pipeline = TrainingPipelineV2()

    def prepare_retrain(
        self,
        dataset: TrainingDataset,
        model_type: str = "intent_classifier",
        force: bool = False,
    ) -> RetrainPlan:
        """Prepare a retraining plan without executing it. Analyzes conditions and returns a plan."""
        production_md = self.registry.get_production(model_type)
        current_size = len(dataset)

        trigger_ready = True
        if self.trigger and not force:
            trigger_ready = self.trigger.should_trigger()

        last_size = production_md.dataset_size if production_md else 0
        growth_ready = self.growth_detector.should_retrain(current_size, last_size) or force

        issues: list[str] = []
        if not trigger_ready:
            issues.append(f"trigger not satisfied ({self.trigger.describe()})" if self.trigger else "")
        if not growth_ready:
            issues.append(f"insufficient growth ({current_size} vs {last_size})")

        ready = (trigger_ready or self.trigger is None) and growth_ready

        return RetrainPlan(
            ready=ready,
            model_type=model_type,
            current_dataset_size=current_size,
            last_training_size=last_size,
            production_version=production_md.version if production_md else None,
            production_metrics=production_md.metrics if production_md else None,
            issues=issues,
            force=force,
        )

    def execute_retrain(
        self,
        dataset: TrainingDataset,
        model_type: str = "intent_classifier",
        force: bool = False,
    ) -> RetrainResult:
        """Execute a full retrain cycle: train -> benchmark -> promote if better."""
        plan = self.prepare_retrain(dataset, model_type, force=force)
        if not plan.ready and not force:
            return RetrainResult(success=False, plan=plan, error="retrain not ready")

        # Train candidate model.
        try:
            if model_type == "intent_classifier":
                model, report = self.pipeline.train_intent(dataset)
                candidate_metrics = {
                    "accuracy": report.accuracy,
                    "macro_f1": report.macro_f1,
                }
            elif model_type == "tool_selector":
                model, report = self.pipeline.train_tool_selector(dataset)
                candidate_metrics = {
                    "precision_at_1": report.precision_at_1,
                    "recall_at_3": report.recall_at_3,
                }
            elif model_type == "memory_retrieval":
                from veyron.intelligence.memory_retrieval.dataset import MemoryRetrievalDataset
                mr_dataset = dataset if isinstance(dataset, MemoryRetrievalDataset) else MemoryRetrievalDataset.generate_synthetic()
                model, metrics = self.pipeline.train_memory_retrieval(dataset=mr_dataset)
                candidate_metrics = {
                    "mrr": metrics.get("mrr", 0.0),
                    "precision@1": metrics.get("precision@1", 0.0),
                    "recall@3": metrics.get("recall@3", 0.0),
                }
            elif model_type == "intent_router":
                from veyron.intelligence.intent_router.dataset import IntentRouterDataset
                ir_dataset = dataset if isinstance(dataset, IntentRouterDataset) else IntentRouterDataset.from_synthetic()
                model, metrics = self.pipeline.train_intent_router(dataset=ir_dataset)
                candidate_metrics = {
                    "mode_accuracy": metrics.get("mode_accuracy", 0.0),
                    "domain_accuracy": metrics.get("domain_accuracy", 0.0),
                    "intent_accuracy": metrics.get("intent_accuracy", 0.0),
                }
            else:
                return RetrainResult(success=False, plan=plan, error=f"unknown model_type: {model_type}")
        except Exception as e:
            logger.error("training failed: %s", e)
            return RetrainResult(success=False, plan=plan, error=f"training failed: {e}")

        # Compare against production.
        comparison = self.comparator.compare(
            candidate_metrics, plan.production_metrics, model_type,
        )

        if not comparison.is_better:
            if not force:
                return RetrainResult(
                    success=False,
                    plan=plan,
                    error=f"candidate not better: {comparison.reason}",
                    candidate_metrics=candidate_metrics,
                    comparison=comparison,
                )
            # force=True, but honour the never-deploy-weaker policy.
            if get_settings().model.never_deploy_weaker:
                return RetrainResult(
                    success=False,
                    plan=plan,
                    error=(
                        f"candidate not better and never_deploy_weaker is enabled"
                        f" (force ignored): {comparison.reason}"
                    ),
                    candidate_metrics=candidate_metrics,
                    comparison=comparison,
                )

        # Save candidate and register.
        version = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        if model_type == "memory_retrieval":
            model_path = str(DATA_DIR / "models" / f"memory_retrieval_{version}.pkl")
            model.save(model_path)
            latest = DATA_DIR / "models" / "memory_retrieval.pkl"
            if latest.exists():
                latest.unlink()
            import shutil
            shutil.copy(model_path, latest)
            model_path = str(latest)
        elif model_type == "intent_router":
            model_path = str(DATA_DIR / "models" / f"intent_router_{version}.pkl")
            model.save(model_path)
            latest = DATA_DIR / "models" / "intent_router.pkl"
            if latest.exists():
                latest.unlink()
            import shutil
            shutil.copy(model_path, latest)
            model_path = str(latest)
        else:
            saved = self.pipeline.save_models(
                model if model_type == "intent_classifier" else None,
                model if model_type == "tool_selector" else None,
            )
            model_path = str(saved.get(
                "intent_model" if model_type == "intent_classifier" else "tool_selector_model", ""
            ))

        metadata = ModelMetadata(
            name=f"{model_type}_v{version}",
            version=version,
            model_type=model_type,
            dataset_hash="",
            dataset_size=len(dataset),
            metrics=candidate_metrics,
            status=STATUS_CANDIDATE,
            path=model_path,
            parent_version=plan.production_version or "",
        )
        self.registry.register(metadata)

        return RetrainResult(
            success=True,
            plan=plan,
            candidate_metrics=candidate_metrics,
            comparison=comparison,
            metadata=metadata,
            model=model,
        )

    # ── Benchmark regression detection ──────────────────────────────────

    def detect_regressions(self, benchmark_history: list[dict]) -> list[dict]:
        """Compare the latest benchmark run against previous runs.

        Flags any metrics that regressed beyond a threshold (>5% drop).

        Args:
            benchmark_history: List of dicts, each containing at minimum
                ``metrics`` (or ``metrics_json``) and ``created_at`` keys.

        Returns:
            List of regression dicts with keys: metric, previous_avg,
            current, pct_change, threshold.
        """
        if len(benchmark_history) < 2:
            return []

        sorted_history = sorted(benchmark_history, key=lambda x: x.get("created_at", ""))
        latest = sorted_history[-1]
        previous = sorted_history[:-1]

        def _extract_metrics(run: dict) -> dict[str, float]:
            m = run.get("metrics", {})
            if not m and "metrics_json" in run:
                import json
                m = json.loads(run["metrics_json"])
            return m

        latest_metrics = _extract_metrics(latest)
        regressions: list[dict] = []

        for key, latest_val in latest_metrics.items():
            prev_values: list[float] = []
            for run in previous:
                pm = _extract_metrics(run)
                if key in pm:
                    prev_values.append(pm[key])
            if not prev_values:
                continue
            avg_prev = sum(prev_values) / len(prev_values)
            if avg_prev == 0:
                continue
            pct_change = ((latest_val - avg_prev) / avg_prev) * 100
            if pct_change < -5.0:
                regressions.append({
                    "metric": key,
                    "previous_avg": round(avg_prev, 4),
                    "current": round(latest_val, 4),
                    "pct_change": round(pct_change, 2),
                    "threshold": -5.0,
                })

        return regressions

    # ── Model rollback ──────────────────────────────────────────────────

    def rollback_to(self, model_type: str, version: str) -> bool:
        """Rollback a model to a previous version by promoting it.

        Args:
            model_type: The model type (e.g. ``intent_classifier``).
            version: The version string to rollback to.

        Returns:
            True if the rollback succeeded, False otherwise.
        """
        return self.registry.rollback(model_type, version) is not None

    def get_version_history(self, model_type: str) -> list[dict]:
        """Get version history for a model type.

        Returns:
            List of ``ModelMetadata.to_dict()`` entries sorted by creation
            date (newest first).
        """
        models = self.registry.list_models(model_type=model_type)
        return [m.to_dict() for m in models]

    # ── Dataset quality assessment ──────────────────────────────────────

    def assess_dataset_quality(self, dataset: TrainingDataset) -> DatasetQualityInfo:
        """Inspect a dataset and return structured quality information.

        Computes total / unique / duplicate counts, average confidence,
        label distribution, and suggested improvement actions.
        """
        total = len(dataset)
        if total == 0:
            return DatasetQualityInfo(
                suggested_actions=["collect more training examples"],
            )

        deduped = dataset.deduplicate()
        unique = len(deduped)
        duplicate_count = total - unique

        scores = [ex.quality_score for ex in dataset.examples if hasattr(ex, "quality_score")]
        avg_conf = sum(scores) / len(scores) if scores else 0.0

        label_dist: dict[str, int] = {}
        for ex in dataset.examples:
            label = ex.category or "unknown"
            label_dist[label] = label_dist.get(label, 0) + 1

        actions: list[str] = []
        if duplicate_count > total * 0.1:
            actions.append("deduplicate dataset (duplicate rate > 10%)")
        if avg_conf < 0.5:
            actions.append("improve example quality (avg confidence < 0.5)")
        if len(label_dist) < 3:
            actions.append("increase category diversity")

        return DatasetQualityInfo(
            total_examples=total,
            unique_examples=unique,
            duplicate_count=duplicate_count,
            avg_confidence=round(avg_conf, 4),
            label_distribution=label_dist,
            suggested_actions=actions,
        )

    # ── Learning event recording ────────────────────────────────────────

    def record_learning_event(
        self,
        event_type: str,
        category: str,
        summary: str,
        details: dict | None = None,
    ) -> LearningEvent | None:
        """Persist a ``LearningEvent`` record to the database.

        Args:
            event_type: High-level type (e.g. ``auto_improvement``).
            category: Sub-category (e.g. ``system``, ``skill``).
            summary: Human-readable summary of the event.
            details: Optional structured dict with additional context.

        Returns:
            The persisted ``LearningEvent`` or None on failure.
        """
        import json as _json

        try:
            with sync_session_scope() as session:
                event = LearningEvent(
                    public_id=str(uuid4()),
                    event_type=event_type,
                    category=category,
                    summary=summary,
                    details_json=_json.dumps(details or {}),
                )
                session.add(event)
                session.flush()
                session.refresh(event)
                logger.info(
                    "recorded learning event: %s/%s — %s",
                    event_type, category, summary,
                )
                return event
        except Exception as e:
            logger.warning("failed to record learning event: %s", e)
            return None

    def promote_if_better(
        self,
        dataset: TrainingDataset,
        model_type: str = "intent_classifier",
    ) -> RetrainResult:
        """Convenience: execute retrain and promote the candidate if it beats production."""
        result = self.execute_retrain(dataset, model_type)
        if result.success and result.metadata:
            self.registry.promote(model_type, result.metadata.version)
            result.promoted = True
        return result


@dataclass
class RetrainPlan:
    ready: bool
    model_type: str
    current_dataset_size: int
    last_training_size: int
    production_version: str | None = None
    production_metrics: dict[str, float] | None = None
    issues: list[str] = field(default_factory=list)
    force: bool = False


@dataclass
class RetrainResult:
    success: bool
    plan: RetrainPlan | None = None
    error: str = ""
    candidate_metrics: dict[str, float] | None = None
    comparison: BenchmarkComparisonResult | None = None
    metadata: ModelMetadata | None = None
    model: Any = None
    promoted: bool = False
