"""Phase 10 tests — Autonomous Improvement Foundation.

Covers:
  - Model registry: register, promote, rollback, production loading
  - Feedback loop: data collection, quality filtering, dedup
  - User interactions: save, load, convert to dataset
  - Retraining preparation: trigger, growth detection, benchmark compare
  - Metrics calculation: inference latency, dataset size
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from unittest.mock import MagicMock, patch

from veyron.intelligence.models.registry import ModelRegistry, get_registry, reset_registry
from veyron.intelligence.models.schema import (
    STATUS_CANDIDATE,
    STATUS_DEPRECATED,
    STATUS_PRODUCTION,
    ModelMetadata,
)
from veyron.intelligence.training.dataset import (
    TrainingDataset,
    TrainingExample,
    UserInteraction,
    load_user_interactions,
    save_user_interaction,
    user_interactions_to_dataset,
)
from veyron.intelligence.training.feedback import TrainingFeedbackLoop, _infer_intent
from veyron.intelligence.training.retrain import (
    BenchmarkComparator,
    DatasetGrowthDetector,
    NewExampleTrigger,
    RetrainingOrchestrator,
    RetrainPlan,
    RetrainResult,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_registry_path() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "test_registry.json"


@pytest.fixture
def registry(temp_registry_path: Path) -> ModelRegistry:
    reset_registry()
    return ModelRegistry(registry_path=temp_registry_path)


@pytest.fixture
def sample_metadata() -> ModelMetadata:
    return ModelMetadata(
        name="test_intent_model",
        version="1.0.0",
        model_type="intent_classifier",
        metrics={"accuracy": 0.95, "macro_f1": 0.94},
        status=STATUS_CANDIDATE,
    )


# ─── Model Registry Tests ────────────────────────────────────────────────────

class TestModelRegistry:
    def test_register_model(self, registry: ModelRegistry, sample_metadata: ModelMetadata):
        result = registry.register(sample_metadata)
        assert result.version == "1.0.0"
        assert result.status == STATUS_CANDIDATE

    def test_register_persists_to_disk(self, registry: ModelRegistry, sample_metadata: ModelMetadata):
        registry.register(sample_metadata)
        assert registry.registry_path.exists()
        with open(registry.registry_path) as f:
            data = json.load(f)
        assert "intent_classifier" in data
        assert data["intent_classifier"]["1.0.0"]["name"] == "test_intent_model"

    def test_load_registry_from_disk(self, temp_registry_path: Path, sample_metadata: ModelMetadata):
        r1 = ModelRegistry(registry_path=temp_registry_path)
        r1.register(sample_metadata)
        r2 = ModelRegistry(registry_path=temp_registry_path)
        loaded = r2.get("intent_classifier", "1.0.0")
        assert loaded is not None
        assert loaded.name == "test_intent_model"
        assert loaded.metrics["accuracy"] == 0.95

    def test_promote_to_production(self, registry: ModelRegistry, sample_metadata: ModelMetadata):
        registry.register(sample_metadata)
        promoted = registry.promote("intent_classifier", "1.0.0")
        assert promoted is not None
        assert promoted.status == STATUS_PRODUCTION
        assert registry.get_production("intent_classifier") is not None

    def test_promote_deprecates_previous(self, registry: ModelRegistry):
        v1 = ModelMetadata(name="m1", version="1.0", model_type="intent_classifier", status=STATUS_CANDIDATE)
        v2 = ModelMetadata(name="m2", version="2.0", model_type="intent_classifier", status=STATUS_CANDIDATE)
        registry.register(v1)
        registry.register(v2)
        registry.promote("intent_classifier", "1.0")
        assert registry.get("intent_classifier", "1.0").status == STATUS_PRODUCTION
        registry.promote("intent_classifier", "2.0")
        assert registry.get("intent_classifier", "1.0").status == STATUS_DEPRECATED
        assert registry.get("intent_classifier", "2.0").status == STATUS_PRODUCTION

    def test_rollback(self, registry: ModelRegistry):
        v1 = ModelMetadata(name="m1", version="1.0", model_type="intent_classifier", status=STATUS_CANDIDATE)
        v2 = ModelMetadata(name="m2", version="2.0", model_type="intent_classifier", status=STATUS_CANDIDATE)
        registry.register(v1)
        registry.register(v2)
        registry.promote("intent_classifier", "1.0")
        registry.rollback("intent_classifier", "2.0")
        prod = registry.get_production("intent_classifier")
        assert prod is not None
        assert prod.version == "2.0"

    def test_get_production_none(self, registry: ModelRegistry):
        assert registry.get_production("intent_classifier") is None

    def test_get_nonexistent(self, registry: ModelRegistry):
        assert registry.get("nonexistent", "1.0") is None

    def test_list_models(self, registry: ModelRegistry):
        m1 = ModelMetadata(name="m1", version="1.0", model_type="intent_classifier", metrics={"acc": 0.9})
        m2 = ModelMetadata(name="m2", version="2.0", model_type="tool_selector", metrics={"p@1": 0.95})
        registry.register(m1)
        registry.register(m2)
        all_models = registry.list_models()
        assert len(all_models) == 2
        intent_models = registry.list_models(model_type="intent_classifier")
        assert len(intent_models) == 1

    def test_to_dict(self, registry: ModelRegistry):
        m1 = ModelMetadata(name="m1", version="1.0", model_type="intent_classifier", metrics={"acc": 0.9}, status=STATUS_CANDIDATE)
        registry.register(m1)
        d = registry.to_dict()
        assert "intent_classifier" in d
        assert len(d["intent_classifier"]["candidates"]) == 1
        assert d["intent_classifier"]["production"] is None

    def test_singleton_get_registry(self):
        reset_registry()
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2
        reset_registry()
        r3 = get_registry()
        assert r3 is not r1

    def test_load_production_model_no_production(self, registry: ModelRegistry):
        result = registry.load_production_model("intent_classifier")
        assert result is None

    def test_load_production_model_missing_file(self, registry: ModelRegistry):
        md = ModelMetadata(
            name="test", version="1.0", model_type="intent_classifier",
            status=STATUS_PRODUCTION, path="/nonexistent/model.pkl",
        )
        registry.register(md)
        registry.promote("intent_classifier", "1.0")
        result = registry.load_production_model("intent_classifier")
        assert result is None

    def test_promote_nonexistent(self, registry: ModelRegistry):
        result = registry.promote("intent_classifier", "nonexistent")
        assert result is None

    def test_rollback_nonexistent(self, registry: ModelRegistry):
        result = registry.rollback("intent_classifier", "nonexistent")
        assert result is None


# ─── Model Metadata Tests ────────────────────────────────────────────────────

class TestModelMetadata:
    def test_default_created_at(self):
        md = ModelMetadata(name="test", version="1.0", model_type="intent_classifier")
        assert md.created_at != ""

    def test_to_dict_roundtrip(self):
        md = ModelMetadata(
            name="test", version="1.0", model_type="tool_selector",
            metrics={"p@1": 0.96}, status=STATUS_PRODUCTION,
            dataset_hash="abc123", dataset_size=5000,
            benchmark_results={"accuracy": 0.99},
        )
        d = md.to_dict()
        restored = ModelMetadata.from_dict(d)
        assert restored.name == "test"
        assert restored.version == "1.0"
        assert restored.metrics["p@1"] == 0.96
        assert restored.status == STATUS_PRODUCTION
        assert restored.dataset_hash == "abc123"
        assert restored.dataset_size == 5000

    def test_status_constants(self):
        assert STATUS_CANDIDATE == "candidate"
        assert STATUS_PRODUCTION == "production"
        assert STATUS_DEPRECATED == "deprecated"


# ─── User Interaction Tests ──────────────────────────────────────────────────

class TestUserInteraction:
    def test_default_timestamp(self):
        ui = UserInteraction(request="hello")
        assert ui.timestamp != ""

    def test_to_dict_roundtrip(self):
        ui = UserInteraction(
            request="list files",
            detected_intent="file_operation",
            selected_tools=["filesystem_read"],
            parameters={"path": "/tmp"},
            result="ok",
            quality_score=0.9,
        )
        d = ui.to_dict()
        restored = UserInteraction.from_dict(d)
        assert restored.request == "list files"
        assert restored.detected_intent == "file_operation"
        assert restored.selected_tools == ["filesystem_read"]
        assert restored.parameters == {"path": "/tmp"}
        assert restored.quality_score == 0.9

    def test_to_training_example(self):
        ui = UserInteraction(
            request="check cpu",
            detected_intent="system_management",
            selected_tools=["system_monitor"],
            quality_score=0.85,
        )
        ex = ui.to_training_example()
        assert ex.request == "check cpu"
        assert ex.intent == "system_management"
        assert ex.tools_used == ["system_monitor"]
        assert ex.quality_score == 0.85
        assert ex.metadata.get("source") == "user_interaction"

    def test_save_and_load_user_interactions(self, tmp_path: Path):
        ui1 = UserInteraction(request="hello", detected_intent="conversation")
        ui2 = UserInteraction(request="list files", detected_intent="file_operation")
        save_user_interaction(ui1, directory=tmp_path)
        save_user_interaction(ui2, directory=tmp_path)
        loaded = load_user_interactions(directory=tmp_path)
        assert len(loaded) == 2
        assert loaded[0].request == "hello"
        assert loaded[1].request == "list files"

    def test_user_interactions_to_dataset(self, tmp_path: Path):
        ui1 = UserInteraction(request="check cpu", detected_intent="system_management", quality_score=0.9)
        ui2 = UserInteraction(request="bad", detected_intent="conversation", quality_score=0.1)
        save_user_interaction(ui1, directory=tmp_path)
        save_user_interaction(ui2, directory=tmp_path)
        dataset = user_interactions_to_dataset(directory=tmp_path, min_quality=0.5)
        assert len(dataset) == 1
        assert dataset[0].request == "check cpu"

    def test_user_interactions_to_dataset_only_successful(self, tmp_path: Path):
        ui1 = UserInteraction(request="ok", detected_intent="coding_task", success=True, quality_score=0.7)
        ui2 = UserInteraction(request="fail", detected_intent="debugging", success=False, quality_score=0.8)
        save_user_interaction(ui1, directory=tmp_path)
        save_user_interaction(ui2, directory=tmp_path)
        dataset = user_interactions_to_dataset(directory=tmp_path, only_successful=True)
        assert len(dataset) == 1
        assert dataset[0].success is True

    def test_load_user_interactions_empty_dir(self, tmp_path: Path):
        loaded = load_user_interactions(directory=tmp_path)
        assert loaded == []


# ─── Feedback Loop Tests ─────────────────────────────────────────────────────

class TestInferIntent:
    def test_tool_based_intent(self):
        assert _infer_intent("read file", ["filesystem_read"]) == "file_operation"
        assert _infer_intent("check cpu", ["system_monitor"]) == "system_management"
        assert _infer_intent("run command", ["terminal"]) == "tool_execution"
        assert _infer_intent("analyze", ["project_analyzer"]) == "project_analysis"

    def test_keyword_based_intent(self):
        assert _infer_intent("what is the weather?", []) == "question_answering"
        assert _infer_intent("write a function to sort", []) == "coding_task"
        assert _infer_intent("debug this error", []) == "debugging"
        assert _infer_intent("plan the deployment", []) == "planning_task"
        assert _infer_intent("hello there", []) == "conversation"


class TestTrainingFeedbackLoop:
    def test_collect_from_db_empty(self, fresh_db):
        loop = TrainingFeedbackLoop(min_quality=0.0)
        dataset = loop.collect_from_db(limit=10)
        assert isinstance(dataset, TrainingDataset)
        assert len(dataset) == 0

    @patch("veyron.intelligence.training.feedback.sync_session_scope")
    def test_collect_returns_dataset(self, mock_session_scope):
        mock_session = MagicMock()
        mock_session_scope.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        loop = TrainingFeedbackLoop(min_quality=0.0)
        dataset = loop.collect_from_db(limit=10)
        assert isinstance(dataset, TrainingDataset)
        assert len(dataset) == 0

    def test_quality_threshold_filter(self):
        loop = TrainingFeedbackLoop(min_quality=0.9)
        assert loop.min_quality == 0.9

    def test_init_default_quality(self):
        loop = TrainingFeedbackLoop()
        assert loop.min_quality == 0.5


# ─── Retraining Preparation Tests ────────────────────────────────────────────

class TestNewExampleTrigger:
    def test_trigger_not_satisfied_initially(self):
        trigger = NewExampleTrigger(min_new_examples=100)
        with patch.object(NewExampleTrigger, "_count_interaction_files", return_value=0):
            assert not trigger.should_trigger()

    def test_trigger_describe(self):
        trigger = NewExampleTrigger(min_new_examples=50)
        assert "50" in trigger.describe()

    def test_trigger_update_last_count(self):
        trigger = NewExampleTrigger(min_new_examples=1)
        with patch.object(NewExampleTrigger, "_count_interaction_files", return_value=5):
            trigger.update_last_count()
            assert trigger._last_count == 5


class TestDatasetGrowthDetector:
    def test_no_growth(self):
        d = DatasetGrowthDetector(min_growth_pct=10.0)
        assert not d.should_retrain(100, 100)

    def test_sufficient_growth(self):
        d = DatasetGrowthDetector(min_growth_pct=10.0)
        assert d.should_retrain(120, 100)

    def test_insufficient_growth(self):
        d = DatasetGrowthDetector(min_growth_pct=50.0)
        assert not d.should_retrain(120, 100)

    def test_empty_last_training(self):
        d = DatasetGrowthDetector(min_growth_pct=10.0)
        assert d.should_retrain(50, 0)

    def test_empty_current(self):
        d = DatasetGrowthDetector(min_growth_pct=10.0)
        assert not d.should_retrain(0, 100)


class TestBenchmarkComparator:
    def test_no_production_is_better(self):
        c = BenchmarkComparator()
        result = c.compare({"accuracy": 0.98}, None, "intent_classifier")
        assert result.is_better
        assert "no production model" in result.reason

    def test_candidate_better(self):
        c = BenchmarkComparator()
        prod = {"accuracy": 0.90, "macro_f1": 0.88}
        cand = {"accuracy": 0.95, "macro_f1": 0.94}
        result = c.compare(cand, prod, "intent_classifier")
        assert result.is_better
        assert result.deltas["accuracy"] > 0

    def test_candidate_worse(self):
        c = BenchmarkComparator()
        prod = {"accuracy": 0.95, "macro_f1": 0.94}
        cand = {"accuracy": 0.90, "macro_f1": 0.88}
        result = c.compare(cand, prod, "intent_classifier")
        assert not result.is_better

    def test_lower_latency_is_better(self):
        c = BenchmarkComparator()
        prod = {"latency_ms": 5.0}
        cand = {"latency_ms": 2.0}
        result = c.compare(cand, prod, "intent_classifier")
        assert result.is_better
        assert "improved" in result.reason

    def test_mixed_metrics(self):
        c = BenchmarkComparator()
        prod = {"accuracy": 0.95, "latency_ms": 5.0}
        cand = {"accuracy": 0.96, "latency_ms": 6.0}
        result = c.compare(cand, prod, "intent_classifier")
        assert not result.is_better

    def test_equal_metrics(self):
        c = BenchmarkComparator()
        prod = {"accuracy": 0.95}
        cand = {"accuracy": 0.95}
        result = c.compare(cand, prod, "intent_classifier")
        assert result.is_better
        assert "equal" in result.reason


class TestRetrainingOrchestrator:
    def test_prepare_retrain_not_ready(self, registry: ModelRegistry):
        trigger = NewExampleTrigger(min_new_examples=999)
        orch = RetrainingOrchestrator(registry=registry, trigger=trigger)
        dataset = TrainingDataset([TrainingExample(request="test", intent="conversation")])
        plan = orch.prepare_retrain(dataset, "intent_classifier")
        assert isinstance(plan, RetrainPlan)
        assert not plan.ready
        assert plan.current_dataset_size == 1
        assert plan.last_training_size == 0

    def test_prepare_retrain_force(self, registry: ModelRegistry):
        orch = RetrainingOrchestrator(registry=registry)
        dataset = TrainingDataset([TrainingExample(request="test", intent="conversation")])
        plan = orch.prepare_retrain(dataset, "intent_classifier", force=True)
        assert plan.ready
        assert plan.force

    def test_execute_retrain_not_ready(self, registry: ModelRegistry):
        orch = RetrainingOrchestrator(registry=registry)
        dataset = TrainingDataset()
        result = orch.execute_retrain(dataset, "intent_classifier")
        assert isinstance(result, RetrainResult)
        assert not result.success

    def test_promote_if_better_not_ready(self, registry: ModelRegistry):
        orch = RetrainingOrchestrator(registry=registry)
        dataset = TrainingDataset()
        result = orch.promote_if_better(dataset, "intent_classifier")
        assert not result.success


# ─── Training Dataset Extension Tests ────────────────────────────────────────

class TestTrainingDatasetExtensions:
    def test_user_interaction_to_dataset_dedup(self, tmp_path: Path):
        ui = UserInteraction(request="hello", detected_intent="conversation", quality_score=0.9)
        save_user_interaction(ui, directory=tmp_path)
        save_user_interaction(ui, directory=tmp_path)
        dataset = user_interactions_to_dataset(directory=tmp_path)
        assert len(dataset) == 1

    def test_training_example_content_hash(self):
        ex1 = TrainingExample(request="hello", tools_used=["tool1"], intent="conversation")
        ex2 = TrainingExample(request="hello", tools_used=["tool1"], intent="conversation")
        ex3 = TrainingExample(request="hello", tools_used=["tool2"], intent="conversation")
        assert ex1.content_hash == ex2.content_hash
        assert ex1.content_hash != ex3.content_hash


# ─── Inference Latency Measurement Tests ─────────────────────────────────────

class TestMetricsCalculation:
    @patch("veyron.api.routes.intelligence._load_intent_model")
    @patch("veyron.api.routes.intelligence._load_ts_model")
    def test_metrics_endpoint_structure(self, mock_ts, mock_ic):
        from veyron.api.routes.intelligence import _measure_inference_latency
        mock_ic.return_value = MagicMock()
        mock_ts.return_value = MagicMock()
        latency = _measure_inference_latency()
        assert "intent_classifier_ms" in latency
        assert "tool_selector_ms" in latency
        assert isinstance(latency["intent_classifier_ms"], float)
        assert isinstance(latency["tool_selector_ms"], float)


# ─── Registry Thread Safety (Singleton) Tests ────────────────────────────────

class TestRegistrySingleton:
    def test_reset_registry(self):
        reset_registry()
        r1 = get_registry()
        reset_registry()
        r2 = get_registry()
        assert r2 is not r1

    def test_registry_path_custom(self, temp_registry_path: Path):
        r = ModelRegistry(registry_path=temp_registry_path)
        assert r.registry_path == temp_registry_path


# ─── Auto-promotion Tests ──────────────────────────────────────────────────

class TestAutoPromotion:
    """Tests for _auto_promote_model in run_training.py."""

    @patch("veyron.intelligence.training.run_training.mlflow")
    def test_promotes_when_no_production(self, mock_mlflow, registry, temp_registry_path, monkeypatch):
        monkeypatch.setattr("veyron.intelligence.training.run_training.get_registry", lambda: registry)
        monkeypatch.setattr("veyron.intelligence.training.run_training.get_settings", lambda: MagicMock(model=MagicMock(auto_promote_models=True)))

        from veyron.intelligence.training.run_training import _auto_promote_model

        _auto_promote_model(
            model_type="intent_classifier",
            model_name="intent_classifier",
            version="v2.0.0-test",
            path="/fake/model.pkl",
            metrics={"accuracy": 0.95, "macro_f1": 0.94},
            primary_metric="macro_f1",
        )

        prod = registry.get_production("intent_classifier")
        assert prod is not None
        assert prod.version == "v2.0.0-test"
        assert prod.status == STATUS_PRODUCTION
        mock_mlflow.log_metric.assert_any_call("promoted_to_production", 1)

    @patch("veyron.intelligence.training.run_training.mlflow")
    def test_promotes_when_better(self, mock_mlflow, registry, temp_registry_path, monkeypatch):
        monkeypatch.setattr("veyron.intelligence.training.run_training.get_registry", lambda: registry)
        monkeypatch.setattr("veyron.intelligence.training.run_training.get_settings", lambda: MagicMock(model=MagicMock(auto_promote_models=True)))

        # Register existing production model with macro_f1=0.90
        registry.register(ModelMetadata(
            name="intent_classifier",
            version="v1.0.0",
            model_type="intent_classifier",
            metrics={"accuracy": 0.88, "macro_f1": 0.90},
            path="/old/model.pkl",
            status=STATUS_CANDIDATE,
        ))
        registry.promote("intent_classifier", "v1.0.0")

        from veyron.intelligence.training.run_training import _auto_promote_model

        _auto_promote_model(
            model_type="intent_classifier",
            model_name="intent_classifier",
            version="v2.0.0-better",
            path="/new/model.pkl",
            metrics={"accuracy": 0.96, "macro_f1": 0.95},  # 0.95 > 0.90 + 0.01
            primary_metric="macro_f1",
        )

        prod = registry.get_production("intent_classifier")
        assert prod is not None
        assert prod.version == "v2.0.0-better"
        mock_mlflow.log_metric.assert_any_call("promoted_to_production", 1)

    @patch("veyron.intelligence.training.run_training.mlflow")
    def test_does_not_promote_when_worse(self, mock_mlflow, registry, temp_registry_path, monkeypatch):
        monkeypatch.setattr("veyron.intelligence.training.run_training.get_registry", lambda: registry)
        monkeypatch.setattr("veyron.intelligence.training.run_training.get_settings", lambda: MagicMock(model=MagicMock(auto_promote_models=True)))

        # Register existing production model with macro_f1=0.95
        registry.register(ModelMetadata(
            name="intent_classifier",
            version="v1.0.0",
            model_type="intent_classifier",
            metrics={"accuracy": 0.96, "macro_f1": 0.95},
            path="/old/model.pkl",
            status=STATUS_CANDIDATE,
        ))
        registry.promote("intent_classifier", "v1.0.0")

        from veyron.intelligence.training.run_training import _auto_promote_model

        _auto_promote_model(
            model_type="intent_classifier",
            model_name="intent_classifier",
            version="v2.0.0-worse",
            path="/new/model.pkl",
            metrics={"accuracy": 0.90, "macro_f1": 0.88},  # 0.88 < 0.95 + 0.01
            primary_metric="macro_f1",
        )

        prod = registry.get_production("intent_classifier")
        assert prod is not None
        assert prod.version == "v1.0.0"  # still the old one

        # The new model should still be registered as candidate
        candidate = registry.get("intent_classifier", "v2.0.0-worse")
        assert candidate is not None
        assert candidate.status == STATUS_CANDIDATE
        mock_mlflow.log_metric.assert_any_call("promoted_to_production", 0)

    @patch("veyron.intelligence.training.run_training.mlflow")
    def test_skips_when_disabled(self, mock_mlflow, registry, temp_registry_path, monkeypatch):
        monkeypatch.setattr("veyron.intelligence.training.run_training.get_registry", lambda: registry)
        monkeypatch.setattr("veyron.intelligence.training.run_training.get_settings", lambda: MagicMock(model=MagicMock(auto_promote_models=False)))

        from veyron.intelligence.training.run_training import _auto_promote_model

        _auto_promote_model(
            model_type="intent_classifier",
            model_name="intent_classifier",
            version="v2.0.0-skip",
            path="/fake/model.pkl",
            metrics={"accuracy": 0.95, "macro_f1": 0.94},
            primary_metric="macro_f1",
        )

        assert registry.get_production("intent_classifier") is None
        mock_mlflow.log_metric.assert_any_call("auto_promote_skipped", 1)
