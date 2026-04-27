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
        "s8_internal_jwt": "test-s8-token",
        "s1_internal_jwt": "test-s1-jwt",
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

        watchers, ok = result
        assert ok is True
        assert len(watchers) == 2
        assert watchers[0].user_id == "u1"
        assert watchers[0].alert_types == ["SIGNAL"]
        assert watchers[1].user_id == "u2"
        mock_client.get.assert_called_once()

    @pytest.mark.unit
    async def test_get_watchers_by_entity_s1_unavailable(self) -> None:
        """S1 503 → graceful empty list (never raises)."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock())
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(), client=mock_client)
        watchers, ok = await client.get_watchers_by_entity("eid-1")

        assert ok is False
        assert watchers == []

    @pytest.mark.unit
    async def test_get_watchers_by_entity_connection_error(self) -> None:
        """Connection refused → graceful empty list, ok=False."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        client = S1Client(_settings(), client=mock_client)
        watchers, ok = await client.get_watchers_by_entity("eid-1")

        assert ok is False
        assert watchers == []

    @pytest.mark.unit
    async def test_get_watchers_by_entities_success(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": {
                "e1": [{"user_id": "u1", "watchlist_id": "w1", "alert_types": []}],
                "e2": [{"user_id": "u2", "watchlist_id": "w2", "alert_types": ["GRAPH_CHANGE"]}],
            },
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
    async def test_internal_jwt_sent_in_header(self) -> None:
        """PRD-0025: S1Client must send X-Internal-JWT (RS256), not X-Internal-Token."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"watchers": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(s1_internal_jwt="rs256.test.jwt"), client=mock_client)
        await client.get_watchers_by_entity("eid-1")

        call_args = mock_client.get.call_args
        headers = call_args.kwargs.get("headers") or (call_args.args[1] if len(call_args.args) > 1 else {})
        assert headers.get("X-Internal-JWT") == "rs256.test.jwt"
        assert "X-Internal-Token" not in headers


class TestGetUserEmail:
    @pytest.mark.unit
    async def test_returns_email_on_success(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"user_id": "u1", "email_address": "user@example.com"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_user_email("u1")

        assert result == "user@example.com"

    @pytest.mark.unit
    async def test_returns_none_when_email_absent(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"user_id": "u1", "email_address": ""}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_user_email("u1")

        assert result is None

    @pytest.mark.unit
    async def test_returns_none_on_s1_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_user_email("u1")

        assert result is None

    @pytest.mark.unit
    async def test_returns_none_on_404(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
        mock_client.get = AsyncMock(return_value=mock_resp)

        client = S1Client(_settings(), client=mock_client)
        result = await client.get_user_email("u1")

        assert result is None


class TestWatcherInfo:
    @pytest.mark.unit
    def test_default_alert_types(self) -> None:
        w = WatcherInfo(user_id="u1", watchlist_id="w1")
        assert w.alert_types == []

    @pytest.mark.unit
    def test_with_alert_types(self) -> None:
        w = WatcherInfo(user_id="u1", watchlist_id="w1", alert_types=["SIGNAL"])
        assert w.alert_types == ["SIGNAL"]
