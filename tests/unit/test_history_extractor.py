"""Tests for the agent history extraction pipeline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from paios.intelligence.history.extractor import HistoryExtractor


class TestHistoryExtractor:
    """Tests for the HistoryExtractor class."""

    def test_init_creates_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            extractor = HistoryExtractor(output_dir=tmp)
            assert Path(tmp).exists()

    def test_infer_intent_from_filesystem_tool(self):
        extractor = HistoryExtractor()
        intent = extractor._infer_intent_from_tools(["filesystem_read"], "list all files")
        assert intent == "file_operation"

    def test_infer_intent_from_system_tool(self):
        extractor = HistoryExtractor()
        intent = extractor._infer_intent_from_tools(["system_monitor"], "check cpu")
        assert intent == "system_management"

    def test_infer_intent_from_terminal_tool(self):
        extractor = HistoryExtractor()
        intent = extractor._infer_intent_from_tools(["terminal"], "run tests")
        assert intent == "tool_execution"

    def test_infer_intent_from_analyzer_tool(self):
        extractor = HistoryExtractor()
        intent = extractor._infer_intent_from_tools(["project_analyzer"], "analyze project")
        assert intent == "project_analysis"

    def test_infer_intent_multi_tool_planning(self):
        extractor = HistoryExtractor()
        intent = extractor._infer_intent_from_tools(
            ["filesystem_read", "project_analyzer"], "first read then analyze"
        )
        assert intent == "planning_task"

    def test_infer_intent_multi_tool_debugging(self):
        extractor = HistoryExtractor()
        intent = extractor._infer_intent_from_tools(
            ["filesystem_read", "terminal"], "debug this error in the log"
        )
        assert intent == "debugging"

    def test_infer_intent_question(self):
        extractor = HistoryExtractor()
        intent = extractor._infer_intent_from_tools([], "What is the meaning of life?")
        assert intent == "question_answering"

    def test_infer_intent_conversation(self):
        extractor = HistoryExtractor()
        intent = extractor._infer_intent_from_tools([], "hello")
        assert intent == "conversation"

    def test_generate_intent_dataset_from_history(self):
        extractor = HistoryExtractor()
        successful = [
            {"request": "check the cpu usage", "tools_used": ["system_monitor"], "outcome": "completed"},
            {"request": "read the file please", "tools_used": ["filesystem_read"], "outcome": "done"},
        ]
        failed = [
            {"request": "deploy the app", "tools_used": ["terminal"], "error": "timeout"},
        ]
        dataset = extractor.generate_intent_dataset_from_history(successful, failed)
        assert len(dataset) == 3
        texts = [ex["text"] for ex in dataset.examples]
        assert "check the cpu usage" in texts
        assert "read the file please" in texts
        assert "deploy the app" in texts

    def test_save_to_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            extractor = HistoryExtractor(output_dir=tmp)
            data = [{"request": "test", "tools_used": ["terminal"]}]
            path = extractor.save_to_jsonl(data, "test.jsonl")
            assert path.exists()
            with open(path, encoding="utf-8") as f:
                line = f.readline().strip()
                obj = json.loads(line)
                assert obj["request"] == "test"

    def test_save_to_jsonl_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            extractor = HistoryExtractor(output_dir=tmp)
            path = extractor.save_to_jsonl([], "empty.jsonl")
            assert path.exists()
            with open(path, encoding="utf-8") as f:
                content = f.read()
                assert content == ""

    @patch("paios.intelligence.history.extractor.HistoryExtractor.extract_from_tracker")
    @patch("paios.intelligence.history.extractor.HistoryExtractor.extract_from_eval_results")
    @patch("paios.intelligence.history.extractor.HistoryExtractor.extract_from_tool_invocations")
    def test_run_full_extraction(
        self, mock_tool, mock_eval, mock_tracker
    ):
        mock_tracker.return_value = (
            [{"request": "test", "tools_used": ["terminal"], "outcome": "ok"}],
            [],
        )
        mock_eval.return_value = ([], [])
        mock_tool.return_value = []

        with tempfile.TemporaryDirectory() as tmp:
            extractor = HistoryExtractor(output_dir=tmp)
            result = extractor.run_full_extraction()
            assert result["tracker_successful"] == 1
            assert result["tracker_failed"] == 0
            assert result["eval_successful"] == 0
