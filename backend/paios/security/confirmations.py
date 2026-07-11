"""User confirmation flow for CONFIRM/RESTRICTED actions.

When a tool wants to run a non-FREE action, it calls request_confirmation().
That publishes a 'security.confirm' event on the bus (the UI shows a dialog)
and awaits a future. The WebSocket layer calls respond_to_confirmation() with
the user's decision; the future resolves and the tool proceeds (or aborts).

RESTRICTED actions additionally require a reason string.

See ARCHITECTURE.md §7.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from paios.core.events import Event, EventBus
from paios.security.audit import record as audit_record
from paios.security.command_policy import PermissionLevel

logger = logging.getLogger(__name__)


@dataclass
class PendingConfirmation:
    id: str
    topic: str  # task public_id
    tool_name: str
    permission: PermissionLevel
    summary: str  # short human-readable description of the action
    inputs: dict[str, Any]
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    reason: Optional[str] = None


class ConfirmationManager:
    """Manages pending confirmations and their resolution."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._pending: dict[str, PendingConfirmation] = {}
        self._max_pending = 100  # safety cap to prevent unbounded growth

    async def request(
        self,
        *,
        topic: str,
        tool_name: str,
        permission: PermissionLevel,
        summary: str,
        inputs: dict[str, Any],
        timeout: float = 120.0,
    ) -> tuple[bool, Optional[str]]:
        """Request user confirmation for an action.

        Returns (approved, reason). On timeout returns (False, None).
        """
        conf = PendingConfirmation(
            id=uuid4().hex,
            topic=topic,
            tool_name=tool_name,
            permission=permission,
            summary=summary,
            inputs=inputs,
        )

        # Cap pending confirmations to prevent unbounded growth.
        if len(self._pending) >= self._max_pending:
            raise RuntimeError("too many pending confirmations")
        self._pending[conf.id] = conf

        audit_id = audit_record(
            action="security.confirm.request",
            subject=topic,
            permission=permission.value,
            inputs={"confirmation_id": conf.id, "tool": tool_name, "summary": summary, **inputs},
            outcome="pending",
        )

        await self._bus.publish(
            Event(
                type="security.confirm",
                topic=topic,
                payload={
                    "confirmation_id": conf.id,
                    "tool": tool_name,
                    "permission": permission.value,
                    "summary": summary,
                    "inputs": inputs,
                    "audit_id": audit_id,
                },
            )
        )

        try:
            approved, reason = await asyncio.wait_for(conf.future, timeout=timeout)
            return approved, reason
        except asyncio.TimeoutError:
            logger.warning("confirmation %s timed out after %ss", conf.id, timeout)
            await self._respond(conf.id, approved=False, reason=None, timed_out=True)
            return False, None
        finally:
            self._pending.pop(conf.id, None)

    async def respond(self, confirmation_id: str, *, approved: bool, reason: Optional[str] = None) -> bool:
        """Resolve a pending confirmation from the user. Returns True if found."""
        return await self._respond(confirmation_id, approved=approved, reason=reason)

    async def _respond(
        self, confirmation_id: str, *, approved: bool, reason: Optional[str], timed_out: bool = False
    ) -> bool:
        conf = self._pending.get(confirmation_id)
        if conf is None:
            return False

        # RESTRICTED actions need a reason when approved.
        if approved and conf.permission == PermissionLevel.RESTRICTED and not reason:
            approved = False
            reason = "restricted action requires a reason"

        if not conf.future.done():
            conf.future.set_result((approved, reason))

        audit_record(
            action="security.confirm.response",
            subject=conf.topic,
            permission=conf.permission.value,
            inputs={"confirmation_id": confirmation_id, "tool": conf.tool_name},
            outcome=("approved" if approved else "timeout" if timed_out else "denied"),
            reason=reason,
        )

        await self._bus.publish(
            Event(
                type="security.confirm.resolved",
                topic=conf.topic,
                payload={
                    "confirmation_id": confirmation_id,
                    "approved": approved,
                    "reason": reason,
                    "timed_out": timed_out,
                },
            )
        )
        return True

    def pending(self) -> list[dict[str, Any]]:
        """Snapshot of pending confirmations (for UI/debug)."""
        return [
            {
                "id": c.id,
                "topic": c.topic,
                "tool": c.tool_name,
                "permission": c.permission.value,
                "summary": c.summary,
            }
            for c in self._pending.values()
        ]


# Process-wide manager (bound to the global bus).
_manager: ConfirmationManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> ConfirmationManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                from paios.core.events import get_bus

                _manager = ConfirmationManager(get_bus())
    return _manager


def reset_manager() -> None:
    """Test helper."""
    global _manager
    _manager = None
