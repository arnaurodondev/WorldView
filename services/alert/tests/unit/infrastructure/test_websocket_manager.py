"""Unit tests for ConnectionManager (WebSocket manager)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alert.infrastructure.websocket.manager import ConnectionManager


def _mock_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


class TestConnectionManager:
    @pytest.mark.unit
    async def test_connect_accepts_and_registers(self) -> None:
        manager = ConnectionManager()
        user_id = uuid4()
        ws = _mock_ws()

        await manager.connect(user_id, ws)

        ws.accept.assert_awaited_once()
        assert manager.is_connected(user_id)
        assert manager.active_count == 1

    @pytest.mark.unit
    async def test_disconnect_removes_connection(self) -> None:
        manager = ConnectionManager()
        user_id = uuid4()
        ws = _mock_ws()
        await manager.connect(user_id, ws)

        manager.disconnect(user_id)

        assert not manager.is_connected(user_id)
        assert manager.active_count == 0

    @pytest.mark.unit
    def test_disconnect_unknown_user_is_noop(self) -> None:
        manager = ConnectionManager()
        # Should not raise
        manager.disconnect(uuid4())

    @pytest.mark.unit
    async def test_send_to_user_returns_false_when_not_connected(self) -> None:
        manager = ConnectionManager()

        result = await manager.send_to_user(uuid4(), {"msg": "hi"})

        assert result is False

    @pytest.mark.unit
    async def test_send_to_user_success(self) -> None:
        manager = ConnectionManager()
        user_id = uuid4()
        ws = _mock_ws()
        await manager.connect(user_id, ws)

        result = await manager.send_to_user(user_id, {"alert": "test"})

        assert result is True
        ws.send_json.assert_awaited_once_with({"alert": "test"})

    @pytest.mark.unit
    async def test_send_to_user_cleans_up_stale_connection(self) -> None:
        """When send_json raises, disconnect() is called and False is returned."""
        manager = ConnectionManager()
        user_id = uuid4()
        ws = _mock_ws()
        ws.send_json = AsyncMock(side_effect=RuntimeError("closed"))
        await manager.connect(user_id, ws)

        result = await manager.send_to_user(user_id, {"alert": "test"})

        assert result is False
        assert not manager.is_connected(user_id)

    @pytest.mark.unit
    async def test_broadcast_sends_to_all_connected(self) -> None:
        manager = ConnectionManager()
        u1, u2 = uuid4(), uuid4()
        ws1, ws2 = _mock_ws(), _mock_ws()
        await manager.connect(u1, ws1)
        await manager.connect(u2, ws2)

        sent = await manager.broadcast({"broadcast": "test"})

        assert sent == 2
        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_awaited_once()

    @pytest.mark.unit
    async def test_broadcast_skips_stale_connections(self) -> None:
        manager = ConnectionManager()
        u1, u2 = uuid4(), uuid4()
        ws1, ws2 = _mock_ws(), _mock_ws()
        ws1.send_json = AsyncMock(side_effect=RuntimeError("closed"))
        await manager.connect(u1, ws1)
        await manager.connect(u2, ws2)

        sent = await manager.broadcast({"broadcast": "test"})

        assert sent == 1  # only u2 succeeded

    @pytest.mark.unit
    async def test_connect_replaces_existing_connection(self) -> None:
        manager = ConnectionManager()
        user_id = uuid4()
        ws1, ws2 = _mock_ws(), _mock_ws()
        await manager.connect(user_id, ws1)
        await manager.connect(user_id, ws2)

        assert manager.active_count == 1
        # New connection is registered
        assert manager.is_connected(user_id)
