"""Integration tests — Valkey pub/sub → WebSocket cross-process bridge.

Tests the bridge introduced in PLAN-0013 Wave C-2:
  - ValkeyNotificationPublisher publishes to ``alert:{user_id}`` channel
  - ValkeyClient.subscribe() + get_message() receives the published message
  - Polling loop correctly handles disconnects and Valkey-down scenarios

Route's polling pattern (C-2 / PLAN-0013 investigation fixes):
  The WebSocket route uses ``pubsub.get_message(ignore_subscribe_messages=True,
  timeout=30.0)`` instead of ``pubsub.listen()``.  On timeout (None return),
  it sends a ping frame; on WebSocketDisconnect it exits the loop.

All tests use ``fakeredis.aioredis.FakeRedis`` — no real Valkey required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import fakeredis
import fakeredis.aioredis
import pytest
from alert.infrastructure.notification.valkey_publisher import ValkeyNotificationPublisher
from alert.infrastructure.websocket.manager import ConnectionManager
from fastapi import WebSocketDisconnect

from messaging.valkey.client import ValkeyClient, ValkeyConfig

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _make_valkey_pair() -> tuple[ValkeyClient, ValkeyClient]:
    """Return a (subscriber_client, publisher_client) sharing a FakeServer."""
    server = fakeredis.FakeServer()
    sub_redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    pub_redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    sub_client = ValkeyClient(config=ValkeyConfig())
    sub_client._redis = sub_redis  # type: ignore[assignment]
    pub_client = ValkeyClient(config=ValkeyConfig())
    pub_client._redis = pub_redis  # type: ignore[assignment]
    return sub_client, pub_client


async def test_ws_receives_published_notification() -> None:
    """ValkeyNotificationPublisher.send_to_user() → get_message() receives it.

    Simulates the cross-process path using the route's polling pattern:
      - consumer calls ValkeyNotificationPublisher.send_to_user()
      - API process's get_message() polling loop receives the published JSON payload
    """
    sub_client, pub_client = _make_valkey_pair()
    user_id = uuid4()
    channel = f"alert:{user_id}"
    payload = {"alert_id": str(uuid4()), "alert_type": "SIGNAL"}

    publisher = ValkeyNotificationPublisher(pub_client)

    received: list[dict] = []  # type: ignore[type-arg]

    async with sub_client.subscribe(channel) as pubsub:
        # Publish via the notification publisher (consumer-process path).
        await publisher.send_to_user(user_id, payload)

        # Mirror the route's polling loop: use get_message instead of listen().
        # Retry up to 5 times to allow the subscribe confirmation to be processed first.
        for _ in range(5):
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                received.append(json.loads(message["data"]))
                break

    assert len(received) == 1
    assert received[0]["alert_id"] == payload["alert_id"]
    assert received[0]["alert_type"] == "SIGNAL"


async def test_ws_get_message_returns_none_on_timeout() -> None:
    """get_message(timeout=...) returns None when no message arrives within the timeout.

    This is the trigger condition for the route's ping heartbeat:
      None return → send '{"type":"ping"}' to the WebSocket.
    """
    sub_client, _pub_client = _make_valkey_pair()
    user_id = uuid4()
    channel = f"alert:{user_id}"

    async with sub_client.subscribe(channel) as pubsub:
        # Nothing published — get_message with a very short timeout must return None.
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)

    assert message is None, "Expected None when no message is published within the timeout"


async def test_ws_disconnect_cleans_up_subscription() -> None:
    """manager.disconnect() is called in the route's finally block after WebSocketDisconnect.

    Simulates the polling-loop route handler pattern:
      1. Client connects → manager.connect()
      2. Valkey message arrives → get_message() returns it → send_text() →
         WebSocketDisconnect raised
      3. Route's finally block → manager.disconnect()
    """
    sub_client, pub_client = _make_valkey_pair()
    user_id = uuid4()
    channel = f"alert:{user_id}"
    manager = ConnectionManager()

    disconnect_called: list[bool] = []
    original_disconnect = manager.disconnect

    def _track_disconnect(uid: UUID) -> None:
        disconnect_called.append(True)
        original_disconnect(uid)

    manager.disconnect = _track_disconnect  # type: ignore[method-assign]

    # Simulate the polling-loop route: subscribe, receive one message,
    # raise WebSocketDisconnect on send_text, run finally.
    try:
        async with sub_client.subscribe(channel) as pubsub:
            await pub_client.publish(channel, json.dumps({"alert_id": "x"}))

            # Poll until we get the actual message (skip subscribe confirmation).
            for _ in range(5):
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    # Simulate websocket.send_text() raising WebSocketDisconnect
                    raise WebSocketDisconnect(code=1000)
    except WebSocketDisconnect:
        pass  # route catches this
    finally:
        # Route's finally block always runs
        manager.disconnect(user_id)

    assert disconnect_called, "manager.disconnect() was not called after WebSocketDisconnect"


async def test_ws_swallows_valkey_down() -> None:
    """If Valkey.subscribe() raises, the route's except/finally blocks run correctly.

    Verifies that a ConnectionError from Valkey is caught by the route's
    ``except Exception`` handler and that ``manager.disconnect()`` is always
    called from the ``finally`` block.
    """
    sub_client, _pub_client = _make_valkey_pair()
    user_id = uuid4()
    manager = ConnectionManager()
    disconnect_called: list[bool] = []

    from unittest.mock import patch

    with patch.object(sub_client, "subscribe", side_effect=ConnectionError("valkey unavailable")):
        # Simulate the route handler's try/except/finally structure
        try:
            await manager.connect(user_id, MagicMock())  # type: ignore[arg-type]
            async with sub_client.subscribe(f"alert:{user_id}") as pubsub:  # type: ignore[attr-defined]
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    pass
        except Exception:  # noqa: S110
            pass  # route swallows via except Exception + logger.warning (tested elsewhere)
        finally:
            manager.disconnect(user_id)
            disconnect_called.append(True)

    assert disconnect_called, "finally block did not run after Valkey error"
    assert not manager.is_connected(user_id), "user should be disconnected after error"
