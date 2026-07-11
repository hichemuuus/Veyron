"""Tests for the confirmation manager."""

from __future__ import annotations

import pytest

from paios.core.events import get_bus
from paios.security.command_policy import PermissionLevel
from paios.security.confirmations import ConfirmationManager, get_manager, reset_manager


class TestConfirmationManager:
    @pytest.mark.asyncio
    async def test_request_and_respond(self):
        manager = ConfirmationManager(get_bus())
        # Respond in a background task.
        async def _respond_later():
            import asyncio
            await asyncio.sleep(0.01)
            # Use the internal _pending to find the confirmation id.
            for cid in manager._pending:
                await manager.respond(cid, approved=True)
                return

        import asyncio
        task = asyncio.create_task(_respond_later())
        approved, reason = await manager.request(
            topic="task_1",
            tool_name="terminal",
            permission=PermissionLevel.CONFIRM,
            summary="Run: ls",
            inputs={"command": "ls"},
            timeout=10.0,
        )
        await task
        assert approved is True

    @pytest.mark.asyncio
    async def test_request_denied(self):
        manager = ConfirmationManager(get_bus())

        async def _deny():
            import asyncio
            await asyncio.sleep(0.01)
            for cid in manager._pending:
                await manager.respond(cid, approved=False)
                return

        import asyncio
        task = asyncio.create_task(_deny())
        approved, reason = await manager.request(
            topic="task_1",
            tool_name="terminal",
            permission=PermissionLevel.CONFIRM,
            summary="Run: dangerous",
            inputs={"command": "dangerous"},
            timeout=10.0,
        )
        await task
        assert approved is False

    @pytest.mark.asyncio
    async def test_request_timeout(self):
        manager = ConfirmationManager(get_bus())
        approved, reason = await manager.request(
            topic="task_1",
            tool_name="terminal",
            permission=PermissionLevel.CONFIRM,
            summary="Run: ls",
            inputs={"command": "ls"},
            timeout=0.05,  # Very short timeout.
        )
        assert approved is False
        assert reason is None

    @pytest.mark.asyncio
    async def test_restricted_requires_reason(self):
        manager = ConfirmationManager(get_bus())

        async def _approve_no_reason():
            import asyncio
            await asyncio.sleep(0.01)
            for cid in manager._pending:
                await manager.respond(cid, approved=True)
                return

        import asyncio
        task = asyncio.create_task(_approve_no_reason())
        approved, reason = await manager.request(
            topic="task_1",
            tool_name="terminal",
            permission=PermissionLevel.RESTRICTED,
            summary="Run: rm",
            inputs={"command": "rm -rf /"},
            timeout=10.0,
        )
        await task
        # Should be denied because no reason was provided for RESTRICTED.
        assert approved is False

    @pytest.mark.asyncio
    async def test_respond_unknown_id(self):
        manager = ConfirmationManager(get_bus())
        ok = await manager.respond("nonexistent", approved=True)
        assert ok is False

    @pytest.mark.asyncio
    async def test_pending_list(self):
        manager = ConfirmationManager(get_bus())

        # Create a pending confirmation but never respond.
        import asyncio
        async def _never_respond():
            pass

        task = asyncio.create_task(manager.request(
            topic="task_1",
            tool_name="terminal",
            permission=PermissionLevel.CONFIRM,
            summary="Run: ls",
            inputs={"command": "ls"},
            timeout=60.0,
        ))

        await asyncio.sleep(0.05)
        pending = manager.pending()
        assert len(pending) >= 1
        assert pending[0]["tool"] == "terminal"

        # Clean up by responding.
        for cid in manager._pending:
            await manager.respond(cid, approved=False)

    def test_get_manager_singleton(self):
        reset_manager()
        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2

    def test_reset_manager(self):
        reset_manager()
        m1 = get_manager()
        reset_manager()
        m2 = get_manager()
        assert m1 is not m2
