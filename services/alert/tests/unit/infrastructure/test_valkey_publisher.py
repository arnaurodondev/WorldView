"""Unit tests for ValkeyNotificationPublisher.

Covers: correct channel format, JSON serialisation, error swallowing.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alert.infrastructure.notification.valkey_publisher import ValkeyNotificationPublisher

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_valkey() -> AsyncMock:
    """Return a mock ValkeyClient with publish as an AsyncMock."""
    client = MagicMock()
    client.publish = AsyncMock(return_value=1)
    return client


@pytest.mark.asyncio
async def test_publish_sends_to_correct_channel(mock_valkey: AsyncMock) -> None:
    """send_to_user publishes to ``alert:{user_id}``."""
    publisher = ValkeyNotificationPublisher(mock_valkey)
    user_id = uuid4()

    await publisher.send_to_user(user_id, {"alert_id": "abc"})

    expected_channel = f"alert:{user_id}"
    mock_valkey.publish.assert_called_once()
    call_args = mock_valkey.publish.call_args
    assert call_args[0][0] == expected_channel


@pytest.mark.asyncio
async def test_publish_serialises_payload(mock_valkey: AsyncMock) -> None:
    """Payload is JSON-serialised; UUID values are coerced to strings via default=str."""
    publisher = ValkeyNotificationPublisher(mock_valkey)
    user_id = uuid4()
    inner_uuid = uuid4()
    payload = {"alert_id": inner_uuid, "score": 0.9}

    await publisher.send_to_user(user_id, payload)  # type: ignore[arg-type]

    call_args = mock_valkey.publish.call_args
    raw_message: str = call_args[0][1]
    parsed = json.loads(raw_message)
    assert parsed["alert_id"] == str(inner_uuid)
    assert parsed["score"] == 0.9


@pytest.mark.asyncio
async def test_publish_swallows_valkey_error(mock_valkey: AsyncMock) -> None:
    """No exception is raised when valkey.publish fails; error is logged."""
    mock_valkey.publish = AsyncMock(side_effect=ConnectionError("valkey down"))
    publisher = ValkeyNotificationPublisher(mock_valkey)
    user_id = uuid4()

    # Must not raise — best-effort delivery
    await publisher.send_to_user(user_id, {"alert_id": "test"})
