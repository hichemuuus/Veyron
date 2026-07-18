"""Tests for dataset preparation pipeline: validator, splitter, formatter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from veyron.intelligence.training.dataset import TrainingDataset, TrainingExample
from veyron.intelligence.training.preparation.formatter import DatasetFormatter
from veyron.intelligence.training.preparation.splitter import (
    INTENT_CATEGORIES,
    DatasetSplitter,
    load_jsonl_as_examples,
)
from veyron.intelligence.training.preparation.validator import (
    DatasetValidator,
    ValidationReport,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_examples() -> list[TrainingExample]:
    return [
        TrainingExample(
            request="show cpu usage",
            intent="system_management",
            tools_used=["system_monitor"],
            task_id="t1",
            metadata={"difficulty": "easy", "planning_required": False, "expected_parameters": {"metric": "cpu"}},
        ),
        TrainingExample(
            request="read the readme",
            intent="file_operation",
            tools_used=["filesystem_read"],
            task_id="t2",
            metadata={"difficulty": "easy", "planning_required": False, "expected_parameters": {"path": "README.md"}},
        ),
        TrainingExample(
            request="analyze the project",
            intent="project_analysis",
            tools_used=["project_analyzer"],
            task_id="t3",
            metadata={"difficulty": "moderate", "planning_required": True, "expected_parameters": {"path": "."}},
        ),
        TrainingExample(
            request="run npm install",
            intent="tool_execution",
            tools_used=["terminal"],
            task_id="t4",
            metadata={"difficulty": "easy", "planning_required": False, "expected_parameters": {"command": "npm install"}},
        ),
        TrainingExample(
            request="debug the build failure",
            intent="debugging",
            tools_used=["terminal", "filesystem_read"],
            task_id="t5",
            metadata={"difficulty": "hard", "planning_required": True, "expected_parameters": {"command": "npm run build"}},
        ),
    ]


@pytest.fixture
def sample_dataset(sample_examples) -> TrainingDataset:
    return TrainingDataset(sample_examples)


@pytest.fixture
def tmp_jsonl(tmp_path: Path) -> Path:
    path = tmp_path / "test_data.jsonl"
    records = [
        {"request": "show cpu", "intent": "system_management", "expected_tools": ["system_monitor"], "difficulty": "easy", "planning_required": False},
        {"request": "read file", "intent": "file_operation", "expected_tools": ["filesystem_read"], "difficulty": "easy", "planning_required": False},
        {"request": "bad intent", "intent": "invalid_category", "expected_tools": ["terminal"], "difficulty": "easy", "planning_required": False},
        {"request": "bad tool", "intent": "tool_execution", "expected_tools": ["nonexistent_tool"], "difficulty": "moderate", "planning_required": False},
        {"request": "missing intent", "expected_tools": ["terminal"], "difficulty": "easy", "planning_required": False},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


# ── Validator tests ───────────────────────────────────────────────────────────

def test_validate_valid_jsonl(tmp_jsonl: Path):
    validator = DatasetValidator(known_tools=["system_monitor", "filesystem_read", "terminal", "project_analyzer"])
    report = validator.validate_jsonl(tmp_jsonl)
    assert report.total == 5
    assert report.valid >= 0
    assert report.invalid >= 1
    assert len(report.invalid_intents) >= 1
    assert len(report.invalid_tools) >= 1
    assert len(report.missing_fields) >= 1


def test_validate_dataset_valid(sample_dataset: TrainingDataset):
    validator = DatasetValidator(known_tools=["system_monitor", "filesystem_read", "project_analyzer", "terminal"])
    report = validator.validate_dataset(sample_dataset)
    assert report.total == 5
    assert report.valid == 5
    assert report.invalid == 0


def test_validate_dataset_invalid_intent():
    dataset = TrainingDataset([
        TrainingExample(request="test", intent="invalid_category", tools_used=["terminal"], task_id="bad"),
    ])
    validator = DatasetValidator(known_tools=["terminal"])
    report = validator.validate_dataset(dataset)
    assert report.invalid == 1
    assert len(report.invalid_intents) == 1


def test_validate_dataset_unknown_tool():
    dataset = TrainingDataset([
        TrainingExample(request="test", intent="tool_execution", tools_used=["unknown_tool"], task_id="bad"),
    ])
    validator = DatasetValidator(known_tools=["terminal"])
    report = validator.validate_dataset(dataset)
    assert report.invalid == 1
    assert len(report.invalid_tools) == 1


def test_validate_dataset_empty_request():
    dataset = TrainingDataset([
        TrainingExample(request="", intent="conversation", tools_used=[], task_id="empty"),
    ])
    validator = DatasetValidator(known_tools=[])
    report = validator.validate_dataset(dataset)
    assert report.invalid >= 1


def test_validate_duplicate_detection():
    dataset = TrainingDataset([
        TrainingExample(request="hello", intent="conversation", tools_used=[], task_id="a"),
        TrainingExample(request="hello", intent="conversation", tools_used=[], task_id="b"),
    ])
    validator = DatasetValidator(known_tools=[])
    report = validator.validate_dataset(dataset)
    assert len(report.duplicates) >= 1


def test_validation_report_to_dict():
    report = ValidationReport()
    report.total = 100
    report.valid = 95
    report.invalid = 5
    report.missing_fields.append({"line": 1, "error": "test"})
    report.intent_distribution = {"conversation": 50, "system_management": 50}
    d = report.to_dict()
    assert d["total"] == 100
    assert d["valid"] == 95
    assert d["pass_rate"] == 0.95
    assert d["issues"]["missing_fields"] == 1
    assert d["intent_distribution"]["conversation"] == 50


def test_validate_jsonl_invalid_json(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    path.write_text("not json\n{\"valid\": true}", encoding="utf-8")
    validator = DatasetValidator(known_tools=[])
    report = validator.validate_jsonl(path)
    assert report.total == 2
    assert report.invalid >= 1


# ── Splitter tests ────────────────────────────────────────────────────────────

def test_stratified_split_preserves_total(sample_dataset: TrainingDataset):
    splitter = DatasetSplitter()
    train, test = splitter.stratified_split(sample_dataset, train_ratio=0.8, seed=42)
    assert len(train) + len(test) == len(sample_dataset)


def test_stratified_split_approximate_ratio():
    examples = [
        TrainingExample(request=f"req_{i}", intent="conversation", tools_used=[], task_id=f"t{i}")
        for i in range(20)
    ]
    dataset = TrainingDataset(examples)
    splitter = DatasetSplitter()
    train, test = splitter.stratified_split(dataset, train_ratio=0.8, seed=42)
    total = len(train) + len(test)
    actual_ratio = len(train) / total if total > 0 else 0
    assert 0.7 <= actual_ratio <= 0.9


def test_stratified_split_preserves_categories(sample_dataset: TrainingDataset):
    splitter = DatasetSplitter()
    train, test = splitter.stratified_split(sample_dataset, train_ratio=0.8, seed=42)
    train_cats = {e.intent for e in train}
    test_cats = {e.intent for e in test}
    for ex in sample_dataset:
        assert ex.intent in train_cats or ex.intent in test_cats


def test_stratified_split_all_same_category():
    examples = [
        TrainingExample(request=f"req_{i}", intent="conversation", tools_used=[], task_id=f"t{i}")
        for i in range(20)
    ]
    dataset = TrainingDataset(examples)
    splitter = DatasetSplitter()
    train, test = splitter.stratified_split(dataset, train_ratio=0.8, seed=42)
    assert len(train) + len(test) == 20
    assert 14 <= len(train) <= 18
    assert 2 <= len(test) <= 6


def test_stratified_split_raises_on_bad_ratio(sample_dataset: TrainingDataset):
    splitter = DatasetSplitter()
    with pytest.raises(ValueError):
        splitter.stratified_split(sample_dataset, train_ratio=0.0)
    with pytest.raises(ValueError):
        splitter.stratified_split(sample_dataset, train_ratio=1.0)


def test_split_by_field():
    examples = [
        TrainingExample(request="easy task", intent="system_management", tools_used=[], task_id="e1",
                        metadata={"difficulty": "easy"}),
        TrainingExample(request="hard task", intent="debugging", tools_used=[], task_id="h1",
                        metadata={"difficulty": "hard"}),
    ]
    dataset = TrainingDataset(examples * 5)
    splitter = DatasetSplitter()
    train, test = splitter.split_by_field(dataset, field="difficulty", train_ratio=0.8, seed=42)
    assert len(train) + len(test) == len(dataset)


def test_load_jsonl_as_examples(tmp_path: Path):
    path = tmp_path / "source.jsonl"
    records = [
        {"request": "hello", "intent": "conversation", "expected_tools": [], "difficulty": "easy", "planning_required": False},
        {"request": "show cpu", "intent": "system_management", "expected_tools": ["system_monitor"], "difficulty": "easy", "planning_required": False},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    dataset = load_jsonl_as_examples(path)
    assert len(dataset) == 2
    assert dataset[0].request == "hello"
    assert dataset[0].intent == "conversation"
    assert dataset[1].tools_used == ["system_monitor"]


def test_load_jsonl_skips_empty_lines(tmp_path: Path):
    path = tmp_path / "mixed.jsonl"
    path.write_text('{"request": "a", "intent": "conversation", "expected_tools": [], "difficulty": "easy", "planning_required": false}\n\n\n{"request": "b", "intent": "conversation", "expected_tools": [], "difficulty": "easy", "planning_required": false}\n', encoding="utf-8")
    dataset = load_jsonl_as_examples(path)
    assert len(dataset) == 2


# ── Formatter tests ───────────────────────────────────────────────────────────

def test_format_intent_classification(sample_dataset: TrainingDataset, tmp_path: Path):
    formatter = DatasetFormatter(output_dir=tmp_path)
    path = formatter.format_intent_classification(sample_dataset, filename="intent.jsonl")
    assert path.exists()
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) == 5
    for line in lines:
        assert "text" in line
        assert "intent" in line


def test_format_tool_selection(sample_dataset: TrainingDataset, tmp_path: Path):
    formatter = DatasetFormatter(output_dir=tmp_path)
    path = formatter.format_tool_selection(sample_dataset, filename="tools.jsonl")
    assert path.exists()
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) == 5
    for line in lines:
        assert "text" in line
        assert "tools" in line


def test_format_parameter_generation(sample_dataset: TrainingDataset, tmp_path: Path):
    formatter = DatasetFormatter(output_dir=tmp_path)
    path = formatter.format_parameter_generation(sample_dataset, filename="params.jsonl")
    assert path.exists()
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) >= 5
    for line in lines:
        assert "text" in line
        assert "tool" in line
        assert "parameters" in line


def test_format_planner_training(sample_dataset: TrainingDataset, tmp_path: Path):
    formatter = DatasetFormatter(output_dir=tmp_path)
    path = formatter.format_planner_training(sample_dataset, filename="planner.jsonl")
    assert path.exists()
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert len(lines) == 5
    for line in lines:
        assert "text" in line
        assert "planning_required" in line
        assert "difficulty" in line
        assert "mode" in line


def test_format_all_returns_all_keys(sample_dataset: TrainingDataset, tmp_path: Path):
    formatter = DatasetFormatter(output_dir=tmp_path)
    result = formatter.format_all(sample_dataset, prefix="test")
    assert set(result.keys()) == {"intent_classification", "tool_selection", "parameter_generation", "planner_training"}
    for path in result.values():
        assert path.exists()


def test_format_planner_training_planning_flag(tmp_path: Path):
    examples = [
        TrainingExample(request="simple task", intent="conversation", tools_used=[], task_id="s",
                        metadata={"planning_required": False, "difficulty": "easy"}),
        TrainingExample(request="complex task", intent="planning_task", tools_used=["terminal", "filesystem_read"], task_id="c",
                        metadata={"planning_required": True, "difficulty": "hard"}),
    ]
    dataset = TrainingDataset(examples)
    formatter = DatasetFormatter(output_dir=tmp_path)
    path = formatter.format_planner_training(dataset, filename="plan_test.jsonl")
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    simple = [l for l in lines if l["planning_required"] is False]
    complex_records = [l for l in lines if l["planning_required"] is True]
    assert len(simple) == 1
    assert len(complex_records) == 1
    assert complex_records[0]["mode"] == "plan"
    assert simple[0]["mode"] == "react"


def test_format_skips_empty_request(tmp_path: Path):
    dataset = TrainingDataset([
        TrainingExample(request="", intent="conversation", tools_used=[], task_id="empty"),
    ])
    formatter = DatasetFormatter(output_dir=tmp_path)
    path = formatter.format_intent_classification(dataset, filename="empty_test.jsonl")
    with open(path, encoding="utf-8") as f:
        content = f.read().strip()
    assert content == ""


def test_intent_categories_are_defined():
    assert len(INTENT_CATEGORIES) == 13
    assert "conversation" in INTENT_CATEGORIES
    assert "system_management" in INTENT_CATEGORIES
    assert "file_operation" in INTENT_CATEGORIES
    assert "tool_execution" in INTENT_CATEGORIES
    assert "project_analysis" in INTENT_CATEGORIES
    assert "debugging" in INTENT_CATEGORIES
    assert "coding_task" in INTENT_CATEGORIES
    assert "planning_task" in INTENT_CATEGORIES
    assert "question_answering" in INTENT_CATEGORIES
    assert "research" in INTENT_CATEGORIES
