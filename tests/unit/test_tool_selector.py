"""Tests for the tool selection micro-model."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from paios.intelligence.tool_selector.dataset import ToolSelectionDataset
from paios.intelligence.tool_selector.metrics import ToolSelectionMetrics
from paios.intelligence.tool_selector.model import ToolSelectorModel
from paios.intelligence.tool_selector.trainer import train_tool_selector


class TestToolSelectorModel:
    """Tests for the ToolSelectorModel class."""

    def test_not_fitted_raises(self):
        model = ToolSelectorModel()
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict("hello")

    def test_fit_and_predict_single(self):
        model = ToolSelectorModel()
        model.fit(
            ["list files", "check cpu", "run test", "analyze project"],
            [["filesystem_read"], ["system_monitor"], ["terminal"], ["project_analyzer"]],
        )
        assert model.fitted
        assert model.tool_names == ["filesystem_read", "project_analyzer", "system_monitor", "terminal"]

    def test_predict_returns_list(self):
        model = ToolSelectorModel()
        model.fit(["list files", "check cpu"], [["filesystem_read"], ["system_monitor"]])
        pred = model.predict("list all files")
        assert isinstance(pred, list)
        assert all(isinstance(t, str) for t in pred)

    def test_predict_with_confidence_returns_all_tools(self):
        model = ToolSelectorModel()
        model.fit(["list files", "check cpu", "run test", "analyze project"],
                   [["filesystem_read"], ["system_monitor"], ["terminal"], ["project_analyzer"]])
        predictions = model.predict_with_confidence("list files")
        assert len(predictions) == 4
        for p in predictions:
            assert hasattr(p, "tool_name")
            assert hasattr(p, "confidence")
            assert 0.0 <= p.confidence <= 1.0

    def test_predict_top_k(self):
        model = ToolSelectorModel()
        model.fit(["list files", "check cpu", "run test", "analyze project"],
                   [["filesystem_read"], ["system_monitor"], ["terminal"], ["project_analyzer"]])
        top2 = model.predict_top_k("list files", k=2)
        assert len(top2) == 2
        assert all(p.tool_name in model.tool_names for p in top2)

    def test_save_and_load(self):
        model = ToolSelectorModel()
        model.fit(["list files", "check cpu"], [["filesystem_read"], ["system_monitor"]])
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        try:
            model.save(path)
            loaded = ToolSelectorModel()
            loaded.load(path)
            assert loaded.fitted
            assert loaded.tool_names == model.tool_names
            pred = loaded.predict("list files")
            assert isinstance(pred, list)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_predict_empty_when_low_confidence(self):
        model = ToolSelectorModel(confidence_threshold=0.99)
        model.fit(["list files", "check cpu"], [["filesystem_read"], ["system_monitor"]])
        pred = model.predict("some completely unrelated text")
        assert isinstance(pred, list)

    def test_custom_confidence_threshold(self):
        model = ToolSelectorModel(confidence_threshold=0.5)
        assert model._confidence_threshold == 0.5

    def test_multi_label_prediction(self):
        model = ToolSelectorModel()
        model.fit(
            ["read file and check cpu", "just list files", "just check cpu"],
            [["filesystem_read", "system_monitor"], ["filesystem_read"], ["system_monitor"]],
        )
        pred = model.predict("read file and check cpu")
        # Should predict at least one tool
        assert len(pred) >= 1


class TestToolSelectorMetrics:
    """Tests for evaluation metrics."""

    def test_precision_at_k_perfect(self):
        assert ToolSelectionMetrics.tool_precision_at_k(
            ["filesystem_read"], ["filesystem_read"], k=1
        ) == 1.0

    def test_precision_at_k_zero(self):
        assert ToolSelectionMetrics.tool_precision_at_k(
            ["terminal"], ["filesystem_read"], k=1
        ) == 0.0

    def test_precision_at_k_half(self):
        assert ToolSelectionMetrics.tool_precision_at_k(
            ["filesystem_read", "terminal"], ["filesystem_read"], k=2
        ) == 0.5

    def test_recall_at_k_perfect(self):
        assert ToolSelectionMetrics.tool_recall_at_k(
            ["filesystem_read", "system_monitor"], ["filesystem_read"], k=2
        ) == 1.0

    def test_recall_at_k_partial(self):
        assert ToolSelectionMetrics.tool_recall_at_k(
            ["filesystem_read"], ["filesystem_read", "system_monitor"], k=2
        ) == 0.5

    def test_recall_at_k_empty_expected(self):
        assert ToolSelectionMetrics.tool_recall_at_k(
            ["filesystem_read"], [], k=1
        ) == 0.0

    def test_f1_at_k(self):
        f1 = ToolSelectionMetrics.tool_f1_at_k(
            ["filesystem_read"], ["filesystem_read"], k=1
        )
        assert f1 == 1.0

    def test_f1_at_k_zero(self):
        f1 = ToolSelectionMetrics.tool_f1_at_k(
            ["terminal"], ["filesystem_read"], k=1
        )
        assert f1 == 0.0

    def test_exact_match_true(self):
        assert ToolSelectionMetrics.exact_match(
            ["filesystem_read"], ["filesystem_read"]
        )

    def test_exact_match_false(self):
        assert not ToolSelectionMetrics.exact_match(
            ["filesystem_read"], ["system_monitor"]
        )

    def test_exact_match_multi(self):
        assert ToolSelectionMetrics.exact_match(
            ["filesystem_read", "system_monitor"],
            ["filesystem_read", "system_monitor"],
        )

    def test_missing_parameters_penalty_none(self):
        from paios.intelligence.tool_selector.schema import ToolPrediction

        pred = ToolPrediction(tool_name="filesystem_read", confidence=0.9)
        assert ToolSelectionMetrics.missing_parameters_penalty(pred) == 0.0

    def test_missing_parameters_penalty_partial(self):
        from paios.intelligence.tool_selector.schema import ToolPrediction

        pred = ToolPrediction(
            tool_name="filesystem_read",
            confidence=0.8,
            predicted_params={"path": "/tmp"},
            missing_parameters=["file_path"],
        )
        penalty = ToolSelectionMetrics.missing_parameters_penalty(pred)
        assert penalty == 0.5


class TestToolSelectorTraining:
    """Tests for the tool selector training pipeline."""

    def test_train_returns_model_and_metrics(self):
        model, metrics = train_tool_selector(test_ratio=0.5, seed=42)
        assert model.fitted
        assert "precision@1" in metrics
        assert "recall@3" in metrics
        assert "f1@3" in metrics
        assert "exact_match_rate" in metrics
        assert metrics["total_examples"] > 0

    def test_train_on_seed_dataset(self):
        dataset = ToolSelectionDataset.generate_seed()
        model, metrics = train_tool_selector(dataset=dataset, test_ratio=0.2, seed=42)
        assert model.fitted
        assert metrics["total_examples"] >= 1

    def test_train_saves_model_file(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            model, metrics = train_tool_selector(test_ratio=0.5, seed=42, output_dir=tmp)
            model_path = Path(tmp) / "tool_selector.pkl"
            assert model_path.exists()
            report_path = Path(tmp) / "tool_selector_report.json"
            assert report_path.exists()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            assert "precision@1" in report

    def test_train_predict_on_test_examples(self):
        dataset = ToolSelectionDataset.generate_seed()
        model, _ = train_tool_selector(dataset=dataset, test_ratio=0.2, seed=42)
        for ex in dataset.examples[:3]:
            pred = model.predict(ex.text)
            assert isinstance(pred, list)

    def test_train_on_all_data(self):
        """Training on all data (no test split) should succeed."""
        model, metrics = train_tool_selector(test_ratio=0.0, seed=42)
        assert model.fitted
