"""Tests for the intent classification micro-model."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from veyron.intelligence.intent.dataset import (
    CATEGORY_TO_DOMAIN,
    CATEGORY_TO_MODE,
    IntentDataset,
)
from veyron.intelligence.intent.inference import (
    ClassifierResult,
    classify_intent,
    reset_model,
    should_use_llm,
)
from veyron.intelligence.intent.model import IntentModel
from veyron.intelligence.intent.trainer import train_model


class TestIntentModel:
    """Tests for the IntentModel wrapper."""

    def test_not_fitted_raises(self):
        model = IntentModel()
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict("hello")

    def test_fit_and_predict(self):
        model = IntentModel()
        texts = ["check cpu", "read file", "hello world"]
        labels = ["system_management", "file_operation", "conversation"]
        model.fit(texts, labels)
        assert model.fitted
        assert model.classes == ["conversation", "file_operation", "system_management"]

    def test_predict_proba_returns_all_categories(self):
        model = IntentModel()
        model.fit(["check cpu", "read file", "hello world"], ["system_management", "file_operation", "conversation"])
        probs = model.predict_proba("check cpu")
        assert set(probs.keys()) == {"conversation", "file_operation", "system_management"}
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_predict_with_confidence(self):
        model = IntentModel()
        model.fit(["check cpu", "read file"], ["system_management", "file_operation"])
        category, confidence = model.predict_with_confidence("check cpu")
        assert category == "system_management"
        assert 0.0 <= confidence <= 1.0

    def test_save_and_load(self):
        model = IntentModel()
        model.fit(["check cpu", "read file"], ["system_management", "file_operation"])
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        try:
            model.save(path)
            loaded = IntentModel()
            loaded.load(path)
            assert loaded.fitted
            assert loaded.classes == ["file_operation", "system_management"]
            assert loaded.predict("check cpu") == "system_management"
        finally:
            Path(path).unlink(missing_ok=True)


class TestIntentDataset:
    """Tests for dataset generation and management."""

    def test_generate_expanded(self):
        dataset = IntentDataset.generate_expanded(target_per_category=5)
        assert len(dataset) >= 50  # 10 categories * at least 5 each
        labels = set(dataset.labels)
        expected = {
            "question_answering", "coding_task", "project_analysis",
            "file_operation", "tool_execution", "planning_task",
            "debugging", "system_management", "research", "conversation",
        }
        assert labels == expected

    def test_train_test_split(self):
        dataset = IntentDataset.generate_expanded(target_per_category=10)
        train_set, test_set = dataset.train_test_split(test_ratio=0.3, seed=42)
        assert len(train_set) > 0
        assert len(test_set) > 0
        assert len(train_set) + len(test_set) == len(dataset)

    def test_from_jsonl_and_to_jsonl(self):
        dataset = IntentDataset()
        dataset.add("test query", "question_answering")
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False, encoding="utf-8") as f:
            path = f.name
            dataset.to_jsonl(path)
        try:
            loaded = IntentDataset.from_jsonl(path)
            assert len(loaded) == 1
            assert loaded[0]["text"] == "test query"
            assert loaded[0]["intent"] == "question_answering"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_category_mappings_complete(self):
        """All 10 intent categories have mode and domain mappings."""
        categories = [
            "question_answering",
            "coding_task",
            "project_analysis",
            "file_operation",
            "tool_execution",
            "planning_task",
            "debugging",
            "system_management",
            "research",
            "conversation",
        ]
        for cat in categories:
            assert cat in CATEGORY_TO_MODE, f"{cat} missing from CATEGORY_TO_MODE"
            assert cat in CATEGORY_TO_DOMAIN, f"{cat} missing from CATEGORY_TO_DOMAIN"


class TestExpandedDataset:
    """Phase 2: tests for the expanded dataset with complexity/tool/planning fields."""

    def test_expanded_dataset_has_all_fields(self):
        dataset = IntentDataset.generate_expanded(target_per_category=10)
        for ex in dataset:
            assert "complexity" in ex
            assert ex["complexity"] in ("simple", "moderate", "complex")
            assert "requires_tool" in ex
            assert isinstance(ex["requires_tool"], bool)
            assert "requires_planning" in ex
            assert isinstance(ex["requires_planning"], bool)

    def test_expanded_dataset_size(self):
        dataset = IntentDataset.generate_expanded(target_per_category=110, seed=42)
        assert len(dataset) >= 1100
        assert len(dataset) <= 1200

    def test_expanded_dataset_all_categories_present(self):
        dataset = IntentDataset.generate_expanded(target_per_category=10)
        labels = set(dataset.labels)
        expected = {
            "question_answering", "coding_task", "project_analysis",
            "file_operation", "tool_execution", "planning_task",
            "debugging", "system_management", "research", "conversation",
        }
        assert labels == expected

    def test_expanded_dataset_balance_report(self):
        dataset = IntentDataset.generate_expanded(target_per_category=50, seed=42)
        report = dataset.balance_report()
        assert report["min"] > 0
        assert report["max"] > 0
        assert report["imbalance_ratio"] <= 1.2

    def test_validate_all_no_errors(self):
        dataset = IntentDataset.generate_expanded(target_per_category=10)
        result = dataset.validate_all()
        assert result["valid"] is True
        assert result["issue_count"] == 0


class TestTrainingPipeline:
    """Tests for the training pipeline."""

    def test_train_model_returns_metrics(self):
        model, metrics = train_model(test_ratio=0.5, seed=42)
        assert model.fitted
        assert "accuracy" in metrics
        assert "correct" in metrics
        assert "total" in metrics
        assert metrics["total"] > 0
        assert 0 <= metrics["accuracy"] <= 1

    def test_train_model_includes_phase2_metrics(self):
        """Training metrics include confusion matrix, calibration, weak categories."""
        model, metrics = train_model(test_ratio=0.5, seed=42)
        assert "macro_precision" in metrics
        assert "macro_recall" in metrics
        assert "macro_f1" in metrics
        assert "confusion_matrix" in metrics
        assert "calibration" in metrics
        assert "weak_categories" in metrics
        assert "per_category" in metrics
        assert 0 <= metrics["macro_f1"] <= 1

    def test_train_model_per_category_metrics(self):
        model, metrics = train_model(test_ratio=0.5, seed=42)
        per_cat = metrics["per_category"]
        for cat in ["question_answering", "file_operation", "system_management", "conversation"]:
            assert cat in per_cat
            assert "precision" in per_cat[cat]
            assert "recall" in per_cat[cat]
            assert "f1_score" in per_cat[cat]
            assert 0 <= per_cat[cat]["f1_score"] <= 1

    def test_train_model_confusion_matrix_shape(self):
        model, metrics = train_model(test_ratio=0.5, seed=42)
        cm = metrics["confusion_matrix"]
        assert isinstance(cm, dict)
        assert len(cm) == 10  # 10 categories
        # Each category maps to another category -> count
        for cat, row in cm.items():
            assert isinstance(row, dict)
            assert len(row) == 10

    def test_train_model_calibration_present(self):
        model, metrics = train_model(test_ratio=0.5, seed=42)
        cal = metrics["calibration"]
        assert len(cal) > 0
        for bucket in cal:
            assert "bucket" in bucket
            assert "count" in bucket
            assert "avg_confidence" in bucket
            assert "accuracy" in bucket

    def test_weak_categories_empty_when_all_above_threshold(self):
        """All categories should have F1 > 0.7 with a fallback-trained model."""
        model, metrics = train_model(test_ratio=0.5, seed=42)
        assert len(metrics["weak_categories"]) == 0

    def test_train_model_with_custom_dataset(self):
        dataset = IntentDataset()
        dataset.add("check cpu usage now", "system_management")
        dataset.add("what is the cpu usage", "system_management")
        dataset.add("read the file", "file_operation")
        dataset.add("list all files here", "file_operation")
        dataset.add("hello there", "conversation")
        dataset.add("how are you today", "conversation")
        model, metrics = train_model(dataset=dataset, test_ratio=0.33, seed=42)
        assert model.fitted
        assert metrics["total"] >= 1  # at least 1 test example
        assert "accuracy" in metrics


class TestInference:
    """Tests for inference API."""

    def test_classify_intent_returns_classifier_result(self):
        reset_model()
        model = IntentModel()
        model.fit(
            ["check cpu usage", "read file", "hello"],
            ["system_management", "file_operation", "conversation"],
        )
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            model_path = f.name
        try:
            model.save(model_path)
            result = classify_intent("What is the CPU usage?", model_path=model_path)
            assert isinstance(result, ClassifierResult)
            assert result.category in [
                "question_answering",
                "coding_task",
                "project_analysis",
                "file_operation",
                "tool_execution",
                "planning_task",
                "debugging",
                "system_management",
                "research",
                "conversation",
            ]
            assert 0.0 <= result.confidence <= 1.0
            assert result.model_used == "micro_model"
        finally:
            Path(model_path).unlink(missing_ok=True)
            reset_model()

    def test_classify_fallback_system_management(self):
        reset_model()
        result = classify_intent("What is the current CPU usage percentage?")
        assert result.category == "system_management"

    def test_classify_fallback_file_operation(self):
        reset_model()
        result = classify_intent("List all files in the directory")
        assert result.category == "file_operation"

    def test_classify_fallback_planning(self, monkeypatch):
        from veyron.intelligence.intent import inference as intent_inference
        monkeypatch.setattr(intent_inference, "_resolve_model_path", lambda: None)
        reset_model()
        result = classify_intent("First do this, then do that, after that finally summarize")
        assert result.category == "planning_task"

    def test_classify_fallback_tool_execution(self):
        reset_model()
        result = classify_intent("Run the command git status")
        assert result.category == "tool_execution"

    def test_classify_fallback_project_analysis(self):
        reset_model()
        result = classify_intent("Analyze this codebase and check the dependencies")
        assert result.category == "project_analysis"

    def test_classify_fallback_default(self):
        reset_model()
        result = classify_intent("What is the meaning of life?")
        assert result.category == "question_answering"

    def test_classify_with_trained_model(self):
        reset_model()
        model = IntentModel()
        model.fit(
            ["check cpu usage", "read the file list", "hey how are you today"],
            ["system_management", "file_operation", "conversation"],
        )
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            model_path = f.name
        try:
            model.save(model_path)
            result = classify_intent("check cpu usage", model_path=model_path)
            assert result.category == "system_management"
            assert result.model_used == "micro_model"
            assert result.confidence > 0.0
        finally:
            Path(model_path).unlink(missing_ok=True)
            reset_model()

    def test_should_use_llm_high_confidence(self):
        result = ClassifierResult(category="system_management", confidence=0.9)
        assert not should_use_llm(result, threshold=0.7)

    def test_should_use_llm_low_confidence(self):
        result = ClassifierResult(category="system_management", confidence=0.5)
        assert should_use_llm(result, threshold=0.7)

    def test_should_use_llm_default_threshold(self):
        """Use config threshold when none provided."""
        result = ClassifierResult(category="system_management", confidence=0.8)
        assert not should_use_llm(result)  # 0.8 >= 0.7 (default config threshold)


class TestCategoryModeDomain:
    """All categories have correct mode/domain mappings."""

    def test_system_management_mapping(self):
        assert CATEGORY_TO_MODE["system_management"] == "react"
        assert CATEGORY_TO_DOMAIN["system_management"] == "system"

    def test_file_operation_mapping(self):
        assert CATEGORY_TO_MODE["file_operation"] == "react"
        assert CATEGORY_TO_DOMAIN["file_operation"] == "filesystem"

    def test_planning_task_mapping(self):
        assert CATEGORY_TO_MODE["planning_task"] == "plan"
        assert CATEGORY_TO_DOMAIN["planning_task"] == "general"

    def test_conversation_mapping(self):
        assert CATEGORY_TO_MODE["conversation"] == "react"
        assert CATEGORY_TO_DOMAIN["conversation"] == "general"
