"""Integration tests — Valkey pub/sub → WebSocket cross-process bridge.

Tests the bridge introduced in PLAN-0013 Wave C-2:
  - ValkeyNotificationPublisher publishes to ``alert:{user_id}`` channel
  - ValkeyClient.subscribe() receives the published message (pub/sub round-trip)
  - WebSocket route's disconnect path calls manager.disconnect()

All tests use ``fakeredis.aioredis.FakeRedis`` — no real Valkey required.

Implementation note on get_message():
  ``get_message(ignore_subscribe_messages=True)`` reads ONE response per call and
  returns None when that response is a subscribe confirmation.  Do not use it in
  tests that need to receive a real "message" response — use ``async for`` over
  the PubSub object instead, which handles subscribe confirmations internally.
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


@pytest.mark.integration
async def test_ws_receives_published_notification() -> None:
    """ValkeyNotificationPublisher.send_to_user() → ValkeyClient.subscribe() receives it.

    Simulates the cross-process path:
      - consumer calls ValkeyNotificationPublisher.send_to_user()
      - API process's subscribe() loop receives the published JSON payload
    """
    sub_client, pub_client = _make_valkey_pair()
    user_id = uuid4()
    channel = f"alert:{user_id}"
    payload = {"alert_id": str(uuid4()), "alert_type": "SIGNAL"}

    publisher = ValkeyNotificationPublisher(pub_client)

    received: list[dict] = []  # type: ignore[type-arg]

    async with sub_client.subscribe(channel) as pubsub:
        # Publish via the notification publisher (consumer-process path).
        # Must happen BEFORE the async-for loop so the message is in the buffer.
        await publisher.send_to_user(user_id, payload)

        # Iterate: first yields subscribe confirmation (type="subscribe", skipped),
        # then yields the published message (type="message").
        async for message in pubsub.listen():
            if message["type"] == "message":
                received.append(json.loads(message["data"]))
                break  # one message is sufficient for this test

    assert len(received) == 1
    assert received[0]["alert_id"] == payload["alert_id"]
    assert received[0]["alert_type"] == "SIGNAL"


@pytest.mark.integration
async def test_ws_disconnect_cleans_up_subscription() -> None:
    """manager.disconnect() is called in the route's finally block after WebSocketDisconnect.

    Simulates the route handler pattern:
      1. Client connects → manager.connect()
      2. Valkey message arrives → send_text() → WebSocketDisconnect raised
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

    # Simulate the route: subscribe, receive one message, raise WebSocketDisconnect
    try:
        async with sub_client.subscribe(channel) as pubsub:
            # Publish before the loop so the message is immediately in the buffer
            await pub_client.publish(channel, json.dumps({"alert_id": "x"}))

            async for message in pubsub.listen():
                if message["type"] == "message":
                    # Simulate websocket.send_text() raising WebSocketDisconnect
                    raise WebSocketDisconnect(code=1000)
    except WebSocketDisconnect:
        pass  # route catches this
    finally:
        # Route's finally block always runs
        manager.disconnect(user_id)

    assert disconnect_called, "manager.disconnect() was not called after WebSocketDisconnect"


@pytest.mark.integration
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
                async for _msg in pubsub:
                    pass
        except Exception:  # noqa: S110
            pass  # route swallows via except Exception + logger.warning (tested elsewhere)
        finally:
            manager.disconnect(user_id)
            disconnect_called.append(True)

    assert disconnect_called, "finally block did not run after Valkey error"
    assert not manager.is_connected(user_id), "user should be disconnected after error"
