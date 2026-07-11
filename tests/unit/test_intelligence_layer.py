"""Tests for the core intelligence integration layer.

Covers:
  - Disabled micro-model mode (default) → falls through to heuristic router
  - Enabled micro-model with high confidence → uses classifier result
  - Enabled micro-model with low confidence → falls through to heuristic router
  - The classify_request function returns a valid Intent
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from paios.config import get_settings, reset_settings_cache
from paios.core.intelligence import classify_request
from paios.intelligence.intent.inference import reset_model
from paios.intelligence.intent.model import IntentModel
from paios.llm.micro.router import INTENT_CATEGORIES, Intent


@pytest.fixture(autouse=True)
def _reset_globals():
    reset_settings_cache()
    reset_model()
    yield


class TestIntelligenceLayerDisabled:
    """When micro_models_enabled=False (the default), the heuristic router is used."""

    def test_disabled_returns_intent(self):
        intent = classify_request("What is the CPU usage?")
        assert isinstance(intent, Intent)
        assert intent.mode in ("react", "plan")
        assert intent.domain in ("system", "filesystem", "project", "terminal", "general")
        assert 0.0 <= intent.confidence <= 1.0
        assert intent.intent_category is None  # Heuristic router doesn't set this

    def test_disabled_plan_request(self):
        intent = classify_request("First analyze the project, then generate a report")
        assert intent.mode == "plan"

    def test_disabled_simple_request(self):
        intent = classify_request("Hello")
        assert intent.mode == "react"

    def test_disabled_domain_system(self):
        intent = classify_request("Check the CPU usage")
        assert intent.domain == "system"

    def test_disabled_domain_filesystem(self):
        intent = classify_request("List files in the current directory")
        assert intent.domain == "filesystem"

    def test_disabled_domain_general(self):
        intent = classify_request("What is the capital of France?")
        assert intent.domain == "general"


class TestIntelligenceLayerEnabled:
    """When micro_models_enabled=True, the intent classifier runs first."""

    @pytest.fixture(autouse=True)
    def _enable_micro_models(self, monkeypatch):
        monkeypatch.setattr(
            get_settings().model, "micro_models_enabled", True
        )
        monkeypatch.setattr(
            get_settings().model, "micro_model_confidence_threshold", 0.7
        )

    def test_enabled_with_trained_model_high_confidence(self, monkeypatch):
        """With a trained model and high confidence, the classifier result is used."""
        from paios.intelligence.intent.inference import classify_intent

        monkeypatch.setattr(
            get_settings().model, "micro_model_confidence_threshold", 0.3
        )
        model = IntentModel()
        model.fit(
            ["check cpu usage right now please", "read the file contents", "hello my friend"],
            ["system_management", "file_operation", "conversation"],
        )
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            model_path = f.name
        try:
            model.save(model_path)
            # Train model and prime the global path.
            classify_intent("dummy", model_path=model_path)
            intent = classify_request("check cpu usage right now please")
            assert isinstance(intent, Intent)
            assert intent.intent_category == "system_management"
            assert intent.mode == "react"
            assert intent.domain == "system"
        finally:
            Path(model_path).unlink(missing_ok=True)
            reset_model()

    def test_enabled_fallback_still_returns_intent(self, monkeypatch):
        """Even without a trained model, the fallback classifier returns a valid intent."""
        monkeypatch.setattr(
            get_settings().model, "micro_model_confidence_threshold", 0.5
        )
        intent = classify_request("What is the CPU usage?")
        assert isinstance(intent, Intent)
        assert intent.intent_category == "system_management"
        assert intent.confidence > 0.0

    def test_enabled_low_confidence_falls_through(self, monkeypatch):
        """Low confidence classification falls through to heuristic router."""
        monkeypatch.setattr(
            get_settings().model, "micro_model_confidence_threshold", 0.9
        )
        intent = classify_request("What is the CPU usage?")
        # Fallback gives 0.6 for system_management, 0.6 < 0.9 → fall through
        # Heuristic router returns intent_category=None
        assert intent.intent_category is None


class TestIntentCategoryDefinitions:
    """All defined intent categories are properly registered."""

    def test_ten_categories(self):
        assert len(INTENT_CATEGORIES) == 10

    def test_all_categories_present(self):
        expected = {
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
        }
        assert set(INTENT_CATEGORIES) == expected


class TestClassifierResultFields:
    """Phase 2: ClassifierResult includes complexity/planning/LLM fields."""

    def test_fallback_result_has_all_fields(self):
        from paios.intelligence.intent.inference import classify_intent, reset_model
        reset_model()
        result = classify_intent("What is the CPU usage?")
        assert hasattr(result, "complexity")
        assert result.complexity in ("simple", "moderate", "complex")
        assert hasattr(result, "requires_tool")
        assert isinstance(result.requires_tool, bool)
        assert hasattr(result, "requires_planning")
        assert isinstance(result.requires_planning, bool)
        assert hasattr(result, "requires_llm")
        assert isinstance(result.requires_llm, bool)

    def test_fallback_routing_decision(self):
        from paios.intelligence.intent.inference import classify_intent, reset_model
        reset_model()
        result = classify_intent("Read the file README.md")
        assert result.category == "file_operation"
        assert result.complexity == "simple"
        assert result.requires_tool is True
        assert result.requires_planning is False

    def test_fallback_planning_routing(self):
        from paios.intelligence.intent.inference import classify_intent, reset_model
        reset_model()
        result = classify_intent("First do this step, then do that, after that finally do the next step")
        assert result.category == "planning_task"
        assert result.complexity == "complex"
        assert result.requires_planning is True

    def test_fallback_llm_escalation_on_low_confidence(self, monkeypatch):
        from paios.intelligence.intent.inference import classify_intent, reset_model
        from paios.config import get_settings
        reset_model()
        monkeypatch.setattr(get_settings().model, "micro_model_confidence_threshold", 0.9)
        result = classify_intent("What is the CPU usage?")
        assert result.requires_llm is True  # confidence 0.6 < 0.9

    def test_fallback_no_llm_on_high_confidence(self, monkeypatch):
        from paios.intelligence.intent.inference import classify_intent, reset_model
        from paios.config import get_settings
        reset_model()
        monkeypatch.setattr(get_settings().model, "micro_model_confidence_threshold", 0.3)
        result = classify_intent("What is the CPU usage?")
        assert result.requires_llm is False  # confidence 0.6 >= 0.3

    def test_intent_routing_uses_complexity(self):
        from paios.core.intelligence import classify_request
        from paios.config import get_settings
        intent = classify_request("Say hello")
        assert isinstance(intent.mode, str)


class TestToolSelectionPrep:
    """Tests for tool selection preparation (no training yet)."""

    def test_seed_dataset_generates_examples(self):
        from paios.intelligence.tool_selector.dataset import ToolSelectionDataset
        from paios.intelligence.tool_selector.schema import ToolSelectionExample

        dataset = ToolSelectionDataset.generate_seed()
        assert len(dataset) > 0
        assert all(isinstance(ex, ToolSelectionExample) for ex in dataset.examples)

    def test_seed_dataset_has_text_and_tools(self):
        from paios.intelligence.tool_selector.dataset import ToolSelectionDataset

        dataset = ToolSelectionDataset.generate_seed()
        for ex in dataset:
            assert ex.text
            assert ex.expected_tools
            assert ex.intent_category

    def test_seed_dataset_to_jsonl_and_back(self):
        from paios.intelligence.tool_selector.dataset import ToolSelectionDataset

        dataset = ToolSelectionDataset.generate_seed()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False, encoding="utf-8") as f:
            path = f.name
            dataset.to_jsonl(path)
        try:
            loaded = ToolSelectionDataset.from_jsonl(path)
            assert len(loaded) == len(dataset)
            for orig, loaded_ex in zip(dataset.examples, loaded.examples):
                assert orig.text == loaded_ex.text
                assert orig.expected_tools == loaded_ex.expected_tools
        finally:
            Path(path).unlink(missing_ok=True)

    def test_tool_selection_metrics(self):
        from paios.intelligence.tool_selector.metrics import ToolSelectionMetrics

        assert ToolSelectionMetrics.tool_precision_at_k(["filesystem_read"], ["filesystem_read"], k=1) == 1.0
        assert ToolSelectionMetrics.tool_precision_at_k(["terminal"], ["filesystem_read"], k=1) == 0.0
        assert ToolSelectionMetrics.tool_recall_at_k(
            ["filesystem_read", "system_monitor"], ["filesystem_read"], k=2
        ) == 1.0
        assert ToolSelectionMetrics.exact_match(["filesystem_read"], ["filesystem_read"])
        assert not ToolSelectionMetrics.exact_match(["filesystem_read"], ["system_monitor"])

    def test_tool_selection_tool_names(self):
        from paios.intelligence.tool_selector.schema import available_tool_names

        names = available_tool_names()
        assert "filesystem_read" in names
        assert "system_monitor" in names
