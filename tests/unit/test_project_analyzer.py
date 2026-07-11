"""Tests for the Project Analyzer tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paios.tools.project_analyzer import (
    ProjectAnalyzerTool,
    analyze_project,
    _detect_issues,
    _detect_technologies,
)


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a small sample project for testing."""
    root = tmp_path / "myproject"
    root.mkdir()
    (root / "src").mkdir()
    (root / "tests").mkdir()

    (root / "README.md").write_text("# My Project")
    (root / "main.py").write_text("print('hello')")
    (root / "src" / "utils.py").write_text("def helper(): pass")
    (root / "src" / "styles.css").write_text("body { color: red; }")
    (root / "src" / "app.js").write_text("console.log('hello')")
    (root / "tests" / "test_main.py").write_text("def test_main(): pass")
    (root / "package.json").write_text(json.dumps({
        "name": "myproject",
        "dependencies": {"react": "^18.0", "lodash": "^4.17"},
        "devDependencies": {"jest": "^29.0"},
    }))
    (root / ".hidden_file").write_text("secret")
    return root


class TestProjectAnalyzer:
    def test_analyze_detects_file_count(self, sample_project):
        analysis = analyze_project(sample_project, max_depth=5, include_hidden=False)
        assert analysis.file_count >= 6  # main.py, utils.py, styles.css, app.js, test_main.py, package.json
        assert analysis.structure["type"] == "dir"

    def test_analyze_technologies(self, sample_project):
        analysis = analyze_project(sample_project, max_depth=5)
        techs = {t["name"] for t in analysis.technologies}
        assert "Python" in techs
        assert "JavaScript" in techs
        assert "HTML/CSS" in techs

    def test_analyze_issues(self, sample_project):
        analysis = analyze_project(sample_project, max_depth=5)
        issues = [i["message"] for i in analysis.issues]
        # Has test directory, so no "no tests" issue.
        assert "No test files or test directories found" not in issues

    def test_analyze_dependencies(self, sample_project):
        analysis = analyze_project(sample_project, max_depth=5)
        assert "npm" in analysis.dependencies
        assert "react" in analysis.dependencies["npm"]
        assert "lodash" in analysis.dependencies["npm"]

    def test_analyze_custom_depth(self, sample_project):
        # Very shallow depth should limit files found.
        analysis = analyze_project(sample_project, max_depth=0)
        # At depth 0, only immediate children of root, not subdirs.
        assert analysis.file_count >= 2  # At least README.md, main.py

    def test_analyze_nonexistent_path(self, tmp_path):
        with pytest.raises(Exception):
            analyze_project(tmp_path / "nonexistent")

    def test_detect_technologies_empty(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        analysis = analyze_project(empty_dir)
        assert analysis.technologies == []
        assert analysis.file_count == 0

    def test_tool_schema(self):
        assert ProjectAnalyzerTool.name == "project_analyzer"
        schema = ProjectAnalyzerTool.schema_for_llm()
        assert "path" in str(schema)
        assert "max_depth" in str(schema)


class TestProjectAnalyzerTool:
    @pytest.mark.asyncio
    async def test_tool_run(self, sandbox_root, settings_with_sandbox):
        """Create project inside sandbox_root so path validation passes."""
        proj = sandbox_root / "myproject"
        proj.mkdir()
        (proj / "README.md").write_text("# Hello")
        (proj / "main.py").write_text("print('hi')")
        (proj / "src").mkdir()
        (proj / "src" / "utils.py").write_text("def f(): pass")

        tool = ProjectAnalyzerTool()
        ctx = type("ctx", (), {"task_public_id": "test"})()
        result = await tool.run(ctx, path=str(proj), max_depth=5)
        assert result.ok
        assert "Project Analysis" in result.output

    @pytest.mark.asyncio
    async def test_tool_nonexistent(self, sandbox_root, settings_with_sandbox):
        tool = ProjectAnalyzerTool()
        ctx = type("ctx", (), {"task_public_id": "test"})()
        result = await tool.run(ctx, path=str(sandbox_root / "nope"))
        assert not result.ok

    @pytest.mark.asyncio
    async def test_tool_not_a_directory(self, sandbox_root, settings_with_sandbox):
        f = sandbox_root / "some_file.txt"
        f.write_text("hello")
        tool = ProjectAnalyzerTool()
        ctx = type("ctx", (), {"task_public_id": "test"})()
        result = await tool.run(ctx, path=str(f))
        assert not result.ok
        assert "not a directory" in result.error
