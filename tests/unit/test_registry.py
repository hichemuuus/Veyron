"""Tests for the tool registry and schema generation."""

from __future__ import annotations

import pytest

from paios.tools.registry import get_registry, reset_registry


def test_registry_discovers_three_tools():
    reset_registry()
    reg = get_registry()
    names = reg.names()
    assert "filesystem_read" in names
    assert "system_monitor" in names
    assert "terminal" in names
    assert len(names) >= 3


def test_get_returns_tool_instance():
    reset_registry()
    reg = get_registry()
    t = reg.get("system_monitor")
    assert t is not None
    assert t.name == "system_monitor"


def test_get_unknown_returns_none():
    reset_registry()
    reg = get_registry()
    assert reg.get("does_not_exist") is None


def test_schemas_for_llm_have_required_fields():
    reset_registry()
    reg = get_registry()
    for schema in reg.schemas_for():
        assert "name" in schema
        assert "description" in schema
        assert "permission" in schema
        assert "parameters" in schema
        # permission is a valid level
        assert schema["permission"] in {"free", "confirm", "restricted"}


def test_schemas_subset():
    reset_registry()
    reg = get_registry()
    subset = reg.schemas_for(["system_monitor"])
    assert len(subset) == 1
    assert subset[0]["name"] == "system_monitor"


def test_schemas_unknown_skipped():
    reset_registry()
    reg = get_registry()
    subset = reg.schemas_for(["system_monitor", "fake_tool"])
    assert len(subset) == 1


def test_filesystem_tool_permission_is_free():
    reset_registry()
    reg = get_registry()
    t = reg.get("filesystem_read")
    assert t.permission.value == "free"


def test_terminal_tool_permission_is_confirm():
    reset_registry()
    reg = get_registry()
    t = reg.get("terminal")
    assert t.permission.value == "confirm"
