"""Unit tests for S1Client — best-effort HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from alert.config import Settings
from alert.infrastructure.clients.s1_client import S1Client, WatcherInfo


def _settings(**overrides: object) -> Settings:
    defaults = {
        "s1_portfolio_base_url": "http://s1:8001",
        "internal_service_token": "test-token",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestS1Client:
    @pytest.mark.unit
    async def test_get_watchers_by_entity_success(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "entity_id": "eid-1",
            "watchers": [
                {"user_id": "u1", "watchlist_id": "w1", "alert_types": ["SIGNAL"]},
                {"user_id": "u2", "watchlist_id": "w2", "alert_types": []},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_watchers_by_entity("eid-1")

        assert len(result) == 2
        assert result[0].user_id == "u1"
        assert result[0].alert_types == ["SIGNAL"]
        assert result[1].user_id == "u2"
        mock_client.get.assert_called_once()

    @pytest.mark.unit
    async def test_get_watchers_by_entity_s1_unavailable(self) -> None:
        """S1 503 → graceful empty list (never raises)."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock())
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_watchers_by_entity("eid-1")

        assert result == []

    @pytest.mark.unit
    async def test_get_watchers_by_entity_connection_error(self) -> None:
        """Connection refused → graceful empty list."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_watchers_by_entity("eid-1")

        assert result == []

    @pytest.mark.unit
    async def test_get_watchers_by_entities_success(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": {
                "e1": [{"user_id": "u1", "watchlist_id": "w1", "alert_types": []}],
                "e2": [{"user_id": "u2", "watchlist_id": "w2", "alert_types": ["GRAPH_CHANGE"]}],
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_watchers_by_entities(["e1", "e2"])

        assert "e1" in result
        assert result["e1"][0].user_id == "u1"
        assert "e2" in result

    @pytest.mark.unit
    async def test_get_watchers_by_entities_s1_unavailable(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_watchers_by_entities(["e1"])

        assert result == {}

    @pytest.mark.unit
    async def test_health_check_healthy(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "healthy"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(), client=mock_client)
        assert await client.health_check() is True

    @pytest.mark.unit
    async def test_health_check_unhealthy(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        client = S1Client(_settings(), client=mock_client)
        assert await client.health_check() is False

    @pytest.mark.unit
    async def test_internal_token_sent_in_header(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"watchers": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(internal_service_token="secret-tok"), client=mock_client)
        await client.get_watchers_by_entity("eid-1")

        call_args = mock_client.get.call_args
        # headers may be in kwargs or positional — check both
        headers = call_args.kwargs.get("headers") or (call_args.args[1] if len(call_args.args) > 1 else {})
        assert headers.get("X-Internal-Token") == "secret-tok"


class TestWatcherInfo:
    @pytest.mark.unit
    def test_default_alert_types(self) -> None:
        w = WatcherInfo(user_id="u1", watchlist_id="w1")
        assert w.alert_types == []

    @pytest.mark.unit
    def test_with_alert_types(self) -> None:
        w = WatcherInfo(user_id="u1", watchlist_id="w1", alert_types=["SIGNAL"])
        assert w.alert_types == ["SIGNAL"]
