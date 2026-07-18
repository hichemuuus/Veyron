"""Shared test fixtures.

Each test gets an isolated in-memory DB, a fresh event bus, and a temporary
sandbox root so nothing touches the user's real filesystem.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from veyron import config as config_module


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    """Redirect backend/data to a tmp dir for every test."""
    tmp = tmp_path_factory.mktemp("veyron_data")
    monkeypatch.setattr(config_module, "DATA_DIR", tmp)
    # Also patch where audit/db files are written.
    from veyron.security import audit as audit_module

    monkeypatch.setattr(audit_module, "AUDIT_DIR", tmp / "audit")
    yield tmp


@pytest.fixture
def sandbox_root(tmp_path) -> Path:
    """A writable directory used as the only sandbox root."""
    root = tmp_path / "sandbox"
    root.mkdir()
    return root


@pytest.fixture(autouse=True)
def settings_with_sandbox(sandbox_root, monkeypatch):
    """Force settings to use only the temp sandbox root."""
    import json

    from veyron.config import get_settings, reset_settings_cache

    reset_settings_cache()
    monkeypatch.setenv("VEYRON_SECURITY__SANDBOX_ROOTS", json.dumps([str(sandbox_root)]))
    # Re-import path policy so it picks up new settings on next validate.
    from veyron.security import path_policy

    monkeypatch.setattr(path_policy, "_load_roots", lambda: [sandbox_root.resolve()])
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all process-wide singletons between tests."""
    from veyron.core.agent import reset_agent
    from veyron.core.events import reset_bus
    from veyron.core.task_manager import reset_task_manager
    from veyron.db.base import reset_async_engine, reset_sync_engine
    from veyron.llm.base import reset_provider
    from veyron.monitor.service import disable_monitor, reset_monitor
    from veyron.security.confirmations import reset_manager
    from veyron.tools.registry import reset_registry

    reset_sync_engine()
    reset_async_engine()
    reset_registry()
    reset_bus()
    reset_manager()
    reset_provider()
    reset_agent()
    reset_task_manager()
    reset_monitor()
    disable_monitor()
    yield
    reset_sync_engine()
    reset_async_engine()
    reset_registry()
    reset_bus()
    reset_manager()
    reset_provider()
    reset_agent()
    reset_task_manager()
    reset_monitor()


@pytest.fixture
def fresh_db(isolated_data_dir):
    """Initialize an isolated SQLite DB."""
    from veyron.db.base import get_sync_engine, init_db

    init_db()
    yield
    # Dispose engine so next test gets a fresh file.
    engine = get_sync_engine()
    engine.dispose()


class StubProvider:
    """A fake LLM provider for deterministic agent tests.

    Yields a scripted sequence of responses (text and/or tool calls).
    """

    def __init__(self, responses: list):
        # responses: list of either str (final answer) or dict (tool call)
        self.responses = list(responses)
        self.calls = 0

    @property
    def name(self):
        return "stub"

    async def is_available(self):
        return True

    async def embed(self, text):
        return [0.0, 0.0, 0.0]

    async def generate_stream(self, messages, opts):
        from veyron.llm.base import GenerateChunk

        idx = self.calls
        self.calls += 1
        if idx >= len(self.responses):
            yield GenerateChunk(text="(no further output)", done=True, finish_reason="stop")
            return
        resp = self.responses[idx]
        if isinstance(resp, str):
            yield GenerateChunk(text=resp, done=True, finish_reason="stop")
        else:
            # Tool call dict {"name":..., "arguments":...}
            yield GenerateChunk(tool_call={"id": f"call_{idx}", **resp}, done=True, finish_reason="tool_use")


@pytest.fixture
def stub_provider():
    """Builder: returns a function that constructs a StubProvider."""
    return StubProvider
