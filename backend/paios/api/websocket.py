"""WebSocket endpoint.

Bidirectional:
  - Server -> client: every event on the bus (task updates, tool calls, agent
    thinking, confirmation requests).
  - Client -> server: subscription to a topic (task id or "system"), and
    confirmation responses (approve/deny + reason).

See ARCHITECTURE.md §8.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from paios.core.events import get_bus
from paios.security.confirmations import get_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


class ClientMessage(BaseModel):
    """Message from the client over the WebSocket."""

    type: str  # "subscribe" | "unsubscribe" | "confirm.respond"
    topic: str | None = None
    confirmation_id: str | None = None
    approved: bool | None = None
    reason: str | None = None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    bus = get_bus()
    manager = get_manager()
    active_lock = asyncio.Lock()

    active_sub_ids: set[str] = set()
    # Map topic -> forwarder task for targeted unsubscription.
    topic_forwarders: dict[str | None, asyncio.Task] = {}
    topic_lock = asyncio.Lock()

    async def _add_sub(sub_id: str) -> None:
        async with active_lock:
            active_sub_ids.add(sub_id)

    async def _discard_sub(sub_id: str) -> None:
        async with active_lock:
            active_sub_ids.discard(sub_id)

    async def _snapshot_subs() -> list[str]:
        async with active_lock:
            return list(active_sub_ids)

    async def forward_events(topic: str | None) -> None:
        sub_id, iterator = await bus.subscribe(topic)
        await _add_sub(sub_id)
        try:
            async for event in iterator:
                await websocket.send_json(
                    {
                        "type": event.type,
                        "topic": event.topic,
                        "ts": event.ts,
                        "payload": event.payload,
                    }
                )
        except asyncio.CancelledError:
            pass
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("event forwarder error: %s", e)
        finally:
            await bus.unsubscribe(sub_id)
            await _discard_sub(sub_id)

    # Default: subscribe to all events on connect.
    all_task = asyncio.create_task(forward_events(None))
    async with topic_lock:
        topic_forwarders[None] = all_task

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = ClientMessage(**json.loads(raw))
            except (json.JSONDecodeError, ValueError) as e:
                await websocket.send_json({"type": "error", "payload": {"error": f"bad message: {e}"}})
                continue

            if msg.type == "subscribe" and msg.topic:
                async with topic_lock:
                    existing = topic_forwarders.get(msg.topic)
                    if existing and not existing.done():
                        await websocket.send_json(
                            {"type": "ack", "payload": {"subscribed": msg.topic, "note": "already subscribed"}}
                        )
                        continue
                    task = asyncio.create_task(forward_events(msg.topic))
                    topic_forwarders[msg.topic] = task
                await websocket.send_json(
                    {"type": "ack", "payload": {"subscribed": msg.topic}}
                )
            elif msg.type == "unsubscribe" and msg.topic:
                async with topic_lock:
                    existing = topic_forwarders.pop(msg.topic, None)
                    if existing and not existing.done():
                        existing.cancel()
                await websocket.send_json(
                    {"type": "ack", "payload": {"unsubscribed": msg.topic}}
                )
            elif msg.type == "confirm.respond":
                if msg.confirmation_id is None or msg.approved is None:
                    await websocket.send_json(
                        {"type": "error", "payload": {"error": "confirm.respond needs confirmation_id + approved"}}
                    )
                    continue
                ok = await manager.respond(
                    msg.confirmation_id, approved=msg.approved, reason=msg.reason
                )
                await websocket.send_json(
                    {"type": "ack", "payload": {"confirmation_id": msg.confirmation_id, "handled": ok}}
                )
    except WebSocketDisconnect:
        logger.debug("ws disconnected")
    except Exception as e:  # noqa: BLE001
        logger.warning("ws error: %s", e)
    finally:
        async with topic_lock:
            for f in topic_forwarders.values():
                if not f.done():
                    f.cancel()
            topic_forwarders.clear()
        for sid in await _snapshot_subs():
            await bus.unsubscribe(sid)
