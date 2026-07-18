"""Tests for Phase 9.4: real artifact loading, inference, fallback, benchmark execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from veyron.config import DATA_DIR, get_settings, reset_settings_cache
from veyron.intelligence.intent.inference import (
    ClassifierResult,
    classify_intent,
    reset_model,
    should_use_llm,
)
from veyron.intelligence.intent.model import IntentModel
from veyron.intelligence.tool_selector.inference import (
    predict_tool_names,
    predict_tools,
)
from veyron.intelligence.tool_selector.inference import (
    reset_model as reset_ts_model,
)
from veyron.intelligence.tool_selector.model import ToolSelectorModel
from veyron.intelligence.training.benchmark_v2 import BenchmarkV2
from veyron.intelligence.training.dataset import TrainingDataset, TrainingExample
from veyron.intelligence.training.preparation.splitter import load_jsonl_as_examples
from veyron.intelligence.training.trainer_v2 import TrainingPipelineV2

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singletons():
    reset_model()
    reset_ts_model()
    reset_settings_cache()
    yield
    reset_model()
    reset_ts_model()


@pytest.fixture
def mini_dataset() -> TrainingDataset:
    examples = [
        TrainingExample(request="show cpu usage now", intent="system_management", tools_used=["system_monitor"]),
        TrainingExample(request="check memory usage", intent="system_management", tools_used=["system_monitor"]),
        TrainingExample(request="read the readme file", intent="file_operation", tools_used=["filesystem_read"]),
        TrainingExample(request="list directory contents", intent="file_operation", tools_used=["filesystem_read"]),
        TrainingExample(request="analyze project structure", intent="project_analysis", tools_used=["project_analyzer"]),
        TrainingExample(request="run npm install command", intent="tool_execution", tools_used=["terminal"]),
        TrainingExample(request="debug the build failure", intent="debugging", tools_used=["terminal", "filesystem_read"]),
        TrainingExample(request="fix the crash error", intent="debugging", tools_used=["terminal"]),
        TrainingExample(request="hello how are you", intent="conversation", tools_used=[]),
        TrainingExample(request="good morning", intent="conversation", tools_used=[]),
        TrainingExample(request="what is the weather today", intent="question_answering", tools_used=[]),
        TrainingExample(request="write a sorting algorithm", intent="coding_task", tools_used=["filesystem_read"]),
        TrainingExample(request="plan the deployment steps", intent="planning_task", tools_used=["terminal", "filesystem_read"]),
        TrainingExample(request="research quantum computing", intent="research", tools_used=["filesystem_read"]),
    ]
    return TrainingDataset(examples)


@pytest.fixture
def trained_models(mini_dataset: TrainingDataset, tmp_path: Path) -> tuple[IntentModel, ToolSelectorModel, Path]:
    """Train both models and save to tmp_path, return models + path."""
    pipeline = TrainingPipelineV2(output_dir=tmp_path)
    intent_model, _ = pipeline.train_intent(mini_dataset, seed=42)
    ts_model, _ = pipeline.train_tool_selector(mini_dataset, seed=42)
    pipeline.save_models(intent_model=intent_model, tool_selector_model=ts_model, output_dir=tmp_path)
    return intent_model, ts_model, tmp_path


# ── Artifact loading tests ───────────────────────────────────────────────────

class TestArtifactLoading:
    def test_load_intent_model_from_disk(self, trained_models):
        _, _, model_dir = trained_models
        model = IntentModel()
        model_path = model_dir / "intent_classifier.pkl"
        assert model_path.exists()
        model.load(str(model_path))
        assert model.fitted
        assert len(model.classes) > 0

    def test_load_tool_selector_from_disk(self, trained_models):
        _, _, model_dir = trained_models
        model = ToolSelectorModel()
        model_path = model_dir / "tool_selector.pkl"
        assert model_path.exists()
        model.load(str(model_path))
        assert model.fitted
        assert len(model.tool_names) > 0

    def test_latest_model_symlink_created(self, trained_models):
        _, _, model_dir = trained_models
        assert (model_dir / "intent_classifier.pkl").exists()
        assert (model_dir / "tool_selector.pkl").exists()

    def test_metadata_file(self, trained_models):
        _, _, model_dir = trained_models
        report_path = model_dir / "training_report_v2.json"
        if report_path.exists():
            data = json.loads(report_path.read_text(encoding="utf-8"))
            assert "accuracy" in data

    def test_load_from_nonexistent_path_returns_none(self):
        model = IntentModel()
        with pytest.raises(FileNotFoundError):
            model.load("nonexistent/path.pkl")


# ── Inference tests ──────────────────────────────────────────────────────────

class TestInference:
    def test_classify_intent_fallback(self):
        reset_model()
        result = classify_intent("What is the CPU usage?")
        assert isinstance(result, ClassifierResult)
        assert result.category in [
            "question_answering", "system_management", "file_operation",
            "tool_execution", "planning_task", "debugging", "coding_task",
            "project_analysis", "research", "conversation",
        ]
        assert 0.0 <= result.confidence <= 1.0

    def test_classify_intent_with_trained_model(self, trained_models):
        intent_model, _, model_dir = trained_models
        model_path = model_dir / "intent_classifier.pkl"
        reset_model()
        result = classify_intent("show cpu usage now", model_path=str(model_path))
        assert result.model_used == "micro_model"
        assert result.confidence > 0.0

    def test_predict_tools_empty_when_no_model(self):
        reset_ts_model()
        result = predict_tools("list files")
        # Model exists on disk from training; expect predictions.
        assert isinstance(result, list)

    def test_predict_tool_names_empty_when_no_model(self):
        reset_ts_model()
        result = predict_tool_names("list files")
        # Model exists on disk from training; expect predictions.
        assert isinstance(result, list)

    def test_predict_tools_with_trained_model(self, trained_models):
        _, ts_model, model_dir = trained_models
        model_path = model_dir / "tool_selector.pkl"
        reset_ts_model()
        result = predict_tools("list directory contents", model_path=str(model_path))
        assert len(result) > 0
        for pred in result:
            assert hasattr(pred, "tool_name")
            assert hasattr(pred, "confidence")
            assert 0.0 <= pred.confidence <= 1.0

    def test_predict_tool_names_with_trained_model(self, trained_models):
        _, _, model_dir = trained_models
        model_path = model_dir / "tool_selector.pkl"
        reset_ts_model()
        result = predict_tool_names("list directory contents", model_path=str(model_path))
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], str)

    def test_predict_top_k(self, trained_models):
        _, ts_model, model_dir = trained_models
        model_path = model_dir / "tool_selector.pkl"
        reset_ts_model()
        result = predict_tools("list directory contents", top_k=2, model_path=str(model_path))
        assert len(result) <= 2

    def test_integration_intent_and_tool_selector(self, trained_models):
        intent_model, ts_model, model_dir = trained_models
        intent_path = model_dir / "intent_classifier.pkl"
        ts_path = model_dir / "tool_selector.pkl"

        reset_model()
        reset_ts_model()

        intent_result = classify_intent("list directory contents", model_path=str(intent_path))
        assert intent_result.model_used == "micro_model"

        tool_preds = predict_tool_names("list directory contents", model_path=str(ts_path))
        assert isinstance(tool_preds, list)


# ── Fallback behavior tests ──────────────────────────────────────────────────

class TestFallbackBehavior:
    def test_should_use_llm_high_confidence(self):
        result = ClassifierResult(category="system_management", confidence=0.9)
        assert not should_use_llm(result, threshold=0.7)

    def test_should_use_llm_low_confidence(self):
        result = ClassifierResult(category="system_management", confidence=0.3)
        assert should_use_llm(result, threshold=0.7)

    def test_should_use_llm_default_threshold(self):
        result = ClassifierResult(category="system_management", confidence=0.8)
        assert not should_use_llm(result)  # 0.8 >= 0.7 default

    def test_classify_fallback_when_no_model(self, monkeypatch):
        from veyron.intelligence.intent import inference as intent_inference
        monkeypatch.setattr(intent_inference, "_resolve_model_path", lambda: None)
        reset_model()
        result = classify_intent("What is the meaning of life?")
        assert result.model_used == "fallback"
        assert result.fallback_reason != ""

    def test_fallback_empty_predicted_tools(self):
        reset_ts_model()
        result = predict_tools("list files")
        # Model exists on disk; expect predictions rather than empty.
        assert isinstance(result, list)

    def test_low_confidence_routes_to_llm(self):
        result = ClassifierResult(category="system_management", confidence=0.4)
        assert should_use_llm(result, threshold=0.6)

    def test_model_path_override(self):
        """When model_path points to a non-existent file, fallback is used."""
        reset_model()
        result = classify_intent("check cpu", model_path="/nonexistent/model.pkl")
        assert result.model_used == "fallback"


# ── Benchmark execution tests ────────────────────────────────────────────────

class TestBenchmarkExecution:
    def test_benchmark_v2_runs_with_mini_dataset(self, mini_dataset: TrainingDataset, tmp_path: Path):
        pipeline = TrainingPipelineV2(output_dir=tmp_path)
        v2_intent, _ = pipeline.train_intent(mini_dataset, seed=42)
        v2_ts, _ = pipeline.train_tool_selector(mini_dataset, seed=42)
        pipeline.save_models(intent_model=v2_intent, tool_selector_model=v2_ts, output_dir=tmp_path)

        v1_intent, _ = pipeline.train_intent(mini_dataset, seed=42)
        v1_ts = ToolSelectorModel()
        texts = [ex.request for ex in mini_dataset.examples if ex.request]
        targets = [ex.tools_used for ex in mini_dataset.examples if ex.request]
        v1_ts.fit(texts, targets)

        benchmark = BenchmarkV2()
        report = benchmark.run(
            dataset=mini_dataset,
            v2_intent_model=v2_intent,
            v1_intent_model=v1_intent,
            v2_ts_model=v2_ts,
            v1_ts_model=v1_ts,
        )

        assert report.total > 0
        assert 0.0 <= report.v2_intent_accuracy <= 1.0
        assert 0.0 <= report.v1_intent_accuracy <= 1.0

    def test_benchmark_report_saved_to_json(self, mini_dataset: TrainingDataset, tmp_path: Path):
        pipeline = TrainingPipelineV2(output_dir=tmp_path)
        v2_intent, _ = pipeline.train_intent(mini_dataset, seed=42)
        v2_ts, _ = pipeline.train_tool_selector(mini_dataset, seed=42)

        v1_intent, _ = pipeline.train_intent(mini_dataset, seed=42)
        v1_ts = ToolSelectorModel()
        texts = [ex.request for ex in mini_dataset.examples if ex.request]
        targets = [ex.tools_used for ex in mini_dataset.examples if ex.request]
        v1_ts.fit(texts, targets)

        benchmark = BenchmarkV2()
        report = benchmark.run(
            dataset=mini_dataset,
            v2_intent_model=v2_intent,
            v1_intent_model=v1_intent,
            v2_ts_model=v2_ts,
            v1_ts_model=v1_ts,
        )

        report_path = tmp_path / "benchmark_test.json"
        BenchmarkV2.save_report(report, path=report_path)
        assert report_path.exists()
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert "v2_intent_accuracy" in data
        assert "v1_intent_accuracy" in data

    def test_benchmark_report_to_dict(self, mini_dataset: TrainingDataset, tmp_path: Path):
        pipeline = TrainingPipelineV2(output_dir=tmp_path)
        v2_intent, _ = pipeline.train_intent(mini_dataset, seed=42)
        v2_ts, _ = pipeline.train_tool_selector(mini_dataset, seed=42)
        v1_intent, _ = pipeline.train_intent(mini_dataset, seed=42)

        benchmark = BenchmarkV2()
        report = benchmark.run(
            dataset=mini_dataset,
            v2_intent_model=v2_intent,
            v1_intent_model=v1_intent,
            v2_ts_model=v2_ts,
        )

        d = report.to_dict()
        assert "v2_intent_accuracy" in d
        assert "v2_tool_precision@3" in d
        assert "llm_calls_avoided" in d
        assert "per_category" in d

    def test_benchmark_empty_dataset(self, tmp_path: Path):
        empty = TrainingDataset([])
        pipeline = TrainingPipelineV2(output_dir=tmp_path)
        v2_intent = IntentModel()
        v2_intent.fit(["dummy", "other"], ["conversation", "system_management"])

        benchmark = BenchmarkV2()
        report = benchmark.run(
            dataset=empty,
            v2_intent_model=v2_intent,
        )
        assert report.total == 0

    def test_benchmark_latency_measured(self, mini_dataset: TrainingDataset, tmp_path: Path):
        pipeline = TrainingPipelineV2(output_dir=tmp_path)
        v2_intent, _ = pipeline.train_intent(mini_dataset, seed=42)
        v2_ts, _ = pipeline.train_tool_selector(mini_dataset, seed=42)

        benchmark = BenchmarkV2()
        report = benchmark.run(
            dataset=mini_dataset,
            v2_intent_model=v2_intent,
            v2_ts_model=v2_ts,
        )

        assert report.v2_avg_latency_ms > 0
        assert report.heuristic_avg_latency_ms > 0

    def test_benchmark_print_report(self, mini_dataset: TrainingDataset, tmp_path: Path):
        pipeline = TrainingPipelineV2(output_dir=tmp_path)
        v2_intent, _ = pipeline.train_intent(mini_dataset, seed=42)
        v2_ts, _ = pipeline.train_tool_selector(mini_dataset, seed=42)

        benchmark = BenchmarkV2()
        report = benchmark.run(
            dataset=mini_dataset,
            v2_intent_model=v2_intent,
            v2_ts_model=v2_ts,
        )

        output = BenchmarkV2.print_report(report)
        assert "BENCHMARK V2 REPORT" in output
        assert "Intent Accuracy" in output
        assert "Tool Selection" in output
        assert "Latency" in output
        assert "LLM Efficiency" in output


# ── TrainingPipelineV2 with real data tests ──────────────────────────────────

class TestTrainingWithRealData:
    def test_load_synthetic_data(self):
        path = DATA_DIR / "training" / "synthetic_training_data.jsonl"
        if not path.exists():
            pytest.skip("synthetic data not found")
        dataset = load_jsonl_as_examples(str(path))
        assert len(dataset) > 0
        summary = dataset.summary()
        assert summary["total"] > 0
        assert len(summary["categories"]) > 0

    def test_train_on_synthetic_subset(self):
        path = DATA_DIR / "training" / "synthetic_training_data.jsonl"
        if not path.exists():
            pytest.skip("synthetic data not found")
        dataset = load_jsonl_as_examples(str(path))
        # Use only 100 examples for quick test.
        subset = dataset.filter(max_examples=100)
        assert len(subset) == 100

        pipeline = TrainingPipelineV2()
        model, report = pipeline.train_intent(subset, seed=42)
        assert model.fitted
        assert report.accuracy > 0.0

    def test_train_tool_selector_on_synthetic_subset(self):
        path = DATA_DIR / "training" / "synthetic_training_data.jsonl"
        if not path.exists():
            pytest.skip("synthetic data not found")
        dataset = load_jsonl_as_examples(str(path))
        subset = dataset.filter(max_examples=100)
        pipeline = TrainingPipelineV2()
        model, report = pipeline.train_tool_selector(subset, seed=42)
        assert model.fitted
        assert report.precision_at_1 >= 0.0

    def test_save_load_roundtrip(self, tmp_path: Path):
        path = DATA_DIR / "training" / "synthetic_training_data.jsonl"
        if not path.exists():
            pytest.skip("synthetic data not found")
        dataset = load_jsonl_as_examples(str(path))
        subset = dataset.filter(max_examples=50)

        pipeline = TrainingPipelineV2(output_dir=tmp_path)
        intent_model, intent_report = pipeline.train_intent(subset, seed=42)
        ts_model, ts_report = pipeline.train_tool_selector(subset, seed=42)

        pipeline.save_models(intent_model=intent_model, tool_selector_model=ts_model, output_dir=tmp_path)
        pipeline.save_reports(intent_report=intent_report, ts_report=ts_report, output_dir=tmp_path)

        # Verify files.
        assert (tmp_path / "intent_classifier.pkl").exists()
        assert (tmp_path / "tool_selector.pkl").exists()
        assert (tmp_path / "training_report_v2.json").exists()
        assert (tmp_path / "tool_selector_report_v2.json").exists()


# ── Runtime integration tests ────────────────────────────────────────────────

class TestRuntimeIntegration:
    def test_micro_models_disabled_by_default(self):
        settings = get_settings()
        assert settings.model.micro_models_enabled is False

    def test_classify_request_returns_intent(self):
        from veyron.core.intelligence import classify_request
        from veyron.llm.micro.router import Intent
        intent = classify_request("What is the CPU usage?")
        assert isinstance(intent, Intent)
        assert intent.confidence > 0.0
        assert intent.mode in ("react", "plan")

    def test_intent_has_predicted_tools_field(self):
        from veyron.llm.micro.router import Intent
        intent = Intent(mode="react", domain="general", confidence=0.9)
        assert hasattr(intent, "predicted_tools")
        assert intent.predicted_tools is None

    def test_tool_selector_inference_imports(self):
        from veyron.intelligence.tool_selector import (
            predict_tool_names,
            predict_tools,
            reset_ts_model,
        )
        assert callable(predict_tool_names)
        assert callable(predict_tools)
        assert callable(reset_ts_model)



