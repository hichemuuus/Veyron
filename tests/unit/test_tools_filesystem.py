"""Tests for the filesystem_read tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from paios.tools.base import ToolContext
from paios.tools.filesystem_read import FilesystemReadTool


@pytest.fixture
def tool():
    return FilesystemReadTool()


@pytest.fixture
def ctx():
    return ToolContext(task_public_id="test")


async def test_read_file(tool, ctx, sandbox_root: Path):
    f = sandbox_root / "hello.txt"
    f.write_text("hello world")
    result = await tool.safe_run(ctx, operation="read_file", path=str(f))
    assert result.ok
    assert "hello world" in result.output


async def test_read_file_truncated(tool, ctx, sandbox_root: Path):
    f = sandbox_root / "big.txt"
    f.write_text("x" * 1000)
    result = await tool.safe_run(ctx, operation="read_file", path=str(f), max_bytes=100)
    assert result.ok
    assert len(result.output) <= 100
    assert result.data["truncated"] is True


async def test_read_file_not_found(tool, ctx, sandbox_root: Path):
    result = await tool.safe_run(ctx, operation="read_file", path=str(sandbox_root / "nope.txt"))
    assert not result.ok
    assert "not found" in result.error.lower()


async def test_read_directory_as_file(tool, ctx, sandbox_root: Path):
    result = await tool.safe_run(ctx, operation="read_file", path=str(sandbox_root))
    assert not result.ok
    assert "directory" in result.error.lower()


async def test_list_dir(tool, ctx, sandbox_root: Path):
    (sandbox_root / "a.txt").write_text("a")
    (sandbox_root / "sub").mkdir()
    result = await tool.safe_run(ctx, operation="list_dir", path=str(sandbox_root))
    assert result.ok
    assert any(e["name"] == "a.txt" for e in result.data["entries"])
    assert any(e["name"] == "sub" and e["type"] == "dir" for e in result.data["entries"])


async def test_list_dir_not_found(tool, ctx, sandbox_root: Path):
    result = await tool.safe_run(ctx, operation="list_dir", path=str(sandbox_root / "nope"))
    assert not result.ok


async def test_stat(tool, ctx, sandbox_root: Path):
    f = sandbox_root / "stat.txt"
    f.write_text("data")
    result = await tool.safe_run(ctx, operation="stat", path=str(f))
    assert result.ok
    assert result.data["is_file"] is True
    assert result.data["size"] == 4


async def test_path_outside_sandbox_rejected(tool, ctx, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    result = await tool.safe_run(ctx, operation="read_file", path=str(outside))
    assert not result.ok
    assert "outside sandbox" in result.error.lower() or "sandbox" in result.error.lower()


async def test_invalid_inputs_rejected(tool, ctx, sandbox_root: Path):
    # operation must be one of the enum values
    result = await tool.safe_run(ctx, operation="delete", path=str(sandbox_root))
    assert not result.ok


async def test_tool_result_llm_text_includes_output(tool, ctx, sandbox_root: Path):
    f = sandbox_root / "f.txt"
    f.write_text("visible content")
    result = await tool.safe_run(ctx, operation="read_file", path=str(f))
    assert "visible content" in result.as_llm_text()
