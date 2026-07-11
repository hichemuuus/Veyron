"""Tests for the WebSocket endpoint."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from paios.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestWebSocket:
    """Tests for the /ws WebSocket endpoint."""

    def test_websocket_subscribe_gets_ack(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "topic": "test-topic-1"})
            ack = ws.receive_json()
            assert ack["type"] == "ack"
            assert ack["payload"]["subscribed"] == "test-topic-1"

    def test_websocket_unsubscribe_gets_ack(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "unsubscribe", "topic": "test-topic-1"})
            ack = ws.receive_json()
            assert ack["type"] == "ack"
            assert ack["payload"]["unsubscribed"] == "test-topic-1"

    def test_websocket_confirm_respond_missing_id(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "confirm.respond", "approved": True})
            err = ws.receive_json()
            assert err["type"] == "error"

    def test_websocket_confirm_respond_missing_approved(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "confirm.respond", "confirmation_id": "xxx"})
            err = ws.receive_json()
            assert err["type"] == "error"

    def test_websocket_bad_message_gets_error(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_text("not valid json")
            err = ws.receive_json()
            assert err["type"] == "error"

    def test_websocket_duplicate_subscribe(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "topic": "dup-topic"})
            ack = ws.receive_json()
            assert ack["type"] == "ack"

            ws.send_json({"type": "subscribe", "topic": "dup-topic"})
            ack2 = ws.receive_json()
            assert ack2["type"] == "ack"
            assert "already subscribed" in str(ack2)

    def test_websocket_subscribes_to_specific_topic(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "topic": "specific-topic"})
            ack = ws.receive_json()
            assert ack["type"] == "ack"
            assert ack["payload"]["subscribed"] == "specific-topic"

    def test_websocket_unsubscribe_nonexistent_topic(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "unsubscribe", "topic": "nonexistent"})
            ack = ws.receive_json()
            assert ack["type"] == "ack"
            assert ack["payload"]["unsubscribed"] == "nonexistent"
